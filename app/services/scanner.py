import asyncio
import json
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse
import httpx
from sqlalchemy import select, or_
from app.config import get_settings
from app.collectors.stepstone import StepStoneCollector
from app.collectors.indeed import IndeedCollector
from app.collectors.generic import GenericCollector
from app.collectors.base import RawJob, safe_job_url
from app.services.discovery import PublicDiscovery
from app.services.deduplicator import canonicalize_url, fingerprint
from app.services.matcher import score_job
from app.models import Job, JobSource

log = logging.getLogger(__name__)

def build_queries(profile):
    return [f"Werkstudent {kw} {profile.location}" for kw in profile.keywords]

class ScanManager:
    def __init__(self, db, profile):
        self.db = db
        self.profile = profile
        self.running = False
        self.status = {
            "running": False, "started_at": None, "finished_at": None,
            "last_error": None, "found": 0, "new": 0, "duplicates": 0,
            "filtered": 0, "errors": 0, "collectors": {}
        }
        self.lock = asyncio.Lock()

    async def scan(self):
        if self.lock.locked():
            return self.status
        async with self.lock:
            settings = get_settings()
            self.running = True
            self.status.update({
                "running": True, "started_at": datetime.now(timezone.utc),
                "finished_at": None, "last_error": None, "found": 0,
                "new": 0, "duplicates": 0, "filtered": 0, "errors": 0, "collectors": {}
            })
            limits = httpx.Limits(max_connections=settings.max_concurrent_requests, max_keepalive_connections=settings.max_concurrent_requests)
            sem = asyncio.Semaphore(settings.max_concurrent_requests)
            headers = {"User-Agent": settings.user_agent, "Accept-Language": "de-DE,de;q=0.8,en;q=0.6"}
            try:
                async with httpx.AsyncClient(timeout=settings.request_timeout, headers=headers, limits=limits, follow_redirects=True) as client:
                    discovery = PublicDiscovery(client, settings.discovery_max_results, 1.0 / max(settings.request_rate_per_second, 0.1))
                    collectors = {
                        "stepstone": StepStoneCollector(),
                        "indeed": IndeedCollector(),
                        "generic": GenericCollector(),
                    }
                    for name in self.profile.sources:
                        collector = collectors.get(name)
                        if not collector:
                            continue
                        count = errors = 0
                        seen_local = set()
                        for q in build_queries(self.profile):
                            try:
                                async with sem:
                                    jobs = await collector.search(q, self.profile.location, {"discovery": discovery})
                                for raw in jobs:
                                    key = canonicalize_url(raw.url)
                                    if not safe_job_url(raw.url) or key in seen_local:
                                        self.status["duplicates"] += 1
                                        continue
                                    seen_local.add(key)
                                    raw.source = name
                                    await self._upsert(raw)
                                    count += 1
                            except Exception as e:
                                errors += 1
                                log.warning("%s query failed: %s", name, e)
                        self.status["collectors"][name] = {"jobs": count, "errors": errors, "status": "OK" if errors == 0 else "PARTIAL"}
                        self.status["errors"] += errors
                self.db.commit()
            except Exception as e:
                self.db.rollback()
                self.status["last_error"] = str(e)
                log.exception("scan failed")
            finally:
                self.status["running"] = False
                self.running = False
                self.status["finished_at"] = datetime.now(timezone.utc)
            return self.status

    async def _upsert(self, raw: RawJob):
        from app.services.matcher import score_job
        url = canonicalize_url(raw.url)
        fp = fingerprint(raw)
        existing = self.db.execute(select(Job).where(or_(Job.canonical_url == url, Job.fingerprint == fp))).scalar_one_or_none()
        score, reasons = score_job(raw, self.profile)
        if existing:
            existing.updated_at = datetime.now(timezone.utc)
            if score > existing.match_score:
                existing.match_score = score
                existing.match_reasons = json.dumps(reasons, ensure_ascii=False)
            prior = self.db.execute(
                select(JobSource).where(JobSource.job_id == existing.id, JobSource.url == raw.url)
            ).scalar_one_or_none()
            if not prior:
                self.db.add(JobSource(job_id=existing.id, source=raw.source[:100], url=raw.url[:2000], source_job_id=raw.source_job_id))
            self.status["duplicates"] += 1
            return
        if score < self.profile.min_score:
            self.status["filtered"] += 1
        job = Job(
            title=raw.title[:500], company=raw.company[:300], location=raw.location[:300],
            description=raw.description[:10000], url=raw.url[:2000], canonical_url=url,
            source=raw.source[:100], source_job_id=raw.source_job_id,
            employment_type=raw.employment_type[:100], hours=raw.hours[:100],
            salary=raw.salary[:300], remote_type=raw.remote_type[:100],
            posted_date=raw.posted_date, match_score=score,
            match_reasons=json.dumps(reasons, ensure_ascii=False),
            status="new", fingerprint=fp
        )
        self.db.add(job)
        self.db.flush()
        self.db.add(JobSource(job_id=job.id, source=raw.source[:100], url=raw.url[:2000], source_job_id=raw.source_job_id))
        self.status["new"] += 1
        self.status["found"] += 1

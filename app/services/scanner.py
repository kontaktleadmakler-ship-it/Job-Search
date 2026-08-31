import asyncio
import json
import logging
from datetime import datetime, timezone
import httpx
from sqlalchemy import select, or_
from app.config import get_settings
from app.collectors.stepstone import StepStoneCollector
from app.collectors.indeed import IndeedCollector
from app.collectors.generic import GenericCollector
from app.collectors.xing import XingCollector
from app.collectors.monster import MonsterCollector
from app.collectors.jobware import JobwareCollector
from app.collectors.kimeta import KimetaCollector
from app.collectors.linkedin import LinkedinCollector
from app.collectors.arbeitsagentur import ArbeitsagenturCollector
from app.collectors.base import RawJob, safe_job_url
from app.services.discovery import PublicDiscovery, is_direct_job_url, is_generic_job_url
from app.services.deduplicator import canonicalize_url, fingerprint
from app.services.matcher import score_job
from app.services.job_parser import parse_html
from app.models import Job, JobSource

log = logging.getLogger(__name__)

def build_queries(profile):
    roles = profile.effective_roles()
    return roles[:15]

class ScanManager:
    def __init__(self, db, profile):
        self.db = db; self.profile = profile; self.running = False
        self.status = {"running": False, "started_at": None, "finished_at": None, "last_error": None,
                       "found": 0, "new": 0, "duplicates": 0, "filtered": 0, "errors": 0, "collectors": {}}
        self.lock = asyncio.Lock()

    async def _enrich(self, client: httpx.AsyncClient, raw: RawJob) -> RawJob:
        if not safe_job_url(raw.url): return raw
        try:
            r = await client.get(raw.url, timeout=min(12, get_settings().request_timeout), follow_redirects=True)
            r.raise_for_status()
            parsed = parse_html(r.text, str(r.url), raw.source)
            if parsed:
                # Search-engine title is often better; keep it if parser title is weak.
                if len(parsed.title) >= 8: raw.title = parsed.title
                if parsed.company: raw.company = parsed.company
                if parsed.location: raw.location = parsed.location
                if parsed.description: raw.description = parsed.description
                redirected = str(r.url)
                # Never replace a verified job URL with a portal homepage/search URL after a redirect.
                if safe_job_url(redirected) and (
                    is_direct_job_url(redirected, raw.source) or
                    (raw.source == "generic" and is_generic_job_url(redirected))
                ):
                    raw.url = redirected
        except Exception as e:
            log.debug("job enrichment failed %s: %s", raw.url, e)
        return raw

    async def scan(self):
        if self.lock.locked(): return self.status
        async with self.lock:
            settings = get_settings(); self.running = True
            self.status.update({"running": True, "started_at": datetime.now(timezone.utc), "finished_at": None,
                                "last_error": None, "found": 0, "new": 0, "duplicates": 0, "filtered": 0, "errors": 0, "collectors": {}})
            limits = httpx.Limits(max_connections=settings.max_concurrent_requests, max_keepalive_connections=settings.max_concurrent_requests)
            headers = {"User-Agent": settings.user_agent, "Accept-Language": "de-DE,de;q=0.8,en;q=0.6"}
            try:
                async with httpx.AsyncClient(timeout=settings.request_timeout, headers=headers, limits=limits, follow_redirects=True) as client:
                    discovery = PublicDiscovery(client, settings.discovery_max_results, 1.0 / max(settings.request_rate_per_second, 0.1), settings.discovery_timeout)
                    collectors = {
                        "stepstone": StepStoneCollector(),
                        "indeed": IndeedCollector(),
                        "generic": GenericCollector(),
                        "xing": XingCollector(),
                        "monster": MonsterCollector(),
                        "jobware": JobwareCollector(),
                        "kimeta": KimetaCollector(),
                        "linkedin": LinkedinCollector(),
                        "arbeitsagentur": ArbeitsagenturCollector(),
                    }
                    for name in self.profile.sources:
                        collector = collectors.get(name)
                        if not collector: continue
                        count = errors = 0; seen_local = set()
                        for q in build_queries(self.profile):
                            try:
                                try:
                                    jobs = await collector.search(q, self.profile.location, {"discovery": discovery, "client": client, "profile": self.profile})
                                except Exception as primary_error:
                                    # Job portals are often not indexable. Fall back to public
                                    # search for direct company/ATS job pages rather than storing
                                    # portal homepages or search pages.
                                    if name in {"stepstone", "indeed", "xing", "monster", "jobware", "kimeta", "linkedin"}:
                                        jobs = []
                                        for employment_type in (self.profile.employment_types or ["Werkstudent"]):
                                            try:
                                                jobs.extend(await discovery.search_generic(q, self.profile.location, employment_type))
                                            except Exception as fallback_error:
                                                log.warning("%s generic fallback failed for %s: %s", name, employment_type, fallback_error)
                                        for raw in jobs:
                                            raw.source = "generic"
                                    else:
                                        raise primary_error
                                for raw in jobs:
                                    raw.source = name
                                    raw = await self._enrich(client, raw)
                                    key = canonicalize_url(raw.url)
                                    if not safe_job_url(raw.url) or key in seen_local: continue
                                    seen_local.add(key)
                                    await self._upsert(raw)
                                    count += 1
                            except Exception as e:
                                errors += 1; log.warning("%s query failed: %s", name, e)
                        provider = "official-api" if name == "arbeitsagentur" else (discovery.last_provider or "none")
                        self.status["collectors"][name] = {"jobs": count, "errors": errors,
                            "status": "OK" if count and not errors else ("PARTIAL" if count or errors else "NO_RESULTS"), "provider": provider}
                        self.status["errors"] += errors
                        # Commit after every source instead of only at the very end: a
                        # scan across many sources/queries can take minutes, and a
                        # deploy/restart mid-scan must not discard already-found jobs.
                        # It also lets the dashboard show results while a scan is
                        # still in progress rather than only once it fully finishes.
                        self.db.commit()
            except Exception as e:
                self.db.rollback(); self.status["last_error"] = str(e); log.exception("scan failed")
            finally:
                self.status["running"] = False; self.running = False; self.status["finished_at"] = datetime.now(timezone.utc)
            return self.status

    async def _upsert(self, raw: RawJob):
        url = canonicalize_url(raw.url); fp = fingerprint(raw)
        existing = self.db.execute(select(Job).where(or_(Job.canonical_url == url, Job.fingerprint == fp))).scalar_one_or_none()
        score, reasons = score_job(raw, self.profile)
        if existing:
            existing.updated_at = datetime.now(timezone.utc)
            # Re-score existing jobs with the current profile; this is important after profile changes.
            existing.match_score = score
            existing.match_reasons = json.dumps(reasons, ensure_ascii=False)
            self.status["duplicates"] += 1
            return
        if score < self.profile.min_score:
            self.status["filtered"] += 1
            # Keep low-score jobs in DB for transparency, but they remain hidden at the UI's default threshold.
        job = Job(title=raw.title[:500], company=raw.company[:300], location=raw.location[:300], description=raw.description[:10000],
                  url=raw.url[:2000], canonical_url=url, source=raw.source[:100], source_job_id=raw.source_job_id,
                  employment_type=raw.employment_type[:100], hours=raw.hours[:100], salary=raw.salary[:300], remote_type=raw.remote_type[:100],
                  posted_date=raw.posted_date, match_score=score, match_reasons=json.dumps(reasons, ensure_ascii=False), status="new", fingerprint=fp)
        self.db.add(job); self.db.flush()
        self.db.add(JobSource(job_id=job.id, source=raw.source[:100], url=raw.url[:2000], source_job_id=raw.source_job_id))
        self.status["new"] += 1; self.status["found"] += 1

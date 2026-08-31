import asyncio
import json
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse, urljoin
import httpx
from bs4 import BeautifulSoup
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
from app.services.discovery import PublicDiscovery, is_direct_job_url, is_generic_job_url, source_for_url, KNOWN_LISTING_PATHS
from app.services.deduplicator import canonicalize_url, fingerprint
from app.services.matcher import score_job
from app.services.job_parser import parse_html, infer_employment_type, has_jobposting_jsonld
from app.models import Job, JobSource

log = logging.getLogger(__name__)
PORTAL_SOURCES = {"stepstone", "indeed", "xing", "monster", "jobware", "kimeta", "linkedin"}


def _clean(value: str) -> str:
    return " ".join((value or "").split())


def build_queries(profile):
    """Generate several focused query clusters from the actual profile.

    Queries are deliberately redundant in a controlled way: title/domain,
    title+skill, domain+skill and explicit keyword variants. This improves recall
    without turning the matcher into a keyword-only filter.
    """
    roles = profile.effective_roles()
    skills = [x.strip() for x in (profile.skills or []) if x and x.strip()]
    keywords = [x.strip() for x in (profile.keywords or []) if x and x.strip()]
    queries = []

    def add(q):
        q = _clean(q)
        if q and q not in queries:
            queries.append(q)

    for role in roles[:8]:
        add(role)
    for role in roles[:6]:
        for skill in skills[:3]:
            add(f"{role} {skill}")
    for skill in skills[:5]:
        add(skill)
    for kw in keywords[:6]:
        add(kw)
    return queries[:20]


class ScanManager:
    def __init__(self, db, profile):
        self.db = db
        self.profile = profile
        self.running = False
        self.status = {"running": False, "started_at": None, "finished_at": None, "last_error": None,
                       "found": 0, "new": 0, "duplicates": 0, "filtered": 0, "errors": 0, "collectors": {}, "queries": []}
        self.lock = asyncio.Lock()

    @staticmethod
    def _is_listing_page(url: str) -> bool:
        p = urlparse(url)
        host = p.netloc.lower().split(":")[0]
        host = host[4:] if host.startswith("www.") else host
        path = p.path.lower().rstrip("/")
        if (host, path) in KNOWN_LISTING_PATHS:
            return True
        generic_listing = {"/jobs", "/job", "/stellenangebote", "/stellenangebote/", "/jobsuche", "/suche", "/search", "/karriere", "/career", "/careers", "/stellenmarkt", "/jobboerse"}
        return path in generic_listing

    @staticmethod
    def _listing_links(html: str, base_url: str, source: str, limit: int = 40) -> list[RawJob]:
        soup = BeautifulSoup(html or "", "html.parser")
        out, seen = [], set()
        base_host = urlparse(base_url).netloc.lower().split(":")[0]
        for a in soup.select("a[href]"):
            href = urljoin(base_url, a.get("href", "").strip())
            title = " ".join(a.stripped_strings)
            if not href or not title or len(title) < 8:
                continue
            p = urlparse(href)
            if p.scheme not in {"http", "https"}:
                continue
            external = p.netloc.lower().split(":")[0] != base_host
            key = href.split("#", 1)[0].rstrip("/")
            if key in seen:
                continue
            # Navigation/filter/pagination links are not job candidates.
            low = (title + " " + p.path).lower()
            if any(x in low for x in ("zurück", "weiter", "seite ", "login", "registr", "datenschutz", "impressum", "newsletter", "studis-online")):
                continue
            if source == "studis_online":
                # Studis Online may link either to an internal job detail page or
                # directly to the employer/ATS. Both are valid detail candidates.
                if not external and ("/jobben/" not in p.path.lower() or ScanManager._is_listing_page(href)):
                    continue
                if external and any(x in p.netloc.lower() for x in ("facebook.", "instagram.", "youtube.", "linkedin.com")):
                    continue
                if not any(x in low for x in ("werkstudent", "praktik", "student", "working", "job", "analyst", "developer", "consulting", "marketing", "finance", "it")):
                    continue
            elif not is_generic_job_url(href):
                continue
            seen.add(key)
            out.append(RawJob(title=title[:500], url=href, source=source))
            if len(out) >= limit:
                break
        return out

    async def _expand_listing(self, client: httpx.AsyncClient, raw: RawJob) -> list[RawJob]:
        try:
            r = await client.get(raw.url, timeout=min(15, get_settings().request_timeout), follow_redirects=True)
            r.raise_for_status()
            final_url = str(r.url)
            if not self._is_listing_page(final_url):
                return [raw]
            source = raw.source or source_for_url(final_url)
            links = self._listing_links(r.text, final_url, source)
            for link in links:
                if source == "studis_online":
                    link.source = source_for_url(link.url)
            log.info("LISTING EXPANSION source=%s url=%s links=%s", source, final_url, len(links))
            return links
        except Exception as exc:
            log.debug("listing expansion failed %s: %s", raw.url, exc)
            return []

    async def _enrich(self, client: httpx.AsyncClient, raw: RawJob) -> RawJob | None:
        if not safe_job_url(raw.url):
            return None
        try:
            r = await client.get(raw.url, timeout=min(15, get_settings().request_timeout), follow_redirects=True)
            r.raise_for_status()
            final_url = str(r.url)
            parsed = parse_html(r.text, final_url, raw.source)
            if not parsed or len(parsed.title.strip()) < 8:
                return None
            combined = " ".join((parsed.title, parsed.company, parsed.location, parsed.description, parsed.employment_type)).lower()
            markers = ("bewerben", "apply", "job description", "stellenangebot", "aufgaben", "qualifikationen", "werkstudent", "vollzeit", "teilzeit", "praktikum", "internship")
            if not any(m in combined for m in markers):
                return None
            generic_titles = ("jobs in", "stellenangebote in", "jobsuche", "karriere", "careers", "job search", "stellenmarkt", "jobboerse")
            structured = has_jobposting_jsonld(r.text)
            if not structured:
                # Without structured JobPosting data, demand enough page-level evidence
                # to distinguish a detail page from a portal/search/category page.
                if (not parsed.company or not parsed.location or len(parsed.description or "") < 250
                        or any(parsed.title.lower().startswith(x) for x in generic_titles)):
                    return None
            if raw.source != "generic" and not is_direct_job_url(final_url, raw.source):
                if urlparse(final_url).netloc.lower() != urlparse(raw.url).netloc.lower():
                    return None
            if not parsed.company or not parsed.location:
                # Keep unknown fields only when the page has structured JobPosting
                # data; otherwise listing/search pages are too risky.
                if len(parsed.description or "") < 180:
                    return None
            raw.title = parsed.title or raw.title
            raw.company = parsed.company or raw.company
            raw.location = parsed.location or raw.location
            raw.description = parsed.description or raw.description
            raw.employment_type = parsed.employment_type or raw.employment_type or infer_employment_type(combined)
            raw.hours = parsed.hours or raw.hours
            raw.salary = parsed.salary or raw.salary
            raw.remote_type = parsed.remote_type or raw.remote_type
            raw.posted_date = parsed.posted_date or raw.posted_date
            raw.url = final_url
            return raw
        except Exception as e:
            log.debug("job enrichment failed %s: %s", raw.url, e)
            return None

    async def _discover_fallback(self, discovery, query):
        jobs = []
        for employment_type in (self.profile.employment_types or ["Werkstudent"]):
            try:
                jobs.extend(await discovery.search_generic(query, self.profile.location, employment_type))
            except Exception as exc:
                log.debug("generic discovery failed for %s/%s: %s", query, employment_type, exc)
        return jobs

    async def scan(self):
        if self.lock.locked():
            return self.status
        async with self.lock:
            settings = get_settings()
            self.running = True
            self.status.update({"running": True, "started_at": datetime.now(timezone.utc), "finished_at": None,
                                "last_error": None, "found": 0, "new": 0, "duplicates": 0, "filtered": 0, "errors": 0, "collectors": {}, "queries": build_queries(self.profile)})
            limits = httpx.Limits(max_connections=settings.max_concurrent_requests, max_keepalive_connections=settings.max_concurrent_requests)
            headers = {"User-Agent": settings.user_agent, "Accept-Language": "de-DE,de;q=0.8,en;q=0.6"}
            try:
                async with httpx.AsyncClient(timeout=settings.request_timeout, headers=headers, limits=limits, follow_redirects=True) as client:
                    discovery = PublicDiscovery(client, settings.discovery_max_results, 1.0 / max(settings.request_rate_per_second, 0.1), settings.discovery_timeout)
                    collectors = {
                        "stepstone": StepStoneCollector(), "indeed": IndeedCollector(), "generic": GenericCollector(),
                        "xing": XingCollector(), "monster": MonsterCollector(), "jobware": JobwareCollector(),
                        "kimeta": KimetaCollector(), "linkedin": LinkedinCollector(), "arbeitsagentur": ArbeitsagenturCollector(),
                    }
                    for name in self.profile.sources:
                        collector = collectors.get(name)
                        if not collector:
                            continue
                        count = errors = 0
                        seen_local = set()
                        for q in build_queries(self.profile):
                            jobs = []
                            try:
                                jobs = await collector.search(q, self.profile.location, {"discovery": discovery, "client": client, "profile": self.profile})
                            except Exception as exc:
                                log.debug("%s primary query failed: %s", name, exc)
                            if not jobs and name in PORTAL_SOURCES:
                                jobs = await self._discover_fallback(discovery, q)
                            for raw in jobs:
                                if raw.source == "generic":
                                    raw.source = source_for_url(raw.url)
                                elif raw.source != name:
                                    raw.source = source_for_url(raw.url) or name
                                candidates = await self._expand_listing(client, raw) if self._is_listing_page(raw.url) else [raw]
                                for candidate in candidates:
                                    if candidate.source == "generic":
                                        candidate.source = source_for_url(candidate.url)
                                    enriched = await self._enrich(client, candidate)
                                    if not enriched:
                                        continue
                                    key = canonicalize_url(enriched.url)
                                    if not safe_job_url(enriched.url) or key in seen_local:
                                        continue
                                    if enriched.source != "generic" and not is_direct_job_url(enriched.url, enriched.source):
                                        continue
                                    if enriched.source == "generic" and not is_generic_job_url(enriched.url):
                                        continue
                                    seen_local.add(key)
                                    try:
                                        result = await self._upsert(enriched)
                                        count += 1 if result in {"new", "duplicate"} else 0
                                    except Exception:
                                        errors += 1
                                        log.exception("upsert failed for %s", enriched.url)
                        provider = "official-api" if name == "arbeitsagentur" else (discovery.last_provider or "none")
                        self.status["collectors"][name] = {"jobs": count, "errors": errors,
                            "status": "OK" if count and not errors else ("PARTIAL" if count or errors else "NO_RESULTS"), "provider": provider}
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
        url = canonicalize_url(raw.url)
        fp = fingerprint(raw)
        existing = self.db.execute(select(Job).where(or_(Job.canonical_url == url, Job.fingerprint == fp))).scalar_one_or_none()
        score, reasons = score_job(raw, self.profile)
        if score < self.profile.min_score:
            self.status["filtered"] += 1
            log.info("FILTERED job=%r score=%s reason=%s", raw.title, score, " | ".join(reasons))
            return "filtered"
        if existing:
            existing.updated_at = datetime.now(timezone.utc)
            existing.match_score = score
            existing.match_reasons = json.dumps(reasons, ensure_ascii=False)
            # Preserve the additional source instead of silently discarding it.
            if raw.source:
                known = self.db.execute(select(JobSource).where(JobSource.job_id == existing.id, JobSource.source == raw.source, JobSource.url == raw.url)).scalar_one_or_none()
                if not known:
                    self.db.add(JobSource(job_id=existing.id, source=raw.source[:100], url=raw.url[:2000], source_job_id=raw.source_job_id))
            self.status["duplicates"] += 1
            return "duplicate"
        job = Job(title=raw.title[:500], company=raw.company[:300], location=raw.location[:300], description=raw.description[:10000],
                  url=raw.url[:2000], canonical_url=url, source=raw.source[:100], source_job_id=raw.source_job_id,
                  employment_type=raw.employment_type[:100], hours=raw.hours[:100], salary=raw.salary[:300], remote_type=raw.remote_type[:100],
                  posted_date=raw.posted_date, match_score=score, match_reasons=json.dumps(reasons, ensure_ascii=False), status="new", fingerprint=fp)
        self.db.add(job)
        self.db.flush()
        self.db.add(JobSource(job_id=job.id, source=raw.source[:100], url=raw.url[:2000], source_job_id=raw.source_job_id))
        self.status["new"] += 1
        self.status["found"] += 1
        return "new"

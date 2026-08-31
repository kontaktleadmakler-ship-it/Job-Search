import logging
from datetime import datetime
import httpx
from app.collectors.base import JobCollector, RawJob, safe_job_url, normalize_space

log = logging.getLogger(__name__)
API_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs"
API_KEY = "jobboerse-jobsuche"

class ArbeitsagenturCollector(JobCollector):
    name = "arbeitsagentur"

    async def search(self, query: str, location: str, filters: dict) -> list[RawJob]:
        client = filters.get("client")
        profile = filters.get("profile")
        discovery = filters.get("discovery")
        if client is None:
            return []
        types = (profile.employment_types if profile else None) or ["Werkstudent"]
        jobs: list[RawJob] = []
        seen = set()
        for employment_type in types:
            params = {"was": f"{employment_type} {query}", "wo": location, "angebotsart": 1, "size": 25}
            try:
                r = await client.get(API_URL, params=params, headers={"X-API-Key": API_KEY, "Accept": "application/json"}, timeout=15)
                r.raise_for_status()
                data = r.json()
            except Exception as e:
                log.warning("Arbeitsagentur API fehlgeschlagen: %s", e)
                continue
            for item in data.get("stellenangebote", []):
                ref = item.get("refnr")
                if not ref or ref in seen:
                    continue
                seen.add(ref)
                url = f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref}"
                if not safe_job_url(url):
                    continue
                ort = normalize_space((item.get("arbeitsort") or {}).get("ort", ""))
                posted = None
                if item.get("aktuelleVeroeffentlichungsdatum"):
                    try: posted = datetime.fromisoformat(item["aktuelleVeroeffentlichungsdatum"])
                    except ValueError: pass
                jobs.append(RawJob(title=normalize_space(item.get("titel", "")), company=normalize_space(item.get("arbeitgeber", "")), location=ort, description=normalize_space(item.get("stellenbeschreibung", "")), url=url, source=self.name, source_job_id=ref, posted_date=posted, employment_type=employment_type))
        if jobs:
            return jobs
        # The public API is intermittently protected with 403. If that happens,
        # use the same direct-job discovery path as the other sources.
        if discovery:
            try:
                rows = await discovery.search_generic(query, location, types[0])
                return [r for r in rows if safe_job_url(r.url)]
            except Exception as exc:
                log.warning("Arbeitsagentur public fallback failed: %s", exc)
        return []

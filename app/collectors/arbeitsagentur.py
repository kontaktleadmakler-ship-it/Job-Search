import logging
from datetime import datetime
import httpx
from app.collectors.base import JobCollector, RawJob, safe_job_url, normalize_space

log = logging.getLogger(__name__)

# Öffentlich dokumentierte Bundesagentur-für-Arbeit "Jobsuche" API.
# Kein Login, kein Scraping, kein Anti-Bot-Bypass: das ist der offizielle,
# frei zugängliche Such-Endpunkt hinter jobboerse.arbeitsagentur.de.
# Der Client-Key ist öffentlich und wird von der offiziellen Web-Oberfläche
# selbst genutzt (kein Secret).
API_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs"
API_KEY = "jobboerse-jobsuche"


class ArbeitsagenturCollector(JobCollector):
    name = "arbeitsagentur"

    async def search(self, query: str, location: str, filters: dict) -> list[RawJob]:
        client: httpx.AsyncClient | None = filters.get("client")
        if client is None:
            return []
        params = {
            "was": query,
            "wo": location,
            "angebotsart": 1,  # Arbeit (keine Ausbildung/Praktikum-Filterung hier; Matcher filtert weiter)
            "size": 25,
        }
        headers = {"X-API-Key": API_KEY}
        try:
            r = await client.get(API_URL, params=params, headers=headers, timeout=15)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            log.warning("Arbeitsagentur API fehlgeschlagen: %s", e)
            return []

        jobs: list[RawJob] = []
        for item in data.get("stellenangebote", []):
            ref = item.get("refnr")
            if not ref:
                continue
            url = f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref}"
            if not safe_job_url(url):
                continue
            arbeitsort = item.get("arbeitsort") or {}
            ort = normalize_space(arbeitsort.get("ort", ""))
            posted = None
            if item.get("aktuelleVeroeffentlichungsdatum"):
                try:
                    posted = datetime.fromisoformat(item["aktuelleVeroeffentlichungsdatum"])
                except ValueError:
                    posted = None
            jobs.append(RawJob(
                title=normalize_space(item.get("titel", "")),
                company=normalize_space(item.get("arbeitgeber", "")),
                location=ort,
                description=normalize_space(item.get("stellenbeschreibung", "")),
                url=url,
                source="arbeitsagentur",
                source_job_id=ref,
                posted_date=posted,
            ))
        return jobs

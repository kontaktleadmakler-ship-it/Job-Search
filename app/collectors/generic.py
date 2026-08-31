from app.collectors.base import JobCollector, RawJob
from app.services.discovery import is_generic_job_url

class GenericCollector(JobCollector):
    name = "generic"

    async def search(self, query: str, location: str, filters: dict) -> list[RawJob]:
        discovery = filters.get("discovery")
        profile = filters.get("profile")
        if not discovery or not profile:
            return []
        out = []
        for employment_type in (profile.employment_types or ["Werkstudent"]):
            out.extend(await discovery.search_generic(query, location, employment_type))
        return [j for j in out if is_generic_job_url(j.url)]

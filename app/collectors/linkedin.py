from app.collectors.base import JobCollector, RawJob

class LinkedinCollector(JobCollector):
    name = "linkedin"

    async def search(self, query: str, location: str, filters: dict) -> list[RawJob]:
        discovery = filters.get("discovery")
        profile = filters.get("profile")
        if not discovery or not profile:
            return []
        out = []
        for employment_type in (profile.employment_types or ["Werkstudent"]):
            out.extend(await discovery.search_site(query, location, self.name, employment_type))
        return out

from app.collectors.base import JobCollector, RawJob

class IndeedCollector(JobCollector):
    name = "indeed"

    async def search(self, query: str, location: str, filters: dict) -> list[RawJob]:
        # Same safe fallback policy as StepStone: public discovery only.
        discovery = filters.get("discovery")
        if not discovery:
            return []
        return await discovery.search_site(query, location, "de.indeed.com")

from app.collectors.base import JobCollector, RawJob

class GenericCollector(JobCollector):
    name = "generic"

    async def search(self, query: str, location: str, filters: dict) -> list[RawJob]:
        discovery = filters.get("discovery")
        if not discovery:
            return []
        return await discovery.search_generic(query, location)

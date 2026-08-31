from app.collectors.base import JobCollector, RawJob

class StepStoneCollector(JobCollector):
    name = "stepstone"

    async def search(self, query: str, location: str, filters: dict) -> list[RawJob]:
        # Direct automated access is deliberately conservative. Use public discovery
        # results instead of bypassing robots/CAPTCHA/anti-bot controls.
        discovery = filters.get("discovery")
        if not discovery:
            return []
        return await discovery.search_site(query, location, "stepstone.de")

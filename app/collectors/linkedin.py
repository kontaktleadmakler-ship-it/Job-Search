from app.collectors.base import JobCollector, RawJob

class LinkedinCollector(JobCollector):
    name = "linkedin"

    async def search(self, query: str, location: str, filters: dict) -> list[RawJob]:
        # Gleiche konservative Policy wie StepStone/Indeed: nur oeffentliche
        # Suchmaschinen-Discovery, kein Login/CAPTCHA/Anti-Bot-Bypass.
        discovery = filters.get("discovery")
        if not discovery:
            return []
        return await discovery.search_site(query, location, "linkedin.com/jobs")

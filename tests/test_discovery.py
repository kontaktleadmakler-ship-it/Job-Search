import pytest
import httpx
from app.services.discovery import PublicDiscovery

@pytest.mark.asyncio
async def test_discovery_falls_back_to_bing(monkeypatch):
    class FakeClient:
        async def get(self, url):
            if "duckduckgo" in url:
                return httpx.Response(503, request=httpx.Request("GET", url))
            html = '<li class="b_algo"><h2><a href="https://stepstone.de/job/123">Werkstudent Finance Analyst</a></h2></li>'
            return httpx.Response(200, text=html, request=httpx.Request("GET", url))
    d = PublicDiscovery(FakeClient(), max_results=5, min_interval=0.1)
    rows = await d.search("site:stepstone.de Werkstudent Finance Berlin")
    assert rows[0][0] == "Werkstudent Finance Analyst"
    assert d.last_provider == "bing"

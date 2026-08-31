import httpx
import pytest
from app.services.discovery import PublicDiscovery

@pytest.mark.asyncio
async def test_discovery_falls_back_to_bing():
    class FakeClient:
        async def get(self, url, **kwargs):
            if "duckduckgo" in url:
                return httpx.Response(503, request=httpx.Request("GET", url))
            html = '<li class="b_algo"><h2><a href="https://stepstone.de/stellenangebote--Werkstudent-Finance-Analyst-Berlin--123.html">Werkstudent Finance Analyst</a></h2><div class="b_caption"><p>Example GmbH · Berlin</p></div></li>'
            return httpx.Response(200, text=html, request=httpx.Request("GET", url))
    d = PublicDiscovery(FakeClient(), max_results=5, min_interval=0.1)
    rows = await d.search_site("Finance Analyst", "Berlin", "stepstone", "Werkstudent")
    assert rows[0].title == "Werkstudent Finance Analyst"
    assert rows[0].url.endswith("123.html")
    assert d.last_provider == "bing"

def test_unwrap_bing_direct_target():
    wrapped = "https://www.bing.com/ck/a?u=https%3A%2F%2Fwww.stepstone.de%2Fstellenangebote--job--123.html"
    assert PublicDiscovery._unwrap(wrapped) == "https://www.stepstone.de/stellenangebote--job--123.html"

def test_unwrap_bing_a1_base64_redirect():
    import base64
    target = "https://www.stepstone.de/stellenangebote--job--456.html"
    encoded = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
    wrapped = f"https://www.bing.com/ck/a?u=a1{encoded}&ntb=1"
    assert PublicDiscovery._unwrap(wrapped) == target

@pytest.mark.asyncio
async def test_bing_accepts_stepstone_job_candidate_with_job_terms():
    class FakeClient:
        async def get(self, url, **kwargs):
            html = '<li class="b_algo"><h2><a href="https://www.stepstone.de/stellenangebote--Werkstudent-Finance-Berlin--999.html">Werkstudent Finance</a></h2><div class="b_caption"><p>Werkstudent Finance · Berlin · Bewerben</p></div></li>'
            return httpx.Response(200, text=html, request=httpx.Request("GET", url))
    d = PublicDiscovery(FakeClient(), max_results=5, min_interval=0.1)
    rows = await d._engine('site:stepstone.de "Werkstudent" "Finance" "Berlin"', 'stepstone', 'bing')
    assert len(rows) == 1
    assert rows[0].url.endswith('999.html')

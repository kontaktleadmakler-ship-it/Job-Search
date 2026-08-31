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


def test_unwrap_bing_direct_target():
    wrapped = "https://www.bing.com/ck/a?u=https%3A%2F%2Fwww.stepstone.de%2Fjob%2F123"
    assert PublicDiscovery._unwrap(wrapped) == "https://www.stepstone.de/job/123"


def test_unwrap_bing_a1_base64_redirect():
    import base64
    target = "https://www.stepstone.de/job/456?utm_source=bing"
    encoded = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
    wrapped = f"https://www.bing.com/ck/a?u=a1{encoded}&ntb=1"
    assert PublicDiscovery._unwrap(wrapped) == target


@pytest.mark.asyncio
async def test_bing_parser_accepts_wrapped_stepstone_url():
    import base64
    target = "https://www.stepstone.de/job/789"
    encoded = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
    html = (
        '<li class="b_algo"><h2>'
        f'<a href="https://www.bing.com/ck/a?u=a1{encoded}&ntb=1">'
        'Werkstudent Risk Management</a>'
        '</h2></li>'
    )

    class FakeClient:
        async def get(self, url):
            return httpx.Response(200, text=html, request=httpx.Request("GET", url))

    d = PublicDiscovery(FakeClient(), max_results=5, min_interval=0.1)
    rows = await d._bing("site:stepstone.de Werkstudent Risk Management Berlin")
    assert rows == [("Werkstudent Risk Management", target)]
    assert d.last_provider == "bing"

import asyncio
import base64
import logging
import re
import time
from urllib.parse import quote_plus, urlparse, parse_qs, unquote
import httpx
from bs4 import BeautifulSoup
from app.collectors.base import RawJob, safe_job_url, normalize_space
from app.services.job_parser import infer_employment_type

log = logging.getLogger(__name__)

SOURCE_DOMAINS = {
    "indeed": ("indeed.com", "de.indeed.com"),
    "stepstone": ("stepstone.de",),
    "xing": ("xing.com",),
    "monster": ("monster.de", "monster.com"),
    "jobware": ("jobware.de",),
    "kimeta": ("kimeta.de",),
    "linkedin": ("linkedin.com",),
    "arbeitsagentur": ("arbeitsagentur.de",),
}

def is_direct_job_url(url: str, source: str) -> bool:
    if not safe_job_url(url):
        return False
    host = urlparse(url).netloc.lower().split(":")[0]
    path = urlparse(url).path.lower()
    domains = SOURCE_DOMAINS.get(source, ())
    if domains and not any(host == d or host.endswith("." + d) for d in domains):
        return False
    if source == "indeed":
        return ("/viewjob" in path or "/rc/clk" in path or "/jobs/" in path) and ("jk=" in urlparse(url).query or "/viewjob" in path or "/rc/clk" in path)
    if source == "stepstone":
        return bool(re.search(r"/stellenangebote--.+", path)) or bool(re.search(r"/job[s]?/\d+", path))
    if source == "linkedin":
        return bool(re.search(r"/jobs/view/\d+", path))
    if source == "xing":
        return "/jobs/" in path and len(path.split("/")) >= 3
    if source == "arbeitsagentur":
        return "/jobsuche/jobdetail/" in path
    if source in {"monster", "jobware", "kimeta"}:
        return any(token in path for token in ("/job/", "/jobs/", "/stellenangebot", "/stellenangebote"))
    return False


GENERIC_PORTAL_HOSTS = {
    "indeed.com", "de.indeed.com", "stepstone.de", "linkedin.com", "xing.com",
    "monster.de", "monster.com", "jobware.de", "kimeta.de", "arbeitsagentur.de",
}

def is_generic_job_url(url: str) -> bool:
    if not safe_job_url(url):
        return False
    parsed = urlparse(url)
    host = parsed.netloc.lower().split(":")[0]
    if any(x in host for x in ("duckduckgo.", "bing.", "google.")):
        return False
    if any(host == d or host.endswith("." + d) for d in GENERIC_PORTAL_HOSTS):
        return False
    path = parsed.path.lower().rstrip("/")
    if path in {"", "/", "/jobs", "/job", "/career", "/careers", "/karriere", "/stellenangebote"}:
        return False
    return any(token in path for token in (
        "/job/", "/jobs/", "/stellenangebot/", "/stellenangebote-",
        "/stellenanzeige", "/karriere/jobs/", "/career/jobs/", "/careers/",
        "/vacancy/", "/vacancies/", "/position/", "/positions/", "/jobdetail/"
    ))

class PublicDiscovery:
    def __init__(self, client: httpx.AsyncClient, max_results=10, min_interval=0.75, request_timeout=8.0):
        self.client = client
        self.max_results = max(1, int(max_results))
        self.min_interval = max(0.1, float(min_interval))
        self.request_timeout = max(2.0, float(request_timeout))
        self._rate_lock = asyncio.Lock()
        self._last_request = 0.0
        self.last_provider = None
        self.last_error = None
        self._ddg_failures = self._bing_failures = 0
        self._ddg_disabled = self._bing_disabled = False

    async def _throttle(self):
        async with self._rate_lock:
            wait = self.min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()

    async def _get(self, url: str) -> httpx.Response:
        await self._throttle()
        return await self.client.get(url, timeout=self.request_timeout)

    @staticmethod
    def _unwrap(url: str) -> str:
        try:
            current = unquote(url)
            p = urlparse(current)
            qs = parse_qs(p.query)
            for key in ("uddg", "url"):
                value = qs.get(key, [None])[0]
                if value and urlparse(unquote(value)).scheme in {"http", "https"}:
                    return unquote(value)
            value = qs.get("u", [None])[0]
            if value:
                value = unquote(value)
                candidates = [value[2:]] if value.startswith("a1") else []
                candidates.append(value)
                for encoded in candidates:
                    try:
                        padded = encoded + "=" * (-len(encoded) % 4)
                        decoded = base64.urlsafe_b64decode(padded).decode()
                        if urlparse(decoded).scheme in {"http", "https"}:
                            return decoded
                    except Exception:
                        pass
                if urlparse(value).scheme in {"http", "https"}:
                    return value
        except Exception:
            pass
        return url

    @staticmethod
    def _result(title: str, href: str, snippet: str, source: str) -> RawJob | None:
        href = PublicDiscovery._unwrap(href)
        title = normalize_space(title)
        snippet = normalize_space(snippet)
        if not title or len(title) < 8 or not safe_job_url(href):
            return None
        if not is_direct_job_url(href, source):
            return None
        text = " ".join((title, snippet))
        return RawJob(
            title=title[:500], description=snippet[:4000], url=href,
            source=source, employment_type=infer_employment_type(text)
        )

    async def _ddg(self, q: str, source: str) -> list[RawJob]:
        last_exc = None
        for endpoint in ("https://html.duckduckgo.com/html/?q=", "https://lite.duckduckgo.com/lite/?q="):
            try:
                r = await self._get(endpoint + quote_plus(q))
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "html.parser")
                out = []
                for a in soup.select("a.result__a, a.result-link"):
                    container = a.find_parent(class_="result") or a.parent
                    snippet_node = container.select_one(".result__snippet") if container else None
                    raw = self._result(a.get_text(" ", strip=True), a.get("href", ""), snippet_node.get_text(" ", strip=True) if snippet_node else "", source)
                    if raw:
                        out.append(raw)
                if out:
                    self.last_provider = "duckduckgo"; self.last_error = None
                    return out[:self.max_results]
                raise RuntimeError("keine direkten Stellenanzeigen in DDG-Ergebnissen")
            except Exception as exc:
                last_exc = exc
        raise RuntimeError(f"DuckDuckGo unavailable: {last_exc}")

    async def _bing(self, q: str, source: str) -> list[RawJob]:
        r = await self._get("https://www.bing.com/search?q=" + quote_plus(q) + "&count=" + str(max(self.max_results, 10)))
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        out = []
        for item in soup.select("li.b_algo"):
            a = item.select_one("h2 a")
            if not a:
                continue
            snippet_node = item.select_one(".b_caption p")
            raw = self._result(a.get_text(" ", strip=True), a.get("href", ""), snippet_node.get_text(" ", strip=True) if snippet_node else "", source)
            if raw:
                out.append(raw)
        if not out:
            raise RuntimeError("Bing: keine direkten Stellenanzeigen")
        self.last_provider = "bing"; self.last_error = None
        return out[:self.max_results]

    async def search(self, q: str, source: str) -> list[RawJob]:
        self.last_error = None
        errors = []
        if not self._ddg_disabled:
            try:
                result = await self._ddg(q, source)
                self._ddg_failures = 0
                return result
            except Exception as exc:
                errors.append(f"duckduckgo: {exc}")
                self._ddg_failures += 1
                if self._ddg_failures >= 2:
                    self._ddg_disabled = True
        if not self._bing_disabled:
            try:
                result = await self._bing(q, source)
                self._bing_failures = 0
                return result
            except Exception as exc:
                errors.append(f"bing: {exc}")
                self._bing_failures += 1
                if self._bing_failures >= 2:
                    self._bing_disabled = True
        self.last_provider = None
        self.last_error = " | ".join(errors) or "keine Discovery-Provider verfügbar"
        raise RuntimeError(self.last_error)

    async def search_site(self, query: str, location: str, source: str, employment_type: str) -> list[RawJob]:
        domain = SOURCE_DOMAINS[source][0]
        q = f'site:{domain} "{employment_type}" "{query}" "{location}"'
        return await self.search(q, source)

    async def search_generic(self, query: str, location: str, employment_type: str) -> list[RawJob]:
        q = f'"{employment_type}" "{query}" "{location}" -jobsuche -stellenmarkt'
        return await self._generic_search(q, employment_type)

    async def _generic_search(self, q: str, employment_type: str) -> list[RawJob]:
        for provider in ("duckduckgo", "bing"):
            try:
                if provider == "duckduckgo":
                    r = await self._get("https://html.duckduckgo.com/html/?q=" + quote_plus(q))
                    r.raise_for_status()
                    soup = BeautifulSoup(r.text, "html.parser")
                    out = []
                    for a in soup.select("a.result__a"):
                        container = a.find_parent(class_="result") or a.parent
                        sn = container.select_one(".result__snippet") if container else None
                        href = self._unwrap(a.get("href", ""))
                        title = normalize_space(a.get_text(" ", strip=True))
                        snippet = normalize_space(sn.get_text(" ", strip=True) if sn else "")
                        inferred = infer_employment_type(" ".join((title, snippet)))
                        if safe_job_url(href) and is_generic_job_url(href) and inferred == employment_type:
                            out.append(RawJob(title=title, description=snippet, url=href, source="generic", employment_type=inferred))
                    if out:
                        self.last_provider = "duckduckgo"; return out[:self.max_results]
                else:
                    r = await self._get("https://www.bing.com/search?q=" + quote_plus(q))
                    r.raise_for_status()
                    soup = BeautifulSoup(r.text, "html.parser")
                    out = []
                    for item in soup.select("li.b_algo"):
                        a = item.select_one("h2 a")
                        if not a: continue
                        sn = item.select_one(".b_caption p")
                        href = self._unwrap(a.get("href", ""))
                        title = normalize_space(a.get_text(" ", strip=True))
                        snippet = normalize_space(sn.get_text(" ", strip=True) if sn else "")
                        inferred = infer_employment_type(" ".join((title, snippet)))
                        if is_generic_job_url(href) and inferred == employment_type:
                            out.append(RawJob(title=title, description=snippet, url=href, source="generic", employment_type=inferred))
                    if out:
                        self.last_provider = "bing"; return out[:self.max_results]
            except Exception:
                continue
        raise RuntimeError("keine generischen Stellenanzeigen gefunden")

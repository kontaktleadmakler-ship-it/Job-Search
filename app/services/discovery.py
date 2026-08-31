import asyncio
import logging
import time
from urllib.parse import quote_plus, urlparse, parse_qs, unquote
import base64
import httpx
from bs4 import BeautifulSoup
from app.collectors.base import RawJob, safe_job_url, normalize_space

log = logging.getLogger(__name__)

class PublicDiscovery:
    """Public search-engine discovery only. No login, CAPTCHA or anti-bot bypass."""

    def __init__(self, client: httpx.AsyncClient, max_results=10, min_interval=0.75, request_timeout=8.0):
        self.client = client
        self.max_results = max(1, int(max_results))
        self.min_interval = max(0.1, float(min_interval))
        self.request_timeout = max(2.0, float(request_timeout))
        self._rate_lock = asyncio.Lock()
        self._last_request = 0.0
        self.last_provider = None
        self.last_error = None
        # Circuit breaker: if a provider fails repeatedly during this scan
        # (e.g. blocked from this host's IP), stop retrying it on every
        # single query and go straight to the next provider instead. This
        # avoids burning the full request_timeout twice per query for the
        # whole duration of a scan with many role queries.
        self._ddg_failures = 0
        self._ddg_disabled = False
        self._bing_failures = 0
        self._bing_disabled = False

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
        """Unwrap common public-search redirect URLs without following them.

        Bing commonly uses ``/ck/a?...&u=a1<base64url>`` links.  The target
        can therefore be hidden behind URL encoding and a URL-safe base64
        payload.  We decode only the redirect value and never make a request
        to the redirect URL here.
        """
        try:
            current = unquote(url)
            p = urlparse(current)
            qs = parse_qs(p.query)

            for key in ("uddg", "url"):
                value = qs.get(key, [None])[0]
                if value:
                    target = unquote(value)
                    if urlparse(target).scheme in {"http", "https"}:
                        return target

            bing_u = qs.get("u", [None])[0]
            if bing_u:
                value = unquote(bing_u)
                # Bing's public result redirect format uses an ``a1`` prefix
                # followed by URL-safe base64.
                candidates = [value[2:]] if value.startswith("a1") else []
                candidates.append(value)
                for encoded in candidates:
                    try:
                        padded = encoded + "=" * (-len(encoded) % 4)
                        decoded = base64.urlsafe_b64decode(padded).decode("utf-8")
                        if urlparse(decoded).scheme in {"http", "https"}:
                            return decoded
                    except (ValueError, UnicodeDecodeError):
                        continue
                if urlparse(value).scheme in {"http", "https"}:
                    return value
        except Exception:
            pass
        return url

    async def _ddg(self, q: str) -> list[tuple[str, str]]:
        endpoints = [
            "https://html.duckduckgo.com/html/?q=",
            "https://lite.duckduckgo.com/lite/?q=",
        ]
        last_exc = None
        for endpoint in endpoints:
            try:
                r = await self._get(endpoint + quote_plus(q))
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "html.parser")
                out = []
                selectors = ["a.result__a", "a.result-link", "a[href]"]
                for selector in selectors:
                    candidates = soup.select(selector)
                    if not candidates:
                        continue
                    for a in candidates:
                        href = self._unwrap(a.get("href", ""))
                        title = normalize_space(a.get_text(" ", strip=True))
                        if title and len(title) >= 8 and safe_job_url(href):
                            out.append((title, href))
                    if out:
                        break
                if out:
                    self.last_provider = "duckduckgo"
                    self.last_error = None
                    return out[:self.max_results]
                raise RuntimeError("search engine returned no usable results")
            except Exception as exc:
                last_exc = exc
        raise RuntimeError(f"DuckDuckGo unavailable: {last_exc}")

    async def _bing(self, q: str) -> list[tuple[str, str]]:
        url = "https://www.bing.com/search?q=" + quote_plus(q) + "&count=" + str(self.max_results)
        r = await self._get(url)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        out = []
        for a in soup.select("li.b_algo h2 a, h2 a"):
            href = self._unwrap(a.get("href", ""))
            title = normalize_space(a.get_text(" ", strip=True))
            if title and len(title) >= 8 and safe_job_url(href):
                out.append((title, href))
        if not out:
            raise RuntimeError("Bing returned no usable results")
        self.last_provider = "bing"
        self.last_error = None
        return out[:self.max_results]

    async def search(self, q: str) -> list[tuple[str, str]]:
        """Try the configured public provider, then a second public provider.

        Uses a per-instance circuit breaker: once a provider has failed
        repeatedly in this scan, it is skipped for subsequent queries so a
        single blocked provider doesn't cost a full timeout on every query.
        """
        self.last_error = None
        errors = []
        if not self._ddg_disabled:
            try:
                result = await self._ddg(q)
                self._ddg_failures = 0
                return result
            except Exception as exc:
                errors.append(f"duckduckgo: {exc}")
                self._ddg_failures += 1
                if self._ddg_failures >= 2:
                    self._ddg_disabled = True
                    log.warning("DuckDuckGo scheint blockiert/unerreichbar zu sein - wird für den Rest dieses Scans übersprungen")
        if not self._bing_disabled:
            try:
                result = await self._bing(q)
                self._bing_failures = 0
                return result
            except Exception as exc:
                errors.append(f"bing: {exc}")
                self._bing_failures += 1
                if self._bing_failures >= 2:
                    self._bing_disabled = True
                    log.warning("Bing scheint blockiert/unerreichbar zu sein - wird für den Rest dieses Scans übersprungen")
        self.last_provider = None
        self.last_error = " | ".join(errors) if errors else "alle Discovery-Provider deaktiviert (zuvor wiederholt fehlgeschlagen)"
        raise RuntimeError(self.last_error)

    async def search_site(self, query: str, location: str, domain: str) -> list[RawJob]:
        try:
            rows = await self.search(f"site:{domain} {query} {location}")
        except Exception as e:
            log.warning("public discovery failed for %s: %s", domain, e)
            return []
        return [RawJob(title=t, url=u, source=domain) for t, u in rows if domain in urlparse(u).netloc.lower()]

    async def search_generic(self, query: str, location: str) -> list[RawJob]:
        try:
            rows = await self.search(f'"{query}" "{location}" Werkstudent')
        except Exception as e:
            log.warning("generic discovery failed: %s", e)
            return []
        return [RawJob(title=t, url=u, source="generic") for t, u in rows]

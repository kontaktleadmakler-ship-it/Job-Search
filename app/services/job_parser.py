import json
import re
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup
from app.collectors.base import RawJob, normalize_space, safe_job_url

EMPLOYMENT_PATTERNS = {
    "Werkstudent": [r"\bwerkstudent(?:in)?\b", r"\bworking student\b", r"\bstudentische(?:r|n)? hilfskraft\b", r"\bstudent assistant\b"],
    "Vollzeit": [r"\bvollzeit\b", r"\bfull[- ]?time\b"],
    "Teilzeit": [r"\bteilzeit\b", r"\bpart[- ]?time\b"],
    "Praktikum": [r"\bpraktikum\b", r"\binternship\b", r"\bpraktikant(?:in)?\b"],
}

def infer_employment_type(text: str) -> str:
    for label, patterns in EMPLOYMENT_PATTERNS.items():
        if any(re.search(p, text or "", re.I) for p in patterns):
            return label
    return ""

def _jsonld(soup: BeautifulSoup) -> list[dict]:
    out = []
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.string or node.get_text())
        except Exception:
            continue
        values = data if isinstance(data, list) else [data]
        for item in values:
            if isinstance(item, dict):
                if item.get("@graph") and isinstance(item["@graph"], list):
                    out.extend(x for x in item["@graph"] if isinstance(x, dict))
                else:
                    out.append(item)
    return out

def _value(value):
    if isinstance(value, dict):
        return value.get("name") or value.get("value") or ""
    return value or ""

def parse_html(html: str, url: str, source: str) -> RawJob | None:
    soup = BeautifulSoup(html or "", "html.parser")
    if not safe_job_url(url):
        return None
    text = normalize_space(soup.get_text(" ", strip=True))
    data = next((x for x in _jsonld(soup) if str(x.get("@type", "")).lower() in {"jobposting", "job"}), None)

    title = normalize_space(_value(data.get("title")) if data else "")
    if not title:
        for sel in ("h1", "meta[property='og:title']", "title"):
            node = soup.select_one(sel)
            if node:
                title = normalize_space(node.get("content") if node.name == "meta" else node.get_text(" ", strip=True))
                if title:
                    break
    if not title:
        return None

    company = normalize_space(_value((data or {}).get("hiringOrganization")))
    location = ""
    if data:
        loc = data.get("jobLocation")
        if isinstance(loc, list):
            loc = loc[0] if loc else {}
        if isinstance(loc, dict):
            addr = loc.get("address", loc)
            if isinstance(addr, dict):
                location = normalize_space(" ".join(str(addr.get(k, "")) for k in ("streetAddress", "postalCode", "addressLocality", "addressRegion", "addressCountry")))
            else:
                location = normalize_space(_value(loc))
        elif loc:
            location = normalize_space(str(loc))

    if not company:
        for sel in ("[data-company]", ".company", "[class*='company']", "[class*='employer']"):
            node = soup.select_one(sel)
            if node:
                company = normalize_space(node.get("data-company") or node.get_text(" ", strip=True))
                if company:
                    break
    if not location:
        for sel in ("[data-location]", ".location", "[class*='location']"):
            node = soup.select_one(sel)
            if node:
                location = normalize_space(node.get("data-location") or node.get_text(" ", strip=True))
                if location:
                    break

    description = normalize_space(_value((data or {}).get("description"))) or text[:10000]
    employment = normalize_space(str((data or {}).get("employmentType", "")))
    if employment:
        employment = {"FULL_TIME": "Vollzeit", "PART_TIME": "Teilzeit", "INTERN": "Praktikum", "CONTRACTOR": "Teilzeit"}.get(employment.upper(), employment)
    employment = employment or infer_employment_type(" ".join((title, description, text)))

    hours = ""
    hour_match = re.search(r"\b(\d{1,2})\s*(?:-|–|bis)?\s*(?:\d{1,2})?\s*(?:stunden|hours|std\.?)\b", text, re.I)
    if hour_match:
        hours = normalize_space(hour_match.group(0))

    salary = ""
    salary_match = re.search(r"(?:€\s?\d[\d.]*|\d[\d.]*\s?€|\d[\d.]*\s?(?:EUR|Euro)\b)[^.!?]{0,40}", text, re.I)
    if salary_match:
        salary = normalize_space(salary_match.group(0))

    remote_type = ""
    if re.search(r"\bhybrid\b", text, re.I): remote_type = "Hybrid"
    elif re.search(r"\b(remote|homeoffice|home office)\b", text, re.I): remote_type = "Remote"
    elif re.search(r"\bvor ort\b|\bon[- ]?site\b", text, re.I): remote_type = "Vor Ort"

    posted_date = None
    date_value = (data or {}).get("datePosted")
    if date_value:
        try:
            posted_date = datetime.fromisoformat(str(date_value).replace("Z", "+00:00"))
        except ValueError:
            pass

    job_id = ""
    path = urlparse(url).path
    qs = parse_qs(urlparse(url).query)
    if source == "indeed":
        job_id = (qs.get("jk") or [""])[0]
    elif source == "arbeitsagentur":
        m = re.search(r"/jobdetail/([^/?#]+)", path)
        job_id = m.group(1) if m else ""

    return RawJob(
        title=title, company=company[:300], location=location[:300],
        description=description[:10000], url=url, source=source,
        source_job_id=job_id or None, employment_type=employment, hours=hours,
        salary=salary, remote_type=remote_type, posted_date=posted_date
    )

def serialize_reasons(reasons: list[str]) -> str:
    return json.dumps(reasons, ensure_ascii=False)

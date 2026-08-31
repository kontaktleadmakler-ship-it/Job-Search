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
    "Minijob": [r"\bminijob\b", r"\bmini[- ]job\b", r"\bgeringfügig\b"],
    "Trainee": [r"\btrainee(?:programm)?\b", r"\bgraduate programme\b"],
}


def infer_employment_type(text: str) -> str:
    found = []
    for label, patterns in EMPLOYMENT_PATTERNS.items():
        if any(re.search(p, text or "", re.I) for p in patterns):
            found.append(label)
    # Prefer the specific student/intern labels over generic full/part time labels.
    for label in ("Werkstudent", "Praktikum", "Minijob", "Trainee", "Teilzeit", "Vollzeit"):
        if label in found:
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
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            if isinstance(graph, list):
                out.extend(x for x in graph if isinstance(x, dict))
            else:
                out.append(item)
    return out


def _is_jobposting(data: dict) -> bool:
    t = data.get("@type", "")
    if isinstance(t, list):
        return any(str(x).lower() == "jobposting" for x in t)
    return str(t).lower() == "jobposting"


def _value(value):
    if isinstance(value, dict):
        return value.get("name") or value.get("value") or ""
    return value or ""


def _location_value(value) -> str:
    if isinstance(value, list):
        return " | ".join(_location_value(x) for x in value if x)
    if isinstance(value, dict):
        addr = value.get("address", value)
        if isinstance(addr, dict):
            return normalize_space(" ".join(str(addr.get(k, "")) for k in ("streetAddress", "postalCode", "addressLocality", "addressRegion", "addressCountry")))
        return normalize_space(str(addr))
    return normalize_space(str(value or ""))


def _salary_value(value) -> str:
    if isinstance(value, list):
        return " - ".join(_salary_value(x) for x in value if x)
    if isinstance(value, dict):
        val = value.get("value")
        if isinstance(val, dict):
            low = val.get("minValue") or val.get("value")
            high = val.get("maxValue")
            if low and high:
                return f"{low}-{high}"
            val = low
        return normalize_space(str(val or value.get("name") or ""))
    return normalize_space(str(value or ""))


def has_jobposting_jsonld(html: str) -> bool:
    soup = BeautifulSoup(html or "", "html.parser")
    return any(_is_jobposting(x) for x in _jsonld(soup))


def parse_html(html: str, url: str, source: str) -> RawJob | None:
    soup = BeautifulSoup(html or "", "html.parser")
    if not safe_job_url(url):
        return None
    text = normalize_space(soup.get_text(" ", strip=True))
    jsonld = _jsonld(soup)
    data = next((x for x in jsonld if _is_jobposting(x)), None)

    title = normalize_space(_value(data.get("title")) if data else "")
    if not title:
        for sel in ("h1", "meta[property='og:title']", "meta[name='twitter:title']", "title"):
            node = soup.select_one(sel)
            if node:
                title = normalize_space(node.get("content") if node.name == "meta" else node.get_text(" ", strip=True))
                if title:
                    break
    if not title:
        return None

    company = normalize_space(_value((data or {}).get("hiringOrganization")))
    location = _location_value((data or {}).get("jobLocation")) if data else ""

    if not company:
        for sel in ("[data-company]", ".company", "[class*='company']", "[class*='employer']", "[itemprop='hiringOrganization']"):
            node = soup.select_one(sel)
            if node:
                company = normalize_space(node.get("data-company") or node.get("content") or node.get_text(" ", strip=True))
                if company:
                    break
    if not location:
        for sel in ("[data-location]", ".location", "[class*='location']", "[itemprop='jobLocation']"):
            node = soup.select_one(sel)
            if node:
                location = normalize_space(node.get("data-location") or node.get("content") or node.get_text(" ", strip=True))
                if location:
                    break

    description = normalize_space(_value((data or {}).get("description"))) or text[:10000]
    salary = _salary_value((data or {}).get("baseSalary") or (data or {}).get("salary"))
    remote_type = ""
    if data:
        job_location_type = str(data.get("jobLocationType", ""))
        if job_location_type.upper() == "TELECOMMUTE":
            remote_type = "Remote"
        elif job_location_type:
            remote_type = job_location_type
    if not remote_type and re.search(r"\b(remote|remote[- ]first|100\s*%\s*remote)\b", text, re.I):
        remote_type = "Remote"
    elif not remote_type and re.search(r"\bhybrid|hybrid[- ]arbeit|mobiles arbeiten\b", text, re.I):
        remote_type = "Hybrid"

    posted_date = None
    if data and data.get("datePosted"):
        try:
            posted_date = datetime.fromisoformat(str(data["datePosted"]).replace("Z", "+00:00"))
        except ValueError:
            pass

    employment_value = (data or {}).get("employmentType", "")
    if isinstance(employment_value, list):
        employment_value = " ".join(str(x) for x in employment_value)
    employment = normalize_space(str(employment_value))
    mapping = {"FULL_TIME": "Vollzeit", "PART_TIME": "Teilzeit", "INTERN": "Praktikum", "CONTRACTOR": "Teilzeit", "TEMPORARY": "Teilzeit"}
    if employment:
        employment = mapping.get(employment.upper(), employment)
    inferred = infer_employment_type(" ".join((title, description)))
    # Prefer an explicit JSON-LD type; otherwise infer from the actual page text.
    employment = employment or inferred

    path = urlparse(url).path
    qs = parse_qs(urlparse(url).query)
    job_id = ""
    if source == "indeed":
        job_id = (qs.get("jk") or [""])[0]
    elif source == "arbeitsagentur":
        m = re.search(r"/jobdetail/([^/?#]+)", path)
        job_id = m.group(1) if m else ""
    elif source == "linkedin":
        m = re.search(r"/jobs/view/(\d+)", path)
        job_id = m.group(1) if m else ""

    hours_match = re.search(r"\b(\d{1,2}(?:[–-]\d{1,2})?)\s*(?:Stunden|Std\.?|hours|hrs?)(?:\s*(?:/|pro)\s*(?:Woche|week))?\b", text, re.I)
    hours = hours_match.group(1) + " Stunden" if hours_match else ""

    return RawJob(
        title=title, company=company[:300], location=location[:300],
        description=description[:10000], url=url, source=source,
        source_job_id=job_id or None, employment_type=employment, hours=hours,
        salary=salary, remote_type=remote_type, posted_date=posted_date
    )


def serialize_reasons(reasons: list[str]) -> str:
    return json.dumps(reasons, ensure_ascii=False)

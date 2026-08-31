import json
import re
from datetime import datetime
from bs4 import BeautifulSoup
from app.collectors.base import RawJob, normalize_space, safe_job_url

def parse_html(html: str, url: str, source: str) -> RawJob | None:
    soup = BeautifulSoup(html or "", "html.parser")
    title = ""
    for sel in ("h1", "meta[property='og:title']", "title"):
        node = soup.select_one(sel)
        if node:
            title = node.get("content") if node.name == "meta" else node.get_text(" ", strip=True)
            if title:
                break
    title = normalize_space(title)
    if not title or not safe_job_url(url):
        return None
    text = normalize_space(soup.get_text(" ", strip=True))
    company = ""
    for sel in ("[data-company]", ".company", "[class*='company']"):
        node = soup.select_one(sel)
        if node:
            company = normalize_space(node.get("data-company") or node.get_text(" ", strip=True))
            if company:
                break
    location = ""
    for sel in ("[data-location]", ".location", "[class*='location']"):
        node = soup.select_one(sel)
        if node:
            location = normalize_space(node.get("data-location") or node.get_text(" ", strip=True))
            if location:
                break
    return RawJob(
        title=title, company=company, location=location,
        description=text[:10000], url=url, source=source
    )

def extract_jobs_from_search_html(html: str, source: str) -> list[RawJob]:
    soup = BeautifulSoup(html or "", "html.parser")
    jobs = []
    for a in soup.select("a[href]"):
        title = normalize_space(a.get_text(" ", strip=True))
        href = a.get("href", "")
        if not title or not href or len(title) < 8:
            continue
        low = (title + " " + href).lower()
        if not any(x in low for x in ("werkstudent", "student", "finance", "risk", "controlling", "recruit")):
            continue
        jobs.append(RawJob(title=title, url=href, source=source))
    return jobs[:100]

def serialize_reasons(reasons: list[str]) -> str:
    return json.dumps(reasons, ensure_ascii=False)

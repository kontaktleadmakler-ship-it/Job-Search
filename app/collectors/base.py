from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
import re

@dataclass
class RawJob:
    title: str
    company: str = ""
    location: str = ""
    description: str = ""
    url: str = ""
    source: str = ""
    source_job_id: str | None = None
    employment_type: str = ""
    hours: str = ""
    salary: str = ""
    remote_type: str = ""
    posted_date: Any = None

class JobCollector:
    name = "base"
    async def search(self, query: str, location: str, filters: dict) -> list[RawJob]:
        raise NotImplementedError

def safe_job_url(url: str) -> bool:
    try:
        p = urlparse(url)
        return p.scheme in {"http", "https"} and bool(p.netloc)
    except Exception:
        return False

def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()

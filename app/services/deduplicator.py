import hashlib
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from app.collectors.base import RawJob

TRACKING = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "referrer", "trk", "source"}


def _norm(value: str) -> str:
    value = (value or "").lower().replace("ß", "ss")
    return re.sub(r"[^a-z0-9äöü\s]", " ", value)


def canonicalize_url(url: str) -> str:
    p = urlsplit((url or "").strip())
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k.lower() not in TRACKING]
    path = re.sub(r"/+$", "", p.path) or "/"
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, urlencode(query), ""))


def fingerprint(job: RawJob) -> str:
    # Stable cross-source identity. Keep the fingerprint deliberately limited to
    # fields that normally survive portal-specific formatting differences.
    raw = "|".join([
        _norm(job.company),
        re.sub(r"\s+", " ", _norm(job.title)).strip(),
        re.sub(r"\s+", " ", _norm(job.location)).strip(),
    ])
    return hashlib.sha256(raw.encode()).hexdigest()


def identity_keys(job: RawJob) -> list[str]:
    keys = []
    if job.source and job.source_job_id:
        keys.append(f"source_id:{job.source}:{job.source_job_id}")
    if job.url:
        keys.append(f"url:{canonicalize_url(job.url)}")
    keys.append(f"fp:{fingerprint(job)}")
    return keys

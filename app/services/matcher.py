import re
from datetime import datetime, timezone, timedelta
from app.schemas import SearchProfile
from app.collectors.base import RawJob


def _has(text: str, words: list[str]) -> bool:
    t = (text or "").lower()
    return any(w.lower() in t for w in words if w)


def _hours_match(job: RawJob, profile: SearchProfile) -> bool:
    nums = [int(x) for x in re.findall(r"\b(\d{1,2})\s*(?:-|–|bis)?\s*(?:stunden|hours|h)\b", (job.hours or "").lower())]
    if not nums:
        nums = [int(x) for x in re.findall(r"\b(\d{1,2})\b", (job.hours or "") + " " + (job.description or ""))]
    return any(profile.hours_min <= n <= profile.hours_max for n in nums)


def score_job(job: RawJob, profile: SearchProfile) -> tuple[int, list[str]]:
    text = " ".join([job.title, job.company, job.location, job.description, job.employment_type, job.hours, job.remote_type])
    score, reasons = 0, []
    selected_types = profile.employment_types or ["Werkstudent"]
    type_aliases = {
        "Werkstudent": ["werkstudent", "working student", "studentische hilfskraft"],
        "Vollzeit": ["vollzeit", "full-time", "full time"],
        "Teilzeit": ["teilzeit", "part-time", "part time"],
        "Praktikum": ["praktikum", "praktikant", "internship", "intern"],
    }
    if any(_has(text, type_aliases.get(t, [t])) for t in selected_types):
        score += 30; reasons.append(next((t for t in selected_types if any(_has(text, type_aliases.get(t, [t])) for _ in [0])), "passende Anstellungsart"))
    else:
        score -= 25; reasons.append("− Anstellungsart nicht bestätigt")
    if _has(job.location or text, [profile.location]):
        score += 20; reasons.append(profile.location)
    if _has(text, profile.target_roles or profile.keywords):
        score += 20; reasons.append("passender Fachbereich")
    if _has(text, profile.skills):
        score += 10; reasons.append("passende Skills")
    if _hours_match(job, profile):
        score += 10; reasons.append(f"{profile.hours_min}–{profile.hours_max} Stunden")
    if _has(text, profile.remote_types):
        score += 5; reasons.append("Remote / Hybrid")
    if job.salary:
        score += 3; reasons.append("Gehalt angegeben")
    if job.posted_date:
        now = datetime.now(timezone.utc); posted = job.posted_date
        if posted.tzinfo is None: posted = posted.replace(tzinfo=timezone.utc)
        if now - posted <= timedelta(days=3): score += 5; reasons.append("aktuelles Angebot")
    negatives = [(profile.exclusions, 35, "Ausschlussbegriff"), (["senior"], 25, "Senior"), (["director"], 25, "Director")]
    for words, penalty, reason in negatives:
        if _has(text, words): score -= penalty; reasons.append(f"− {reason}")
    if job.location and profile.location.lower() not in job.location.lower():
        score -= 15; reasons.append("− falscher Standort")
    return max(0, min(100, score)), reasons

import re
from datetime import datetime, timezone, timedelta
from app.schemas import SearchProfile
from app.collectors.base import RawJob

def _has(text: str, words: list[str]) -> bool:
    t = (text or "").lower()
    return any(w.lower() in t for w in words if w)

def _hours_match(job: RawJob, profile: SearchProfile) -> bool:
    s = (job.hours or "").lower()
    nums = [int(x) for x in re.findall(r"\b(\d{1,2})\b", s)]
    if not nums:
        return False
    return any(profile.hours_min <= n <= profile.hours_max for n in nums)

def score_job(job: RawJob, profile: SearchProfile) -> tuple[int, list[str]]:
    text = " ".join([job.title, job.company, job.location, job.description, job.employment_type, job.hours, job.remote_type])
    score, reasons = 0, []
    if _has(text, ["werkstudent"]):
        score += 25; reasons.append("Werkstudent")
    if _has(job.location or text, [profile.location, "berlin"]):
        score += 20; reasons.append("Berlin")
    if _has(text, profile.keywords):
        score += 15; reasons.append("passender Fachbereich")
    if _hours_match(job, profile):
        score += 10; reasons.append(f"{profile.hours_min}–{profile.hours_max} Stunden")
    if _has(text, profile.remote_types):
        score += 10; reasons.append("Hybrid / Remote")
    if _has(text, profile.keywords):
        score += 10; reasons.append("passende Skills")
    if job.salary:
        score += 5; reasons.append("Gehalt angegeben")
    if job.posted_date:
        now = datetime.now(timezone.utc)
        posted = job.posted_date
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=timezone.utc)
        if now - posted <= timedelta(days=3):
            score += 5; reasons.append("aktuelles Angebot")
    negatives = [
        (["praktikum"], 40, "Praktikum"),
        (["vollzeit", "full time"], 40, "Vollzeit"),
        (["ausbildung"], 40, "Ausbildung"),
        (["senior"], 30, "Senior"),
        (["manager"], 30, "Manager"),
        (["director"], 30, "Director"),
    ]
    for words, penalty, reason in negatives:
        if _has(text, words):
            score -= penalty
            reasons.append(f"− {reason}")
    if job.location and profile.location.lower() not in job.location.lower() and "berlin" not in job.location.lower():
        score -= 20
        reasons.append("− falscher Standort")
    return max(0, min(100, score)), reasons

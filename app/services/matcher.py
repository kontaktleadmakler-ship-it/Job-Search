import re
from datetime import datetime, timezone, timedelta
from app.schemas import SearchProfile
from app.collectors.base import RawJob

ROLE_ALIASES = {
    "data analytics": ["data analytics", "data analyst", "data analysis", "analytics analyst", "reporting analyst", "business analyst"],
    "data analyst": ["data analyst", "data analytics", "data analysis", "analytics analyst", "reporting analyst"],
    "business intelligence": ["business intelligence", "bi analyst", "reporting analyst", "power bi", "business analytics"],
    "risk management": ["risk management", "risk analyst", "risk controlling", "risk & compliance", "risikomanagement", "risikoanalyse", "risk assessment"],
    "risikomanagement": ["risikomanagement", "risk management", "risk analyst", "risikoanalyse", "risk controlling"],
    "finance": ["finance", "financial analyst", "financial planning", "fp&a", "finance operations", "corporate finance"],
    "banking": ["banking", "bank", "banksteuerung", "credit analyst", "kreditrisiko", "financial services"],
    "controlling": ["controlling", "controller", "financial controlling", "reporting", "fp&a"],
    "accounting": ["accounting", "buchhaltung", "financial accounting", "accounts payable", "accounts receivable"],
    "recruiting": ["recruiting", "recruitment", "talent acquisition", "personalbeschaffung", "sourcing"],
    "human resources": ["human resources", "hr", "people operations", "people & culture", "personalwesen"],
    "customer service": ["customer service", "kundenservice", "customer success", "client service"],
    "operations": ["operations", "business operations", "finance operations", "operations analyst"],
    "business development": ["business development", "commercial development", "growth", "partnerships"],
}

TYPE_ALIASES = {
    "Werkstudent": ["werkstudent", "working student", "studentische hilfskraft", "student assistant"],
    "Vollzeit": ["vollzeit", "full-time", "full time"],
    "Teilzeit": ["teilzeit", "part-time", "part time"],
    "Praktikum": ["praktikum", "internship", "praktikant", "intern"],
}

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()

def _has(text: str, words: list[str]) -> bool:
    t = _norm(text)
    return any(_norm(w) in t for w in words if w)

def detect_employment_types(job: RawJob) -> list[str]:
    text = " ".join((job.title, job.description, job.employment_type, job.hours))
    return [label for label, aliases in TYPE_ALIASES.items() if _has(text, aliases)]

def _hours_match(job: RawJob, profile: SearchProfile) -> bool:
    nums = [int(x) for x in re.findall(r"\b(\d{1,2})\b", _norm(job.hours))]
    return bool(nums) and any(profile.hours_min <= n <= profile.hours_max for n in nums)

def _aliases(role: str) -> list[str]:
    r = _norm(role)
    return list(dict.fromkeys([role] + ROLE_ALIASES.get(r, [])))

def _wanted_types(profile: SearchProfile) -> list[str]:
    return list(dict.fromkeys(x for x in (profile.employment_types or ["Werkstudent"]) if x in TYPE_ALIASES))

def score_job(job: RawJob, profile: SearchProfile) -> tuple[int, list[str]]:
    title = _norm(job.title)
    desc = _norm(job.description)
    location = _norm(job.location)
    full = " ".join(filter(None, [title, desc, location, _norm(job.company), _norm(job.employment_type), _norm(job.hours), _norm(job.remote_type)]))
    reasons = []
    wanted = _wanted_types(profile)
    detected = detect_employment_types(job)

    if not detected:
        return 0, ["− Anstellungsart nicht eindeutig erkannt"]
    if not any(x in wanted for x in detected):
        return 0, [f"− falsche Anstellungsart: {', '.join(detected)}"]
    matched_types = [x for x in detected if x in wanted]
    reasons.append("Anstellung: " + ", ".join(matched_types))
    if "Werkstudent" in matched_types: reasons.append("Werkstudent")
    score = 25

    exclusions = [x for x in (profile.exclusions or []) if _norm(x) not in {_norm(t) for t in wanted}]
    hits = [x for x in exclusions if x and _norm(x) in full]
    if hits:
        return 0, [f"− ausgeschlossen: {', '.join(hits[:3])}"]

    roles = profile.effective_roles()
    title_roles = [r for r in roles if _has(title, _aliases(r))]
    body_roles = [r for r in roles if _has(desc, _aliases(r))]
    if title_roles:
        score += 35; reasons.append("Zielposition im Titel")
        if body_roles: score += 8; reasons.append("Zielbereich im Anzeigentext")
    elif body_roles:
        score += 22; reasons.append("Zielbereich in Aufgaben/Anforderungen")
    else:
        return 0, ["− keine passende Zielposition / kein passender Fachbereich"]

    skill_hits = [x for x in (profile.skills or []) if x and _norm(x) in full]
    if skill_hits:
        score += min(15, 5 * len(skill_hits)); reasons.append("Skills: " + ", ".join(skill_hits[:4]))

    extra_hits = [x for x in (profile.keywords or []) if x and _norm(x) in full]
    if extra_hits:
        score += min(8, 2 * len(extra_hits)); reasons.append("Profil-Keywords: " + ", ".join(extra_hits[:3]))

    if location and (_norm(profile.location) in location or _norm(profile.location) == "berlin" and "berlin" in location):
        score += 10; reasons.append(profile.location)
    elif _has(full, profile.remote_types or []) or _has(full, ["remote", "hybrid", "homeoffice", "home office"]):
        score += 8; reasons.append("Remote / Hybrid")
    else:
        score -= 8; reasons.append("− Standort nicht eindeutig passend")

    if _hours_match(job, profile):
        score += 7; reasons.append(f"{profile.hours_min}–{profile.hours_max} Stunden")
    if job.salary:
        score += 2; reasons.append("Gehalt angegeben")
    if job.posted_date:
        posted = job.posted_date.replace(tzinfo=timezone.utc) if job.posted_date.tzinfo is None else job.posted_date
        if datetime.now(timezone.utc) - posted <= timedelta(days=7):
            score += 3; reasons.append("aktuell")

    return max(0, min(100, score)), reasons

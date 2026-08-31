import re
from datetime import datetime, timezone, timedelta
from app.schemas import SearchProfile
from app.collectors.base import RawJob

ROLE_ALIASES = {
    "data analytics": ["data analytics", "data analyst", "data analysis", "analytics analyst", "reporting analyst", "business analyst", "data & business analyst"],
    "data analyst": ["data analyst", "data analytics", "data analysis", "analytics analyst", "reporting analyst"],
    "business intelligence": ["business intelligence", "bi analyst", "bi", "reporting analyst", "power bi", "business analytics"],
    "risk management": ["risk management", "risk analyst", "risk controlling", "risk & compliance", "risikomanagement", "risikoanalyse", "risk assessment"],
    "risikomanagement": ["risikomanagement", "risk management", "risk analyst", "risikoanalyse", "risk controlling"],
    "finance": ["finance", "financial analyst", "financial planning", "fp&a", "finance operations", "financial operations", "corporate finance"],
    "banking": ["banking", "bank", "banksteuerung", "credit analyst", "kreditrisiko", "financial services"],
    "controlling": ["controlling", "controller", "financial controlling", "reporting", "fp&a", "performance management"],
    "accounting": ["accounting", "buchhaltung", "financial accounting", "accounts payable", "accounts receivable"],
    "recruiting": ["recruiting", "recruitment", "talent acquisition", "personalbeschaffung", "sourcing"],
    "human resources": ["human resources", "hr", "people operations", "people & culture", "personalwesen"],
    "customer service": ["customer service", "kundenservice", "customer success", "client service"],
    "operations": ["operations", "business operations", "finance operations", "operations analyst"],
    "business development": ["business development", "commercial development", "growth", "partnerships"],
}

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()

def _has(text: str, words: list[str]) -> bool:
    t = _norm(text)
    return any(_norm(w) in t for w in words if w)

def _hours_match(job: RawJob, profile: SearchProfile) -> bool:
    s = _norm(job.hours)
    nums = [int(x) for x in re.findall(r"\b(\d{1,2})\b", s)]
    return bool(nums) and any(profile.hours_min <= n <= profile.hours_max for n in nums)

def _aliases(role: str) -> list[str]:
    r = _norm(role)
    return list(dict.fromkeys([role] + ROLE_ALIASES.get(r, [])))

def score_job(job: RawJob, profile: SearchProfile) -> tuple[int, list[str]]:
    title = _norm(job.title)
    desc = _norm(job.description)
    location = _norm(job.location)
    full = " ".join(filter(None, [title, desc, location, _norm(job.company), _norm(job.employment_type), _norm(job.hours), _norm(job.remote_type)]))
    reasons: list[str] = []

    # Hard exclusions first. A generic IT/support job must never become a high-score result.
    exclusions = list(profile.exclusions or [])
    if any(_norm(x) in full for x in exclusions if x):
        hits = [x for x in exclusions if x and _norm(x) in full]
        return 0, [f"− ausgeschlossen: {', '.join(hits[:3])}"]

    score = 0

    student = _has(full, ["werkstudent", "working student", "studentische hilfskraft", "student assistant"])
    if student:
        score += 20; reasons.append("Werkstudent")
    else:
        return 0, ["− keine Werkstudent-Stelle erkannt"]

    # Role relevance: title gets substantially more weight than generic body mentions.
    roles = profile.effective_roles()
    matched_roles = []
    title_match = False
    body_match = False
    for role in roles:
        aliases = _aliases(role)
        if _has(title, aliases):
            title_match = True; matched_roles.append(role)
        elif _has(desc, aliases):
            body_match = True; matched_roles.append(role)
    if title_match:
        score += 35; reasons.append("Zielposition im Titel")
        if body_match:
            score += 8; reasons.append("Zielbereich auch im Anzeigentext")
    elif body_match:
        score += 22; reasons.append("Zielbereich in Aufgaben/Anforderungen")
    else:
        return 0, ["− keine passende Zielposition / kein passender Fachbereich"]

    # Skill evidence only counts when the actual job text contains it.
    skills = [x for x in (profile.skills or []) if x]
    skill_hits = [x for x in skills if _norm(x) in full]
    if skill_hits:
        score += min(15, 5 * len(skill_hits)); reasons.append("Skills: " + ", ".join(skill_hits[:4]))

    # User keywords are secondary evidence, not search drivers and not enough by themselves.
    extra_hits = [x for x in (profile.keywords or []) if x and _norm(x) in full]
    if extra_hits:
        score += min(8, 2 * len(extra_hits)); reasons.append("Profil-Keywords: " + ", ".join(extra_hits[:3]))

    if location and (profile.location.lower() in location or "berlin" in location):
        score += 10; reasons.append("Berlin")
    elif location and any(x in full for x in ["remote", "hybrid", "homeoffice", "home office"]):
        score += 8; reasons.append("Remote / Hybrid")
    else:
        score -= 8; reasons.append("− Standort nicht eindeutig passend")

    if _hours_match(job, profile):
        score += 7; reasons.append(f"{profile.hours_min}–{profile.hours_max} Stunden")

    if job.salary:
        score += 2; reasons.append("Gehalt angegeben")
    if job.posted_date:
        now = datetime.now(timezone.utc)
        posted = job.posted_date.replace(tzinfo=timezone.utc) if job.posted_date.tzinfo is None else job.posted_date
        if now - posted <= timedelta(days=7):
            score += 3; reasons.append("aktuell")

    return max(0, min(100, score)), reasons

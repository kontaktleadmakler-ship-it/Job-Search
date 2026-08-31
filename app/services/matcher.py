import re
from datetime import datetime, timezone, timedelta
from app.schemas import SearchProfile
from app.collectors.base import RawJob

ROLE_SYNONYMS = {
    "data analytics": ["data analyst", "data analytics", "analytics", "business intelligence", "bi analyst", "reporting analyst", "business analyst", "data & business analyst", "data insights", "reporting"],
    "data analyst": ["data analyst", "data analytics", "analytics", "reporting analyst", "business intelligence", "bi analyst"],
    "business intelligence": ["business intelligence", "bi analyst", "business analyst", "reporting analyst", "data analytics", "power bi", "tableau"],
    "risk management": ["risk management", "risikomanagement", "risk analyst", "risk controlling", "credit risk", "market risk", "operational risk", "model risk", "risk reporting", "banksteuerung"],
    "risikomanagement": ["risikomanagement", "risk management", "risk analyst", "risk controlling", "kreditrisiko", "credit risk", "market risk", "banksteuerung"],
    "finance": ["finance", "financial analyst", "financial analytics", "corporate finance", "financial planning", "fp&a", "financial reporting", "treasury", "finance operations"],
    "banking": ["banking", "bank", "banksteuerung", "financial services", "credit", "kredit", "risk", "regulatory"],
    "controlling": ["controlling", "controller", "financial controlling", "business controlling", "reporting", "fp&a"],
    "software engineering": ["software engineer", "software development", "softwareentwickler", "developer", "backend", "frontend", "full stack", "fullstack"],
    "ai": ["artificial intelligence", "ai", "machine learning", "ml", "deep learning", "generative ai", "llm", "data science"],
}

HARD_NEGATIVE_GROUPS = [
    (["it support", "helpdesk", "help desk", "1st level support", "2nd level support", "technical support", "technischer support", "system administrator", "systemadministrator", "desktop support", "service desk"], "Support/Helpdesk"),
    (["call center", "callcenter", "telefonischer kundendienst"], "Call Center"),
    (["praktikum", "internship"], "Praktikum"),
    (["ausbildung", "apprenticeship"], "Ausbildung"),
]

SENIOR_TITLE_TERMS = ["senior", "manager", "director", "head of", "lead", "principal"]
EMPLOYMENT_TERMS = ["werkstudent", "working student", "studentische hilfskraft", "student assistant", "student job", "studentische/r mitarbeiter"]
REMOTE_TERMS = ["remote", "hybrid", "homeoffice", "home office", "mobiles arbeiten"]

# Context words make a generic role phrase much stronger when it occurs in a
# job's actual responsibilities/requirements rather than only in boilerplate.
ROLE_CONTEXT = [
    "analyse", "analysieren", "analysis", "analyst", "reporting", "dashboard", "kennzahlen",
    "risiko", "risk", "finanz", "finance", "bank", "controlling", "modell", "model",
    "daten", "data", "sql", "python", "excel", "power bi", "tableau", "forecast",
    "budget", "portfolio", "kredit", "credit", "valuation", "regulatory", "prozess", "process"
]

def norm(s: str) -> str:
    s = (s or "").lower().replace("&", " and ")
    return re.sub(r"\s+", " ", s).strip()

def contains_term(text: str, term: str) -> bool:
    t, x = norm(text), norm(term)
    if not x:
        return False
    return re.search(r"(?<![a-z0-9äöüß])" + re.escape(x) + r"(?![a-z0-9äöüß])", t) is not None

def expanded_terms(values: list[str]) -> set[str]:
    out = set()
    for value in values:
        v = norm(value)
        if not v:
            continue
        out.add(v)
        out.update(norm(x) for x in ROLE_SYNONYMS.get(v, []))
    return out

def _sections(description: str):
    """Approximate semantic sections without requiring an external LLM/API."""
    d = norm(description)
    markers = ["aufgaben", "deine aufgaben", "responsibilities", "your tasks", "profil", "anforderungen", "requirements", "qualifikationen", "was du mitbringst", "what you bring"]
    positions = [(d.find(m), m) for m in markers if d.find(m) >= 0]
    positions.sort()
    if not positions:
        return d, d, d
    task_start = next((p for p,m in positions if m in ["aufgaben", "deine aufgaben", "responsibilities", "your tasks"]), None)
    req_start = next((p for p,m in positions if m in ["profil", "anforderungen", "requirements", "qualifikationen", "was du mitbringst", "what you bring"]), None)
    tasks = d[task_start:req_start if req_start and req_start > task_start else len(d)] if task_start is not None else d
    reqs = d[req_start:] if req_start is not None else d
    return d, tasks, reqs

def _hours_match(job: RawJob, profile: SearchProfile) -> bool:
    nums = [int(x) for x in re.findall(r"\b(\d{1,2})\b", norm(job.hours))]
    if not nums:
        return False
    return any(profile.hours_min <= n <= profile.hours_max for n in nums)

def _has_employment(job: RawJob) -> bool:
    text = " ".join([job.title, job.employment_type, job.description[:2500]])
    return any(contains_term(text, x) for x in EMPLOYMENT_TERMS)

def score_job(job: RawJob, profile: SearchProfile) -> tuple[int, list[str]]:
    title = norm(job.title)
    location = norm(job.location)
    description = norm(job.description)
    employment = norm(job.employment_type)
    hours = norm(job.hours)
    remote = norm(job.remote_type)
    full = " ".join([title, norm(job.company), location, description, employment, hours, remote])
    full_desc, task_text, req_text = _sections(description)

    # Hard negatives are primarily title-level. A description saying e.g.
    # "working with the IT support team" must not disqualify a finance job.
    for words, reason in HARD_NEGATIVE_GROUPS:
        if any(contains_term(title, w) for w in words):
            return 0, [f"✗ {reason} ausgeschlossen"]
    for exclusion in profile.exclusions:
        if contains_term(title, exclusion):
            return 0, [f"✗ {exclusion} ausgeschlossen"]
    if any(contains_term(title, x) for x in SENIOR_TITLE_TERMS):
        return 0, ["✗ Zu senior für ein Werkstudentenprofil"]

    if not _has_employment(job):
        return 0, ["✗ Keine Werkstudentenstelle"]

    reasons = []
    weights = {k: max(0, int(v)) for k, v in profile.weights.items()}
    total_weight = max(1, sum(weights.values()))
    earned = 0.0

    roles = expanded_terms(profile.target_roles)
    title_hits = sorted({x for x in roles if contains_term(title, x)}, key=len, reverse=True)
    task_hits = sorted({x for x in roles if contains_term(task_text, x)}, key=len, reverse=True)
    req_hits = sorted({x for x in roles if contains_term(req_text, x)}, key=len, reverse=True)
    desc_hits = sorted({x for x in roles if contains_term(full_desc, x)}, key=len, reverse=True)

    # Role relevance is the gate. A role only appearing in generic company text
    # is not enough. Title > tasks > requirements > generic description.
    if title_hits:
        # Exact title role is stronger than a generic mention in the body.
        role_quality = 1.25
        reasons.append(f"✓ Zielrolle passt ({title_hits[0]})")
    elif task_hits:
        role_quality = 0.82
        reasons.append(f"✓ Zielrolle passt zu den Aufgaben ({task_hits[0]})")
    elif req_hits:
        role_quality = 0.68
        reasons.append(f"✓ Zielrolle passt zu den Anforderungen ({req_hits[0]})")
    elif desc_hits:
        role_quality = 0.45
        reasons.append("✓ Zielrolle im Stelleninhalt erkannt")
    else:
        return 0, ["✗ Keine passende Zielrolle im Stelleninhalt"]
    earned += weights.get("role", 0) * role_quality

    # Context boost: prevents a single broad synonym from winning by itself.
    context_hits = [x for x in ROLE_CONTEXT if contains_term(title + " " + task_text + " " + req_text, x)]
    if context_hits:
        earned += min(weights.get("role", 0) * 0.35, len(context_hits) * 1.5)
        reasons.append(f"✓ Aufgaben fachlich relevant ({min(len(context_hits), 8)} Signale)")

    study_terms = [x.strip() for x in re.split(r"[,;|]", profile.study) if x.strip()]
    if study_terms:
        study_hits = [x for x in study_terms if contains_term(full, x)]
        if study_hits:
            earned += weights.get("study", 0)
            reasons.append("✓ Studienprofil passt")
        else:
            # Do not hard-reject; many listings don't name a study programme.
            reasons.append("• Studiengang nicht explizit genannt")

    skill_terms = expanded_terms(profile.skills + profile.additional_keywords)
    skill_hits = [x for x in skill_terms if contains_term(task_text + " " + req_text, x)]
    if skill_hits:
        denominator = max(1, min(5, len(profile.skills)))
        ratio = min(1.0, len(skill_hits) / denominator)
        earned += weights.get("skills", 0) * ratio
        reasons.append(f"✓ Relevante Skills ({len(skill_hits)})")

    industry_hits = [x for x in expanded_terms(profile.industries) if contains_term(full, x)]
    if industry_hits:
        earned += weights.get("industry", 0)
        reasons.append(f"✓ Branche passt ({industry_hits[0]})")

    earned += weights.get("employment", 0)
    reasons.append("✓ Werkstudent")
    # Compatibility markers for the existing test/API contract.
    reasons.append("Werkstudent")

    location_ok = False
    if profile.location:
        location_ok = contains_term(location, profile.location) or any(contains_term(full, x) for x in profile.remote_types)
    else:
        location_ok = True
    if location_ok:
        earned += weights.get("location", 0)
        reasons.append(f"✓ Standort/Remote passt ({profile.location or 'flexibel'})")
        if profile.location and contains_term(location, profile.location):
            reasons.append(f"✓ {profile.location}")
            reasons.append(profile.location)
    else:
        return 0, ["✗ Standort passt nicht"]

    if _hours_match(job, profile):
        earned += weights.get("hours", 0)
        reasons.append(f"✓ {profile.hours_min}–{profile.hours_max} Stunden")
    elif hours:
        reasons.append("• Arbeitszeit nicht eindeutig im Wunschbereich")

    if job.posted_date:
        now = datetime.now(timezone.utc)
        posted = job.posted_date.replace(tzinfo=timezone.utc) if job.posted_date.tzinfo is None else job.posted_date
        if now - posted <= timedelta(days=3):
            reasons.append("✓ Aktuelles Angebot")

    score = round((earned / total_weight) * 100)
    return max(0, min(100, score)), reasons

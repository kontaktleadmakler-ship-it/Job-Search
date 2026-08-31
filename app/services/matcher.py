"""Deterministic profile/job matching.

The matcher deliberately separates hard constraints (employment type, explicit
location conflicts, exclusions) from soft relevance (title, role family, skills,
hours, remote model and freshness).  It never treats one matching keyword as
proof that a job is relevant.
"""
import re
import unicodedata
from datetime import datetime, timezone, timedelta
from app.schemas import SearchProfile
from app.collectors.base import RawJob


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").lower()
    value = value.replace("ß", "ss")
    return re.sub(r"[^a-z0-9äöü\s+#./-]", " ", value)


def _tokens(value: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9äöü]{2,}(?:\+\+|#)?", _norm(value)) if x}


def _contains(text: str, phrase: str) -> bool:
    p = _norm(phrase).strip()
    if not p:
        return False
    return p in _norm(text)


EMPLOYMENT_ALIASES = {
    "werkstudent": ["werkstudent", "working student", "studentische hilfskraft", "student assistant"],
    "vollzeit": ["vollzeit", "full-time", "full time", "fulltime"],
    "teilzeit": ["teilzeit", "part-time", "part time", "parttime"],
    "praktikum": ["praktikum", "praktikant", "internship", "intern"],
    "minijob": ["minijob", "mini job", "geringfügig"],
    "trainee": ["trainee", "traineeprogramm", "graduate programme"],
}

# Generic semantic families. These are intentionally narrow: they bridge common
# job-title variants but do not turn a generic skill into a domain match.
ROLE_FAMILIES = [
    {"data analyst", "data analytics", "data analysis", "datenanalyse", "analytics", "business analytics", "business analyst", "business intelligence", "bi analyst", "reporting"},
    {"softwareentwicklung", "software development", "software developer", "software engineer", "developer", "backend developer", "frontend developer", "full stack developer", "full-stack developer"},
    {"finance", "financial", "finance analyst", "financial analyst", "banking", "banksteuerung", "risk management", "risikomanagement", "controlling", "accounting"},
    {"recruiting", "recruitment", "talent acquisition", "human resources", "hr", "personalwesen"},
    {"customer service", "customer support", "kundenservice", "kundendienst"},
    {"operations", "business operations", "operations analyst", "operational"},
    {"business development", "sales development", "business development representative", "bd"},
]


def _family_for(value: str) -> set[str]:
    n = _norm(value)
    for family in ROLE_FAMILIES:
        if any(term in n for term in family):
            return family
    return {n} if n else set()


def _employment_type(job: RawJob) -> str:
    explicit = _norm(job.employment_type)
    if explicit:
        for canonical, aliases in EMPLOYMENT_ALIASES.items():
            if any(_contains(explicit, a) for a in aliases):
                return canonical
    text = " ".join((job.title, job.description))
    for canonical, aliases in EMPLOYMENT_ALIASES.items():
        if any(_contains(text, a) for a in aliases):
            return canonical
    return ""


def _hours(job: RawJob) -> list[int]:
    # Only accept numbers that are explicitly tied to working time. This avoids
    # interpreting postal codes, years, IDs or salary figures as hours.
    text = " ".join((job.hours or "", job.description or ""))
    values = []
    for m in re.finditer(r"\b(\d{1,2})(?:\s*[-–]\s*(\d{1,2}))?\s*(?:stunden|std\.?|hours|hrs?)(?:\s*(?:/|pro)\s*(?:woche|week))?\b", text, re.I):
        values.append(int(m.group(1)))
        if m.group(2):
            values.append(int(m.group(2)))
    return values


def _location_status(job: RawJob, profile: SearchProfile) -> str:
    wanted = _norm(profile.location)
    if not wanted:
        return "unknown"
    loc = _norm(job.location)
    text = _norm(job.description)
    remote = any(_contains(job.remote_type, r) for r in profile.remote_types or []) or _contains(text, "remote")
    if not loc:
        if remote and profile.remote_types:
            return "remote"
        # A location mentioned in the body is useful but is not as reliable as a
        # parsed location field; never claim exact radius from text alone.
        return "match" if wanted in text else "unknown"
    if wanted in loc:
        return "match"
    if remote and profile.remote_types:
        # Fully remote roles can be location-independent; hybrid roles still need
        # a local office match because the employee must be able to commute.
        remote_label = _norm(job.remote_type)
        if "remote" in remote_label and "hybrid" not in remote_label:
            return "remote"
    # Common German wording: "Berlin und Umgebung", districts, postal codes.
    if wanted == "berlin" and re.search(r"\b(10|12|13|14)\d{3}\b", loc):
        return "match"
    return "conflict"


def _role_match(profile_roles: list[str], title: str, body: str) -> tuple[float, list[str]]:
    if not profile_roles:
        return 0.0, []
    title_n = _norm(title)
    body_n = _norm(body)
    best = 0.0
    matched = []
    for role in profile_roles:
        role_n = _norm(role)
        if not role_n:
            continue
        if role_n in title_n:
            value = 1.0
        else:
            family = _family_for(role)
            title_hits = sum(1 for term in family if term and term in title_n)
            body_hits = sum(1 for term in family if term and term in body_n)
            value = 0.9 if title_hits else (0.55 if body_hits else 0.0)
        if value > best:
            best = value
            matched = [role]
    return best, matched


def score_job(job: RawJob, profile: SearchProfile) -> tuple[int, list[str]]:
    title = job.title or ""
    body = " ".join((job.description or "", job.employment_type or "", job.hours or "", job.remote_type or ""))
    full = " ".join((title, job.company or "", job.location or "", body))
    reasons: list[str] = []

    selected = [(_norm(x), x) for x in (profile.employment_types or ["Werkstudent"]) if x.strip()]
    detected_type = _employment_type(job)
    wanted_types = {EMPLOYMENT_ALIASES.get(k, [k])[0] if k in EMPLOYMENT_ALIASES else k for k, _ in selected}

    # Hard exclusion: explicit known employment type must agree with the profile.
    if selected and detected_type and detected_type not in wanted_types:
        reasons.append(f"− falscher Jobtyp: {detected_type.title()}")
        return 0, reasons
    if selected and detected_type in wanted_types:
        reasons.append(next(label for key, label in selected if (EMPLOYMENT_ALIASES.get(key, [key])[0] == detected_type)))
    else:
        reasons.append("− Anstellungsart nicht eindeutig")

    for exclusion in profile.exclusions or []:
        if _contains(full, exclusion):
            return 0, [f"− Ausschlussbegriff: {exclusion}"]

    location = _location_status(job, profile)
    if location == "conflict":
        reasons.append("− Standort außerhalb des gewünschten Ortes")
        return 0, reasons
    if location in {"match", "remote"}:
        reasons.append(profile.location if location == "match" else "Remote")

    roles = profile.effective_roles()
    role_score, matched_roles = _role_match(roles, title, body)
    if role_score:
        reasons.append(f"passender Fachbereich: {matched_roles[0]}")
    else:
        # A skill-only match is intentionally not enough for a high score.
        reasons.append("− Fachbereich nicht ausreichend belegt")

    skill_hits = [s for s in (profile.skills or []) if _contains(full, s)]
    keyword_hits = [k for k in (profile.keywords or []) if _contains(full, k)]
    hours = _hours(job)
    hours_ok = bool(hours and any(profile.hours_min <= h <= profile.hours_max for h in hours))
    remote_ok = bool(profile.remote_types and any(_contains(job.remote_type, x) for x in profile.remote_types))

    # Weighted score, capped by an explicit domain relevance gate.
    score = 0.0
    if detected_type in wanted_types:
        score += 25
    elif not detected_type:
        score += 8

    score += 28 * role_score
    if title and any(_contains(title, r) for r in roles):
        score += 8
    elif role_score >= 0.9:
        score += 5

    if location in {"match", "remote"}:
        score += 18
    elif location == "unknown":
        score += 6

    skill_ratio = min(1.0, len(skill_hits) / max(1, min(4, len(profile.skills or []))))
    score += 10 * skill_ratio
    if skill_hits:
        reasons.append("Skills: " + ", ".join(skill_hits[:4]))

    if keyword_hits:
        score += min(5, 2 * len(keyword_hits))
        reasons.append("Keywords: " + ", ".join(keyword_hits[:3]))

    if hours_ok:
        score += 7
        reasons.append(f"{profile.hours_min}–{profile.hours_max} Stunden")
    elif hours and profile.hours_min <= profile.hours_max:
        reasons.append("− gewünschte Wochenstunden nicht bestätigt")

    if remote_ok:
        score += 4
        reasons.append(job.remote_type)

    if job.salary:
        score += 2
        reasons.append("Gehalt angegeben")

    if job.posted_date:
        posted = job.posted_date.replace(tzinfo=timezone.utc) if job.posted_date.tzinfo is None else job.posted_date
        age = datetime.now(timezone.utc) - posted
        if age <= timedelta(days=3):
            score += 3
            reasons.append("aktuelles Angebot")
        elif age > timedelta(days=90):
            score -= 3

    # Prevent generic skill matches from becoming high-quality matches.
    if roles and role_score == 0:
        score = min(score, 34)
    elif roles and role_score < 0.55:
        score = min(score, 55)

    # Unknown employment type is deliberately capped; explicit mismatch was
    # already rejected above.
    if selected and not detected_type:
        score = min(score, 58)

    return max(0, min(100, round(score))), reasons

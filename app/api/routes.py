import json
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, func, desc
from app.database import get_db
from app.models import Job, Setting
from app.schemas import JobOut, JobStatusUpdate, SearchProfile, ProfileList, ActiveProfile
from app.collectors.base import RawJob
from app.services.matcher import score_job

router = APIRouter(prefix="/api")
PROFILE_KEY = "search_profiles"
LEGACY_KEY = "search_profile"

def _profiles_from_db(db):
    row = db.get(Setting, PROFILE_KEY)
    if row:
        data = json.loads(row.value)
        return data.get("active", "Mein Profil"), {k: SearchProfile.model_validate(v) for k, v in data.get("profiles", {}).items()}
    legacy = db.get(Setting, LEGACY_KEY)
    profile = SearchProfile.model_validate_json(legacy.value) if legacy else SearchProfile()
    return profile.name, {profile.name: profile}

def profile_from_db(db):
    active, profiles = _profiles_from_db(db)
    return profiles.get(active) or next(iter(profiles.values()), SearchProfile())

def _save_profiles(db, active, profiles):
    data = {"active": active, "profiles": {k: v.model_dump(mode="json") for k, v in profiles.items()}}
    row = db.get(Setting, PROFILE_KEY)
    if row: row.value = json.dumps(data, ensure_ascii=False)
    else: db.add(Setting(key=PROFILE_KEY, value=json.dumps(data, ensure_ascii=False)))
    db.commit()

def _restart_scanner(payload=None):
    from app.main import scan_manager, scheduler
    if payload is not None and scan_manager:
        scan_manager.profile = payload
    if scheduler and scan_manager:
        scheduler.interval_minutes = scan_manager.profile.scan_interval_minutes
        scheduler.stop(); scheduler.start()

@router.get("/jobs", response_model=list[JobOut])
def jobs(page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=100), min_score: int | None = Query(None, ge=0, le=100), source: str | None = None, status: str | None = None, remote: str | None = None, company: str | None = None, q: str | None = None, hours: str | None = None, db: Session = Depends(get_db)):
    stmt = select(Job)
    if min_score is not None: stmt = stmt.where(Job.match_score >= min_score)
    if source: stmt = stmt.where(Job.source == source)
    if status: stmt = stmt.where(Job.status == status)
    if remote: stmt = stmt.where(Job.remote_type.ilike(f"%{remote}%"))
    if company: stmt = stmt.where(Job.company.ilike(f"%{company}%"))
    if q: stmt = stmt.where(Job.title.ilike(f"%{q}%") | Job.description.ilike(f"%{q}%"))
    if hours: stmt = stmt.where(Job.hours.ilike(f"%{hours}%"))
    stmt = stmt.order_by(desc(Job.match_score), desc(Job.posted_date), desc(Job.discovered_at)).offset((page-1)*per_page).limit(per_page)
    rows = db.execute(stmt).scalars().all()
    for j in rows:
        try: j.match_reasons = json.loads(j.match_reasons or "[]")
        except Exception: j.match_reasons = []
    return rows

@router.get("/jobs/{job_id}", response_model=JobOut)
def job(job_id: int, db: Session = Depends(get_db)):
    j = db.get(Job, job_id)
    if not j: raise HTTPException(404, "Job not found")
    try: j.match_reasons = json.loads(j.match_reasons or "[]")
    except Exception: j.match_reasons = []
    return j

@router.post("/jobs/{job_id}/save", response_model=JobOut)
def save_job(job_id: int, db: Session = Depends(get_db)):
    j = db.get(Job, job_id)
    if not j: raise HTTPException(404, "Job not found")
    j.status = "saved"; db.commit(); db.refresh(j); j.match_reasons = json.loads(j.match_reasons or "[]"); return j

@router.post("/jobs/{job_id}/status", response_model=JobOut)
def status_job(job_id: int, payload: JobStatusUpdate, db: Session = Depends(get_db)):
    j = db.get(Job, job_id)
    if not j: raise HTTPException(404, "Job not found")
    j.status = payload.status; db.commit(); db.refresh(j); j.match_reasons = json.loads(j.match_reasons or "[]"); return j

@router.get("/settings", response_model=SearchProfile)
def get_settings_api(db: Session = Depends(get_db)):
    return profile_from_db(db)

@router.post("/settings", response_model=SearchProfile)
def save_settings(payload: SearchProfile, db: Session = Depends(get_db)):
    active, profiles = _profiles_from_db(db)
    name = payload.name.strip() or active or "Mein Profil"
    profiles[name] = payload.model_copy(update={"name": name})
    active_profile = profiles[name]
    _save_profiles(db, name, profiles)

    # Re-score already collected jobs immediately. Otherwise an old profile
    # could leave unrelated jobs visible with stale high scores.
    for j in db.execute(select(Job)).scalars().all():
        raw = RawJob(
            title=j.title, company=j.company, location=j.location,
            description=j.description, url=j.url, source=j.source,
            source_job_id=j.source_job_id, employment_type=j.employment_type,
            hours=j.hours, salary=j.salary, remote_type=j.remote_type,
            posted_date=j.posted_date
        )
        score, reasons = score_job(raw, active_profile)
        j.match_score = score
        j.match_reasons = json.dumps(reasons, ensure_ascii=False)
    db.commit()
    _restart_scanner(active_profile)
    return active_profile

@router.get("/profiles", response_model=ProfileList)
def get_profiles(db: Session = Depends(get_db)):
    active, profiles = _profiles_from_db(db)
    return ProfileList(active=active, profiles=profiles)

@router.post("/profiles/active", response_model=SearchProfile)
def set_active_profile(payload: ActiveProfile, db: Session = Depends(get_db)):
    active, profiles = _profiles_from_db(db)
    if payload.name not in profiles: raise HTTPException(404, "Profil nicht gefunden")
    _save_profiles(db, payload.name, profiles)
    _restart_scanner(profiles[payload.name])
    return profiles[payload.name]

@router.delete("/profiles/{name}")
def delete_profile(name: str, db: Session = Depends(get_db)):
    active, profiles = _profiles_from_db(db)
    if name not in profiles: raise HTTPException(404, "Profil nicht gefunden")
    if len(profiles) <= 1: raise HTTPException(400, "Das letzte Profil kann nicht gelöscht werden")
    del profiles[name]
    new_active = active if active != name else next(iter(profiles))
    _save_profiles(db, new_active, profiles)
    _restart_scanner(profiles[new_active])
    return {"active": new_active}

@router.get("/scan/status")
def scan_status():
    from app.main import scan_manager
    return scan_manager.status

@router.post("/scan")
async def scan():
    from app.main import scan_manager
    if scan_manager.running: return {"status": "already_running"}
    import asyncio; asyncio.create_task(scan_manager.scan()); return {"status": "started"}

@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    return {"new": db.scalar(select(func.count()).select_from(Job).where(Job.status=="new")) or 0, "high_score": db.scalar(select(func.count()).select_from(Job).where(Job.match_score>=90)) or 0, "saved": db.scalar(select(func.count()).select_from(Job).where(Job.status=="saved")) or 0, "applied": db.scalar(select(func.count()).select_from(Job).where(Job.status=="applied")) or 0, "total": db.scalar(select(func.count()).select_from(Job)) or 0}

@router.get("/jobs/{job_id}/sources")
def job_sources(job_id: int, db: Session = Depends(get_db)):
    from app.models import JobSource
    if not db.get(Job, job_id): raise HTTPException(404, "Job not found")
    return [{"source": s.source, "url": s.url, "source_job_id": s.source_job_id} for s in db.execute(select(JobSource).where(JobSource.job_id == job_id)).scalars().all()]

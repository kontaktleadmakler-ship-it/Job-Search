import json
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, func, desc
from app.database import get_db
from app.models import Job, Setting
from app.schemas import JobOut, JobStatusUpdate, SearchProfile
from app.config import get_settings

router = APIRouter(prefix="/api")

def profile_from_db(db):
    row = db.get(Setting, "search_profile")
    if not row:
        return SearchProfile()
    return SearchProfile.model_validate_json(row.value)

@router.get("/jobs", response_model=list[JobOut])
def jobs(
    page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=100),
    min_score: int | None = Query(None, ge=0, le=100),
    source: str | None = None, status: str | None = None,
    remote: str | None = None, company: str | None = None,
    q: str | None = None, hours: str | None = None,
    db: Session = Depends(get_db)
):
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
    j.status = "saved"; db.commit(); db.refresh(j)
    j.match_reasons = json.loads(j.match_reasons or "[]")
    return j

@router.post("/jobs/{job_id}/status", response_model=JobOut)
def status_job(job_id: int, payload: JobStatusUpdate, db: Session = Depends(get_db)):
    j = db.get(Job, job_id)
    if not j: raise HTTPException(404, "Job not found")
    j.status = payload.status; db.commit(); db.refresh(j)
    j.match_reasons = json.loads(j.match_reasons or "[]")
    return j

@router.get("/settings", response_model=SearchProfile)
def get_settings_api(db: Session = Depends(get_db)):
    return profile_from_db(db)

@router.post("/settings", response_model=SearchProfile)
def save_settings(payload: SearchProfile, db: Session = Depends(get_db)):
    row = db.get(Setting, "search_profile")
    value = payload.model_dump_json()
    if row: row.value = value
    else: db.add(Setting(key="search_profile", value=value))
    db.commit()
    from app.main import scan_manager, scheduler
    if scan_manager:
        scan_manager.profile = payload
    if scheduler:
        scheduler.interval_minutes = payload.scan_interval_minutes
        scheduler.stop()
        scheduler.start()
    return payload

@router.get("/scan/status")
def scan_status():
    from app.main import scan_manager
    return scan_manager.status

@router.post("/scan")
async def scan():
    from app.main import scan_manager
    if scan_manager.running:
        return {"status": "already_running"}
    import asyncio
    asyncio.create_task(scan_manager.scan())
    return {"status": "started"}

@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    return {
        "new": db.scalar(select(func.count()).select_from(Job).where(Job.status=="new")) or 0,
        "high_score": db.scalar(select(func.count()).select_from(Job).where(Job.match_score>=90)) or 0,
        "saved": db.scalar(select(func.count()).select_from(Job).where(Job.status=="saved")) or 0,
        "applied": db.scalar(select(func.count()).select_from(Job).where(Job.status=="applied")) or 0,
        "total": db.scalar(select(func.count()).select_from(Job)) or 0,
    }


@router.get("/jobs/{job_id}/sources")
def job_sources(job_id: int, db: Session = Depends(get_db)):
    from app.models import JobSource
    if not db.get(Job, job_id):
        raise HTTPException(404, "Job not found")
    return [
        {"source": s.source, "url": s.url, "source_job_id": s.source_job_id}
        for s in db.execute(select(JobSource).where(JobSource.job_id == job_id)).scalars().all()
    ]

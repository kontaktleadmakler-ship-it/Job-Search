import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from app.config import get_settings
from app.database import init_db, SessionLocal
from app.schemas import SearchProfile
from app.models import Setting
from app.api.routes import router
from app.services.scheduler import ScanScheduler
from app.services.scanner import ScanManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
settings = get_settings()
templates = Jinja2Templates(directory=str(settings.data_dir.parent / "app" / "templates"))
scan_manager = None
scheduler = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global scan_manager, scheduler
    init_db()
    db = SessionLocal()
    try:
        if not db.get(Setting, "search_profile"):
            db.add(Setting(key="search_profile", value=SearchProfile().model_dump_json()))
            db.commit()
        profile = SearchProfile.model_validate_json(db.get(Setting, "search_profile").value)
        scan_manager = ScanManager(db, profile)
        scheduler = ScanScheduler(lambda: scan_manager.scan(), profile.scan_interval_minutes)
        scheduler.start()
    finally:
        # ScanManager owns the session for its lifetime.
        pass
    yield
    if scheduler:
        scheduler.stop()
    if scan_manager:
        scan_manager.db.close()

app = FastAPI(title="Berlin Werkstudent Job Radar", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(settings.data_dir.parent / "app" / "static")), name="static")
app.include_router(router)

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={})

@app.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request):
    return templates.TemplateResponse(request=request, name="jobs.html", context={})

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse(request=request, name="settings.html", context={})

@app.get("/health")
def health():
    return {"status": "ok"}

from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    company: str
    location: str
    description: str
    url: str
    source: str
    source_job_id: str | None
    employment_type: str
    hours: str
    salary: str
    remote_type: str
    posted_date: datetime | None
    discovered_at: datetime
    match_score: int
    match_reasons: list[str]
    status: str

class JobStatusUpdate(BaseModel):
    status: str = Field(pattern="^(new|seen|saved|applied|rejected)$")

class SearchProfile(BaseModel):
    location: str = "Berlin"
    radius_km: int = Field(default=20, ge=0, le=200)
    min_score: int = Field(default=70, ge=0, le=100)
    hours_min: int = Field(default=15, ge=0, le=80)
    hours_max: int = Field(default=20, ge=0, le=80)
    remote_types: list[str] = ["Hybrid", "Remote", "Berlin"]
    languages: list[str] = ["Deutsch", "Englisch"]
    keywords: list[str] = [
        "Finance","Banking","Risikomanagement","Risk Management","Controlling",
        "Accounting","Recruiting","Human Resources","Customer Service","Data",
        "Data Analysis","AI","Artificial Intelligence","IT","Software",
        "Operations","Business Development"
    ]
    exclusions: list[str] = [
        "Vollzeit","Praktikum","Ausbildung","Minijob","Senior","Manager","Director"
    ]
    sources: list[str] = ["stepstone", "indeed", "generic"]
    scan_interval_minutes: int = Field(default=60, ge=5, le=1440)

class ScanStatus(BaseModel):
    running: bool
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_error: str | None = None
    found: int = 0
    new: int = 0
    duplicates: int = 0
    filtered: int = 0
    errors: int = 0
    collectors: dict[str, dict] = Field(default_factory=dict)

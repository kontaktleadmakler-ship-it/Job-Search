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
    name: str = "Mein Profil"
    study: str = ""
    # Legacy alias kept for compatibility with older API clients/tests.
    keywords: list[str] = Field(default_factory=list)
    target_roles: list[str] = Field(default_factory=lambda: [
        "Data Analytics", "Data Analyst", "Business Intelligence",
        "Risk Management", "Risikomanagement", "Finance", "Banking", "Controlling"
    ])
    industries: list[str] = Field(default_factory=lambda: ["Finance", "Banking", "FinTech", "Insurance"])
    skills: list[str] = Field(default_factory=lambda: ["Python", "SQL", "Excel", "Power BI"])
    additional_keywords: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=lambda: [
        "IT Support", "Helpdesk", "1st Level Support", "2nd Level Support",
        "Call Center", "Callcenter", "Technischer Support", "Systemadministrator",
        "Praktikum", "Ausbildung", "Vollzeit", "Senior", "Manager", "Director"
    ])
    location: str = "Berlin"
    radius_km: int = Field(default=20, ge=0, le=200)
    remote_types: list[str] = Field(default_factory=lambda: ["Hybrid", "Remote", "Berlin"])
    languages: list[str] = Field(default_factory=lambda: ["Deutsch", "Englisch"])
    hours_min: int = Field(default=15, ge=0, le=80)
    hours_max: int = Field(default=20, ge=0, le=80)
    min_score: int = Field(default=70, ge=0, le=100)
    sources: list[str] = Field(default_factory=lambda: ["stepstone", "indeed", "generic"])
    scan_interval_minutes: int = Field(default=60, ge=5, le=1440)
    weights: dict[str, int] = Field(default_factory=lambda: {
        "role": 35, "study": 10, "skills": 20, "industry": 10,
        "employment": 10, "location": 10, "hours": 5
    })

class ProfileList(BaseModel):
    active: str
    profiles: dict[str, SearchProfile]

class ActiveProfile(BaseModel):
    name: str

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

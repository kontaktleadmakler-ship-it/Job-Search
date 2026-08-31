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
    min_score: int = Field(default=60, ge=0, le=100)
    hours_min: int = Field(default=15, ge=0, le=80)
    hours_max: int = Field(default=20, ge=0, le=80)
    remote_types: list[str] = ["Hybrid", "Remote"]
    languages: list[str] = ["Deutsch", "Englisch"]

    # User-controlled target profile. `keywords` is retained for backwards compatibility.
    target_roles: list[str] = [
        "Data Analytics", "Data Analyst", "Business Intelligence",
        "Risk Management", "Risikomanagement", "Finance", "Banking",
        "Controlling", "Accounting", "Recruiting", "Human Resources",
        "Customer Service", "Operations", "Business Development"
    ]
    skills: list[str] = ["Python", "SQL", "Excel", "Power BI"]
    keywords: list[str] = []
    exclusions: list[str] = [
        "Vollzeit", "Praktikum", "Ausbildung", "Minijob", "Senior", "Manager", "Director",
        "IT Support", "Helpdesk", "1st Level Support", "2nd Level Support", "First Level Support",
        "Second Level Support", "Technischer Support", "Technical Support", "Systemadministrator",
        "System Administration"
    ]
    sources: list[str] = ["stepstone", "indeed", "generic"]
    scan_interval_minutes: int = Field(default=60, ge=5, le=1440)

    def effective_roles(self) -> list[str]:
        # Legacy profiles stored their target roles in `keywords`. If the user
        # supplies legacy keywords and no explicit target_roles, keep them as
        # the search roles so existing configurations do not suddenly broaden.
        roles = self.keywords if self.keywords and self.target_roles == SearchProfile.model_fields["target_roles"].default else self.target_roles
        roles = roles or self.keywords
        return list(dict.fromkeys(x.strip() for x in roles if x and x.strip()))

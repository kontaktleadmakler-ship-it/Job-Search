from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime

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
    status: str = Field(pattern=r"^(new|seen|saved|applied|rejected)$")

class SearchProfile(BaseModel):
    location: str = "Berlin"
    radius_km: int = Field(default=20, ge=0, le=200)
    min_score: int = Field(default=70, ge=0, le=100)
    hours_min: int = Field(default=15, ge=0, le=80)
    hours_max: int = Field(default=20, ge=0, le=80)
    remote_types: list[str] = Field(default_factory=lambda: ["Hybrid", "Remote"])
    languages: list[str] = Field(default_factory=lambda: ["Deutsch", "Englisch"])
    employment_types: list[str] = Field(default_factory=lambda: ["Werkstudent"])
    target_roles: list[str] = Field(default_factory=lambda: [
        "Data Analytics", "Data Analyst", "Business Intelligence",
        "Risk Management", "Risikomanagement", "Finance", "Banking",
        "Controlling", "Accounting", "Recruiting", "Human Resources",
        "Customer Service", "Operations", "Business Development"
    ])
    skills: list[str] = Field(default_factory=lambda: ["Python", "SQL", "Excel", "Power BI"])
    keywords: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=lambda: [
        "Ausbildung", "Minijob", "Senior", "Manager", "Director",
        "IT Support", "Helpdesk", "1st Level Support", "2nd Level Support",
        "First Level Support", "Second Level Support", "Technischer Support",
        "Technical Support", "Systemadministrator", "System Administration"
    ])
    sources: list[str] = Field(default_factory=lambda: [
        "stepstone", "indeed", "generic", "xing", "monster",
        "jobware", "kimeta", "linkedin", "arbeitsagentur"
    ])
    scan_interval_minutes: int = Field(default=60, ge=5, le=1440)

    def effective_roles(self) -> list[str]:
        default_roles = type(self).model_fields["target_roles"].default_factory()
        if self.keywords and self.target_roles == default_roles:
            roles = self.keywords
        else:
            roles = self.target_roles or self.keywords
        return list(dict.fromkeys(x.strip() for x in roles if x and x.strip()))

from datetime import datetime, timezone
from sqlalchemy import String, Text, Integer, Float, DateTime, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

def utcnow():
    return datetime.now(timezone.utc)

class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500), index=True)
    company: Mapped[str] = mapped_column(String(300), default="", index=True)
    location: Mapped[str] = mapped_column(String(300), default="", index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(2000))
    canonical_url: Mapped[str] = mapped_column(String(2000), index=True)
    source: Mapped[str] = mapped_column(String(100), index=True)
    source_job_id: Mapped[str | None] = mapped_column(String(300), nullable=True, index=True)
    employment_type: Mapped[str] = mapped_column(String(100), default="", index=True)
    hours: Mapped[str] = mapped_column(String(100), default="")
    salary: Mapped[str] = mapped_column(String(300), default="")
    remote_type: Mapped[str] = mapped_column(String(100), default="", index=True)
    posted_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    match_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    match_reasons: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(30), default="new", index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)

    __table_args__ = (
        UniqueConstraint("source", "source_job_id", name="uq_job_source_id"),
        Index("ix_job_score_date", "match_score", "posted_date"),
    )

class JobSource(Base):
    __tablename__ = "job_sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(Integer, index=True)
    source: Mapped[str] = mapped_column(String(100), index=True)
    url: Mapped[str] = mapped_column(String(2000))
    source_job_id: Mapped[str | None] = mapped_column(String(300), nullable=True)

class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")

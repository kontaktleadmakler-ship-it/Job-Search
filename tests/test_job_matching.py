from app.collectors.base import RawJob
from app.schemas import SearchProfile
from app.services.discovery import is_direct_job_url, is_generic_job_url
from app.services.matcher import score_job


def profile(**kwargs):
    base = SearchProfile(
        location="Berlin",
        target_roles=["Data Analyst"],
        skills=["Python", "SQL"],
        min_score=60,
        employment_types=["Werkstudent"],
        exclusions=[]
    )
    return base.model_copy(update=kwargs)


def test_only_direct_portal_job_urls_are_accepted():
    assert is_direct_job_url("https://de.indeed.com/viewjob?jk=abc123", "indeed")
    assert is_direct_job_url("https://www.stepstone.de/stellenangebote--Werkstudent-Data-Analyst-Berlin--1234566-inline.html", "stepstone")
    assert not is_direct_job_url("https://de.indeed.com/", "indeed")
    assert not is_direct_job_url("https://www.stepstone.de/", "stepstone")


def test_generic_rejects_portal_homepages():
    assert is_generic_job_url("https://careers.example.com/jobs/123-data-analyst")
    assert not is_generic_job_url("https://careers.example.com/")
    assert not is_generic_job_url("https://www.indeed.com/")


def test_wanted_employment_type_is_required_for_high_score():
    job = RawJob(
        title="Data Analyst",
        company="Example GmbH",
        location="Berlin",
        description="Wir suchen eine Werkstudentin als Data Analyst mit Python und SQL.",
        url="https://careers.example.com/jobs/123"
    )
    score, reasons = score_job(job, profile())
    assert score >= 60
    assert any("Werkstudent" in x for x in reasons)


def test_wrong_employment_type_is_hard_filtered():
    job = RawJob(title="Data Analyst", company="Example", location="Berlin", description="Vollzeit mit Python und SQL")
    score, _ = score_job(job, profile(employment_types=["Werkstudent"]))
    assert score == 0


def test_role_context_beats_single_skill():
    job = RawJob(title="Verkäufer im Einzelhandel", company="Example", location="Berlin", description="Excel Kenntnisse wünschenswert")
    score, _ = score_job(job, profile())
    assert score < 40


def test_synonym_business_intelligence_matches_data_analyst():
    job = RawJob(title="Werkstudent Business Intelligence", company="Example", location="Berlin", description="SQL Reporting und Datenanalyse")
    score, reasons = score_job(job, profile())
    assert score >= 60
    assert any("Fachbereich" in x for x in reasons)


def test_wrong_location_is_hard_filtered():
    job = RawJob(title="Werkstudent Data Analyst", company="Example", location="Hamburg", description="Python SQL")
    score, _ = score_job(job, profile())
    assert score == 0


def test_remote_job_can_match_when_remote_is_selected():
    job = RawJob(title="Werkstudent Data Analyst", company="Example", location="Deutschland", description="Python SQL Remote", remote_type="Remote")
    score, _ = score_job(job, profile(remote_types=["Remote"]))
    assert score >= 60

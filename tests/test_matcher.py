from app.collectors.base import RawJob
from app.schemas import SearchProfile
from app.services.matcher import score_job

def test_werkstudent_berlin_finance_high():
    p=SearchProfile()
    j=RawJob(title="Werkstudent Finance Analyst",location="Berlin",description="Finance Banking Hybrid 20 Stunden",hours="20",remote_type="Hybrid")
    score,reasons=score_job(j,p)
    assert score >= 80
    assert "Werkstudent" in reasons and "Berlin" in reasons

def test_fulltime_penalty():
    p=SearchProfile()
    j=RawJob(title="Werkstudent Finance",location="Berlin",description="Vollzeit Finance")
    score,_=score_job(j,p)
    assert score < 80

def test_internship_penalty():
    p=SearchProfile()
    j=RawJob(title="Praktikum Finance",location="Berlin",description="Praktikum")
    score,_=score_job(j,p)
    assert score < 60

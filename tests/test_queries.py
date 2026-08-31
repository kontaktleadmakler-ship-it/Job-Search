from app.schemas import SearchProfile
from app.services.scanner import build_queries

def test_queries_are_dynamic():
    p=SearchProfile(keywords=["Finance","AI"], location="Berlin")
    assert build_queries(p)==["Finance","AI"]

def test_default_queries_use_profile_roles():
    p=SearchProfile(location="Berlin", target_roles=["Data Analyst"], employment_types=["Vollzeit"])
    assert build_queries(p)==["Data Analyst"]

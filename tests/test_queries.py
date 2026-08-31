from app.schemas import SearchProfile
from app.services.scanner import build_queries


def test_queries_are_profile_driven():
    p = SearchProfile(keywords=["Finance", "AI"], target_roles=[], skills=["Python"], location="Berlin")
    q = build_queries(p)
    assert "Finance" in q and "AI" in q
    assert any(x == "Finance Python" for x in q)


def test_queries_include_role_skill_clusters():
    p = SearchProfile(location="Berlin", target_roles=["Data Analyst"], skills=["Python", "SQL"])
    q = build_queries(p)
    assert q[0] == "Data Analyst"
    assert "Data Analyst Python" in q
    assert "Data Analyst SQL" in q

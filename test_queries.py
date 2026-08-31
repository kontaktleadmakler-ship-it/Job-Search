from app.schemas import SearchProfile
from app.services.scanner import build_queries

def test_queries_are_dynamic():
    p=SearchProfile(keywords=["Finance","AI"], location="Berlin")
    assert build_queries(p)==["Werkstudent Finance Berlin","Werkstudent AI Berlin"]

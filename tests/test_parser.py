from app.services.job_parser import parse_html

def test_parser_basic_html():
    html="<html><head><title>Werkstudent Finance</title></head><body><h1>Werkstudent Finance</h1><div class='company'>ABC GmbH</div><div class='location'>Berlin</div><p>20 Stunden Hybrid</p></body></html>"
    j=parse_html(html,"https://example.com/job/1","generic")
    assert j is not None
    assert j.title=="Werkstudent Finance"
    assert j.company=="ABC GmbH"
    assert j.location=="Berlin"

def test_parser_rejects_bad_url():
    assert parse_html("<h1>X</h1>","javascript:alert(1)","generic") is None

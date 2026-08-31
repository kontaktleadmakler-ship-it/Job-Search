from app.collectors.base import RawJob
from app.services.deduplicator import canonicalize_url, fingerprint, identity_keys

def test_same_url_canonicalizes():
    a=canonicalize_url("https://example.com/job/1/?utm_source=x")
    b=canonicalize_url("https://EXAMPLE.com/job/1")
    assert a==b

def test_source_job_id_identity():
    j=RawJob(title="X",company="C",location="Berlin",url="https://x.test/1",source="indeed",source_job_id="123")
    assert "source_id:indeed:123" in identity_keys(j)

def test_fingerprint_same():
    a=RawJob(title="Werkstudent Finance",company="ABC",location="Berlin")
    b=RawJob(title=" Werkstudent Finance ",company="ABC",location="Berlin")
    assert fingerprint(a)==fingerprint(b)

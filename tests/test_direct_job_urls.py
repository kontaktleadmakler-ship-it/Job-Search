from app.services.discovery import is_direct_job_url, is_generic_job_url


def test_stepstone_direct_urls_are_accepted():
    assert is_direct_job_url("https://www.stepstone.de/stellenangebote--Werkstudent-Finance-Berlin--123456-inline.html", "stepstone")
    assert is_direct_job_url("https://www.stepstone.de/jobs/123456", "stepstone")


def test_indeed_direct_urls_are_accepted():
    assert is_direct_job_url("https://de.indeed.com/viewjob?jk=abc123", "indeed")
    assert not is_direct_job_url("https://de.indeed.com/", "indeed")


def test_generic_career_job_urls_are_accepted_but_homepages_are_not():
    assert is_generic_job_url("https://careers.example.com/job/12345/working-student-finance")
    assert is_generic_job_url("https://jobs.example.com/career/jobs/working-student-123")
    assert not is_generic_job_url("https://www.indeed.com/")
    assert not is_generic_job_url("https://www.stepstone.de/stellenangebote")

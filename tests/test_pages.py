from fastapi.testclient import TestClient
from app.main import app

def test_dashboard_pages():
    with TestClient(app) as c:
        assert c.get("/").status_code == 200
        assert c.get("/jobs").status_code == 200
        assert c.get("/settings").status_code == 200

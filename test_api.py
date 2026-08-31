from fastapi.testclient import TestClient
from app.main import app

def test_health():
    with TestClient(app) as c:
        assert c.get("/health").json()["status"]=="ok"

def test_settings_api():
    with TestClient(app) as c:
        r=c.get("/api/settings")
        assert r.status_code==200
        assert r.json()["location"]=="Berlin"

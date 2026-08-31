from functools import lru_cache
from pathlib import Path
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

class Settings(BaseModel):
    app_env: str = os.getenv("APP_ENV", "development")
    database_url: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'jobs.db'}")
    scan_interval_minutes: int = int(os.getenv("SCAN_INTERVAL_MINUTES", "60"))
    request_timeout: float = float(os.getenv("REQUEST_TIMEOUT", "20"))
    max_concurrent_requests: int = int(os.getenv("MAX_CONCURRENT_REQUESTS", "3"))
    request_rate_per_second: float = float(os.getenv("REQUEST_RATE_PER_SECOND", "1.0"))
    default_location: str = os.getenv("DEFAULT_LOCATION", "Berlin")
    default_radius_km: int = int(os.getenv("DEFAULT_RADIUS_KM", "20"))
    min_match_score: int = int(os.getenv("MIN_MATCH_SCORE", "70"))
    user_agent: str = os.getenv(
        "USER_AGENT",
        "BerlinJobRadar/1.0 (+personal job discovery; respectful public-page access)"
    )
    discovery_enabled: bool = os.getenv("DISCOVERY_ENABLED", "true").lower() == "true"
    discovery_provider: str = os.getenv("DISCOVERY_PROVIDER", "duckduckgo")
    discovery_max_results: int = int(os.getenv("DISCOVERY_MAX_RESULTS", "10"))
    discovery_timeout: float = float(os.getenv("DISCOVERY_TIMEOUT", "8"))
    source_urls: str = os.getenv("SOURCE_URLS", "")

    @property
    def data_dir(self) -> Path:
        return BASE_DIR / "data"

@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    return s

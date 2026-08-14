"""IMPACT-NCATS configuration: paths, API endpoints, rate limits."""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
WEBSITE_DATA_DIR = PROJECT_ROOT / "docs" / "data"

NCATS_DB_PATH = DATA_DIR / "ncats.db"
IMPACT_DB_PATH = Path(
    os.getenv("IMPACT_DB_PATH", Path.home() / "Projects/IMPACT/data/impact.db")
)

# --- APIs ---
REPORTER_PROJECTS_URL = "https://api.reporter.nih.gov/v2/projects/search"
REPORTER_PUBS_URL = "https://api.reporter.nih.gov/v2/publications/search"
ICITE_BASE_URL = "https://icite.od.nih.gov/api/pubs"

# RePORTER documents a 1 req/sec ceiling.
REPORTER_RATE_LIMIT = 1.0
REPORTER_PAGE_SIZE = 500
ICITE_RATE_LIMIT = 5.0
ICITE_MAX_BATCH = 200

# --- Scope ---
AGENCY = "NCATS"
FIRST_FISCAL_YEAR = 2012
HUB_ACTIVITY_CODES = ["UL1", "UM1"]

# --- R2 ---
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "impact-data")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "")
R2_PREFIX = os.getenv("R2_PREFIX", "ncats")

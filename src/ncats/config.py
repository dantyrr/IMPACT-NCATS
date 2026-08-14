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
# RePORTER returns HTTP 400 for offset >= 10000. Verified empirically:
# offset 9000 succeeds, 10000 fails.
REPORTER_OFFSET_CAP = 10000
ICITE_RATE_LIMIT = 5.0
ICITE_MAX_BATCH = 200

# --- Scope ---
AGENCY = "NCATS"
FIRST_FISCAL_YEAR = 2012
HUB_ACTIVITY_CODES = ["UL1", "UM1"]

# Non-grant and one-off funding instruments, excluded by scope decision.
# OT2/OT3 are Other Transactions and N-series are R&D contracts - neither is a
# grant. SB1 and DP2 are grants but are one-off mechanisms in this portfolio and
# are excluded so every remaining award maps to a standard NIH mechanism letter
# (R, K, U, T, F, P). Documented in METHODS_ncats.md.
EXCLUDED_ACTIVITY_CODES = {
    "OT2", "OT3",                  # Other Transactions
    "N01", "N03", "N43", "N44",    # R&D contracts
    "SB1",                         # SBIR-related
    "DP2",                         # NIH Director's New Innovator
}

# --- R2 ---
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "impact-data")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "")
R2_PREFIX = os.getenv("R2_PREFIX", "ncats")

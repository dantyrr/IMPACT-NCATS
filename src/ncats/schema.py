"""ncats.db schema definition and connection helpers."""

import sqlite3
from src.ncats.config import NCATS_DB_PATH, IMPACT_DB_PATH

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sites (
    ipf_code          INTEGER PRIMARY KEY,
    org_name          TEXT NOT NULL,
    slug              TEXT,
    hub_name          TEXT,
    city              TEXT,
    state             TEXT,
    is_ctsa_hub       INTEGER NOT NULL DEFAULT 0,
    first_funded_year INTEGER,
    last_funded_year  INTEGER
);

CREATE TABLE IF NOT EXISTS grants (
    core_project_num   TEXT PRIMARY KEY,
    ipf_code           INTEGER REFERENCES sites(ipf_code),
    activity_code      TEXT,
    title              TEXT,
    first_fy           INTEGER,
    last_fy            INTEGER,
    total_award_amount REAL DEFAULT 0,
    is_hub_award       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS grant_years (
    core_project_num TEXT NOT NULL REFERENCES grants(core_project_num),
    fiscal_year      INTEGER NOT NULL,
    project_num      TEXT NOT NULL,
    award_amount     REAL DEFAULT 0,
    UNIQUE(core_project_num, fiscal_year, project_num)
);

CREATE TABLE IF NOT EXISTS investigators (
    profile_id INTEGER PRIMARY KEY,
    full_name  TEXT,
    first_name TEXT,
    last_name  TEXT
);

CREATE TABLE IF NOT EXISTS grant_pis (
    core_project_num TEXT NOT NULL REFERENCES grants(core_project_num),
    profile_id       INTEGER NOT NULL REFERENCES investigators(profile_id),
    is_contact_pi    INTEGER NOT NULL DEFAULT 0,
    UNIQUE(core_project_num, profile_id)
);

CREATE TABLE IF NOT EXISTS grant_pubs (
    core_project_num TEXT NOT NULL REFERENCES grants(core_project_num),
    pmid             INTEGER NOT NULL,
    UNIQUE(core_project_num, pmid)
);

CREATE TABLE IF NOT EXISTS pub_metrics (
    pmid               INTEGER PRIMARY KEY,
    rcr                REAL,
    citation_count     INTEGER DEFAULT 0,
    journal_id         INTEGER,
    journal_name       TEXT,
    journal_rolling_if REAL,
    pub_year           INTEGER,
    is_research        INTEGER,
    in_impact_db       INTEGER NOT NULL DEFAULT 0,
    n_linked_hubs      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS site_metrics (
    ipf_code          INTEGER NOT NULL REFERENCES sites(ipf_code),
    year              INTEGER NOT NULL,
    activity_group    TEXT NOT NULL,
    pub_count         INTEGER DEFAULT 0,
    research_count    INTEGER DEFAULT 0,
    citation_count    INTEGER DEFAULT 0,
    mean_rcr          REAL,
    mean_journal_if   REAL,
    award_total       REAL DEFAULT 0,
    cost_per_pub      REAL,
    cost_per_citation REAL,
    UNIQUE(ipf_code, year, activity_group)
);

CREATE INDEX IF NOT EXISTS idx_grants_ipf ON grants(ipf_code);
CREATE INDEX IF NOT EXISTS idx_grants_activity ON grants(activity_code);
CREATE INDEX IF NOT EXISTS idx_grant_years_fy ON grant_years(fiscal_year);
CREATE INDEX IF NOT EXISTS idx_grant_pubs_pmid ON grant_pubs(pmid);
CREATE INDEX IF NOT EXISTS idx_grant_pubs_core ON grant_pubs(core_project_num);
CREATE INDEX IF NOT EXISTS idx_site_metrics_site ON site_metrics(ipf_code, year);
"""


def create_schema(conn: sqlite3.Connection) -> None:
    """Create all tables and indexes. Safe to call repeatedly."""
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def connect_ncats() -> sqlite3.Connection:
    """Open (creating if needed) the writable ncats.db."""
    NCATS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(NCATS_DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    create_schema(conn)
    return conn


def connect_impact_readonly() -> sqlite3.Connection:
    """Open the existing impact.db strictly read-only."""
    if not IMPACT_DB_PATH.exists():
        raise FileNotFoundError(
            f"impact.db not found at {IMPACT_DB_PATH}. Set IMPACT_DB_PATH in .env"
        )
    return sqlite3.connect(f"file:{IMPACT_DB_PATH}?mode=ro", uri=True)

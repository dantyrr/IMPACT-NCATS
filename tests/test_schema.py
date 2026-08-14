import sqlite3
import pytest
from src.ncats.schema import create_schema

EXPECTED_TABLES = {
    "sites", "grants", "grant_years", "investigators",
    "grant_pis", "grant_pubs", "pub_metrics", "site_metrics",
}


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    create_schema(c)
    yield c
    c.close()


def test_all_tables_created(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    assert EXPECTED_TABLES <= {r[0] for r in rows}


def test_create_schema_is_idempotent(conn):
    create_schema(conn)  # second call must not raise
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    assert EXPECTED_TABLES <= {r[0] for r in rows}


def test_grant_pubs_rejects_duplicate_link(conn):
    conn.execute("INSERT INTO sites (ipf_code, org_name) VALUES (1, 'X')")
    conn.execute(
        "INSERT INTO grants (core_project_num, ipf_code, activity_code) "
        "VALUES ('UL1TR000001', 1, 'UL1')"
    )
    conn.execute("INSERT INTO grant_pubs (core_project_num, pmid) VALUES ('UL1TR000001', 42)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO grant_pubs (core_project_num, pmid) VALUES ('UL1TR000001', 42)"
        )


def test_site_is_keyed_on_ipf_code(conn):
    conn.execute("INSERT INTO sites (ipf_code, org_name) VALUES (7, 'A')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO sites (ipf_code, org_name) VALUES (7, 'B')")

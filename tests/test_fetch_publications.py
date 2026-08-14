import sqlite3
import pytest
from src.ncats.schema import create_schema
from scripts.fetch_publications import ingest_pubs_for_grant


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=ON")
    create_schema(c)
    c.execute("INSERT INTO sites (ipf_code, org_name) VALUES (1,'X')")
    c.execute("INSERT INTO grants (core_project_num, ipf_code, activity_code) VALUES ('UL1TR000090',1,'UL1')")
    yield c
    c.close()


def test_inserts_links(conn):
    assert ingest_pubs_for_grant(conn, "UL1TR000090", [1, 2, 3]) == 3
    assert conn.execute("SELECT COUNT(*) FROM grant_pubs").fetchone()[0] == 3


def test_rerun_inserts_nothing_new(conn):
    ingest_pubs_for_grant(conn, "UL1TR000090", [1, 2, 3])
    assert ingest_pubs_for_grant(conn, "UL1TR000090", [1, 2, 3]) == 0
    assert conn.execute("SELECT COUNT(*) FROM grant_pubs").fetchone()[0] == 3


def test_partial_overlap_adds_only_new(conn):
    ingest_pubs_for_grant(conn, "UL1TR000090", [1, 2])
    assert ingest_pubs_for_grant(conn, "UL1TR000090", [2, 3]) == 1
    assert conn.execute("SELECT COUNT(*) FROM grant_pubs").fetchone()[0] == 3

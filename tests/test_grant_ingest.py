import sqlite3
import pytest
from src.ncats.schema import create_schema
from src.ncats.grant_ingest import ingest_projects


def _record(core="UL1TR001881", fy=2024, amount=1000.0, ipf=577504,
            org="UCLA", act="UL1", proj=None):
    return {
        "core_project_num": core,
        "project_num": proj or f"5{core}-01",
        "activity_code": act,
        "project_title": "Test Award",
        "fiscal_year": fy,
        "award_amount": amount,
        "organization": {
            "org_name": org, "org_city": "LOS ANGELES",
            "org_state": "CA", "org_ipf_code": ipf,
        },
        "principal_investigators": [
            {"profile_id": 1, "first_name": "Ada", "last_name": "Lovelace",
             "full_name": "Ada Lovelace", "is_contact_pi": True},
        ],
    }


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    create_schema(c)
    yield c
    c.close()


def test_ingest_creates_site_grant_and_pi(conn):
    ingest_projects(conn, [_record()])
    assert conn.execute("SELECT COUNT(*) FROM sites").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM grants").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM investigators").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM grant_pis").fetchone()[0] == 1


def test_award_amounts_sum_across_fiscal_years(conn):
    ingest_projects(conn, [
        _record(fy=2023, amount=100.0, proj="5UL1TR001881-01"),
        _record(fy=2024, amount=250.0, proj="5UL1TR001881-02"),
    ])
    total, first, last = conn.execute(
        "SELECT total_award_amount, first_fy, last_fy FROM grants"
    ).fetchone()
    assert total == 350.0
    assert (first, last) == (2023, 2024)


def test_ingest_is_idempotent(conn):
    recs = [_record(fy=2023, amount=100.0, proj="5UL1TR001881-01"),
            _record(fy=2024, amount=250.0, proj="5UL1TR001881-02")]
    ingest_projects(conn, recs)
    ingest_projects(conn, recs)  # re-run
    assert conn.execute("SELECT COUNT(*) FROM grant_years").fetchone()[0] == 2
    assert conn.execute("SELECT total_award_amount FROM grants").fetchone()[0] == 350.0


def test_hub_awards_are_flagged(conn):
    ingest_projects(conn, [
        _record(core="UL1TR001881", act="UL1"),
        _record(core="R01TR009999", act="R01", ipf=999999, org="OTHER"),
    ])
    flags = dict(conn.execute(
        "SELECT core_project_num, is_hub_award FROM grants"))
    assert flags["UL1TR001881"] == 1
    assert flags["R01TR009999"] == 0


def test_record_with_no_ipf_code_is_skipped(conn):
    bad = _record()
    bad["organization"]["org_ipf_code"] = None
    counts = ingest_projects(conn, [bad])
    assert counts["grants"] == 0
    assert conn.execute("SELECT COUNT(*) FROM grants").fetchone()[0] == 0

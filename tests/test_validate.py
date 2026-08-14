import sqlite3
import pytest
from src.ncats.schema import create_schema
from scripts.validate_ncats import run_checks


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    create_schema(c)
    c.execute("INSERT INTO sites (ipf_code, org_name, slug, hub_name, is_ctsa_hub) VALUES (1,'A','a','Hub A',1)")
    c.execute("INSERT INTO grants (core_project_num, ipf_code, activity_code, is_hub_award) VALUES ('UL1TR000001',1,'UL1',1)")
    c.execute("INSERT INTO grant_pubs VALUES ('UL1TR000001',100)")
    c.execute("INSERT INTO pub_metrics (pmid, in_impact_db, n_linked_hubs) VALUES (100,1,1)")
    yield c
    c.close()


def _result(results, name):
    return [r for r in results if r[0] == name][0]


def test_all_checks_pass_on_clean_db(conn):
    results = run_checks(conn)
    assert all(passed for _, passed, _ in results), results


def test_low_match_rate_fails(conn):
    conn.execute("INSERT INTO grant_pubs VALUES ('UL1TR000001',200)")
    conn.execute("INSERT INTO pub_metrics (pmid, in_impact_db, n_linked_hubs) VALUES (200,0,1)")
    # 1 of 2 matched = 50%, below the 95% floor
    assert _result(run_checks(conn), "impact_db_match_rate")[1] is False


def test_orphan_grant_pub_fails(conn):
    conn.execute("INSERT INTO grant_pubs VALUES ('NOSUCHGRANT',300)")
    assert _result(run_checks(conn), "no_orphan_grant_pubs")[1] is False


def test_grant_with_missing_site_fails(conn):
    conn.execute("INSERT INTO grants (core_project_num, ipf_code, activity_code) VALUES ('R01TR000009',999,'R01')")
    assert _result(run_checks(conn), "no_orphan_grants")[1] is False


def test_hub_without_slug_fails(conn):
    conn.execute("UPDATE sites SET slug=NULL WHERE ipf_code=1")
    assert _result(run_checks(conn), "all_hubs_have_slug")[1] is False


def test_duplicate_hub_slug_fails(conn):
    conn.execute("INSERT INTO sites (ipf_code, org_name, slug, hub_name, is_ctsa_hub) VALUES (2,'B','a','Hub B',1)")
    assert _result(run_checks(conn), "hub_slugs_unique")[1] is False


def test_hub_without_display_name_fails(conn):
    """Regression: null hub_name rendered as the literal string 'null' in the UI."""
    conn.execute("UPDATE sites SET hub_name=NULL WHERE ipf_code=1")
    assert _result(run_checks(conn), "all_hubs_have_name")[1] is False

import sqlite3
import pytest
from src.ncats.schema import create_schema
from src.ncats.metrics import (
    activity_group, compute_n_linked_hubs, enrich_from_impact, compute_site_metrics,
)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    create_schema(c)
    for ipf, name in [(1, "HUB A"), (2, "HUB B")]:
        c.execute("INSERT INTO sites (ipf_code, org_name, is_ctsa_hub) VALUES (?,?,1)", (ipf, name))
    c.execute("INSERT INTO grants (core_project_num, ipf_code, activity_code, is_hub_award, total_award_amount) VALUES ('UL1TR000001',1,'UL1',1,1000)")
    c.execute("INSERT INTO grants (core_project_num, ipf_code, activity_code, is_hub_award, total_award_amount) VALUES ('KL2TR000002',1,'KL2',0,500)")
    c.execute("INSERT INTO grants (core_project_num, ipf_code, activity_code, is_hub_award, total_award_amount) VALUES ('UL1TR000003',2,'UL1',1,2000)")
    c.execute("INSERT INTO grant_years (core_project_num, fiscal_year, project_num, award_amount) VALUES ('UL1TR000001',2020,'a',1000)")
    c.execute("INSERT INTO grant_years (core_project_num, fiscal_year, project_num, award_amount) VALUES ('UL1TR000003',2020,'c',2000)")
    yield c
    c.close()


@pytest.fixture
def impact_conn():
    c = sqlite3.connect(":memory:")
    c.executescript("""
        CREATE TABLE journals (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE papers (pmid INTEGER PRIMARY KEY, journal_id INTEGER,
                             pub_year INTEGER, is_research INTEGER);
        CREATE TABLE citations (id INTEGER PRIMARY KEY, cited_pmid INTEGER,
                                citing_pmid INTEGER);
    """)
    c.execute("INSERT INTO journals VALUES (10,'Nature')")
    c.execute("INSERT INTO papers VALUES (100,10,2020,1)")
    c.execute("INSERT INTO papers VALUES (200,10,2020,1)")
    c.execute("INSERT INTO citations VALUES (1,100,901)")
    c.execute("INSERT INTO citations VALUES (2,100,902)")
    yield c
    c.close()


def test_activity_group():
    assert activity_group("R01") == "R"
    assert activity_group("UL1") == "U"
    assert activity_group("KL2") == "K"
    assert activity_group("TL1") == "T"
    assert activity_group("R44") == "R"
    assert activity_group(None) == "other"


def test_n_linked_hubs_counts_sites_not_grants(conn):
    # PMID 100 is linked to two grants at the SAME hub -> 1 hub
    conn.execute("INSERT INTO grant_pubs VALUES ('UL1TR000001',100)")
    conn.execute("INSERT INTO grant_pubs VALUES ('KL2TR000002',100)")
    # PMID 200 is linked to grants at TWO different hubs -> 2 hubs
    conn.execute("INSERT INTO grant_pubs VALUES ('UL1TR000001',200)")
    conn.execute("INSERT INTO grant_pubs VALUES ('UL1TR000003',200)")
    compute_n_linked_hubs(conn)
    got = dict(conn.execute("SELECT pmid, n_linked_hubs FROM pub_metrics"))
    assert got[100] == 1
    assert got[200] == 2


def test_enrich_marks_missing_pmids_as_not_in_impact_db(conn, impact_conn):
    conn.execute("INSERT INTO grant_pubs VALUES ('UL1TR000001',100)")
    conn.execute("INSERT INTO grant_pubs VALUES ('UL1TR000001',999)")  # absent
    compute_n_linked_hubs(conn)
    stats = enrich_from_impact(conn, impact_conn)
    rows = dict(conn.execute("SELECT pmid, in_impact_db FROM pub_metrics"))
    assert rows[100] == 1
    assert rows[999] == 0
    assert stats["matched"] == 1
    assert stats["total"] == 2


def test_enrich_pulls_citation_count_and_journal(conn, impact_conn):
    conn.execute("INSERT INTO grant_pubs VALUES ('UL1TR000001',100)")
    compute_n_linked_hubs(conn)
    enrich_from_impact(conn, impact_conn)
    cites, jname, yr = conn.execute(
        "SELECT citation_count, journal_name, pub_year FROM pub_metrics WHERE pmid=100"
    ).fetchone()
    assert cites == 2
    assert jname == "Nature"
    assert yr == 2020


def test_site_metrics_give_full_credit_to_each_hub(conn, impact_conn):
    # One shared paper, linked to a grant at each of two hubs.
    conn.execute("INSERT INTO grant_pubs VALUES ('UL1TR000001',100)")
    conn.execute("INSERT INTO grant_pubs VALUES ('UL1TR000003',100)")
    compute_n_linked_hubs(conn)
    enrich_from_impact(conn, impact_conn)
    compute_site_metrics(conn)
    counts = dict(conn.execute(
        "SELECT ipf_code, pub_count FROM site_metrics WHERE year=2020 AND activity_group='U'"))
    assert counts[1] == 1
    assert counts[2] == 1  # full credit to BOTH, not 0.5 each


def test_cost_per_pub_is_award_total_over_pubs(conn, impact_conn):
    conn.execute("INSERT INTO grant_pubs VALUES ('UL1TR000001',100)")
    compute_n_linked_hubs(conn)
    enrich_from_impact(conn, impact_conn)
    compute_site_metrics(conn)
    cost = conn.execute(
        "SELECT cost_per_pub FROM site_metrics "
        "WHERE ipf_code=1 AND year=2020 AND activity_group='U'").fetchone()[0]
    assert cost == 1000.0


def test_recompute_does_not_duplicate_rows(conn, impact_conn):
    conn.execute("INSERT INTO grant_pubs VALUES ('UL1TR000001',100)")
    compute_n_linked_hubs(conn)
    enrich_from_impact(conn, impact_conn)
    compute_site_metrics(conn)
    first = conn.execute("SELECT COUNT(*) FROM site_metrics").fetchone()[0]
    compute_site_metrics(conn)
    assert conn.execute("SELECT COUNT(*) FROM site_metrics").fetchone()[0] == first

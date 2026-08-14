import json
import sqlite3
import pytest
from src.ncats.schema import create_schema
from src.ncats.site_registry import slugify, mark_ctsa_hubs, export_registry


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    create_schema(c)
    c.execute("INSERT INTO sites (ipf_code, org_name) VALUES (1, 'UNIVERSITY OF CALIFORNIA LOS ANGELES')")
    c.execute("INSERT INTO sites (ipf_code, org_name) VALUES (2, 'INSIGHTFIL')")
    # Hub with two renewal core projects at the same IPF
    c.execute("INSERT INTO grants (core_project_num, ipf_code, activity_code, is_hub_award) VALUES ('UL1TR000090',1,'UL1',1)")
    c.execute("INSERT INTO grants (core_project_num, ipf_code, activity_code, is_hub_award) VALUES ('UL1TR001070',1,'UL1',1)")
    c.execute("INSERT INTO grant_years (core_project_num, fiscal_year, project_num) VALUES ('UL1TR000090',2012,'a')")
    c.execute("INSERT INTO grant_years (core_project_num, fiscal_year, project_num) VALUES ('UL1TR001070',2024,'b')")
    # Non-hub award
    c.execute("INSERT INTO grants (core_project_num, ipf_code, activity_code, is_hub_award) VALUES ('R44TR003071',2,'R44',0)")
    c.execute("INSERT INTO grant_years (core_project_num, fiscal_year, project_num) VALUES ('R44TR003071',2024,'c')")
    yield c
    c.close()


def test_slugify():
    assert slugify("UNIVERSITY OF CALIFORNIA LOS ANGELES") == "university-of-california-los-angeles"
    assert slugify("Mayo Clinic  Rochester") == "mayo-clinic-rochester"
    assert slugify("St. Jude's & Co.") == "st-judes-co"


def test_only_hub_sites_are_flagged(conn):
    assert mark_ctsa_hubs(conn) == 1
    flags = dict(conn.execute("SELECT ipf_code, is_ctsa_hub FROM sites"))
    assert flags[1] == 1
    assert flags[2] == 0


def test_renewal_chain_collapses_to_one_site(conn):
    mark_ctsa_hubs(conn)
    rows = conn.execute("SELECT COUNT(*) FROM sites WHERE is_ctsa_hub=1").fetchone()[0]
    assert rows == 1, "two core projects at one IPF must be one site, not two"


def test_funded_year_span_covers_all_renewals(conn):
    mark_ctsa_hubs(conn)
    first, last = conn.execute(
        "SELECT first_funded_year, last_funded_year FROM sites WHERE ipf_code=1"
    ).fetchone()
    assert (first, last) == (2012, 2024)


def test_export_preserves_hand_edited_hub_name(conn, tmp_path):
    mark_ctsa_hubs(conn)
    path = tmp_path / "ctsa_registry.json"
    path.write_text(json.dumps([{"ipf_code": 1, "hub_name": "UCLA CTSI"}]))
    out = export_registry(conn, path)
    entry = [e for e in out if e["ipf_code"] == 1][0]
    assert entry["hub_name"] == "UCLA CTSI"
    assert entry["core_project_nums"] == ["UL1TR000090", "UL1TR001070"]

import sqlite3

import pytest
from src.ncats.schema import create_schema
from src.ncats.hub_merge import merge_hub_sites
from src.ncats.json_exporter import export_index


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    create_schema(c)
    for ipf, org, first, last in [(9, "DARTMOUTH COLLEGE", 2013, 2017),
                                  (10, "DARTMOUTH-HITCHCOCK CLINIC", 2024, 2026),
                                  (20, "DUKE UNIVERSITY", 2012, 2026)]:
        c.execute("INSERT INTO sites (ipf_code, org_name, slug, hub_name, is_ctsa_hub, "
                  "first_funded_year, last_funded_year) VALUES (?,?,?,?,1,?,?)",
                  (ipf, org, org.lower().replace(" ", "-"), org.title(), first, last))
    for core, ipf, code, fy, pmid in [("UL1A", 9, "UL1", 2015, 100),
                                      ("UM1B", 10, "UM1", 2025, 200),
                                      ("UL1C", 20, "UL1", 2015, 300)]:
        c.execute("INSERT INTO grants (core_project_num, ipf_code, activity_code, is_hub_award) "
                  "VALUES (?,?,?,1)", (core, ipf, code))
        c.execute("INSERT INTO grant_years (core_project_num, fiscal_year, project_num, award_amount) "
                  "VALUES (?,?,?,100)", (core, fy, core))
        c.execute("INSERT INTO grant_pubs VALUES (?,?)", (core, pmid))
        c.execute("INSERT INTO pub_metrics (pmid, pub_year, citation_count) VALUES (?,?,5)", (pmid, fy))
    yield c
    c.close()


@pytest.fixture
def hubs_csv(tmp_path):
    p = tmp_path / "hubs.csv"
    p.write_text("hub_id,label,member_ipf_codes,city,state,notes\n"
                 "10,Dartmouth,9;10,Lebanon,NH,\n"
                 "20,Duke University,20,Durham,NC,\n")
    return p


def test_merge_folds_hub_sites_without_touching_the_database(conn, hubs_csv):
    assert merge_hub_sites(conn, hubs_csv) == {9: 10}

    hubs = conn.execute("SELECT ipf_code, slug, hub_name, city, first_funded_year, "
                        "last_funded_year FROM sites WHERE is_ctsa_hub=1 ORDER BY ipf_code").fetchall()
    assert hubs[0] == (10, "dartmouth", "Dartmouth", "Lebanon", 2013, 2026)
    assert [h[0] for h in hubs] == [10, 20]
    assert conn.execute("SELECT ipf_code FROM grants WHERE core_project_num='UL1A'").fetchone()[0] == 10
    years = {r[0] for r in conn.execute("SELECT year FROM site_metrics WHERE ipf_code=10")}
    assert years == {2015, 2025}

    # ncats.db itself is unchanged.
    assert conn.execute("SELECT ipf_code FROM main.grants WHERE core_project_num='UL1A'").fetchone()[0] == 9
    assert conn.execute("SELECT COUNT(*) FROM main.sites WHERE is_ctsa_hub=1").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM main.site_metrics").fetchone()[0] == 0


def test_exporter_sees_one_merged_site(conn, hubs_csv, tmp_path):
    import json
    merge_hub_sites(conn, hubs_csv)
    index = json.loads(export_index(conn, tmp_path).read_text())
    assert index["total_sites"] == 2
    assert {s["slug"] for s in index["sites"]} == {"dartmouth", "duke-university"}


def test_no_multi_site_hub_leaves_connection_alone(conn, tmp_path):
    p = tmp_path / "hubs.csv"
    p.write_text("hub_id,label,member_ipf_codes,city,state,notes\n"
                 "9,A,9,X,NH,\n10,B,10,X,NH,\n20,C,20,X,NC,\n")
    assert merge_hub_sites(conn, p) == {}
    assert conn.execute("SELECT COUNT(*) FROM temp.sqlite_master").fetchone()[0] == 0

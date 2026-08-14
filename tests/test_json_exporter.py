import json
import sqlite3
import pytest
from src.ncats.schema import create_schema
from src.ncats.json_exporter import export_index, export_sites


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=ON")
    create_schema(c)
    c.execute("INSERT INTO sites (ipf_code, org_name, slug, hub_name, city, state, is_ctsa_hub, first_funded_year, last_funded_year) "
              "VALUES (1,'HUB A','hub-a','Hub A CTSI','BOSTON','MA',1,2012,2025)")
    c.execute("INSERT INTO grants (core_project_num, ipf_code, activity_code, title, is_hub_award, total_award_amount, first_fy, last_fy) "
              "VALUES ('UL1TR000001',1,'UL1','Award',1,1000,2012,2025)")
    c.execute("INSERT INTO site_metrics (ipf_code, year, activity_group, pub_count, research_count, citation_count, mean_rcr, award_total, cost_per_pub) "
              "VALUES (1,2020,'U',10,8,100,1.5,1000,100.0)")
    yield c
    c.close()


def test_index_lists_only_hub_sites(conn, tmp_path):
    conn.execute("INSERT INTO sites (ipf_code, org_name, slug, is_ctsa_hub) VALUES (2,'SMALL CO','small-co',0)")
    path = export_index(conn, tmp_path)
    data = json.loads(path.read_text())
    slugs = [s["slug"] for s in data["sites"]]
    assert slugs == ["hub-a"]
    assert data["total_grants"] == 1


def test_site_file_has_metrics_by_year(conn, tmp_path):
    assert export_sites(conn, tmp_path) == 1
    data = json.loads((tmp_path / "sites" / "hub-a.json").read_text())
    assert data["hub_name"] == "Hub A CTSI"
    assert data["metrics"][0]["year"] == 2020
    assert data["metrics"][0]["pub_count"] == 10
    assert data["grants"][0]["core_project_num"] == "UL1TR000001"

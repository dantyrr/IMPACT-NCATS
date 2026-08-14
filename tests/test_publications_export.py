import json
import sqlite3
import pytest
from src.ncats.schema import create_schema
from src.ncats.json_exporter import export_publications


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("PRAGMA foreign_keys=ON")
    create_schema(c)
    c.execute("INSERT INTO sites (ipf_code, org_name, slug, hub_name, state, is_ctsa_hub) VALUES (1,'A','a','Hub A','MA',1)")
    c.execute("INSERT INTO sites (ipf_code, org_name, slug, hub_name, state, is_ctsa_hub) VALUES (2,'B','b','Hub B','CA',1)")
    c.execute("INSERT INTO grants (core_project_num, ipf_code, activity_code, is_hub_award) VALUES ('UL1TR000001',1,'UL1',1)")
    c.execute("INSERT INTO grants (core_project_num, ipf_code, activity_code, is_hub_award) VALUES ('UL1TR000002',2,'UL1',1)")
    # Hub A: 2 papers, one shared with Hub B
    for pmid, rcr, cites in [(100, 9.5, 500), (101, 1.0, 10)]:
        c.execute("INSERT INTO pub_metrics (pmid,title,rcr,citation_count,journal_name,pub_year,is_research,in_impact_db,n_linked_hubs) "
                  "VALUES (?,?,?,?,'Nature',2020,1,1,1)", (pmid, f"Paper {pmid}", rcr, cites))
        c.execute("INSERT INTO grant_pubs VALUES ('UL1TR000001',?)", (pmid,))
    c.execute("INSERT INTO grant_pubs VALUES ('UL1TR000002',100)")
    c.execute("UPDATE pub_metrics SET n_linked_hubs=2 WHERE pmid=100")
    yield c
    c.close()


def test_top_by_rcr_is_ordered_and_titled(conn, tmp_path):
    path = export_publications(conn, tmp_path)
    d = json.loads(path.read_text())
    assert [p["pmid"] for p in d["top_by_rcr"]] == [100, 101]
    assert d["top_by_rcr"][0]["title"] == "Paper 100"
    assert d["top_by_rcr"][0]["rcr"] == 9.5


def test_shared_paper_lists_every_site(conn, tmp_path):
    d = json.loads(export_publications(conn, tmp_path).read_text())
    top = d["top_by_rcr"][0]
    assert top["sites"] == ["Hub A", "Hub B"]
    assert top["n_linked_hubs"] == 2


def test_top_by_citations_uses_citation_order(conn, tmp_path):
    d = json.loads(export_publications(conn, tmp_path).read_text())
    assert [p["pmid"] for p in d["top_by_citations"]] == [100, 101]
    assert d["top_by_citations"][0]["citations"] == 500


def test_site_rankings_sorted_by_mean_rcr_desc(conn, tmp_path):
    d = json.loads(export_publications(conn, tmp_path).read_text())
    r = d["site_rankings"]
    assert r[0]["hub_name"] == "Hub B"   # only paper 100, rcr 9.5
    assert r[1]["hub_name"] == "Hub A"   # mean of 9.5 and 1.0 = 5.25
    assert r[1]["mean_rcr"] == pytest.approx(5.25)


def test_small_sites_are_flagged_not_hidden(conn, tmp_path):
    """A site with few papers can post an extreme mean RCR; flag it."""
    d = json.loads(export_publications(conn, tmp_path, min_pubs=2).read_text())
    flags = {r["hub_name"]: r["below_threshold"] for r in d["site_rankings"]}
    assert flags["Hub B"] == 1   # 1 paper, below threshold of 2
    assert flags["Hub A"] == 0   # 2 papers, meets it
    assert len(d["site_rankings"]) == 2, "flagged sites must still be present"


def test_export_prunes_stale_investigator_files(conn, tmp_path):
    """A record removed from the DB must not leave its JSON behind, or the
    stale file keeps being uploaded and served forever."""
    from src.ncats.json_exporter import export_investigators
    inv_dir = tmp_path / "investigators"
    inv_dir.mkdir()
    (inv_dir / "999999.json").write_text('{"stale": true}')

    conn.execute("INSERT INTO investigators (profile_id, full_name) VALUES (1,'A')")
    conn.execute("INSERT INTO grant_pis (core_project_num, profile_id) VALUES ('UL1TR000001',1)")
    export_investigators(conn, tmp_path)

    assert (inv_dir / "1.json").exists()
    assert not (inv_dir / "999999.json").exists(), "stale file must be removed"


def test_export_prunes_stale_site_files(conn, tmp_path):
    from src.ncats.json_exporter import export_sites
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir()
    (sites_dir / "defunct-hub.json").write_text('{"stale": true}')

    export_sites(conn, tmp_path)
    assert (sites_dir / "a.json").exists()
    assert not (sites_dir / "defunct-hub.json").exists()

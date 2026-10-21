import sqlite3

import pytest
from src.ncats.schema import create_schema
from scripts.export_collaboration_json import build, sole_grant_hubs

HUBS = {
    10: {"label": "Beta Hub", "members": [10], "city": "Durham", "state": "NC"},
    20: {"label": "Alpha Hub", "members": [20], "city": "Boston", "state": "MA"},
}


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    create_schema(c)
    for ipf in (10, 20, 30):   # 30 is not a hub
        c.execute("INSERT INTO sites (ipf_code, org_name) VALUES (?, 'X')", (ipf,))
    c.executemany("INSERT INTO grants (core_project_num, ipf_code, activity_code) VALUES (?,?,?)",
                  [("UL1A", 10, "UL1"), ("UL1B", 20, "UL1"), ("R01C", 30, "R01")])
    c.executemany("INSERT INTO grant_years (core_project_num, fiscal_year, project_num) VALUES (?,?,?)",
                  [("UL1A", 2015, "x"), ("UL1A", 2016, "x"), ("UL1B", 2014, "y")])
    c.executemany("INSERT INTO grant_pubs (core_project_num, pmid) VALUES (?,?)",
                  [("UL1A", 1), ("UL1B", 1),   # co-funded by both hubs
                   ("UL1A", 2),                # only hub 10's grant
                   ("UL1B", 3), ("R01C", 3),   # a hub and a non-hub grant
                   ("UL1A", 4)])               # too old to export
    c.executemany("INSERT INTO pub_author_fetch (pmid, returned, n_authors, pub_year) VALUES (?,1,2,?)",
                  [(1, 2015), (2, 2016), (3, 2017), (4, 2010)])
    c.executemany("INSERT INTO pub_hubs (pmid, hub_id, tier, n_authors, n_core) VALUES (?,?,?,?,?)",
                  [(1, 10, "core", 1, 1), (1, 20, "partner", 1, 0), (2, 10, "core", 2, 2),
                   (3, 20, "core", 1, 1), (4, 10, "core", 1, 1)])
    yield c
    c.close()


def test_sole_grant_hubs(conn):
    assert sole_grant_hubs(conn, {10: 10, 20: 20}) == {2: 10, 4: 10}


def test_build_orders_hubs_by_label_and_encodes_papers(conn):
    d, pmids, idx = build(conn, HUBS, gaz=None, slugs={10: "beta"}, outreach={})
    assert pmids == [1, 2, 3] and idx == {20: 0, 10: 1}
    assert [h["label"] for h in d["hubs"]] == ["Alpha Hub", "Beta Hub"]   # Alpha = 0, Beta = 1
    beta = d["hubs"][1]
    assert beta["slug"] == "beta" and (beta["award_first"], beta["award_last"]) == (2015, 2016)
    assert beta["lat"] is None                      # no gazetteer
    p = d["papers"]
    assert p["y"] == [2015, 2016, 2017]             # 2010 paper dropped
    assert p["c"] == [[1], [1], [0]]
    assert p["p"] == [[0], [], []]
    assert p["f"] == [[0, 1], [1], [0]]
    assert p["s"] == [-1, 1, -1]
    assert d["n_papers"] == 3


def test_institution_layer_places_partners_and_other_institutions(conn):
    from scripts.export_collaboration_json import institution_layer
    from scripts.build_nonhub_collaboration import Part
    from src.ncats.gazetteer import Point
    from src.ncats.hub_matching import Alias, HubMatcher

    class FakeGazetteer:
        def city_point(self, city, state):
            return Point(42.36, -71.06, "x", "Boston city", "place") if (city or "").lower() == "boston" else None

        def zip_point(self, zip5):
            return None

    cullowhee = Point(35.31, -83.18, "y", "Cullowhee CDP", "place")
    wcu = lambda pmid: Part(pmid, 2, 1, country="USA", state="NC", city="Cullowhee",
                            inst_key="western carolina university", inst_name="Western Carolina University",
                            inst_type="university", point=cullowhee)
    by_paper = {1: [wcu(1)], 2: [wcu(2)], 3: [wcu(3)]}
    conn.execute("INSERT INTO pub_author_affils (pmid, position, affil_order, affiliation) VALUES "
                 "(1, 1, 1, 'Massachusetts General Hospital, Boston, MA, USA')")
    conn.execute("INSERT INTO pub_author_hubs (pmid, position, hub_id, tier) VALUES (1, 1, 20, 'partner')")
    matcher = HubMatcher([Alias(20, "Massachusetts General Hospital", "partner",
                                institution="Massachusetts General Hospital")])
    layer = institution_layer(conn, FakeGazetteer(), matcher, by_paper,
                              {"western carolina university": "Western Carolina University"},
                              layer_pos={1: 0, 2: 1, 3: 2}, hub_idx={20: 0, 10: 1})
    insts = layer["institutions"]
    assert [(d["name"], d["kind"], d["hub"], d["papers"]) for d in insts] == [
        ("Massachusetts General Hospital", "partner", 0, 1),
        ("Western Carolina University", "other", None, 3)]
    assert (insts[0]["city"], insts[0]["state"]) == ("Boston", "MA")
    assert insts[1]["lat"] == 35.31
    assert layer["rows"] == [0, 1, 2]
    assert layer["inst"] == [[0, 1], [1], [1]]

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
    c.executemany("INSERT INTO grants (core_project_num, ipf_code, activity_code, total_award_amount) VALUES (?,?,?,?)",
                  [("UL1A", 10, "UL1", 5e6), ("UL1B", 20, "UL1", 2e6), ("R01C", 30, "R01", 1e6)])
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
    assert (d["hubs"][0]["award_total"], beta["award_total"]) == (2000000, 5000000)
    p = d["papers"]
    assert p["y"] == [2015, 2016, 2017]             # 2010 paper dropped
    assert p["c"] == [[1], [1], [0]]
    assert p["p"] == [[0], [], []]
    assert p["f"] == [[0, 1], [1], [0]]
    assert p["s"] == [-1, 1, -1]
    assert d["n_papers"] == 3
    assert p["covid"] == [] and p["big"] == []


def test_build_lists_covid_and_big_author_list_papers(conn):
    conn.execute("INSERT INTO pub_metrics (pmid, title) VALUES (2, 'Hospital outcomes of COVID-19')")
    conn.execute("UPDATE pub_author_fetch SET n_authors = 150 WHERE pmid = 3")
    d, pmids, _ = build(conn, HUBS, gaz=None, slugs={}, outreach={})
    assert pmids == [1, 2, 3]
    assert d["papers"]["covid"] == [1] and d["papers"]["big"] == [2]


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


@pytest.mark.parametrize("code, num, group", [
    ("UL1", "UL1TR000433", "hub"), ("UM1", "UM1TR004404", "hub"),
    ("UM1", "UM1TR006029", "research"),          # NAMs center, not a hub award
    ("KL2", "KL2X", "training"), ("TL1", "TL1X", "training"), ("K12", "K12X", "training"),
    ("T32", "T32X", "training"), ("R25", "R25X", "training"),
    ("R43", "R43X", "small_business"), ("R44", "R44X", "small_business"), ("R41", "R41X", "small_business"),
    ("R21", "R21X", "research"), ("U01", "U01X", "research"), ("UH3", "UH3X", "research"),
])
def test_funding_group(code, num, group):
    from scripts.export_collaboration_json import funding_group
    assert funding_group(code, num) == group


def test_paper_attributes(conn):
    from scripts.export_collaboration_json import paper_attributes, FUNDING_BITS
    conn.execute("INSERT INTO themes (theme_id, label, size, mesh_label) VALUES (7, 'diab', 2, 'Diabetes Mellitus')")
    conn.executemany("INSERT INTO pub_themes (pmid, theme_id) VALUES (?, 7)", [(1,), (3,)])
    conn.executemany("INSERT INTO pub_metrics (pmid, pub_year, is_research, rcr, human, animal, molecular_cellular) "
                     "VALUES (?,?,?,?,?,?,?)",
                     [(1, 2015, 1, 2.34, 0.9, 0.0, 0.1), (2, 2016, 0, None, None, None, None)])
    conn.execute("INSERT INTO investigators (profile_id, full_name) VALUES (5, 'JANE A DOE')")
    conn.execute("INSERT INTO grant_pis (core_project_num, profile_id) VALUES ('UL1A', 5)")
    conn.execute("INSERT INTO pub_author_hubs (pmid, position, hub_id, tier) VALUES (1, 1, 10, 'core'), "
                 "(1, 2, 20, 'partner'), (1, 3, 20, 'core')")    # pmid 1 has 2 authors: position 3 is not last
    d = paper_attributes(conn, [1, 2, 3], HUBS, {20: 0, 10: 1})
    assert d["pmid_delta"] == [1, 1, 1]
    assert [t["label"] for t in d["themes"]] == ["Diabetes Mellitus"]
    assert d["theme"] == [0, -1, 0]
    assert d["research"] == [1, 0, -1]
    assert d["rcr10"] == [23, -1, -1]
    assert d["tri"] == [0, -1, -1]                  # human
    nums = [g["num"] for g in d["grant_list"]]
    assert d["funding"] == [FUNDING_BITS["hub"], FUNDING_BITS["hub"], FUNDING_BITS["hub"] | FUNDING_BITS["research"]]
    assert [sorted(nums[i] for i in gs) for gs in d["grants"]] == [["UL1A", "UL1B"], ["UL1A"], ["R01C", "UL1B"]]
    assert d["pis"] == [{"name": "Jane A Doe", "g": [nums.index("UL1A")]}]
    assert d["lead_core"] == [[1], [], []]          # first author at hub 10 (index 1)
    assert d["lead_broad"] == [[0, 1], [], []]      # plus the partner-tier last author at hub 20


def test_institution_layer_merges_spellings_and_prefers_a_nearby_zip(conn):
    from scripts.export_collaboration_json import institution_layer
    from scripts.build_nonhub_collaboration import Part
    from src.ncats.gazetteer import Point
    from src.ncats.hub_matching import HubMatcher

    chicago = Point(41.84, -87.68, "c", "Chicago city", "place")
    zips = {"60612": Point(41.88, -87.69, "z", "ZCTA 60612", "zcta"),
            "90210": Point(34.10, -118.41, "z2", "ZCTA 90210", "zcta")}   # a typo, far away

    class FakeGazetteer:
        def city_point(self, city, state):
            return None

        def zip_point(self, zip5):
            return zips.get(zip5)

    def rush(pmid, key, zip5):
        return Part(pmid, 2, 1, country="USA", state="IL", city="Chicago", zip=zip5, inst_key=key,
                    inst_name=key, inst_type="hospital", point=chicago)

    by_paper = {1: [rush(1, "rush university", "60612")], 2: [rush(2, "rush university medical center", "60612")],
                3: [rush(3, "rush university medical center", "90210")]}
    labels = {"rush university": "Rush University", "rush university medical center": "Rush University Medical Center"}
    layer = institution_layer(conn, FakeGazetteer(), HubMatcher([]), by_paper, labels,
                              layer_pos={1: 0, 2: 1, 3: 2}, hub_idx={20: 0, 10: 1})
    [d] = layer["institutions"]
    assert (d["name"], d["papers"]) == ("Rush University Medical Center", 3)
    assert (d["lat"], d["lon"]) == (41.88, -87.69)          # ZIP 60612, not the city point or the typo
    assert layer["inst"] == [[0], [0], [0]]


def test_hub_points_use_the_most_common_nearby_zip(conn):
    from scripts.export_collaboration_json import hub_points
    from src.ncats.gazetteer import Point

    class FakeGazetteer:
        def city_point(self, city, state):
            return Point(36.0, -78.9, "c", city, "place")

        def zip_point(self, zip5):
            return {"27710": Point(36.01, -78.94, "z", "ZCTA 27710", "zcta")}.get(zip5)

    conn.executemany("INSERT INTO pub_author_affils (pmid, position, affil_order, affiliation) VALUES (?,?,1,?)",
                     [(10 + i, 1, "Duke University School of Medicine, Durham, NC 27710, USA") for i in range(25)])
    conn.executemany("INSERT INTO pub_author_hubs (pmid, position, hub_id, tier) VALUES (?,1,10,'core')",
                     [(10 + i,) for i in range(25)])
    pts = hub_points(conn, HUBS, FakeGazetteer())
    assert pts[10] == (36.01, -78.94)        # 25 ZIP votes
    assert pts[20] == (36.0, -78.9)          # no votes: the city point

import sqlite3

import pytest
from src.ncats.schema import create_schema
from src.ncats.hub_matching import Alias, HubMatcher
from src.ncats.gazetteer import Point
from scripts.build_nonhub_collaboration import (Part, likely_hub, load_inputs, parse_rows,
                                                outreach_parts, hub_tables, coverage,
                                                possible_hub_names, map_point)

HUBS = {10: {"label": "Duke University", "city": "Durham", "state": "NC"},
        20: {"label": "Yale University", "city": "New Haven", "state": "CT"}}
DURHAM = Point(35.98, -78.90, "3719000", "Durham city", "place")
RALEIGH = Point(35.83, -78.64, "3755000", "Raleigh city", "place")
BOSTON = Point(42.34, -71.02, "2507000", "Boston city", "place")


@pytest.fixture
def matcher():
    return HubMatcher([Alias(30, "Massachusetts General Hospital", "partner"),
                       Alias(10, "Duke University", "core")])


def test_likely_hub_splits_fused_words(matcher):
    assert likely_hub("4Massachusetts General Hospital, Boston, MA", matcher) == 30
    assert likely_hub("Department of MedicineDuke University, Durham", matcher) == 10
    assert likely_hub("Massachusetts General Hospital, Boston", matcher) is None   # nothing to fix
    assert likely_hub("4Somewhere Else, Boston, MA", matcher) is None


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    create_schema(c)
    c.executemany("INSERT INTO pub_author_fetch (pmid, returned, n_authors, pub_year) VALUES (?,1,?,?)",
                  [(1, 3, 2013), (2, 3, 2015), (3, 2, 2016)])
    c.executemany("INSERT INTO pub_hubs (pmid, hub_id, tier, n_authors, n_core) VALUES (?,?,?,?,?)",
                  [(1, 10, "core", 1, 1), (2, 10, "core", 1, 1), (2, 20, "partner", 1, 0)])
    c.executemany("INSERT INTO pub_author_hubs (pmid, position, hub_id, tier) VALUES (?,?,?,?)",
                  [(1, 1, 10, "core"), (2, 1, 10, "core"), (2, 2, 20, "partner")])
    c.executemany("INSERT INTO pub_author_affils (pmid, position, affil_order, affiliation) VALUES (?,?,?,?)", [
        (1, 1, 1, "Duke University, Durham, NC"), (1, 2, 1, "RTI International, Durham, NC"),
        (2, 1, 1, "Duke University, Durham, NC"), (2, 2, 1, "Yale New Haven Hospital, CT"),
        (2, 3, 1, "NC State University, Raleigh, NC"), (2, 3, 2, "Department of Medicine."),
        (3, 1, 1, "Acme Inc, Boston, MA")])
    yield c
    c.close()


def test_load_inputs_keeps_non_hub_rows_from_the_start_year(conn):
    years, n_authors, hub_papers, rows = load_inputs(conn, 2014)
    assert years == {2: 2015, 3: 2016}
    assert hub_papers == {2: {10, 20}}
    assert sorted(rows) == [(2, 3, 1, "NC State University, Raleigh, NC"),
                            (2, 3, 2, "Department of Medicine."),
                            (3, 1, 1, "Acme Inc, Boston, MA")]
    _, _, hub_papers, _ = load_inputs(conn, 2014, core_only=True)
    assert hub_papers == {2: {10}}


def test_parse_rows_and_outreach_parts(matcher):
    rows = [(5, 2, 1, "NC State University, Raleigh, NC, USA"),
            (5, 3, 1, "Department of Medicine."),
            (5, 4, 1, "4Massachusetts General Hospital, Boston, MA")]
    parts, labels = parse_rows(rows, matcher)
    assert [(p.position, p.country, p.state, p.city, p.inst_key) for p in parts] == [
        (2, "USA", "NC", "Raleigh", "nc state university"),
        (3, None, None, None, None),
        (4, "USA", "MA", "Boston", "4massachusetts general hospital")]
    assert [p.missed_hub for p in parts] == [None, None, 30]
    assert labels["nc state university"] == "NC State University"
    by_paper, unmatched = outreach_parts(parts)
    assert unmatched[5] == {2, 3, 4}                 # every author without a hub row
    assert [p.position for p in by_paper[5]] == [2]  # not the stub, not the missed hub author


class _Gaz:
    def city_point(self, city, state):
        return {("Raleigh", "NC"): RALEIGH}.get((city, state))

    def zip_point(self, z):
        return {"02115": BOSTON}.get(z)


def test_map_point_prefers_the_city_then_the_zip():
    from src.ncats.affil_location import Location
    assert map_point(_Gaz(), Location("USA", "NC", None, "named", "Raleigh")) is RALEIGH
    assert map_point(_Gaz(), Location("USA", "MA", "02115", "named", "Bostn")) is BOSTON
    assert map_point(_Gaz(), Location("France", None, None, "named")) is None
    assert map_point(None, Location("USA", "NC", None, "named", "Raleigh")) is None


def _part(pmid, pos, **kw):
    return Part(pmid, pos, 1, **kw)


@pytest.fixture
def tables():
    by_paper = {
        # paper 1: Duke with an in-state university near Durham and a UK industry co-author
        1: [_part(1, 2, country="USA", state="NC", inst_key="nc state", inst_type="university", point=RALEIGH),
            _part(1, 3, country="United Kingdom", inst_key="acme ltd", inst_type="industry")],
        # paper 2: Duke and Yale with a Boston hospital; 150 authors
        2: [_part(2, 4, country="USA", state="MA", inst_key="bmc", inst_type="hospital", point=BOSTON)],
    }
    unmatched = {1: {2, 3}, 2: {4}, 3: {5}}
    hub_papers = {1: {10}, 2: {10, 20}, 3: {20}}
    years = {1: 2015, 2: 2016, 3: 2016}
    n_authors = {1: 5, 2: 150, 3: 4}
    labels = {"nc state": "NC State", "acme ltd": "Acme Ltd", "bmc": "Boston Medical Center"}
    return hub_tables(hub_papers, by_paper, unmatched, HUBS, years, n_authors, labels,
                      {10: DURHAM, 20: Point(41.31, -72.92, "", "New Haven city", "place")})


def test_hub_summary(tables):
    duke, yale = tables["summary"]
    assert duke["hub_id"] == 10 and duke["papers"] == 2
    assert duke["papers_with_nonhub_coauthor"] == 2 and duke["pct_with_nonhub_coauthor"] == 100.0
    assert duke["papers_nonhub_us"] == 2 and duke["papers_nonhub_international"] == 1
    assert duke["pct_international_of_located"] == 50.0
    assert duke["papers_nonhub_in_state"] == 1 and duke["papers_nonhub_out_of_state"] == 1
    assert duke["papers_nonhub_within_100km"] == 1            # Raleigh is ~25 km from Durham
    assert duke["median_km_to_nonhub_us"] > 25
    assert (duke["nonhub_states"], duke["nonhub_countries"]) == (2, 1)
    assert (duke["nonhub_states_under_100_authors"], duke["nonhub_countries_under_100_authors"]) == (1, 1)
    assert (duke["nonhub_states_5plus_papers"], duke["nonhub_countries_5plus_papers"]) == (0, 0)
    assert (duke["papers_nonhub_university"], duke["papers_nonhub_industry"],
            duke["papers_nonhub_hospital"]) == (1, 1, 1)
    # Yale's paper 3 has only a stub co-author: unmatched, but not outreach.
    assert yale["papers"] == 2 and yale["papers_with_unmatched_author"] == 2
    assert yale["papers_with_nonhub_coauthor"] == 1


def test_hub_place_tables(tables):
    states = {(r["hub_id"], r["state"]): r for r in tables["states"]}
    assert states[(10, "NC")]["in_state"] == 1 and states[(10, "MA")]["in_state"] == 0
    assert states[(10, "MA")]["papers"] == 1 and states[(10, "MA")]["papers_under_100_authors"] == 0
    assert states[(20, "MA")]["papers"] == 1
    cities = {(r["hub_id"], r["place"]): r for r in tables["cities"]}
    assert cities[(10, "Raleigh city")]["km_from_hub"] == pytest.approx(25, abs=5)
    assert cities[(10, "Raleigh city")]["precision"] == "city"
    assert {(r["hub_id"], r["country"]) for r in tables["countries"]} == {
        (10, "USA"), (10, "United Kingdom"), (20, "USA")}
    assert [(r["hub_id"], r["rank"], r["institution"]) for r in tables["top"]] == [
        (10, 1, "Acme Ltd"), (10, 2, "Boston Medical Center"), (10, 3, "NC State"),
        (20, 1, "Boston Medical Center")]
    inst = {r["institution_key"]: r for r in tables["institutions"]}
    assert inst["bmc"]["hubs_reached"] == 2 and inst["bmc"]["state"] == "MA"
    yearly = {(r["hub_id"], r["year"]): r for r in tables["yearly"]}
    assert yearly[(20, 2016)]["papers"] == 2 and yearly[(20, 2016)]["papers_nonhub_us"] == 1


def test_coverage_counts_each_affiliation_row_once():
    parts = [_part(1, 2, country="USA", state="NC", basis="named", inst_key="x", point=RALEIGH),
             _part(1, 3, country="USA", basis="named"),
             _part(2, 2), _part(2, 3, country="France", basis="named", missed_hub=30)]
    rows = {r["year"]: r for r in coverage(parts, {1: 2015, 2: 2016})}
    a = rows["all"]
    assert (a["affiliations"], a["with_country"], a["us"], a["us_with_state"]) == (4, 3, 2, 1)
    assert a["pct_us_with_point"] == 50.0 and a["likely_missed_hub"] == 1
    assert rows[2016]["affiliations"] == 2


def test_possible_hub_names():
    aliases = [Alias(1, "Johns Hopkins University", "core"), Alias(2, "University of Florida", "core")]
    insts = [{"institution_key": "john hopkins university", "country": "USA", "papers": 30},
             {"institution_key": "florida state university", "country": "USA", "papers": 30},
             {"institution_key": "hopkins hospital", "country": "UK", "papers": 30}]
    out = possible_hub_names(insts, aliases)
    assert [(r["institution_key"], r["resembles_hub_ids"]) for r in out] == [("john hopkins university", "1")]

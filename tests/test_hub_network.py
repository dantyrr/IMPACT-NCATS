import sqlite3

import pytest
from src.ncats.schema import create_schema
from scripts.build_hub_network import (pair_weights, coauthor_hub_sets, cofunding_hub_sets,
                                       write_vosviewer)


def test_pair_weights_full_and_fractional():
    sets = {1: ({10, 20}, 2015), 2: ({10, 20, 30}, 2015), 3: ({10}, 2016)}
    full, frac = pair_weights(sets)
    assert full == {(10, 20): 2, (10, 30): 1, (20, 30): 1}
    # A paper with k hubs gives each of its pairs 1/(k-1), so each hub's total
    # link strength from one paper is 1 (Perianes-Rodriguez et al. 2016).
    assert frac[(10, 20)] == pytest.approx(1 + 0.5)
    assert frac[(10, 30)] == pytest.approx(0.5)


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    create_schema(c)
    c.executemany("INSERT INTO pub_author_fetch (pmid, returned, n_authors, pub_year) VALUES (?,1,3,?)",
                  [(1, 2013), (2, 2015), (3, 2016)])
    c.execute("INSERT INTO pub_metrics (pmid, pub_year) VALUES (2, 2014)")   # pub_metrics year wins
    c.executemany("INSERT INTO pub_hubs (pmid, hub_id, tier, n_authors, n_core) VALUES (?,?,?,?,?)", [
        (1, 10, "core", 1, 1), (1, 20, "core", 1, 1),
        (2, 10, "core", 2, 2), (2, 20, "partner", 1, 0),
        (3, 30, "core", 1, 1)])
    yield c
    c.close()


def test_coauthor_hub_sets_strict_drops_partner_only_hubs(conn):
    strict = coauthor_hub_sets(conn, broad=False, from_year=2012)
    assert strict == {1: ({10, 20}, 2013), 2: ({10}, 2014), 3: ({30}, 2016)}


def test_coauthor_hub_sets_broad_and_year_floor(conn):
    broad = coauthor_hub_sets(conn, broad=True, from_year=2014)
    assert broad == {2: ({10, 20}, 2014), 3: ({30}, 2016)}


def test_cofunding_hub_sets_count_only_ctsa_program_awards(conn):
    conn.executemany("INSERT INTO grants (core_project_num, ipf_code, activity_code) VALUES (?,?,?)", [
        ("UL1A", 100, "UL1"), ("KL2B", 200, "KL2"), ("R21C", 300, "R21"), ("UM1TR006029", 300, "UM1")])
    conn.executemany("INSERT INTO grant_pubs (core_project_num, pmid) VALUES (?,?)", [
        ("UL1A", 2), ("KL2B", 2), ("R21C", 2), ("UM1TR006029", 3), ("UL1A", 3)])
    to_hub = {100: 10, 200: 20, 300: 30}
    sets = cofunding_hub_sets(conn, to_hub, from_year=2012)
    assert sets == {2: ({10, 20}, 2014), 3: ({10}, 2016)}


def test_write_vosviewer(tmp_path):
    nodes = [{"hub_id": 10, "label": "Duke University", "papers": 5, "cross_hub_papers": 2},
             {"hub_id": 20, "label": "UNC Chapel Hill", "papers": 4, "cross_hub_papers": 2}]
    m, n = tmp_path / "map.txt", tmp_path / "net.txt"
    write_vosviewer(nodes, {(10, 20): 2}, m, n)
    lines = m.read_text().splitlines()
    assert lines[0] == "id\tlabel\tweight<Papers>\tweight<Cross-hub papers>"
    assert lines[1] == "10\tDuke University\t5\t2"
    assert n.read_text() == "10\t20\t2\n"

import csv
import sqlite3

import pytest
from src.ncats.schema import create_schema
from scripts.export_author_affiliations import classify, coverage_by_year, write_affiliations_csv


@pytest.mark.parametrize("n_person, n_affil, first_affil, expected", [
    (3, 3, True, "all"),
    (1, 1, True, "all"),          # a lone affiliated author is complete, not "first only"
    (3, 1, True, "first_only"),
    (3, 1, False, "partial"),     # one co-author affiliated, but not the first
    (3, 2, True, "partial"),
    (3, 0, False, "none"),
    (0, 0, False, None),          # group author only: nothing to measure
])
def test_classify(n_person, n_affil, first_affil, expected):
    assert classify(n_person, n_affil, first_affil) == expected


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    create_schema(c)

    def paper(pmid, year, authors, metrics_year=None):
        c.execute("INSERT INTO pub_author_fetch (pmid, returned, n_authors, pub_year) "
                  "VALUES (?,1,?,?)", (pmid, len(authors), year))
        if metrics_year is not None:
            c.execute("INSERT INTO pub_metrics (pmid, pub_year) VALUES (?,?)",
                      (pmid, metrics_year))
        for pos, (name, affils) in enumerate(authors, start=1):
            collective = name if name.startswith("Group") else None
            c.execute("INSERT INTO pub_authors (pmid, position, last_name, collective_name) "
                      "VALUES (?,?,?,?)", (pmid, pos, None if collective else name, collective))
            for k, a in enumerate(affils, start=1):
                c.execute("INSERT INTO pub_author_affils VALUES (?,?,?,?)", (pmid, pos, k, a))

    # pub_metrics year wins over PubMed's where both exist.
    paper(1, 2012, [("A", ["U1"]), ("B", []), ("C", [])], metrics_year=2013)
    paper(2, 2013, [("A", ["U1"]), ("B", ["U2", "U3"])])
    paper(3, 2013, [("A", ["U1"]), ("B", []), ("Group X", [])])   # group excluded
    paper(4, 2013, [("A", []), ("B", [])])
    c.execute("INSERT INTO pub_author_fetch (pmid, returned) VALUES (5, 0)")
    yield c
    c.close()


def test_coverage_by_year(conn):
    rows = {r["pub_year"]: r for r in coverage_by_year(conn)}
    assert set(rows) == {2013}
    r = rows[2013]
    assert r["papers"] == 4
    assert r["n_all"] == 1 and r["n_first_only"] == 2 and r["n_none"] == 1
    assert r["pct_all"] == 25.0
    assert r["pct_first_only"] == 50.0
    assert r["mean_authors"] == 2.5   # (3 + 2 + 3 + 2) / 4, group author counted


def test_csv_has_one_row_per_author_affiliation(conn, tmp_path):
    out = tmp_path / "a.csv"
    n = write_affiliations_csv(conn, out)
    rows = list(csv.DictReader(out.open()))
    assert n == len(rows)
    # paper 2 author B has two affiliations -> two rows, in order
    b = [r for r in rows if r["pmid"] == "2" and r["position"] == "2"]
    assert [r["affiliation"] for r in b] == ["U2", "U3"]
    # an author with no affiliation still gets one row, blank affiliation
    nb = [r for r in rows if r["pmid"] == "1" and r["position"] == "2"]
    assert len(nb) == 1 and nb[0]["affiliation"] == "" and nb[0]["affil_order"] == ""
    assert {r["pub_year"] for r in rows if r["pmid"] == "1"} == {"2013"}
    assert {r["n_authors"] for r in rows if r["pmid"] == "1"} == {"3"}

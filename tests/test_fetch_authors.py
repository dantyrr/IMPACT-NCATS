import sqlite3
from pathlib import Path

import pytest
from src.ncats.schema import create_schema
from scripts.fetch_authors import parse_authors, normalize_orcid, store_batch

FIXTURE = Path(__file__).parent / "fixtures" / "pubmed_authors.xml"


@pytest.fixture(scope="module")
def records():
    return {r["pmid"]: r for r in parse_authors(FIXTURE.read_bytes())}


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    create_schema(c)
    yield c
    c.close()


def test_parses_every_article_and_book(records):
    assert set(records) == {31000001, 23000002, 35000003, 28000004}


def test_multi_affiliation_author_keeps_each_string_in_order(records):
    smith = records[31000001]["authors"][0]
    assert smith["last_name"] == "Smith"
    assert smith["fore_name"] == "Jane A"
    assert smith["initials"] == "JA"
    assert smith["affiliations"] == [
        "Department of Medicine, University of Michigan, Ann Arbor, MI, USA.",
        "Michigan Institute for Clinical & Health Research, Ann Arbor, MI, USA.",
    ]


def test_semicolon_joined_affiliation_is_not_split(records):
    jones = records[31000001]["authors"][1]
    assert len(jones["affiliations"]) == 1
    assert "; Department of Biostatistics" in jones["affiliations"][0]


def test_author_without_affiliation_has_empty_list(records):
    lee = records[31000001]["authors"][2]
    assert lee["last_name"] == "Lee"
    assert lee["affiliations"] == []
    assert lee["orcid"] is None


def test_invalid_author_entry_is_dropped_and_positions_are_contiguous(records):
    authors = records[31000001]["authors"]
    assert [a["last_name"] for a in authors] == ["Smith", "Jones", "Lee"]
    assert [a["position"] for a in authors] == [1, 2, 3]


def test_orcid_is_normalized_from_url_and_unhyphenated_forms(records):
    smith, jones = records[31000001]["authors"][:2]
    assert smith["orcid"] == "0000-0002-1825-0097"
    assert jones["orcid"] == "0000-0002-1825-0097"


@pytest.mark.parametrize("raw, expected", [
    ("0000-0002-1825-0097", "0000-0002-1825-0097"),
    ("http://orcid.org/0000-0002-1825-009X", "0000-0002-1825-009X"),
    (" 000000021825009x ", "0000-0002-1825-009X"),
    ("not-an-orcid", None),
    ("", None),
])
def test_normalize_orcid(raw, expected):
    assert normalize_orcid(raw) == expected


def test_collective_author_has_name_and_no_person_fields(records):
    group = records[23000002]["authors"][1]
    assert group["collective_name"] == "CTSA Consortium Working Group"
    assert group["last_name"] is None
    assert group["affiliations"] == []


def test_investigator_list_is_not_part_of_byline(records):
    names = [a["last_name"] for a in records[23000002]["authors"]]
    assert "Patel" not in names
    assert len(names) == 2


def test_affiliation_strips_only_surrounding_whitespace(records):
    garcia = records[23000002]["authors"][0]
    assert garcia["affiliations"] == ["University of Rochester, Rochester, NY."]


def test_article_without_author_list_has_no_authors(records):
    assert records[35000003]["authors"] == []


def test_book_keeps_authors_not_editors_and_skips_empty_affiliation(records):
    authors = records[28000004]["authors"]
    assert [a["last_name"] for a in authors] == ["Writer"]
    assert authors[0]["affiliations"] == ["Johns Hopkins University, Baltimore, MD."]


@pytest.mark.parametrize("pmid, year", [
    (31000001, 2019),   # PubDate/Year
    (23000002, 2013),   # MedlineDate
    (35000003, 2022),   # ArticleDate fallback
    (28000004, 2017),   # Book PubDate
])
def test_pub_year(records, pmid, year):
    assert records[pmid]["pub_year"] == year


def test_store_batch_writes_authors_affiliations_and_status(conn, records):
    store_batch(conn, [31000001, 99999999], [records[31000001]])
    assert conn.execute("SELECT COUNT(*) FROM pub_authors").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM pub_author_affils").fetchone()[0] == 3
    status = dict((r[0], r[1:]) for r in conn.execute(
        "SELECT pmid, returned, n_authors, pub_year FROM pub_author_fetch"))
    assert status == {31000001: (1, 3, 2019), 99999999: (0, 0, None)}


def test_store_batch_is_idempotent(conn, records):
    recs = list(records.values())
    pmids = list(records)
    store_batch(conn, pmids, recs)
    store_batch(conn, pmids, recs)
    assert conn.execute("SELECT COUNT(*) FROM pub_authors").fetchone()[0] == 6
    assert conn.execute("SELECT COUNT(*) FROM pub_author_affils").fetchone()[0] == 5
    assert conn.execute("SELECT COUNT(*) FROM pub_author_fetch").fetchone()[0] == 4


def test_refetch_replaces_a_shortened_author_list(conn, records):
    full = records[31000001]
    store_batch(conn, [31000001], [full])
    shorter = {**full, "authors": full["authors"][:1]}
    store_batch(conn, [31000001], [shorter])
    assert conn.execute("SELECT COUNT(*) FROM pub_authors").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM pub_author_affils").fetchone()[0] == 2
    assert conn.execute(
        "SELECT n_authors FROM pub_author_fetch WHERE pmid=31000001").fetchone()[0] == 1

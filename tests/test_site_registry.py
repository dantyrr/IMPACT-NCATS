import json
import sqlite3
import pytest
from src.ncats.schema import create_schema
from src.ncats.site_registry import (
    slugify, mark_ctsa_hubs, export_registry, canonicalize_ipf_codes,
)


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


def test_canonicalize_merges_alias_ipf_into_one_site(conn):
    """One institution re-registered under a new IPF must collapse to one site."""
    # IPF 3 is the same institution as IPF 1, registered later.
    conn.execute("INSERT INTO sites (ipf_code, org_name) VALUES (3, 'UCLA INC')")
    conn.execute("INSERT INTO grants (core_project_num, ipf_code, activity_code, is_hub_award) "
                 "VALUES ('UL1TR009999',3,'UL1',1)")
    conn.execute("INSERT INTO grant_years (core_project_num, fiscal_year, project_num) "
                 "VALUES ('UL1TR009999',2030,'z')")

    moved = canonicalize_ipf_codes(conn, {3: 1})
    assert moved == 1

    # The alias site is gone and its grant now belongs to the canonical site.
    assert conn.execute("SELECT COUNT(*) FROM sites WHERE ipf_code=3").fetchone()[0] == 0
    assert conn.execute(
        "SELECT ipf_code FROM grants WHERE core_project_num='UL1TR009999'"
    ).fetchone()[0] == 1

    mark_ctsa_hubs(conn)
    assert conn.execute("SELECT COUNT(*) FROM sites WHERE is_ctsa_hub=1").fetchone()[0] == 1
    first, last = conn.execute(
        "SELECT first_funded_year, last_funded_year FROM sites WHERE ipf_code=1"
    ).fetchone()
    assert (first, last) == (2012, 2030)


def test_canonicalize_is_idempotent(conn):
    conn.execute("INSERT INTO sites (ipf_code, org_name) VALUES (3, 'UCLA INC')")
    conn.execute("INSERT INTO grants (core_project_num, ipf_code, activity_code, is_hub_award) "
                 "VALUES ('UL1TR009999',3,'UL1',1)")
    canonicalize_ipf_codes(conn, {3: 1})
    assert canonicalize_ipf_codes(conn, {3: 1}) == 0


def test_export_raises_on_duplicate_slug(conn, tmp_path):
    """A slug collision must fail loudly, never silently overwrite a hub file."""
    conn.execute("INSERT INTO sites (ipf_code, org_name) VALUES (9, 'UNIVERSITY OF CALIFORNIA LOS ANGELES')")
    conn.execute("INSERT INTO grants (core_project_num, ipf_code, activity_code, is_hub_award) "
                 "VALUES ('UL1TR008888',9,'UL1',1)")
    mark_ctsa_hubs(conn)
    with pytest.raises(ValueError, match="[Dd]uplicate slug"):
        export_registry(conn, tmp_path / "ctsa_registry.json")


def test_export_writes_hub_name_back_to_sites_table(conn, tmp_path):
    """export_index() reads sites.hub_name, so the registry must populate it."""
    mark_ctsa_hubs(conn)
    export_registry(conn, tmp_path / "ctsa_registry.json")
    name = conn.execute("SELECT hub_name FROM sites WHERE ipf_code=1").fetchone()[0]
    assert name, "hub_name must not be null after export_registry"


def test_export_preserves_hand_edited_hub_name(conn, tmp_path):
    mark_ctsa_hubs(conn)
    path = tmp_path / "ctsa_registry.json"
    path.write_text(json.dumps([{"ipf_code": 1, "hub_name": "UCLA CTSI"}]))
    out = export_registry(conn, path)
    entry = [e for e in out if e["ipf_code"] == 1][0]
    assert entry["hub_name"] == "UCLA CTSI"
    assert entry["core_project_nums"] == ["UL1TR000090", "UL1TR001070"]

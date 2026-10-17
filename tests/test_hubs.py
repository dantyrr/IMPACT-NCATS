import sqlite3

import pytest
from src.ncats.schema import create_schema
from src.ncats.hubs import (is_ctsa_hub_award, is_ctsa_program_award, load_hubs,
                            site_to_hub, check_hubs_cover_awards)


@pytest.mark.parametrize("code, num, expected", [
    ("UL1", "UL1TR000433", True),
    ("UM1", "UM1TR004404", True),     # Michigan's hub UM1, title just "MICHR"
    ("UM1", "UM1TR006029", False),    # MIT NAMs center
    ("UM1", "UM1TR006047", False),    # Brigham and Women's NAMs center
    ("KL2", "KL2TR000435", False),
])
def test_is_ctsa_hub_award(code, num, expected):
    assert is_ctsa_hub_award(code, num) is expected


@pytest.mark.parametrize("code, num, expected", [
    ("KL2", "KL2X", True), ("TL1", "TL1X", True), ("K12", "K12X", True), ("T32", "T32X", True),
    ("UL1", "UL1X", True),
    ("UM1", "UM1TR006055", False),
    ("R21", "R21X", False), ("U01", "U01X", False),
])
def test_is_ctsa_program_award(code, num, expected):
    assert is_ctsa_program_award(code, num) is expected


@pytest.fixture
def hubs_csv(tmp_path):
    p = tmp_path / "hubs.csv"
    p.write_text("hub_id,label,member_ipf_codes,city,state,notes\n"
                 "10,Dartmouth,9;10,Lebanon,NH,merged\n"
                 "20,Duke University,20,Durham,NC,\n")
    return p


def test_load_hubs_and_site_mapping(hubs_csv):
    hubs = load_hubs(hubs_csv)
    assert hubs[10]["label"] == "Dartmouth"
    assert hubs[10]["members"] == [9, 10]
    assert site_to_hub(hubs) == {9: 10, 10: 10, 20: 20}


def test_check_hubs_cover_awards(hubs_csv):
    conn = sqlite3.connect(":memory:")
    create_schema(conn)
    for ipf in (9, 20, 30):
        conn.execute("INSERT INTO sites (ipf_code, org_name) VALUES (?, 'X')", (ipf,))
    conn.execute("INSERT INTO grants (core_project_num, ipf_code, activity_code, title) "
                 "VALUES ('UL1A', 9, 'UL1', 'x'), ('UL1B', 20, 'UL1', 'x'), "
                 "('UM1TR006029', 30, 'UM1', 'NAMs center')")
    check_hubs_cover_awards(conn, load_hubs(hubs_csv))   # NAMs site 30 is correctly absent
    conn.execute("INSERT INTO grants (core_project_num, ipf_code, activity_code, title) "
                 "VALUES ('UL1D', 30, 'UL1', 'x')")
    with pytest.raises(ValueError, match="30"):
        check_hubs_cover_awards(conn, load_hubs(hubs_csv))

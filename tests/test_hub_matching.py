import pytest
from src.ncats.hub_matching import Alias, HubMatcher, normalize, load_aliases, institution_segments

ALIASES = [
    Alias(1, "University of Pennsylvania", "core"),
    Alias(None, "Indiana University of Pennsylvania", "block"),
    Alias(2, "Indiana University", "core"),
    Alias(3, "Mount Sinai", "core", ("new york", "ny")),
    Alias(4, "Harvard Medical School", "core"),
    Alias(4, "Massachusetts General Hospital", "partner"),
    Alias(5, "Washington University", "core"),
    Alias(None, "George Washington University", "block"),
    Alias(6, "University of Washington", "core"),
    Alias(7, "UCLA", "core"),
]


@pytest.fixture(scope="module")
def m():
    return HubMatcher(ALIASES)


def test_normalize():
    assert normalize("Children's Hospital & Medical Center") == "children s hospital and medical center"
    assert normalize("University of Wisconsin–Madison.") == "university of wisconsin madison"
    assert normalize(None) == ""


@pytest.mark.parametrize("text, expected", [
    ("Dept of Medicine, University of Pennsylvania, Philadelphia, PA", {1: "core"}),
    ("Indiana University School of Medicine, Indianapolis, IN", {2: "core"}),
    ("Washington University School of Medicine, St. Louis, MO", {5: "core"}),
    ("University of Washington, Seattle; Washington University in St. Louis", {5: "core", 6: "core"}),
    ("Private practice, Springfield, IL", {}),
])
def test_basic_matches(m, text, expected):
    assert m.match(text) == expected


def test_block_alias_hides_the_hub_name_inside_it(m):
    assert m.match("Indiana University of Pennsylvania, Indiana, PA") == {}
    assert m.match("George Washington University, Washington, DC") == {}
    assert m.aliases_found("Indiana University of Pennsylvania, Indiana, PA") == []


def test_aliases_found_reports_each_matched_name(m):
    assert m.aliases_found("Massachusetts General Hospital and Harvard Medical School") == [
        ("Massachusetts General Hospital", 4, "partner"), ("Harvard Medical School", 4, "core")]


def test_requires_context_word(m):
    assert m.match("Mount Sinai Hospital, Toronto, Ontario, Canada") == {}
    assert m.match("Icahn School of Medicine at Mount Sinai, New York, NY") == {3: "core"}


def test_strongest_tier_wins_for_one_hub(m):
    assert m.match("Massachusetts General Hospital, Boston, MA") == {4: "partner"}
    assert m.match("Massachusetts General Hospital and Harvard Medical School") == {4: "core"}


@pytest.mark.parametrize("text, expected", [
    ("4Massachusetts General Hospital, Boston, MA", {4: "partner"}),       # footnote number
    ("6915Harvard Medical School", {4: "core"}),
    ("Department of MedicineHarvard Medical SchoolBoston", {4: "core"}),   # run-together words
    ("Indiana University of PennsylvaniaDepartment of Biology", {}),       # a fused block still blocks
    ("UCLADepartment of Medicine", {7: "core"}),                           # acronym run into a word
])
def test_fused_text_is_split_before_matching(m, text, expected):
    assert m.match(text) == expected


def test_alias_with_internal_capitals_matches_either_spelling():
    m = HubMatcher([Alias(4, "Partners HealthCare", "partner"), Alias(4, "McLean Hospital", "partner")])
    for text in ["Partners HealthCare, Boston", "Partners Healthcare, Boston",
                 "McLean Hospital, Belmont, MA", "Mclean Hospital, Belmont, MA"]:
        assert m.match(text) == {4: "partner"}, text


def test_email_addresses_are_not_affiliations(m):
    assert m.match("Dept of Medicine, Harvard Medical School. Electronic address: jdoe@ucla.edu.") == {4: "core"}


def test_alias_matches_whole_words_only(m):
    assert m.match("University of Central Lancashire (UCLan), Preston, UK") == {}
    assert m.match("David Geffen School of Medicine at UCLA, Los Angeles") == {7: "core"}


def test_same_alias_for_two_hubs_is_rejected():
    with pytest.raises(ValueError, match="NewYork-Presbyterian"):
        HubMatcher([Alias(1, "NewYork-Presbyterian", "partner"),
                    Alias(2, "NewYork Presbyterian", "partner")])


def test_one_alias_can_serve_several_hubs_when_context_separates_them():
    m = HubMatcher([
        Alias(10, "University of California", "core", ("san francisco",)),
        Alias(11, "University of California", "core", ("los angeles",)),
        Alias(None, "University of California Berkeley", "block"),
    ])
    assert m.match("University of California, Dept of Medicine, San Francisco, CA") == {10: "core"}
    assert m.match("University of California, Los Angeles, CA") == {11: "core"}
    assert m.match("University of California, Berkeley, CA") == {}
    # Both cities present: ambiguous, so neither hub is claimed.
    assert m.match("University of California, San Francisco and Los Angeles") == {}


def test_shared_alias_without_context_is_rejected():
    with pytest.raises(ValueError, match="context"):
        HubMatcher([Alias(10, "University of California", "core", ("san francisco",)),
                    Alias(11, "University of California", "core")])


def test_unknown_tier_is_rejected():
    with pytest.raises(ValueError, match="tier"):
        HubMatcher([Alias(1, "Somewhere", "maybe")])


def test_load_aliases_from_csv(tmp_path):
    p = tmp_path / "aliases.csv"
    p.write_text("hub_id,alias,tier,requires,note\n"
                 "3,Mount Sinai,core,new york;ny,\n"
                 ",Mount Sinai Hospital Toronto,block,,Canada\n")
    a = load_aliases(p)
    assert a[0] == Alias(3, "Mount Sinai", "core", ("new york", "ny"))
    assert a[1] == Alias(None, "Mount Sinai Hospital Toronto", "block", ())


def test_institution_segments_skip_departments():
    segs = institution_segments(
        "Department of Medicine, University of Michigan Medical School; "
        "Division of Cardiology, VA Ann Arbor Healthcare System, Ann Arbor, MI, USA.")
    assert segs == ["university of michigan medical school", "va ann arbor healthcare system"]

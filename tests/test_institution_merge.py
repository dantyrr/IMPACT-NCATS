import re

from src.ncats.institution_merge import InstitutionAlias, load_institution_aliases, merge_institutions

CHICAGO, EVANSTON = (41.84, -87.68), (42.05, -87.69)
DALLAS, ARLINGTON_TX = (32.79, -96.77), (32.70, -97.12)
TUSCALOOSA, BIRMINGHAM = (33.23, -87.53), (33.53, -86.80)


def entry(label, state, at, weight=10):
    return {"label": label, "state": state, "lat": at[0], "lon": at[1], "weight": weight}


def labels(entries, aliases=()):
    group_of, groups = merge_institutions(entries, aliases)
    return [[groups[g]["label"] for g in gs] for gs in group_of]


def test_same_name_in_the_same_place_is_one_institution():
    got = labels([entry("University of Alabama", "AL", TUSCALOOSA, 60),
                  entry("The University of Alabama", "AL", TUSCALOOSA, 17),
                  entry("University of Alabama", "AL", BIRMINGHAM, 5)])     # 90 km away: not merged
    assert got == [["University of Alabama"], ["University of Alabama"], ["University of Alabama"]]
    group_of, _ = merge_institutions([entry("University of Alabama", "AL", TUSCALOOSA),
                                      entry("University of Alabama", "AL", TUSCALOOSA),
                                      entry("University of Alabama", "AL", BIRMINGHAM)])
    assert group_of[0] == group_of[1] != group_of[2]


def test_a_name_inside_another_nearby_name_is_part_of_it():
    got = labels([entry("Brown University", "RI", (41.82, -71.41), 900),
                  entry("Warren Alpert Medical School of Brown University", "RI", (41.82, -71.41), 170),
                  entry("Rhode Island Hospital", "RI", (41.82, -71.41), 50)])
    assert got == [["Brown University"], ["Brown University"], ["Rhode Island Hospital"]]


def test_the_largest_spelling_names_the_group():
    got = labels([entry("Moffitt Cancer Center", "FL", (27.95, -82.46), 230),
                  entry("H. Lee Moffitt Cancer Center", "FL", (27.95, -82.46), 60)])
    assert got == [["Moffitt Cancer Center"]] * 2


def test_generic_names_are_not_parents():
    got = labels([entry("Cancer Center", "CA", (32.84, -117.27)),
                  entry("Scripps Cancer Center", "CA", (32.84, -117.27))])
    assert got == [["Cancer Center"], ["Scripps Cancer Center"]]


def test_a_system_name_inside_two_campuses_is_left_alone():
    got = labels([entry("University of Texas", "TX", DALLAS, 14),
                  entry("University of Texas at Dallas", "TX", DALLAS, 88),
                  entry("University of Texas at Arlington", "TX", (32.80, -96.80), 53)])
    assert got == [["University of Texas"], ["University of Texas at Dallas"], ["University of Texas at Arlington"]]
    got = labels([entry("University of Texas", "TX", (30.27, -97.74), 66),
                  entry("University of Texas at Austin", "TX", (30.27, -97.74), 333)])
    assert got == [["University of Texas at Austin"]] * 2


def test_curated_names_join_spellings_that_share_no_words():
    aliases = [InstitutionAlias(re.compile(r"\bstroger\b|\bcook county health"), "IL", "Cook County Health")]
    got = labels([entry("John H. Stroger Jr Hospital of Cook County", "IL", CHICAGO, 25),
                  entry("Stroger Hospital", "IL", CHICAGO, 23),
                  entry("Cook County Health and Hospitals System", "IL", CHICAGO, 18),
                  entry("Stroger Hospital", "TX", DALLAS, 3)], aliases)        # another state: not curated
    assert got == [["Cook County Health"]] * 3 + [["Stroger Hospital"]]


def test_a_joint_name_counts_for_each_institution():
    aliases = [InstitutionAlias(re.compile(r"\bstroger\b"), "IL", "Cook County Health")]
    got = labels([entry("Rush University", "IL", CHICAGO, 150),
                  entry("Stroger Hospital of Cook County", "IL", CHICAGO, 51),
                  entry("Stroger Hospital and Rush University", "IL", CHICAGO, 17),
                  entry("Brigham and Women's Hospital", "MA", (42.36, -71.06), 40)], aliases)
    assert got[:2] == [["Rush University"], ["Cook County Health"]]
    assert sorted(got[2]) == ["Cook County Health", "Rush University"]
    assert got[3] == ["Brigham and Women's Hospital"]


def test_far_apart_places_are_not_merged():
    got = labels([entry("Northwestern Medicine", "IL", CHICAGO), entry("Northwestern Medicine", "IL", (41.0, -89.0))])
    group_of, _ = merge_institutions([entry("Northwestern Medicine", "IL", CHICAGO),
                                      entry("Northwestern Medicine", "IL", (41.0, -89.0))])
    assert group_of[0] != group_of[1]
    assert merge_institutions([entry("X Clinic", "IL", CHICAGO), entry("X Clinic", "IL", EVANSTON)])[0][0] == [0]


def test_the_curated_list_loads_and_compiles():
    aliases = load_institution_aliases()
    assert len(aliases) > 20
    names = {a.name for a in aliases}
    assert {"Cook County Health", "Rush University Medical Center", "National Institutes of Health"} <= names


def test_va_saint_and_campus_spellings_compare_equal():
    got = labels([entry("Jesse Brown VA Medical Center", "IL", CHICAGO, 14),
                  entry("Jesse Brown Veterans Affairs Medical Center", "IL", CHICAGO, 6)])
    assert got == [["Jesse Brown VA Medical Center"]] * 2
    berkeley = (37.87, -122.25)
    got = labels([{**entry("University of California", "CA", berkeley, 387), "key": "university of california berkeley"},
                  entry("University of California at Berkeley", "CA", berkeley, 27)])
    assert got == [["University of California"]] * 2


def test_an_uncurated_name_joins_the_curated_institution_containing_it():
    aliases = [InstitutionAlias(re.compile(r"^kaiser permanente southern california"), "CA", "Kaiser Permanente Southern California")]
    pasadena = (34.15, -118.14)
    got = labels([entry("Kaiser Permanente", "CA", pasadena, 39),
                  entry("Kaiser Permanente Southern California", "CA", pasadena, 233)], aliases)
    assert got == [["Kaiser Permanente Southern California"]] * 2


def test_a_mistyped_state_joins_the_institution_it_names():
    got = labels([entry("University of Mississippi Medical Center", "MS", (32.33, -90.18), 522),
                  entry("University of Mississippi Medical Center", "MI", (42.25, -84.40), 8)])
    assert got == [["University of Mississippi Medical Center"]] * 2
    group_of, _ = merge_institutions([entry("University of Mississippi Medical Center", "MS", (32.33, -90.18)),
                                      entry("University of Mississippi Medical Center", "MI", (42.25, -84.40))])
    assert group_of[0] == group_of[1]


def test_two_va_hospitals_in_one_metro_stay_apart():
    got = labels([entry("Jesse Brown VA Medical Center", "IL", CHICAGO, 14),
                  entry("Hines VA Medical Center", "IL", (41.86, -87.84), 40),
                  entry("VA Medical Center", "IL", CHICAGO, 5)])
    assert got == [["Jesse Brown VA Medical Center"], ["Hines VA Medical Center"], ["VA Medical Center"]]


def test_a_name_containing_two_institutions_does_not_merge_them():
    providence = (41.82, -71.41)
    group_of, groups = merge_institutions([
        entry("Brown University", "RI", providence, 900),
        entry("Rhode Island Hospital", "RI", providence, 47),
        entry("Rhode Island Hospital and Alpert Medical School of Brown University", "RI", providence, 5)])
    assert len(groups) == 2 and group_of[0] != group_of[1]
    assert sorted(group_of[2]) == sorted(group_of[0] + group_of[1])


def test_no_chains_across_a_metro_area():
    # Each 25 km from the next: the outer two are 50 km apart and stay apart.
    got = merge_institutions([entry("Acme Clinic", "TX", (32.0, -97.0), 30),
                              entry("Acme Clinic", "TX", (32.0, -96.735), 20),
                              entry("Acme Clinic", "TX", (32.0, -96.47), 10)])[0]
    assert got[0] == got[1] and got[2] != got[0]


def test_a_mixed_member_name_does_not_pull_in_another_institution():
    aliases = [InstitutionAlias(re.compile(r"^henry ford"), "MI", "Henry Ford Health")]
    detroit = (42.33, -83.05)
    got = labels([entry("Henry Ford Health System", "MI", detroit, 167),
                  entry("Henry Ford Hospital Wayne State University", "MI", detroit, 4),
                  entry("Wayne State University", "MI", detroit, 552)], aliases)
    assert got == [["Henry Ford Health"], ["Henry Ford Health"], ["Wayne State University"]]


def test_a_curated_name_with_and_in_it_stays_whole():
    aliases = [InstitutionAlias(re.compile(r"^broad institute"), "MA", "Broad Institute of MIT and Harvard")]
    cambridge = (42.37, -71.11)
    got = labels([entry("Broad Institute of MIT and Harvard", "MA", cambridge, 407),
                  entry("Harvard", "MA", cambridge, 12)], aliases)
    assert got == [["Broad Institute of MIT and Harvard"], ["Harvard"]]

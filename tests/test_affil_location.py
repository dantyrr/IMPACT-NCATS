import pytest
from src.ncats.affil_location import (Location, NOWHERE, parse_location, parse_locations,
                                      parse_part, zip_state, clean)


@pytest.mark.parametrize("text, country, state, zip5", [
    # US: state codes, names, ZIPs, with and without "USA"
    ("Johns Hopkins School of Medicine, Baltimore, MD 21205, USA.", "USA", "MD", "21205"),
    ("Department of Medicine, Baltimore, MD 21205-2196, USA", "USA", "MD", "21205"),
    ("National Cancer Institute, Bethesda, Maryland, USA.", "USA", "MD", None),
    ("Center for Vaccine Development, Baltimore, Maryland 21201, USA.", "USA", "MD", "21201"),
    ("Broad Institute, Cambridge, MA", "USA", "MA", None),
    ("Boston, MA", "USA", "MA", None),
    ("Kaiser Permanente, Pasadena, CA, 91101, USA.", "USA", "CA", "91101"),
    ("Department of Statistics, University of Connecticut, Storrs, CT USA.", "USA", "CT", None),
    ("Institute for Genome Sciences, Baltimore MD 21201 USA.", "USA", "MD", "21201"),
    ("NIH, Bethesda, MD20892", "USA", "MD", "20892"),
    ("Bethesda 20892, USA", "USA", "MD", "20892"),            # state from the ZIP
    ("Wills Eye Hospital, Philadelphia, Pennsylvania, United States.", "USA", "PA", None),
    ("Chao Cancer Center, Orange, California, United States of America.", "USA", "CA", None),
    ("Viterbo University, La Crosse, Wisconsin.", "USA", "WI", None),
    ("Physics Department, Brookhaven National Laboratory, Upton, NY USA.", "USA", "NY", None),
    ("Department of Psychiatry, Baltimore, Md.", "USA", "MD", None),
    ("Stanford University, Stanford, Calif.", "USA", "CA", None),
    ("Columbia University, New York, N.Y.", "USA", "NY", None),
    ("Health Share of Oregon, USA.", "USA", "OR", None),
    ("San Juan, Puerto Rico", "USA", "PR", None),
    # Washington state vs. DC
    ("Howard University, Washington, DC 20059, USA", "USA", "DC", "20059"),
    ("Georgetown University, Washington, D.C.", "USA", "DC", None),
    ("Virginia Mason Medical Center, Seattle, Washington.", "USA", "WA", None),
    # Georgia the state vs. the country; Lebanon NH vs. the country
    ("Centers for Disease Control and Prevention, Atlanta, Georgia.", "USA", "GA", None),
    ("Ivane Javakhishvili Tbilisi State University, Tbilisi, Georgia", "Georgia", None, None),
    ("Dartmouth-Hitchcock Medical Center, Lebanon, NH", "USA", "NH", None),
    ("Geisel School of Medicine at Dartmouth, Lebanon, New Hampshire", "USA", "NH", None),
    ("American University of Beirut, Beirut, Lebanon", "Lebanon", None, None),
    # New Mexico vs. Mexico
    ("University of New Mexico, Albuquerque, New Mexico", "USA", "NM", None),
    ("Instituto Nacional de Salud Publica, Mexico City, Mexico", "Mexico", None, None),
    # other countries and their variants
    ("University of Glasgow, 126 University Place, Glasgow G12 8TA, UK.", "United Kingdom", None, None),
    ("King's College London, London, England.", "United Kingdom", None, None),
    ("Erasmus University Medical Center, Rotterdam, The Netherlands.", "Netherlands", None, None),
    ("Peking University Third Hospital, Beijing 100191, China.", "China", None, None),
    ("Fuwai Hospital, National Center for Cardiovascular Diseases Beijing People's Republic of China.",
     "China", None, None),
    ("West China Hospital, Chengdu, P. R. China", "China", None, None),
    ("Chinese University of Hong Kong, Shatin, Hong Kong SAR, China", "Hong Kong", None, None),
    ("National Taiwan University, Taipei, Taiwan, ROC", "Taiwan", None, None),
    ("Yonsei University, Seoul, Korea (the Republic of)", "South Korea", None, None),
    ("Seoul National University, Seoul, Republic of Korea", "South Korea", None, None),
    ("McGill University, Montreal, QC H3G 0B1, Canada.", "Canada", None, None),
    ("University of Toronto, Toronto, Ontario M5S 1A8", "Canada", None, None),   # province, no country
    ("Royal Perth Hospital, Perth, WA, Australia", "Australia", None, None),
    ("Paris 75012, France", "France", None, None),                            # no ZIP outside the US
    ("Yeditepe University Hospital, Istanbul, Türkiye", "Turkey", None, None),
    ("Universidad Peruana Cayetano Heredia, Lima, Perú", "Peru", None, None),
    # trailing email and "Electronic address", phone numbers
    ("Kaiser Permanente, Pasadena, CA, USA. huong.q2.nguyen@kp.org.", "USA", "CA", None),
    ("Mayo Clinic, Rochester, MN, USA. Electronic address: smith.john@mayo.edu.", "USA", "MN", None),
    ("Dept of X, Baltimore, MD 21201, USA. Tel: +1 410 555 1212", "USA", "MD", "21201"),
    # nothing to go on
    ("Department of Medicine.", None, None, None),
    ("Department of Medicine and.", None, None, None),
    ("Boston University, Boston", None, None, None),           # a city alone is ambiguous
    ("", None, None, None),
])
def test_parse_location(text, country, state, zip5):
    loc = parse_location(text)
    assert (loc.country, loc.state, loc.zip) == (country, state, zip5)


def test_zip_must_fit_the_state():
    # 90210 is California; written next to MD it is dropped rather than trusted.
    assert parse_location("Somewhere, MD 90210, USA") == Location("USA", "MD", None, "named", "Somewhere")


def test_basis_says_whether_the_country_was_written():
    assert parse_location("Boston, MA, USA").basis == "named"
    assert parse_location("Boston, MA").basis == "inferred"
    assert parse_location("Toronto, Ontario").basis == "inferred"
    assert parse_location("Lyon, France").basis == "named"


def test_state_name_inside_an_institution_name_is_not_read_early():
    # Reading stops at the first segment that is not a place, so "Washington"
    # in the university's name never competes with the real state.
    assert parse_location("University of Washington, Seattle, WA 98195, USA").state == "WA"
    assert parse_location("Washington University, St. Louis, MO, USA").state == "MO"
    assert parse_location("George Washington University, Washington, DC, USA").state == "DC"


def test_several_affiliations_in_one_string():
    locs = parse_locations("Univ A, Boston, MA, USA; Univ B, London, UK")
    assert [(l.country, l.state) for l in locs] == [("USA", "MA"), ("United Kingdom", None)]
    assert parse_location("Univ A, Boston, MA, USA; Univ B, London, UK").country == "United Kingdom"
    assert parse_locations("Department of Medicine.") == []


def test_head_keeps_the_segments_before_the_place():
    loc, head = parse_part("Real World Solutions, IQVIA, Durham, NC, USA")
    assert loc == Location("USA", "NC", None, "named", "Durham")
    assert head == ["Real World Solutions", "IQVIA", "Durham"]
    _, head = parse_part("Dept, Acme, Durham NC")
    assert head == ["Dept", "Acme", "Durham"]           # the city shares a segment with the code
    _, head = parse_part("Psychology, University of Oregon, USA")
    assert head == ["Psychology", "University of Oregon"]
    _, head = parse_part("ICES, Toronto, Ontario, Canada")
    assert head == ["ICES", "Toronto"]


def test_zip_state():
    assert zip_state("21205") == "MD"
    assert zip_state("20892") == "MD"
    assert zip_state("20001") == "DC"
    assert zip_state("02115") == "MA"
    assert zip_state("00936") == "PR"
    assert zip_state("99501") == "AK"
    assert zip_state("09001") is None      # military mail


def test_clean_drops_emails_and_asides():
    assert "@" not in clean("Dept, Univ, City, USA. a.b@c.edu")
    assert "CDC" not in clean("Centers for Disease Control and Prevention (CDC), Atlanta, GA")
    assert NOWHERE.country is None


@pytest.mark.parametrize("text, city", [
    ("Johns Hopkins School of Medicine, Baltimore, MD 21205, USA.", "Baltimore"),
    ("Physics Department, Brookhaven National Laboratory, Upton, NY USA.", "Upton"),
    ("Washington University, St. Louis, MO, USA", "St. Louis"),
    ("Bethesda 20892, USA", "Bethesda"),
    ("NIH, Bethesda, MD20892", "Bethesda"),
    ("Center for Genome Sciences, Fort Detrick, Frederick, Maryland 21702, USA.", "Frederick"),
    ("Department of Psychology, University of Oregon, United States.", None),   # state in a name
    ("Carnegie Mellon University, USA.", None),                                 # no state
    ("University of Toronto, Toronto, ON, Canada", None),                       # US only
])
def test_city_is_the_segment_before_the_state(text, city):
    assert parse_location(text).city == city

"""Country, US state and ZIP code from a PubMed affiliation string.

PubMed affiliations end with the place: "..., Baltimore, MD 21205, USA",
"..., Boston, MA", "..., Seattle, Washington", "..., Lyon, France". The parser
reads comma-separated segments from the end of the string and stops at the
first one that names no place, so a state name inside an institution name
earlier in the string ("University of Washington, Seattle, WA") is not read.

Everything is matched against lists kept in this file: country names and
common variants, US state and territory names, USPS codes and the older AP
abbreviations ("Calif", "Md"), and the USPS 3-digit ZIP prefix ranges, which
check a ZIP against its state.

The city is taken to be the segment before the state, unverified: a
string that names a city without a state gets no location at all, since a
city name alone is ambiguous (Burlington, Jackson, Columbia).

A US state or ZIP code without "USA" counts as US. Puerto Rico, Guam and the
US Virgin Islands are US with their USPS code as the state, as in NIH
RePORTER. Hong Kong, Macau and Taiwan are kept as written.
"""

import re
import unicodedata
from dataclasses import dataclass

USA = "USA"

# Canonical name -> other ways PubMed affiliations write it.
_COUNTRIES = {
    USA: ["United States", "United States of America", "U.S.A.", "U.S.", "US", "U S A"],
    "Afghanistan": [], "Albania": [], "Algeria": [], "Andorra": [], "Angola": [],
    "Antigua and Barbuda": [], "Argentina": [], "Armenia": [], "Australia": [], "Austria": [],
    "Azerbaijan": [], "Bahamas": ["The Bahamas"], "Bahrain": [], "Bangladesh": [], "Barbados": [],
    "Belarus": ["Republic of Belarus"], "Belgium": [], "Belize": [], "Benin": [], "Bermuda": [],
    "Bhutan": [], "Bolivia": [], "Bosnia and Herzegovina": ["Bosnia-Herzegovina", "Bosnia"],
    "Botswana": [], "Brazil": ["Brasil"], "Brunei": ["Brunei Darussalam"], "Bulgaria": [],
    "Burkina Faso": [], "Burundi": [], "Cabo Verde": ["Cape Verde"], "Cambodia": [],
    "Cameroon": [], "Canada": [], "Cayman Islands": [], "Central African Republic": [],
    "Chad": [], "Chile": [],
    "China": ["People's Republic of China", "PR China", "P.R. China", "PRC",
              "China (mainland)", "Mainland China"],
    "Colombia": [], "Comoros": [], "Congo": ["Republic of the Congo", "Republic of Congo"],
    "Democratic Republic of the Congo": ["Democratic Republic of Congo", "DR Congo", "DRC",
                                         "Congo DR", "D.R. Congo"],
    "Costa Rica": [], "Cote d'Ivoire": ["Côte d'Ivoire", "Ivory Coast"], "Croatia": [],
    "Cuba": [], "Curacao": ["Curaçao"], "Cyprus": [], "Czech Republic": ["Czechia"],
    "Denmark": [], "Djibouti": [], "Dominica": [], "Dominican Republic": [], "Ecuador": [],
    "Egypt": [], "El Salvador": [], "Equatorial Guinea": [], "Eritrea": [], "Estonia": [],
    "Eswatini": ["Swaziland"], "Ethiopia": [], "Faroe Islands": [], "Fiji": [], "Finland": [],
    "France": [], "French Guiana": [], "French Polynesia": [], "Gabon": [],
    "Gambia": ["The Gambia"], "Georgia": [], "Germany": [], "Ghana": [], "Greece": [],
    "Greenland": [], "Grenada": [], "Guadeloupe": [], "Guatemala": [], "Guinea": [],
    "Guinea-Bissau": [], "Guyana": [], "Haiti": [], "Honduras": [],
    "Hong Kong": ["Hong Kong SAR", "Hong Kong S.A.R."], "Hungary": [], "Iceland": [],
    "India": [], "Indonesia": [], "Iran": ["Islamic Republic of Iran", "I.R. Iran", "IR Iran"],
    "Iraq": [], "Ireland": ["Republic of Ireland", "Eire"], "Israel": [], "Italy": [],
    "Jamaica": [], "Japan": [], "Jordan": [], "Kazakhstan": [], "Kenya": [], "Kiribati": [],
    "Kosovo": [], "Kuwait": [], "Kyrgyzstan": ["Kyrgyz Republic"],
    "Laos": ["Lao PDR", "Lao People's Democratic Republic"], "Latvia": [], "Lebanon": [],
    "Lesotho": [], "Liberia": [], "Libya": [], "Liechtenstein": [], "Lithuania": [],
    "Luxembourg": [], "Macau": ["Macao", "Macau SAR", "Macao SAR"], "Madagascar": [],
    "Malawi": [], "Malaysia": [], "Maldives": [], "Mali": [], "Malta": [],
    "Marshall Islands": [], "Martinique": [], "Mauritania": [], "Mauritius": [],
    "Mexico": ["México"], "Micronesia": [], "Moldova": ["Republic of Moldova"], "Monaco": [],
    "Mongolia": [], "Montenegro": [], "Morocco": [], "Mozambique": [], "Myanmar": ["Burma"],
    "Namibia": [], "Nepal": [], "Netherlands": ["The Netherlands", "Holland"],
    "New Caledonia": [], "New Zealand": [], "Nicaragua": [], "Niger": [], "Nigeria": [],
    "North Korea": ["Democratic People's Republic of Korea", "DPR Korea"],
    "North Macedonia": ["Macedonia", "Republic of North Macedonia", "Republic of Macedonia"],
    "Norway": [], "Oman": [], "Pakistan": [], "Palau": [],
    "Palestine": ["State of Palestine", "Palestinian Territories", "West Bank", "Gaza"],
    "Panama": [], "Papua New Guinea": [], "Paraguay": [], "Peru": ["Perú"],
    "Philippines": ["The Philippines"], "Poland": [], "Portugal": [], "Qatar": [],
    "Reunion": ["Réunion"], "Romania": [], "Russia": ["Russian Federation"], "Rwanda": [],
    "Saint Kitts and Nevis": [], "Saint Lucia": [], "Samoa": [], "San Marino": [],
    "Saudi Arabia": ["Kingdom of Saudi Arabia", "KSA"], "Senegal": [], "Serbia": [],
    "Seychelles": [], "Sierra Leone": [], "Singapore": [], "Slovakia": ["Slovak Republic"],
    "Slovenia": [], "Solomon Islands": [], "Somalia": [], "South Africa": [],
    "South Korea": ["Korea", "Republic of Korea", "Korea (South)", "Korea South", "Rep. of Korea",
                    "Korea, Republic of"],
    "South Sudan": [], "Spain": [], "Sri Lanka": [], "Sudan": [], "Suriname": [],
    "Sweden": [], "Switzerland": [], "Syria": ["Syrian Arab Republic"],
    "Taiwan": ["Republic of China", "ROC", "R.O.C.", "Taiwan ROC"], "Tajikistan": [],
    "Tanzania": ["United Republic of Tanzania"], "Thailand": [], "Timor-Leste": ["East Timor"],
    "Togo": [], "Tonga": [], "Trinidad and Tobago": ["Trinidad"], "Tunisia": [],
    "Turkey": ["Türkiye", "Turkiye"], "Turkmenistan": [], "Uganda": [], "Ukraine": [],
    "United Arab Emirates": ["UAE", "U.A.E."],
    "United Kingdom": ["UK", "U.K.", "England", "Scotland", "Wales", "Northern Ireland",
                       "Great Britain", "GB"],
    "Uruguay": [], "Uzbekistan": [], "Vanuatu": [], "Venezuela": [],
    "Vietnam": ["Viet Nam"], "Yemen": [], "Zambia": [], "Zimbabwe": [],
}

# Sub-national names that settle the country when it is left off.
_REGIONS = {
    "Canada": ["Ontario", "Quebec", "Québec", "British Columbia", "Alberta", "Manitoba",
               "Saskatchewan", "Nova Scotia", "New Brunswick", "Newfoundland",
               "Newfoundland and Labrador", "Prince Edward Island"],
    "Australia": ["New South Wales", "Queensland", "Tasmania", "Western Australia",
                  "South Australia", "Australian Capital Territory", "Northern Territory"],
}
_REGION_CODES = {
    "Canada": ["ON", "QC", "BC", "AB", "MB", "SK", "NS", "NB", "NL", "PE"],
    "Australia": ["NSW", "VIC", "QLD", "TAS"],   # not WA or SA, which are also US codes
}

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "PR": "Puerto Rico", "GU": "Guam", "VI": "US Virgin Islands",
}
_STATE_VARIANTS = {
    "DC": ["Washington DC", "Washington D.C.", "Washington D C"],
    "NY": ["New York City", "NYC"],
    "VI": ["Virgin Islands", "U.S. Virgin Islands"],
}
# AP-style abbreviations. Only read when they are the whole segment, since
# several are ordinary words ("Del", "Miss", "La").
_AP = {
    "Ala": "AL", "Ariz": "AZ", "Ark": "AR", "Calif": "CA", "Cal": "CA", "Colo": "CO",
    "Conn": "CT", "Del": "DE", "Fla": "FL", "Ga": "GA", "Ill": "IL", "Ind": "IN", "Kan": "KS",
    "Kans": "KS", "Ky": "KY", "La": "LA", "Md": "MD", "Mass": "MA", "Mich": "MI", "Minn": "MN",
    "Miss": "MS", "Mo": "MO", "Mont": "MT", "Neb": "NE", "Nebr": "NE", "Nev": "NV",
    "Okla": "OK", "Ore": "OR", "Oreg": "OR", "Pa": "PA", "Penn": "PA", "Tenn": "TN",
    "Tex": "TX", "Vt": "VT", "Va": "VA", "Wash": "WA", "Wis": "WI", "Wisc": "WI", "Wyo": "WY",
    "W Va": "WV", "N Mex": "NM",
}

# USPS 3-digit ZIP prefix ranges. Military (APO/FPO) prefixes are left out.
_ZIP_RANGES = [
    (5, 5, "NY"), (6, 7, "PR"), (8, 8, "VI"), (9, 9, "PR"), (10, 27, "MA"), (28, 29, "RI"),
    (30, 38, "NH"), (39, 49, "ME"), (50, 54, "VT"), (55, 55, "MA"), (56, 59, "VT"),
    (60, 69, "CT"), (70, 89, "NJ"), (100, 149, "NY"), (150, 196, "PA"), (197, 199, "DE"),
    (200, 200, "DC"), (201, 201, "VA"), (202, 205, "DC"), (206, 219, "MD"), (220, 246, "VA"),
    (247, 268, "WV"), (270, 289, "NC"), (290, 299, "SC"), (300, 319, "GA"), (320, 339, "FL"),
    (341, 349, "FL"), (350, 369, "AL"), (370, 385, "TN"), (386, 397, "MS"), (398, 399, "GA"),
    (400, 427, "KY"), (430, 459, "OH"), (460, 479, "IN"), (480, 499, "MI"), (500, 528, "IA"),
    (530, 549, "WI"), (550, 567, "MN"), (569, 569, "DC"), (570, 577, "SD"), (580, 588, "ND"),
    (590, 599, "MT"), (600, 629, "IL"), (630, 658, "MO"), (660, 679, "KS"), (680, 693, "NE"),
    (700, 714, "LA"), (716, 729, "AR"), (730, 732, "OK"), (733, 733, "TX"), (734, 749, "OK"),
    (750, 799, "TX"), (800, 816, "CO"), (820, 831, "WY"), (832, 838, "ID"), (840, 847, "UT"),
    (850, 865, "AZ"), (870, 884, "NM"), (885, 885, "TX"), (889, 898, "NV"), (900, 961, "CA"),
    (967, 968, "HI"), (969, 969, "GU"), (970, 979, "OR"), (980, 994, "WA"), (995, 999, "AK"),
]

_GEORGIA_COUNTRY = {"tbilisi", "batumi", "kutaisi"}
_LEBANON_NH = {"hanover", "dartmouth", "hampshire"}


def _ascii(text):
    if text.isascii():
        return text
    return "".join(ch for ch in unicodedata.normalize("NFKD", text)
                   if unicodedata.category(ch) != "Mn").encode("ascii", "ignore").decode()


def _tokens(text):
    """Words as written (case kept), on ASCII letters and digits."""
    return re.findall(r"[A-Za-z0-9]+", _ascii(text))


def _key(text):
    return tuple(t.lower() for t in _tokens(text))


_PLACES = {}   # lowercase token tuple -> (country, state or None)
for _c, _vs in _COUNTRIES.items():
    for _v in [_c, *_vs]:
        _PLACES[_key(_v)] = (_c, None)
_COUNTRY_KEYS = set(_PLACES)
for _c, _vs in _REGIONS.items():
    for _v in _vs:
        _PLACES[_key(_v)] = (_c, None)
for _code, _name in STATES.items():
    for _v in [_name, *_STATE_VARIANTS.get(_code, [])]:
        _PLACES[_key(_v)] = (USA, _code)
_PLACES[_key("Georgia")] = (USA, "GA")   # the country only beside Tbilisi etc.; see _disambiguate
_MAX_PLACE = max(map(len, _PLACES))

_CODES = {c: (USA, c) for c in STATES}
for _c, _vs in _REGION_CODES.items():
    _CODES.update({v: (_c, None) for v in _vs})
_AP_KEYS = {tuple(k.split()): v for k, v in _AP.items()}


@dataclass(frozen=True)
class Location:
    country: str | None = None   # "USA", or the country's English short name
    state: str | None = None     # USPS code; US only
    zip: str | None = None       # 5-digit ZIP; US only, and only if it fits the state
    basis: str | None = None     # "named": the country is written; "inferred": from a
                                 # state, province or ZIP only
    city: str | None = None      # US only: the text before the state, unverified
                                 # (gazetteer.py checks it against Census places)

    @property
    def is_us(self):
        return self.country == USA


NOWHERE = Location()


def zip_state(zip5):
    """USPS state code for a 5-digit ZIP, from its 3-digit prefix."""
    p = int(zip5[:3])
    for lo, hi, st in _ZIP_RANGES:
        if lo <= p <= hi:
            return st
    return None


_EMAIL = re.compile(r"electronic address\s*:?.*$|\S+@\S+", re.IGNORECASE)
_PHONE = re.compile(r"[.,;]?\s*\b(?:tel|telephone|phone|fax|ph)\b\.?\s*:?\s*\+?[\d(].*$", re.IGNORECASE)
_PARENS = re.compile(r"\(([^()]*)\)")
_LEADING_MARK = re.compile(r"^\s*(?:\d+|[a-z])\s+(?=[A-Z])")
_CODE_ZIP = re.compile(r"\b([A-Z]{2})(\d{5})\b")


def _strip_parens(text):
    """Drop parenthetical asides ("(CDC)", author initials), keeping one that
    is itself a place, as in "Korea (the Republic of)"."""
    def repl(m):
        inner = m.group(1)
        return ", " + inner if _key(inner) in _PLACES else " "
    return _PARENS.sub(repl, text)


def clean(text):
    """Affiliation text without email addresses, parenthetical asides or a
    leading footnote mark."""
    t = _EMAIL.sub(" ", text or "")
    t = _PHONE.sub(" ", t)
    t = _strip_parens(t)
    t = _LEADING_MARK.sub("", t)
    return t


def split_parts(text):
    """Separate affiliations run together in one string with semicolons."""
    return [p for p in (s.strip(" .,") for s in clean(text).split(";")) if p]


def _segments(part):
    return [s.strip() for s in _CODE_ZIP.sub(r"\1 \2", part).split(",") if s.strip()]


def _strip_postcode(toks):
    """Drop trailing tokens that contain digits (postcodes); return the rest
    and a US ZIP if the dropped tokens were one (12345 or 12345-6789)."""
    i = len(toks)
    while i and any(ch.isdigit() for ch in toks[i - 1]):
        i -= 1
    tail = toks[i:]
    z = None
    if tail and re.fullmatch(r"\d{5}", tail[0]) and (len(tail) == 1 or re.fullmatch(r"\d{4}", tail[1])):
        z = tail[0]
    return toks[:i], z


def _place(toks):
    """Longest place name the tokens end with: ((country, state), rest)."""
    low = [t.lower() for t in toks]
    for n in range(min(len(low), _MAX_PLACE), 0, -1):
        hit = _PLACES.get(tuple(low[-n:]))
        if hit:
            return hit, toks[:-n]
    return None, toks


def _code(toks):
    """A USPS (or Canadian/Australian) code ending the segment: "MD", "Boston MA",
    "N.Y.", or an AP abbreviation that is the whole segment. ((country, state), rest)."""
    if not toks:
        return None, toks
    if tuple(toks) in _AP_KEYS:
        return (USA, _AP_KEYS[tuple(toks)]), []
    last, n = toks[-1], 1
    if len(toks) >= 2 and len(toks[-2]) == 1 == len(last) and toks[-2].isupper() and last.isupper():
        last, n = toks[-2] + last, 2    # "N.Y." / "D.C." tokenize to single letters
    if last.isupper() and last in _CODES:
        return _CODES[last], toks[:-n]
    return None, toks


def _is_junk(toks):
    return not toks or [t.lower() for t in toks] in (["and"], ["the"])


def _disambiguate(hit, rest, before, context):
    """Settle the few place names that mean two places."""
    if hit == (USA, "GA") and context & _GEORGIA_COUNTRY:
        return "Georgia", None
    if hit[0] == "Lebanon" and context & _LEBANON_NH:
        return USA, "NH"                        # Lebanon, New Hampshire (Dartmouth)
    if hit[0] == "China":                       # "Hong Kong, China" stays Hong Kong
        prev, _ = _place(rest or (_tokens(before[-1]) if before else []))
        if prev and prev[0] in ("Hong Kong", "Macau"):
            return prev
    return hit


def parse_part(part, whole=None):
    """(Location, head) for one affiliation. head is the list of segments
    before the place, where the institution is named, ending with whatever
    shared a segment with the place ("Durham" of "Durham NC")."""
    segs = _segments(part)
    context = {t.lower() for t in _tokens(whole or part)}
    country = state = zip_ = None
    named = False
    tail, left = len(segs), []
    for i in range(len(segs) - 1, -1, -1):
        toks, z = _strip_postcode(_tokens(segs[i]))
        zip_ = zip_ or z
        if _is_junk(toks):
            continue
        found = False
        if country is None:
            hit, rest = _place(toks)
            if hit:
                country, state = _disambiguate(hit, rest, segs[:i], context)
                named = _key(" ".join(toks[len(rest):])) in _COUNTRY_KEYS and state is None
                found = True
                toks, z = _strip_postcode(rest)    # "Baltimore MD 21201 USA"
                zip_ = zip_ or z
        if country in (None, USA) and state is None and toks:
            # A state code ("Boston MA"), or after "USA" a state name.
            hit, rest = _code(toks)
            if hit is None and country == USA:
                hit, rest = _place(toks)
            if hit and (country is None or (hit[0] == USA and hit[1])):
                country, state = hit
                found, toks = True, rest
        if not found:
            break
        tail, left = i, toks
        if country != USA and not left and i:
            # "Toronto, Ontario, Canada": the province is part of the place
            prev, _ = _strip_postcode(_tokens(segs[i - 1]))
            hit, rest = _place(prev)
            if hit is None:
                hit, rest = _code(prev)
            if hit and hit[0] == country and _key(" ".join(prev[len(rest):])) not in _COUNTRY_KEYS:
                tail, left = i - 1, rest
        if state or country != USA:
            break
    if country is None:
        return NOWHERE, segs
    if country == USA and zip_:
        zs = zip_state(zip_)
        if state is None:
            state = zs
        elif zs != state:
            zip_ = None
    else:
        zip_ = None
    in_name = bool(left) and left[-1].lower() in ("of", "at", "for", "and", "de")
    if in_name:
        left = [segs[tail]]             # "University of Oregon": the state is part of the name
    head = segs[:tail] + ([" ".join(left)] if left else [])
    city = None
    if country == USA and state and head and not in_name:
        city = re.sub(r"\s*\b\d{5}(?:-\d{4})?\b", "", head[-1]).strip(" .") or None
    return Location(country, state, zip_, "named" if named else "inferred", city), head


def parse_locations(text):
    """One Location per semicolon-separated affiliation that names a place."""
    return [loc for loc, _ in (parse_part(p, text) for p in split_parts(text)) if loc.country]


def parse_location(text):
    """The place named at the end of an affiliation string, or NOWHERE."""
    locs = parse_locations(text)
    return locs[-1] if locs else NOWHERE

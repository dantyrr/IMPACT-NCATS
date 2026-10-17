"""Rough institution name and type for affiliations that match no CTSA hub.

Hubs are recognized by a curated alias list (hub_matching.py). Everything else
gets a name read from the affiliation itself: of the segments before the
place (see affil_location.py) that name an institution rather than a
department, the most organization-like one, preferring the rightmost, since
PubMed affiliations run from department to institution to city. Spellings of
one institution are grouped by a normalized key, which is rough: "University
of Cambridge" and "Cambridge University" stay separate.

Type comes from keywords in the name, checked in this order:
  government  NIH and its institutes, CDC, FDA, VA, the military, national
              laboratories, ministries and health departments
  hospital    hospitals, medical centers, clinics, health systems
  industry    company suffixes (Inc, Ltd, GmbH) and drug, device and data firms
  university  universities, colleges, medical and graduate schools
  other       research institutes, foundations, societies and the rest
"""

import re
from dataclasses import dataclass

from src.ncats.affil_location import Location, NOWHERE, split_parts, parse_part
from src.ncats.hub_matching import normalize, is_institution_part, is_subunit

TYPES = ("university", "hospital", "government", "industry", "other")


def _rx(*alts):
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(alts) + r")(?![a-z0-9])")


_COMPANY_SUFFIX = (r"inc", r"incorporated", r"llc", r"l l c", r"ltd", r"limited", r"corp",
                   r"corporation", r"company", r"co ltd", r"gmbh", r"ag", r"a s", r"s a",
                   r"s p a", r"spa", r"plc", r"b v", r"n v", r"pty", r"k k", r"s r l", r"srl")
_COMPANY = (r"pharmaceuticals?", r"pharma", r"biopharma\w*", r"therapeutics", r"biotherapeutics",
            r"biosciences", r"biotech\w*", r"diagnostics", r"biologics", r"genomics inc",
            r"pfizer", r"merck", r"novartis", r"roche", r"genentech", r"amgen", r"janssen",
            r"johnson and johnson", r"glaxosmithkline", r"gsk", r"astrazeneca", r"sanofi",
            r"bayer", r"eli lilly", r"lilly research", r"abbvie", r"bristol myers squibb",
            r"gilead", r"regeneron", r"biogen", r"moderna", r"novo nordisk", r"takeda",
            r"boehringer ingelheim", r"illumina", r"iqvia", r"23andme", r"optum", r"ibm",
            r"google", r"microsoft", r"verily", r"flatiron health", r"tempus", r"medtronic",
            r"siemens", r"philips", r"ge healthcare", r"quest diagnostics", r"labcorp",
            r"vertex", r"alnylam", r"biomarin", r"incyte", r"celgene", r"teva", r"astellas",
            r"daiichi sankyo", r"eisai", r"otsuka", r"ucb", r"servier", r"ipsen", r"grail",
            r"insitro", r"invitae", r"natera", r"exact sciences", r"10x genomics", r"evidation",
            r"komodo health", r"aetna", r"humana", r"unitedhealth\w*", r"anthem", r"elevance",
            r"cvs health", r"walgreens", r"cerner", r"epic systems", r"deloitte",
            r"rti health solutions", r"evidera", r"syneos", r"parexel", r"icon plc", r"covance",
            r"medpace", r"westat", r"mathematica policy", r"abt associates")
_GOVERNMENT = (r"national institutes? of health", r"nih", r"national (?:cancer|eye) institute",
               r"national institute (?:of|on|for)", r"national library of medicine",
               r"national human genome", r"national heart lung", r"national center for advancing",
               r"niaid", r"nhlbi", r"nci", r"nimh", r"nida", r"niaaa", r"ninds", r"nichd",
               r"niddk", r"niehs", r"nia", r"ncats", r"nhgri", r"nlm", r"nidcr", r"nibib",
               r"nimhd", r"ninr", r"nccih",
               r"centers? for disease control", r"cdc", r"food and drug administration", r"fda",
               r"centers for medicare", r"agency for healthcare research", r"ahrq",
               r"health resources and services administration", r"hrsa", r"indian health service",
               r"environmental protection agency", r"national science foundation",
               r"department of (?:veterans|defense|energy|health|public health|homeland)",
               r"veterans", r"va", r"vamc", r"walter reed", r"uniformed services",
               r"army", r"navy", r"naval", r"air force", r"military", r"national laborator\w*",
               r"ministry", r"ministerio", r"inserm", r"cnrs", r"medical research council",
               r"indian council of medical research")
# Checked after hospital and university: "Hennepin County Medical Center" is a
# hospital and "Federal University of Juiz de Fora" a university.
_GOVERNMENT_WEAK = (r"public health agency", r"public health england", r"public health ontario",
                    r"health department", r"department of public health", r"county",
                    r"government", r"federal", r"commonwealth of", r"state of", r"city of new york")
_HOSPITAL = (r"hospital\w*", r"hopital\w*", r"ospedale", r"klinikum", r"medical cent(?:er|re)s?",
             r"health ?care system", r"health system", r"health network", r"health services",
             r"clinic", r"clinics", r"infirmary", r"kaiser permanente", r"permanente",
             r"medical group", r"hospices?", r"nursing home",
             r"cancer cent(?:er|re)", r"children s (?:health|mercy|national)", r"u?mc",
             r"city of hope", r"geisinger", r"ochsner", r"intermountain")
_UNIVERSITY = (r"universit\w*", r"universidad\w*", r"universidade", r"college", r"polytechnic\w*",
               r"politecnico", r"institute of technology", r"karolinska institut\w*",
               r"ku leuven", r"eth zurich", r"epfl", r"ucl",
               r"school of medicine", r"medical school", r"school of public health",
               r"health sciences? cent(?:er|re)",
               r"faculty of", r"graduate school", r"ecole", r"hochschule", r"school")
_OTHER_ORG = (r"foundation", r"association", r"society", r"organi[sz]ation", r"agency", r"council",
              r"trust", r"consortium", r"academy", r"alliance", r"cern", r"institut\w*")

_COMPANY_RX = _rx(*_COMPANY_SUFFIX, *_COMPANY)
_GOVERNMENT_RX = _rx(*_GOVERNMENT)
_GOVERNMENT_WEAK_RX = _rx(*_GOVERNMENT_WEAK)
_HOSPITAL_RX = _rx(*_HOSPITAL)
# "Jefferson Health", not "School of Public Health" or "Center for Environmental Health"
_HEALTH_END = re.compile(r"^(?!.* (?:for|of) ).*(?<!public) health(?:care)?$")
_UNIVERSITY_RX = _rx(*_UNIVERSITY)
_OTHER_RX = _rx(*_OTHER_ORG)
# Organization words hub_matching's institution test misses: companies,
# agencies and societies often have no "university" or "hospital".
_EXTRA_RX = _rx(*_COMPANY_SUFFIX, *_COMPANY, *_GOVERNMENT, *_GOVERNMENT_WEAK, *_HOSPITAL,
                *_UNIVERSITY, *_OTHER_ORG)

_PLACEHOLDER = re.compile(
    r"affiliations? (?:are|is) (?:listed|provided|given|available)|list of (?:authors|affiliations)|"
    r"see (?:the )?(?:appendix|notes|supplement)|supplementa\w* (?:material|appendix)|"
    r"listed (?:at the end|in the)|on behalf of", re.IGNORECASE)
_LEAD = re.compile(r"^(?:(?:and|the|from|from the|at|at the|\d+)\s+)+")
_GENERIC = re.compile(r"^(?:school|college|faculty|department|division|institute|center|centre) of "
                      r"(?:medicine|public health|pharmacy|nursing|dentistry|medical sciences|"
                      r"health sciences|engineering|science|sciences|arts and sciences|"
                      r"veterinary medicine|osteopathic medicine)$|^(?:medical|graduate) school$")
_ADDRESS = re.compile(r"^\d+[a-z]? |(?<![a-z0-9])\d{5,}(?![a-z0-9])|(?<![a-z])(?:street|avenue|ave|"
                      r"road|boulevard|blvd|drive|parkway|suite|room|floor|building|bldg|p o box|"
                      r"po box)(?![a-z])")
_SUBUNIT_MORE = re.compile(r"^(?:from (?:the )?)?(?:departments|depts|divisions|sections|programs|"
                           r"units|services|branch|office of|core|laborator(?:y|ies) of|and)\b")
# Names that contain commas, rejoined before splitting into segments.
_COMMA_NAMES = [(re.compile(r"National Heart,\s*Lung,?\s*and Blood Institute", re.I),
                 "National Heart Lung and Blood Institute"),
                (re.compile(r"Agency for Science,\s*Technology and Research", re.I),
                 "Agency for Science Technology and Research")]
_SYNONYMS = {
    "nih": "national institutes of health",
    "national institutes of health nih": "national institutes of health",
    "cdc": "centers for disease control and prevention",
    "centers for disease control": "centers for disease control and prevention",
    "fda": "food and drug administration",
    "broad institute of mit and harvard": "broad institute",
    "broad institute of harvard and mit": "broad institute",
    "karolinska institute": "karolinska institutet",
    "erasmus mc": "erasmus university medical center",
    "erasmus medical center": "erasmus university medical center",
}
_US_PREFIX = re.compile(r"^(?:u s|us|united states) (?=(?:centers|food|department|national)\b)")
_CITY_NAMES = {"college station", "college park", "university park", "university heights",
               "university place", "medical center"}
# Names shared by several campuses; the campus follows after a comma.
_SYSTEMS = {"university of california", "university of texas", "university of maryland",
            "university of massachusetts", "university of wisconsin", "university of illinois",
            "university of colorado", "university of missouri", "university of north carolina",
            "university of nebraska", "university of tennessee", "university of hawaii",
            "university of minnesota", "university of michigan", "university of alabama",
            "university of arkansas", "university of south carolina", "university of louisiana",
            "state university of new york", "city university of new york", "suny", "cuny",
            "indiana university", "purdue university", "pennsylvania state university",
            "penn state", "rutgers university", "university of pittsburgh",
            "university of washington", "university of virginia"}
_UNIV_SUBUNIT = re.compile(r"^(.*?universit\w*\b.*?) (?:(?:school|college|faculty|graduate school) of|"
                           r"medical school|medical college)\b.*$")
_CORP_TAIL = re.compile(r"(?: (?:and|inc|incorporated|llc|ltd|limited|co|corp|corporation|company|"
                        r"plc|gmbh|ag|a s|s a|pty|l l c))+$")


@dataclass(frozen=True)
class Institution:
    key: str     # normalized, to group spellings
    name: str    # the segment as written
    type: str


@dataclass(frozen=True)
class AffiliationPart:
    location: Location
    institution: Institution | None

    @property
    def informative(self):
        return bool(self.location.country or self.institution)


def institution_type(name):
    """One of TYPES, from keywords in an institution name."""
    k = normalize(name)
    if _GOVERNMENT_RX.search(k):
        return "government"
    if _HOSPITAL_RX.search(k):
        return "hospital"
    if _COMPANY_RX.search(k):
        return "industry"
    if _UNIVERSITY_RX.search(k):
        return "university"
    if _HEALTH_END.search(k):
        return "hospital"
    if _GOVERNMENT_WEAK_RX.search(k):
        return "government"
    return "other"


def _rank(norm):
    """Lower is more organization-like."""
    if _GENERIC.match(norm):
        return 3
    if (re.search(r"universit|polytechnic|institute of technology|karolinska institutet", norm)
            or _HOSPITAL_RX.search(norm) or _GOVERNMENT_RX.search(norm) or _COMPANY_RX.search(norm)):
        return 0
    if _OTHER_RX.search(norm) or _UNIVERSITY_RX.search(norm) or _GOVERNMENT_WEAK_RX.search(norm):
        return 1
    return 2


def institution_key(name, next_segment=None):
    """Grouping key: normalized, without a leading "the", a corporate suffix
    or a university's school or college; a multi-campus system keeps the
    campus that follows it ("University of Maryland, Baltimore")."""
    k = _LEAD.sub("", normalize(name))
    m = _UNIV_SUBUNIT.match(k)
    if m:
        k = m.group(1)
    k = _CORP_TAIL.sub("", k) or k
    k = re.sub(r"(?: \S*\d\S*)+$", "", k)          # unit numbers: "inserm u1163"
    k = _US_PREFIX.sub("", k)
    k = _SYNONYMS.get(k, k)
    if k in _SYSTEMS and next_segment:
        nxt = normalize(next_segment)
        if nxt in _CITY_NAMES or (nxt and len(nxt.split()) <= 3 and not _ADDRESS.search(nxt)
                                  and not _EXTRA_RX.search(nxt)):
            k = f"{k} {nxt}"
    return k


def _candidate(seg):
    norm = normalize(seg)
    if (not norm or norm in _CITY_NAMES or _ADDRESS.search(norm) or is_subunit(seg)
            or _SUBUNIT_MORE.match(norm)):
        return False
    return is_institution_part(seg) or bool(_EXTRA_RX.search(norm))


def _merge_suffixes(head):
    """Put a bare "Inc." or "Ltd" segment back onto the name before it."""
    out = []
    for seg in head:
        norm = normalize(seg)
        if out and norm != "and" and not _CORP_TAIL.sub("", " " + norm).strip():
            out[-1] = f"{out[-1]}, {seg.strip()}"
        else:
            out.append(seg)
    return out


def institution(head, located=False):
    """The Institution named in the segments before the place, or None.

    If no segment looks like an institution but a place was found, the
    segment before the city is taken ("Real World Solutions, IQVIA, Durham,
    NC": IQVIA), since that is where PubMed puts the institution."""
    head = _merge_suffixes(head)
    cands = [(i, s) for i, s in enumerate(head) if _candidate(s)]
    for j in range(len(head) - 2, max(len(head) - 4, -1), -1):
        if cands or not located:
            break
        seg, norm = head[j], normalize(head[j])
        if _ADDRESS.search(norm):
            continue                    # skip a street address between institution and city
        if norm and not is_subunit(seg) and not _SUBUNIT_MORE.match(norm) \
                and len(norm.split()) <= 8 and seg.strip()[:1].isupper():
            cands = [(j, seg)]
        break
    if not cands:
        return None
    i, seg = min(cands, key=lambda c: (_rank(normalize(c[1])), -c[0]))
    name = _LEAD.sub("", seg.strip(" .")).strip() or seg.strip()
    nxt = head[i + 1] if i + 1 < len(head) else None
    return Institution(institution_key(name, nxt), name, institution_type(name))


def describe(affiliation):
    """[AffiliationPart] for each semicolon-separated affiliation in the
    string. Placeholders ("affiliations are listed in the appendix") give none."""
    if _PLACEHOLDER.search(affiliation or ""):
        return []
    for rx, joined in _COMMA_NAMES:
        affiliation = rx.sub(joined, affiliation)
    out = []
    for part in split_parts(affiliation):
        loc, head = parse_part(part, affiliation)
        out.append(AffiliationPart(loc, institution(head, located=loc is not NOWHERE)))
    return out

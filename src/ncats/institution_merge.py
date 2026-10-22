"""Group the spellings and sub-units of one non-hub institution into one map node.

The affiliation parser keys an institution by its normalized name, so one
place turns up under several keys: "Rush University" and "Rush University
Medical Center", "University of Alabama" with and without its campus,
"Stroger Hospital" and "Cook County Health". Entries are (name, place) pairs.

Curated names come first (data/institution_aliases.csv): a pattern, optionally
limited to one state, gives the canonical name, for spellings that share no
words ("Stroger Hospital", "Hektoen Institute" -> Cook County Health). Entries
with one canonical name are one institution within a state, or within
CURATED_KM across a state line (NIH listed in Washington, DC).

The rest are taken largest first. Each joins one institution already formed,
when that institution's first (largest) entry lies within MERGE_KM and
  - has the same name ("Jesse Brown VA Medical Center", "Jesse Brown
    Veterans Affairs Medical Center"), or
  - has a name this one contains as whole words ("Warren Alpert Medical
    School of Brown University" -> "Brown University"). The contained name
    needs a distinctive word ("Cancer Center" alone is no parent), or
  - has a name containing this one ("University of Texas" in Austin ->
    "University of Texas at Austin"). A multi-campus system name joins only
    when just one institution nearby contains it.
Otherwise it starts an institution of its own. Comparing against each
institution's first entry, not against any member, keeps chains from forming
(A near B, B near C, so A joins C 60 km away).

A name containing two institutions that are not one another's parts
("Rhode Island Hospital and Alpert Medical School of Brown University",
"Stroger Hospital and Rush University") is not an institution: it counts for
each of them.

An institution takes its curated name, or else the name of its largest entry.
"""

import csv
import math
import re
from collections import defaultdict
from dataclasses import dataclass

from src.ncats.affil_institution import _SYSTEMS
from src.ncats.affil_location import STATES
from src.ncats.config import DATA_DIR
from src.ncats.hub_matching import normalize

ALIASES_CSV = DATA_DIR / "institution_aliases.csv"
MERGE_KM = 30
CURATED_KM = 50
_STATE_NAMES = {normalize(name): code for code, name in STATES.items()}

_GENERIC = set("""a an the of at and for in on de del la le y university universities universitat college
    colleges school schools faculty campus medical medicine center centre centers health healthcare care
    sciences science institute institutes hospital hospitals system systems clinic clinics research
    national graduate general memorial foundation department division services service program
    cancer children s womens women childrens heart public community regional state county city
    jr inc llc ltd corp group network alliance trust partners practice associates va veterans affairs""".split())
# Words that start a sub-unit after a system's name ("University of Maryland
# Medical Center"); anything else is another campus ("... Baltimore County").
_SUBUNIT_WORDS = set("""school college medical medicine health hospital hospitals center cancer department
    faculty institute graduate clinical comprehensive children s""".split())
_JOINER = re.compile(r"\s+(?:and|&)\s+|\s*/\s*|\s*;\s*", re.IGNORECASE)
# Spellings that differ only in these are compared as one.
_SAME = [(re.compile(p), r) for p, r in (
    (r"\b(?:department of )?veterans? (?:affairs|administration)\b", "va"), (r"\bsaint\b", "st"),
    (r"\bmount\b", "mt"), (r"\bcentre\b", "center"), (r"^the ", ""), (r"\b(?:at|in) ", ""))]


@dataclass(frozen=True)
class InstitutionAlias:
    pattern: re.Pattern
    state: str | None
    name: str


def load_institution_aliases(path=ALIASES_CSV):
    with open(path, newline="") as fh:
        return [InstitutionAlias(re.compile(r["pattern"]), (r.get("state") or "").strip() or None,
                                 r["canonical"].strip())
                for r in csv.DictReader(fh)]


def km(a, b):
    """Great-circle distance between (lat, lon) points."""
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(min(1, math.sqrt(h)))


def _canonical(norm, state, aliases):
    for a in aliases:
        if (a.state is None or a.state == state) and a.pattern.search(norm):
            return a.name
    return None


def _form(norm):
    for rx, rep in _SAME:
        norm = rx.sub(rep, norm)
    return " ".join(norm.split())


def _distinctive(phrase):
    return any(w not in _GENERIC and len(w) > 1 for w in phrase.split())


def _system(phrase):
    return any(phrase == s or phrase.startswith(s + " ") for s in _SYSTEMS)


def _ngrams(words):
    """Every contiguous phrase shorter than the whole."""
    for i in range(len(words)):
        for j in range(i + 1, len(words) + 1):
            if j - i < len(words):
                yield " ".join(words[i:j])


def _part_of(phrase, name):
    """Whether `name`, which contains `phrase`, is a part of what `phrase`
    names. After a system name only a sub-unit word may follow."""
    if not (_system(phrase) and name.startswith(phrase + " ")):
        return True
    return name[len(phrase) + 1:].split()[0] in _SUBUNIT_WORDS


def merge_institutions(entries, aliases=(), merge_km=MERGE_KM):
    """entries: [{"label", "state", "lat", "lon", "weight", optional "key"}].

    Returns (group_of, groups): group_of[e] lists the groups entry e counts
    for (two or more for a name joining institutions), and
    groups[g] = {"label", "members"}."""
    n = len(entries)
    norms = [normalize(e["label"]) for e in entries]
    canon = [_canonical(norms[e], entries[e]["state"], aliases)
             or (_canonical(entries[e]["key"], entries[e]["state"], aliases) if entries[e].get("key") else None)
             for e in range(n)]
    pt = [(e["lat"], e["lon"]) for e in entries]
    near = lambda a, b, limit=merge_km: km(pt[a], pt[b]) <= limit
    # Each entry is compared under its label and its parser key (which keeps
    # a system's campus: "university of california berkeley").
    forms = [{_form(norms[e])} | ({_form(entries[e]["key"])} if entries[e].get("key") else set())
             for e in range(n)]
    order = sorted(range(n), key=lambda e: (-entries[e]["weight"], e))

    # Names joining institutions by "and" or "/" ("Stroger Hospital and Rush
    # University") are set aside first, when every part is curated or is
    # another entry's name nearby; they count for each part's institution.
    plain = defaultdict(list)
    for e in range(n):
        if not _JOINER.search(entries[e]["label"]):
            for f in forms[e]:
                plain[f].append(e)
    joint = {}
    for e in range(n):
        pieces = [_form(normalize(p)) for p in _JOINER.split(entries[e]["label"]) if normalize(p)]
        if len(pieces) < 2:
            continue
        parts = []
        for p in pieces:
            c = _canonical(p, entries[e]["state"], aliases)
            hit = [o for o in plain.get(p, ()) if near(e, o)]
            if not c and not hit:
                break
            parts.append(("canon", c) if c else ("entry", max(hit, key=lambda o: entries[o]["weight"])))
        else:
            # A curated institution whose own name has "and" in it ("Broad
            # Institute of MIT and Harvard") is one institution.
            if not (canon[e] and _JOINER.search(canon[e])):
                joint[e] = parts

    groups, group_of = [], [None] * n
    by_form = defaultdict(set)      # a member's name -> groups
    by_gram = defaultdict(set)      # a distinctive phrase inside a group's first name -> groups

    def join(e, g):
        groups[g]["members"].append(e)
        group_of[e] = [g]
        for f in forms[e]:
            by_form[f].add(g)

    def start(e):
        groups.append({"members": [], "first": e, "canon": canon[e]})
        join(e, len(groups) - 1)
        # Only the first name: a member such as "Henry Ford Hospital Wayne
        # State University" must not pull Wayne State into Henry Ford.
        for f in forms[e]:
            for x in _ngrams(f.split()):
                if _distinctive(x):
                    by_gram[x].add(len(groups) - 1)

    # Curated names: one institution per state, and across a state line nearby.
    for e in order:
        if canon[e] and e not in joint:
            g = next((g for g, G in enumerate(groups) if G["canon"] == canon[e] and any(
                entries[m]["state"] == entries[e]["state"] or near(e, m, CURATED_KM) for m in G["members"])), None)
            join(e, g) if g is not None else start(e)

    # A mistyped state ("University of Mississippi Medical Center, Jackson, MI"):
    # a name that names another state joins the same name in that state.
    def named_state_group(e):
        named = {code for name, code in _STATE_NAMES.items()
                 if code != entries[e]["state"] and re.search(rf"\b{name}\b", norms[e])}
        hits = [g for f in forms[e] for g in by_form.get(f, ())
                if entries[groups[g]["first"]]["state"] in named]
        return hits[0] if hits else None

    for e in order:
        if canon[e] or e in joint:
            continue
        close = lambda g: near(e, groups[g]["first"])
        same = sorted({g for f in forms[e] for g in by_form.get(f, ()) if close(g)})
        if same:
            join(e, same[0])          # the earliest is the largest
            continue
        # This name contains institutions' names: its parents.
        parents = defaultdict(set)    # group -> phrases matched
        for f in forms[e]:
            for x in _ngrams(f.split()):
                if _distinctive(x) and _part_of(x, f):
                    for g in by_form.get(x, ()):
                        if close(g):
                            parents[g].add(x)
        if parents:
            # Drop a parent whose matched name sits inside another parent's
            # ("brown university" inside "alpert medical school of brown university").
            longest = {g: max(xs, key=len) for g, xs in parents.items()}
            top = [g for g, x in longest.items()
                   if not any(h != g and x != y and x in y for h, y in longest.items())]
            if len(top) == 1:
                join(e, top[0])
            else:
                group_of[e] = sorted(top)     # names several institutions: counts for each
            continue
        # This name sits inside institutions' names, though not just after
        # "and" ("Harvard" is not part of the Broad Institute of MIT and Harvard).
        after_and = lambda f, g: any(re.search(rf"\band {re.escape(f)}\b", h) for h in forms[groups[g]["first"]])
        inside = sorted({g for f in forms[e] for g in by_gram.get(f, ()) if close(g) and not after_and(f, g)})
        if len(inside) == 1 or (inside and not any(_system(f) for f in forms[e])):
            join(e, inside[0])
            continue
        g = named_state_group(e)
        join(e, g) if g is not None else start(e)

    for e, parts in joint.items():
        gs = set()
        for kind, v in parts:
            if kind == "entry":
                gs.update(group_of[v] or ())
            else:
                gs.update(g for g, G in enumerate(groups) if G["canon"] == v and any(
                    entries[m]["state"] == entries[e]["state"] or near(e, m, CURATED_KM) for m in G["members"]))
        group_of[e] = sorted(gs)
        if not gs:
            start(e)

    keep = [g for g, G in enumerate(groups) if G["members"]]
    renum = {g: i for i, g in enumerate(keep)}
    out = []
    for g in keep:
        G = groups[g]
        label = G["canon"] or entries[min(G["members"], key=lambda e: (-entries[e]["weight"], e))]["label"]
        out.append({"label": label, "members": sorted(G["members"])})
    return [sorted({renum[g] for g in gs if g in renum}) for gs in group_of], out

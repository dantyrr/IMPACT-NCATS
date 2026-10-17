"""Match PubMed affiliation strings to CTSA hubs with a curated alias list.

Only the ~67 CTSA hubs need recognizing, not every institution in the world, so
matching is a list of names kept in data/hub_aliases.csv rather than a
dependency on an external institution registry. Anything that matches no alias
is non-hub.

Each alias has a tier:
  core     the hub's own institution: university, medical school, health system
  partner  an affiliated hospital or institute that is part of the hub
  block    a different institution whose name contains a hub alias
           ("Indiana University of Pennsylvania", "George Washington University").
           Matching it consumes that span of text so the hub alias inside it
           cannot match.

An alias may list context words (`requires`), at least one of which must also
appear in the string. This handles names shared across cities, such as
Mount Sinai in New York and Toronto. The same alias can serve several hubs if
every entry has context words: "University of California" goes to UCSF when
the string mentions San Francisco and to UCLA when it mentions Los Angeles. A
string whose context fits more than one of them is left unmatched.
"""

import csv
import re
import unicodedata
from dataclasses import dataclass

from src.ncats.config import DATA_DIR

ALIASES_CSV = DATA_DIR / "hub_aliases.csv"
TIERS = {"core": 0, "partner": 1, "block": 2}


def normalize(text):
    """Lowercase ASCII words joined by single spaces. Punctuation becomes a
    word break, so "Wisconsin-Madison" and "Wisconsin Madison" are the same."""
    t = (text or "").replace("&", " and ")
    if not t.isascii():
        # Accents drop to the bare letter; non-ASCII dashes and quotes must
        # become breaks first, or "Wisconsin–Madison" fuses into one word.
        t = "".join(" " if unicodedata.category(ch)[0] in "PZS" else ch
                    for ch in unicodedata.normalize("NFKD", t)
                    if unicodedata.category(ch) != "Mn")
        t = t.encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


@dataclass(frozen=True)
class Alias:
    hub_id: int | None
    alias: str
    tier: str
    requires: tuple = ()


def load_aliases(path=ALIASES_CSV):
    out = []
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            req = tuple(w.strip() for w in (row.get("requires") or "").split(";") if w.strip())
            out.append(Alias(int(row["hub_id"]) if row["hub_id"].strip() else None,
                             row["alias"].strip(), row["tier"].strip(), req))
    return out


_EMAIL = re.compile(r"\S+@\S+|electronic address:?", re.IGNORECASE)


def _clean(affiliation):
    """Normalize, dropping email addresses: a domain such as ucla.edu says where
    the author's mailbox is, not the affiliation they listed."""
    return normalize(_EMAIL.sub(" ", affiliation or ""))


def _word(w):
    return re.compile(r"(?<![a-z0-9])" + re.escape(normalize(w)) + r"(?![a-z0-9])")


class HubMatcher:
    def __init__(self, aliases):
        self._by_norm = {}   # normalized alias -> [(Alias, [context regexes])]
        for a in aliases:
            if a.tier not in TIERS:
                raise ValueError(f"unknown tier {a.tier!r} for alias {a.alias!r}")
            key = normalize(a.alias)
            entries = self._by_norm.setdefault(key, [])
            if any(prev.hub_id == a.hub_id for prev, _ in entries):
                continue   # same name listed twice for one hub
            entries.append((a, [_word(w) for w in a.requires]))
            if len(entries) > 1 and not all(prev.requires for prev, _ in entries):
                names = " / ".join(repr(prev.alias) for prev, _ in entries)
                raise ValueError(f"alias {names} maps to several hubs without context words "
                                 f"to tell them apart; add `requires` or block it")
        # Longest alias first, so at any position the most specific name wins
        # and a block alias swallows the shorter hub name inside it.
        alts = sorted(self._by_norm, key=len, reverse=True)
        self._rx = re.compile(r"(?<![a-z0-9])(?:" + "|".join(map(re.escape, alts)) + r")(?![a-z0-9])")

    def _resolve(self, key, norm):
        """The one alias entry this occurrence stands for, or None."""
        fits = [a for a, req in self._by_norm[key]
                if not req or any(rx.search(norm) for rx in req)]
        return fits[0] if len(fits) == 1 else None

    def match(self, affiliation):
        """{hub_id: strongest tier} for every hub the string names."""
        norm = _clean(affiliation)
        hits = {}
        for m in self._rx.finditer(norm):
            a = self._resolve(m.group(0), norm)
            if a is None or a.tier == "block":
                continue
            prev = hits.get(a.hub_id)
            if prev is None or TIERS[a.tier] < TIERS[prev]:
                hits[a.hub_id] = a.tier
        return hits

    def aliases_found(self, affiliation):
        """(alias, hub_id, tier) for each name matched, for auditing a match."""
        norm = _clean(affiliation)
        out = []
        for m in self._rx.finditer(norm):
            a = self._resolve(m.group(0), norm)
            if a is not None and a.tier != "block":
                out.append((a.alias, a.hub_id, a.tier))
        return out


_INSTITUTION_WORD = re.compile(
    r"universit|college|hospital|institut|school|center|centre|clinic|health|"
    r"medicine|foundation|cancer|laborator", re.IGNORECASE)
_SUBUNIT = re.compile(r"^(department|dept|division|section|program|unit|service|laboratory of|lab of)\b",
                      re.IGNORECASE)


def is_subunit(part):
    """Whether a segment names a department, division or similar unit."""
    return bool(_SUBUNIT.match(part.strip()))


def is_institution_part(part):
    """Whether one comma-separated segment names an institution rather than
    a department or an address."""
    part = part.strip()
    return bool(part) and bool(_INSTITUTION_WORD.search(part)) and not is_subunit(part)


def institution_segments(affiliation):
    """Comma- or semicolon-separated parts of a string that name an
    institution rather than a department or an address. Used to discover
    aliases, not to match."""
    return [normalize(p) for p in re.split(r"[;,]", affiliation or "") if is_institution_part(p)]

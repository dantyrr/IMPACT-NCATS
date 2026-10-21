"""Map points for US cities and ZIP codes, from the Census Bureau Gazetteer.

The Gazetteer files give each ZIP Code Tabulation Area, place (city, town,
CDP) and county subdivision an internal point (latitude, longitude). They
are federal, free and used here only to put a US affiliation on a map; its
state and country still come from the affiliation text (affil_location.py).
Approved for this use on 17 Oct 2026.

Files, from https://www2.census.gov/geo/docs/maps-data/data/gazetteer/<vintage>_Gazetteer/,
unzipped into data/gazetteer/<vintage>/{zcta,place,cousubs}/ (gitignored):
  <vintage>_Gaz_zcta_national.txt     ZIP Code Tabulation Areas
  <vintage>_Gaz_place_national.txt    incorporated places and CDPs
  <vintage>_Gaz_cousubs_national.txt  county subdivisions: New England towns,
                                      New York City boroughs
A city is looked up among places first, then county subdivisions, by name
within its state. A ZIP that is not a ZCTA (PO boxes, single buildings) has
no point.
"""

import csv
import math
import re
from dataclasses import dataclass
from pathlib import Path

from src.ncats.config import DATA_DIR
from src.ncats.hub_matching import normalize

GAZETTEER_DIR = DATA_DIR / "gazetteer"
VINTAGE = 2026
KINDS = ("zcta", "place", "cousubs")

# Neighborhoods, research parks and federal sites written as if they were
# cities, mapped to the place that contains or adjoins them.
CITY_ALIASES = {
    ("la jolla", "CA"): "san diego", ("northridge", "CA"): "los angeles",
    ("moffett field", "CA"): "mountain view",
    ("honolulu", "HI"): "urban honolulu", ("boise", "ID"): "boise city",
    ("argonne", "IL"): "lemont", ("hines", "IL"): "maywood", ("de kalb", "IL"): "dekalb",
    ("abbott park", "IL"): "north chicago", ("urbana champaign", "IL"): "urbana",
    ("jamaica plain", "MA"): "boston", ("charlestown", "MA"): "boston",
    ("roxbury", "MA"): "boston", ("dorchester", "MA"): "boston",
    ("chestnut hill", "MA"): "newton",
    ("fort detrick", "MD"): "frederick",
    ("research triangle park", "NC"): "durham", ("rtp", "NC"): "durham",
    ("manhattan", "NY"): "new york", ("new york city", "NY"): "new york", ("nyc", "NY"): "new york",
    ("flushing", "NY"): "queens", ("long island city", "NY"): "queens",
    ("glen oaks", "NY"): "queens", ("jamaica", "NY"): "queens", ("bronx", "NY"): "bronx",
    ("upton", "NY"): "brookhaven",
    ("pittsburg", "PA"): "pittsburgh",
    ("fort sam houston", "TX"): "san antonio", ("jbsa fort sam houston", "TX"): "san antonio",
    ("kingwood", "TX"): "houston",
    ("fort gordon", "GA"): "augusta",
    ("joint base lewis mcchord", "WA"): "fort lewis",
}
_STATUS_RANK = {"A": 0, "N": 1, "G": 1, "S": 2}   # active government first, statistical last


@dataclass(frozen=True)
class Point:
    lat: float
    lon: float
    geoid: str
    name: str      # as in the Gazetteer: "Baltimore city", "ZCTA 21205"
    kind: str      # "zcta", "place" or "cousubs"


def path(kind, root=GAZETTEER_DIR, vintage=VINTAGE):
    return Path(root) / str(vintage) / kind / f"{vintage}_Gaz_{kind}_national.txt"


def _rows(p):
    with open(p, newline="", encoding="utf-8") as fh:
        first = fh.readline()
        fh.seek(0)
        delim = "|" if "|" in first else "\t"      # 2026 uses "|", earlier vintages tabs
        for row in csv.DictReader(fh, delimiter=delim):
            yield {k.strip(): (v or "").strip() for k, v in row.items() if k}


_DESCRIPTOR = re.compile(r"(?:\s+(?:\(balance\)|[a-z][a-z ]*|CDP))+$")


def city_key(name):
    """Comparable form of a city name: "St. Louis" and "Saint Louis city" are
    both "st louis"; digits (ZIPs) are dropped."""
    k = normalize(re.sub(r"\d+", " ", name or ""))
    k = re.sub(r"^saint ", "st ", k)
    k = re.sub(r" saint ", " st ", k)
    k = re.sub(r"^ft ", "fort ", k)
    k = re.sub(r"^mt ", "mount ", k)
    return k


def place_keys(gaz_name):
    """Every key a Gazetteer name answers to. "Nashville-Davidson metropolitan
    government (balance)" -> nashville davidson, nashville; "San Buenaventura
    (Ventura) city" -> san buenaventura, ventura."""
    base = _DESCRIPTOR.sub("", gaz_name).strip()
    base = re.sub(r" Town$", "", base)          # Massachusetts "Amherst Town city"
    keys = {city_key(re.sub(r"\([^)]*\)", " ", base))}
    keys |= {city_key(x) for x in re.findall(r"\(([^)]*)\)", base)}
    consolidated = base != gaz_name.strip() and re.search(r"government|county|urban", gaz_name)
    if consolidated or " County" in base:
        keys.add(city_key(re.split(r"[-/]", base)[0]))
    return {k for k in keys if k}


class Gazetteer:
    def __init__(self, zctas, places, cousubs):
        self.zctas = zctas          # {zip5: Point}
        self.places = places        # {(key, state): Point}
        self.cousubs = cousubs

    @classmethod
    def load(cls, root=GAZETTEER_DIR, vintage=VINTAGE):
        missing = [str(path(k, root, vintage)) for k in KINDS if not path(k, root, vintage).exists()]
        if missing:
            raise FileNotFoundError("Census Gazetteer files not found: " + ", ".join(missing)
                                    + ". See src/ncats/gazetteer.py for where to get them.")
        zctas = {r["GEOID"]: Point(float(r["INTPTLAT"]), float(r["INTPTLONG"]), r["GEOID"],
                                   f"ZCTA {r['GEOID']}", "zcta")
                 for r in _rows(path("zcta", root, vintage))}
        return cls(zctas, cls._index(path("place", root, vintage), "place"),
                   cls._index(path("cousubs", root, vintage), "cousubs"))

    @staticmethod
    def _index(p, kind):
        best = {}
        for r in _rows(p):
            pt = Point(float(r["INTPTLAT"]), float(r["INTPTLONG"]), r["GEOID"], r["NAME"], kind)
            rank = (_STATUS_RANK.get(r.get("FUNCSTAT"), 3), -float(r.get("ALAND") or 0))
            for k in place_keys(r["NAME"]):
                key = (k, r["USPS"])
                if key not in best or rank < best[key][0]:
                    best[key] = (rank, pt)
        return {k: pt for k, (_, pt) in best.items()}

    def zip_point(self, zip5):
        return self.zctas.get(zip5) if zip5 else None

    def city_point(self, city, state):
        if not city or not state:
            return None
        k = city_key(city)
        k = CITY_ALIASES.get((k, state), k)
        return self.places.get((k, state)) or self.cousubs.get((k, state))


def km(a, b):
    """Great-circle distance between two Points, in kilometres."""
    la1, lo1, la2, lo2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))

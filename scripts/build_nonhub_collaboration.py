#!/usr/bin/env python3
"""Measure each CTSA hub's collaboration with institutions that are not hubs.

A non-hub co-author is an author with a PubMed affiliation and no row in
pub_author_hubs. Their place (country, US state, ZIP, city) and a rough
institution name and type come from the affiliation text alone
(affil_location.py, affil_institution.py); no outside institution registry
is used. US cities and ZIPs get a map point from the Census Bureau Gazetteer
(gazetteer.py), which also places each hub at its city's center, giving the
distance from a hub to its non-hub co-authors. A hub's papers are those in
pub_hubs (any tier), from --from-year on: before 2014 PubMed recorded only
the first author's affiliation.

Two kinds of non-hub author are set aside:
  - authors whose affiliations name nothing ("Department of Medicine."):
    counted in papers_with_unmatched_author but not as outreach, since they
    are often at the same hub as the paper's other authors;
  - authors whose affiliation matches a hub once a footnote number or a
    missing space is fixed ("4Massachusetts General Hospital"): hub authors the
    matcher missed, listed in likely_missed_hub_authors.csv.

Papers with 100 or more authors are kept, but every hub x place table also
gives papers_under_100_authors, since one physics or GWAS consortium paper
reaches dozens of countries at once.

Outputs (in --out-dir):
  hub_outreach_summary.csv          one row per hub
  hub_outreach_by_year.csv          hub x year
  hub_nonhub_states.csv             hub x US state (for a map), + _by_year
  hub_nonhub_cities.csv             hub x US city or ZIP point, with distance from the hub
  hub_nonhub_countries.csv          hub x country
  hub_nonhub_institutions.csv       hub x non-hub institution (network edges)
  hub_top_nonhub_institutions.csv   each hub's 25 most frequent non-hub institutions
  hub_coordinates.csv               each hub's city center
  nonhub_institutions.csv           every non-hub institution: type, place, hubs reached
  nonhub_affiliations.csv           one row per non-hub affiliation, parsed; join to
                                    author_affiliations.csv on pmid, position, affil_order
  location_coverage.csv             share of non-hub affiliations with a country, state, point
  location_check_sample.csv         random affiliations with columns for a hand check
  likely_missed_hub_authors.csv     strings that match a hub once repaired
  possible_hub_names.csv            frequent non-hub US names that resemble a hub's

Usage:
    python scripts/build_nonhub_collaboration.py [--out-dir exports/nonhub_collaboration]
"""

import sys, os, csv, re, time, random, sqlite3, argparse, logging, statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ncats.config import PROJECT_ROOT, NCATS_DB_PATH
from src.ncats.hubs import load_hubs
from src.ncats.hub_matching import HubMatcher, load_aliases, normalize
from src.ncats.affil_location import USA, STATES
from src.ncats.affil_institution import describe, TYPES
from src.ncats.gazetteer import Gazetteer, GAZETTEER_DIR, VINTAGE, km

BIG_PAPER = 100      # authors
LOCAL_KM = 100       # "near the hub"
MIN_PAPERS = 5       # a state or country "reached" with at least this many papers
TOP_N = 25
SAMPLE_SEED = 20261017

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def connect_readonly(path=NCATS_DB_PATH):
    """ncats.db opened read-only; another process may be writing to it."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=60)
    conn.execute("PRAGMA busy_timeout = 60000")
    return conn


def _query(conn, sql, params=(), tries=10):
    for attempt in range(tries):
        try:
            return conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError as e:
            if "locked" not in str(e) or attempt == tries - 1:
                raise
            log.warning("database is locked; retrying in %ds", 2 ** min(attempt, 5))
            time.sleep(2 ** min(attempt, 5))


# --- loading ---------------------------------------------------------------

def load_inputs(conn, from_year, core_only=False):
    """years {pmid: year}, n_authors {pmid: n}, hub_papers {pmid: {hub}},
    nonhub_rows [(pmid, position, affil_order, affiliation)]."""
    years, n_authors = {}, {}
    for pmid, year, n in _query(conn, """
            SELECT f.pmid, COALESCE(pm.pub_year, f.pub_year), f.n_authors
            FROM pub_author_fetch f LEFT JOIN pub_metrics pm USING(pmid)"""):
        if year and year >= from_year:
            years[pmid], n_authors[pmid] = year, n
    hub_papers = defaultdict(set)
    for pmid, hub in _query(conn, "SELECT pmid, hub_id FROM pub_hubs"
                                  + (" WHERE n_core > 0" if core_only else "")):
        if pmid in years:
            hub_papers[pmid].add(hub)
    hub_authors = {(p, pos) for p, pos in _query(conn, "SELECT DISTINCT pmid, position FROM pub_author_hubs")}
    rows = [r for r in _query(conn, "SELECT pmid, position, affil_order, affiliation FROM pub_author_affils")
            if r[0] in years and (r[0], r[1]) not in hub_authors]
    return years, n_authors, dict(hub_papers), rows


# --- parsing ---------------------------------------------------------------

_FUSED = re.compile(r"(?<=\d)(?=[A-Za-z])|(?<=[a-z])(?=[A-Z][a-z])")


def likely_hub(affiliation, matcher):
    """A hub the string names once a footnote number fused to a word
    ("4Massachusetts") or a missing space ("MedicineUniversity") is split."""
    fixed = _FUSED.sub(" ", affiliation or "")
    if fixed == affiliation:
        return None
    hits = matcher.match(fixed)
    return min(hits) if hits else None


@dataclass
class Part:
    pmid: int
    position: int
    affil_order: int
    part: int = 0
    country: str | None = None
    state: str | None = None
    zip: str | None = None
    basis: str | None = None
    city: str | None = None
    inst_key: str | None = None
    inst_name: str | None = None
    inst_type: str | None = None
    missed_hub: int | None = None
    point: object = None          # gazetteer.Point: the city's, else the ZIP's

    @property
    def informative(self):
        return bool(self.country or self.inst_key)


def map_point(gaz, loc):
    """The Gazetteer point for a US location: its city if found, else its
    ZIP. The city comes first because authors mistype ZIPs more often than
    cities (where both are found but over 50 km apart, the ZIP is usually wrong)."""
    if gaz is None or loc.country != USA:
        return None
    return gaz.city_point(loc.city, loc.state) or gaz.zip_point(loc.zip)


def parse_rows(rows, matcher, gaz=None):
    """[Part] for each affiliation row (a row naming nothing still gets one
    Part, empty), plus the institution label for each key: its most common
    spelling."""
    cache, points, parts, spellings = {}, {}, [], defaultdict(Counter)
    for pmid, pos, order, aff in rows:
        hit = cache.get(aff)
        if hit is None:
            hit = cache[aff] = (describe(aff), likely_hub(aff, matcher))
        described, missed = hit
        if not described:
            parts.append(Part(pmid, pos, order, missed_hub=missed))
        for i, d in enumerate(described):
            loc, inst = d.location, d.institution
            if loc not in points:
                points[loc] = map_point(gaz, loc)
            parts.append(Part(pmid, pos, order, i, loc.country, loc.state, loc.zip, loc.basis, loc.city,
                              inst and inst.key, inst and inst.name, inst and inst.type, missed,
                              points[loc]))
            if inst:
                spellings[inst.key][inst.name] += 1
    labels = {k: c.most_common(1)[0][0] for k, c in spellings.items()}
    log.info("parsed %d non-hub affiliation rows (%d distinct strings)", len(rows), len(cache))
    return parts, labels


# --- aggregation -----------------------------------------------------------

def outreach_parts(parts):
    """{pmid: [Part]} for informative parts of authors who are not missed hub
    authors; and {pmid: set of authors} with any non-hub affiliation at all."""
    missed = {(p.pmid, p.position) for p in parts if p.missed_hub is not None}
    by_paper, unmatched = defaultdict(list), defaultdict(set)
    for p in parts:
        unmatched[p.pmid].add(p.position)
        if (p.pmid, p.position) not in missed and p.informative:
            by_paper[p.pmid].append(p)
    return by_paper, unmatched


def _pct(a, b):
    return round(100 * a / b, 1) if b else None


_FLAGS = ("papers", "papers_with_unmatched_author", "papers_with_nonhub_coauthor",
          "papers_nonhub_located", "papers_nonhub_us", "papers_nonhub_international",
          "papers_nonhub_in_state", "papers_nonhub_out_of_state", "papers_nonhub_us_mapped",
          f"papers_nonhub_within_{LOCAL_KM}km", *[f"papers_nonhub_{t}" for t in TYPES])


def _paper_flags(pmid, ps, unmatched, home_state, home_point):
    """Flags for one hub on one paper, and each mapped non-hub author's
    distance from the hub (nearest of their affiliations)."""
    located = [p for p in ps if p.country]
    us = [p for p in located if p.country == USA]
    mapped = [p for p in us if p.point]
    dist = {}
    if home_point:
        for p in mapped:
            d = km(home_point, p.point)
            dist[p.position] = min(d, dist.get(p.position, d))
    types = {p.inst_type for p in ps if p.inst_type}
    f = {"papers": 1,
         "papers_with_unmatched_author": bool(unmatched.get(pmid)),
         "papers_with_nonhub_coauthor": bool(ps),
         "papers_nonhub_located": bool(located),
         "papers_nonhub_us": bool(us),
         "papers_nonhub_international": any(p.country != USA for p in located),
         "papers_nonhub_in_state": any(p.state == home_state for p in us),
         "papers_nonhub_out_of_state": any(p.state and p.state != home_state for p in us),
         "papers_nonhub_us_mapped": bool(mapped),
         f"papers_nonhub_within_{LOCAL_KM}km": any(d <= LOCAL_KM for d in dist.values()),
         **{f"papers_nonhub_{t}": t in types for t in TYPES}}
    return {k: int(v) for k, v in f.items()}, dist


def hub_tables(hub_papers, by_paper, unmatched, hubs, years, n_authors, labels, hub_points=None):
    """All hub-level tables as lists of dicts. hub_points {hub_id: Point}
    adds distances; without it the distance columns are empty."""
    hub_points = hub_points or {}
    flags = defaultdict(Counter)                  # hub -> flag -> papers
    by_year = defaultdict(Counter)                # (hub, year) -> flag -> papers
    dists = defaultdict(list)                     # hub -> km per (paper, mapped non-hub author)
    # (hub, key) -> [pmids, (pmid, author)s, pmids of papers under BIG_PAPER authors]
    cells = {k: defaultdict(lambda: [set(), set(), set()])
             for k in ("state", "country", "inst", "point")}
    states_by_year = defaultdict(set)             # (hub, state, year) -> pmids
    inst_years = defaultdict(set)
    point_of, point_state = {}, defaultdict(Counter)

    for pmid, hubs_on in hub_papers.items():
        year, big = years[pmid], n_authors.get(pmid, 0) >= BIG_PAPER
        ps = by_paper.get(pmid, [])
        keyed = {"state": [(p, p.state) for p in ps if p.country == USA],
                 "country": [(p, p.country) for p in ps],
                 "inst": [(p, p.inst_key) for p in ps],
                 "point": [(p, p.point.geoid) for p in ps if p.point]}
        for hub in hubs_on:
            f, dist = _paper_flags(pmid, ps, unmatched, hubs[hub]["state"], hub_points.get(hub))
            flags[hub].update(f)
            by_year[(hub, year)].update(f)
            dists[hub] += dist.values()
            for kind, pairs in keyed.items():
                for p, k in pairs:
                    if k:
                        cell = cells[kind][(hub, k)]
                        cell[0].add(pmid)
                        cell[1].add((pmid, p.position))
                        if not big:
                            cell[2].add(pmid)
            for p, st in keyed["state"]:
                if st:
                    states_by_year[(hub, st, year)].add(pmid)
            for p, k in keyed["inst"]:
                if k:
                    inst_years[(hub, k)].add(year)
            for p, g in keyed["point"]:
                point_of[g] = p.point
                point_state[g][p.state] += 1

    reach = defaultdict(lambda: defaultdict(set))   # hub -> kind -> keys
    for kind in ("state", "country"):
        for (hub, k), (pm, _, small) in cells[kind].items():
            if kind == "country" and k == USA:
                continue
            reach[hub][kind].add(k)
            if small:
                reach[hub][kind + "_small"].add(k)
            if len(pm) >= MIN_PAPERS:
                reach[hub][kind + "_min"].add(k)

    lab = {k: h["label"] for k, h in hubs.items()}
    home = {k: h["state"] for k, h in hubs.items()}
    inst_info = institution_info(cells["inst"], by_paper)
    edges = []
    for (hub, k), (pm, au, small) in cells["inst"].items():
        info, yrs = inst_info[k], inst_years[(hub, k)]
        edges.append({"hub_id": hub, "hub_label": lab[hub], "institution_key": k,
                      "institution": labels.get(k, k), "type": info["type"],
                      "country": info["country"], "state": info["state"],
                      "papers": len(pm), "nonhub_authors": len(au),
                      f"papers_under_{BIG_PAPER}_authors": len(small),
                      "first_year": min(yrs), "last_year": max(yrs)})
    edges.sort(key=lambda e: (lab[e["hub_id"]], -e["papers"], e["institution_key"]))
    by_hub = defaultdict(list)
    for e in edges:
        by_hub[e["hub_id"]].append(e)

    local = f"papers_nonhub_within_{LOCAL_KM}km"
    summary = []
    for hub_id, h in sorted(hubs.items(), key=lambda kv: kv[1]["label"]):
        f, n, best = flags[hub_id], flags[hub_id]["papers"], by_hub[hub_id][:1]
        summary.append({
            "hub_id": hub_id, "label": h["label"], "state": h["state"], "papers": n,
            "papers_with_unmatched_author": f["papers_with_unmatched_author"],
            "papers_with_nonhub_coauthor": f["papers_with_nonhub_coauthor"],
            "pct_with_nonhub_coauthor": _pct(f["papers_with_nonhub_coauthor"], n),
            "papers_nonhub_located": f["papers_nonhub_located"],
            "papers_nonhub_us": f["papers_nonhub_us"],
            "papers_nonhub_international": f["papers_nonhub_international"],
            "pct_us_of_located": _pct(f["papers_nonhub_us"], f["papers_nonhub_located"]),
            "pct_international_of_located": _pct(f["papers_nonhub_international"],
                                                 f["papers_nonhub_located"]),
            "papers_nonhub_in_state": f["papers_nonhub_in_state"],
            "papers_nonhub_out_of_state": f["papers_nonhub_out_of_state"],
            "pct_in_state_of_us": _pct(f["papers_nonhub_in_state"], f["papers_nonhub_us"]),
            "papers_nonhub_us_mapped": f["papers_nonhub_us_mapped"],
            local: f[local],
            f"pct_within_{LOCAL_KM}km_of_mapped": _pct(f[local], f["papers_nonhub_us_mapped"]),
            "median_km_to_nonhub_us": round(statistics.median(dists[hub_id])) if dists[hub_id] else None,
            "nonhub_states": len(reach[hub_id]["state"]),
            f"nonhub_states_{MIN_PAPERS}plus_papers": len(reach[hub_id]["state_min"]),
            "nonhub_states_under_100_authors": len(reach[hub_id]["state_small"]),
            "nonhub_countries": len(reach[hub_id]["country"]),
            f"nonhub_countries_{MIN_PAPERS}plus_papers": len(reach[hub_id]["country_min"]),
            "nonhub_countries_under_100_authors": len(reach[hub_id]["country_small"]),
            **{f"papers_nonhub_{t}": f[f"papers_nonhub_{t}"] for t in TYPES},
            "nonhub_institutions": len(by_hub[hub_id]),
            "top_nonhub_institution": best[0]["institution"] if best else None,
            "top_nonhub_institution_papers": best[0]["papers"] if best else 0,
        })

    yearly = [{"hub_id": hub, "label": lab[hub], "year": year, **{k: c[k] for k in _FLAGS}}
              for (hub, year), c in sorted(by_year.items())]
    states = [{"hub_id": hub, "hub_label": lab[hub], "hub_state": home[hub], "state": st,
               "state_name": STATES.get(st), "in_state": int(st == home[hub]), "papers": len(pm),
               "nonhub_authors": len(au), f"papers_under_{BIG_PAPER}_authors": len(small)}
              for (hub, st), (pm, au, small) in sorted(cells["state"].items())]
    states_year = [{"hub_id": hub, "hub_label": lab[hub], "state": st, "year": y, "papers": len(pm)}
                   for (hub, st, y), pm in sorted(states_by_year.items())]
    countries = [{"hub_id": hub, "hub_label": lab[hub], "country": c, "papers": len(pm),
                  "nonhub_authors": len(au), f"papers_under_{BIG_PAPER}_authors": len(small)}
                 for (hub, c), (pm, au, small) in sorted(cells["country"].items())]
    cities = []
    for (hub, g), (pm, au, small) in cells["point"].items():
        pt, hp = point_of[g], hub_points.get(hub)
        cities.append({"hub_id": hub, "hub_label": lab[hub], "state": point_state[g].most_common(1)[0][0],
                       "place": pt.name, "geoid": g, "precision": "zip" if pt.kind == "zcta" else "city",
                       "lat": pt.lat, "lon": pt.lon,
                       "km_from_hub": round(km(hp, pt), 1) if hp else None,
                       "papers": len(pm), "nonhub_authors": len(au),
                       f"papers_under_{BIG_PAPER}_authors": len(small)})
    cities.sort(key=lambda r: (lab[r["hub_id"]], -r["papers"], r["geoid"]))
    top_rows = [{"rank": i + 1, **e} for hub in sorted(hubs, key=lambda k: lab[k])
                for i, e in enumerate(by_hub[hub][:TOP_N])]
    hubs_of = defaultdict(set)
    for (hub, k) in cells["inst"]:
        hubs_of[k].add(hub)
    institutions = sorted(({"institution_key": k, "institution": labels.get(k, k), **info,
                            "hubs_reached": len(hubs_of[k])} for k, info in inst_info.items()),
                          key=lambda r: (-r["papers"], r["institution_key"]))
    return dict(summary=summary, yearly=yearly, states=states, states_year=states_year,
                cities=cities, countries=countries, edges=edges, top=top_rows,
                institutions=institutions)


def institution_info(inst_cells, by_paper):
    """{key: type, most common country and state, papers, non-hub authors}
    over hub papers."""
    pmids_of = defaultdict(set)
    for (_, k), (pm, _, _) in inst_cells.items():
        pmids_of[k] |= pm
    places, types, authors = defaultdict(Counter), defaultdict(Counter), defaultdict(set)
    for pmid, ps in by_paper.items():
        for p in ps:
            if p.inst_key and pmid in pmids_of.get(p.inst_key, ()):
                places[p.inst_key][(p.country, p.state)] += 1
                types[p.inst_key][p.inst_type] += 1
                authors[p.inst_key].add((pmid, p.position))
    out = {}
    for k, pm in pmids_of.items():
        located = [cs for cs, _ in places[k].most_common() if cs[0]]
        country, state = located[0] if located else (None, None)
        out[k] = {"type": types[k].most_common(1)[0][0], "country": country, "state": state,
                  "papers": len(pm), "nonhub_authors": len(authors[k])}
    return out


def coverage(parts, years):
    """Share of non-hub affiliation rows with a country, US state, ZIP and
    map point, overall and by year. A row counts once, by its last part."""
    last = {}
    for p in parts:
        last[(p.pmid, p.position, p.affil_order)] = p
    tally = defaultdict(Counter)
    for (pmid, _, _), p in last.items():
        us = p.country == USA
        for y in ("all", years[pmid]):
            t = tally[y]
            t["affiliations"] += 1
            t["with_country"] += bool(p.country)
            t["country_named"] += p.basis == "named"
            t["us"] += us
            t["us_with_state"] += us and bool(p.state)
            t["us_with_zip"] += us and bool(p.zip)
            t["us_with_city_point"] += us and bool(p.point) and p.point.kind != "zcta"
            t["us_with_zip_point_only"] += us and bool(p.point) and p.point.kind == "zcta"
            t["with_institution"] += bool(p.inst_key)
            t["informative"] += p.informative
            t["likely_missed_hub"] += p.missed_hub is not None
    rows = []
    for y in ["all", *sorted(k for k in tally if k != "all")]:
        t = tally[y]
        rows.append({"year": y, **t,
                     "pct_with_country": _pct(t["with_country"], t["affiliations"]),
                     "pct_us_with_state": _pct(t["us_with_state"], t["us"]),
                     "pct_us_with_zip": _pct(t["us_with_zip"], t["us"]),
                     "pct_us_with_point": _pct(t["us_with_city_point"] + t["us_with_zip_point_only"], t["us"]),
                     "pct_with_institution": _pct(t["with_institution"], t["affiliations"]),
                     "pct_informative": _pct(t["informative"], t["affiliations"])})
    return rows


def possible_hub_names(institutions, aliases, min_papers=20):
    """Frequent US non-hub institution names sharing a distinctive word with
    a hub's core alias ("John Hopkins University"), for the alias list."""
    generic = set("university universities of the at and for in medical medicine center centre "
                  "school college health sciences science institute hospital hospitals system "
                  "clinic clinics state new saint st research national children s graduate "
                  "faculty campus city general memorial foundation".split())
    generic |= {w for name in STATES.values() for w in normalize(name).split()}
    words = defaultdict(set)
    for a in aliases:
        if a.tier == "core" and a.hub_id is not None:
            for w in normalize(a.alias).split():
                if w not in generic and len(w) > 2:
                    words[w].add(a.hub_id)
    out = []
    for r in institutions:
        if r["country"] != USA or r["papers"] < min_papers:
            continue
        hit = sorted({h for w in r["institution_key"].split() for h in words.get(w, ())})
        if hit:
            out.append({**r, "resembles_hub_ids": ";".join(map(str, hit))})
    return out


# --- output ----------------------------------------------------------------

def _write(path, rows, header=None):
    header = header or (list(rows[0]) if rows else [])
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    log.info("wrote %s (%d rows)", path, len(rows))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=PROJECT_ROOT / "exports" / "nonhub_collaboration")
    ap.add_argument("--from-year", type=int, default=2014)
    ap.add_argument("--core-only", action="store_true",
                    help="count a hub's papers only where it has a core-tier author")
    ap.add_argument("--gazetteer-dir", type=Path, default=GAZETTEER_DIR)
    ap.add_argument("--gazetteer-vintage", type=int, default=VINTAGE)
    ap.add_argument("--sample", type=int, default=50)
    args = ap.parse_args()
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)

    conn = connect_readonly()
    hubs = load_hubs()
    aliases = load_aliases()
    matcher = HubMatcher(aliases)
    years, n_authors, hub_papers, rows = load_inputs(conn, args.from_year, args.core_only)
    conn.close()
    log.info("%d papers from %d, %d with a hub author, %d non-hub affiliation rows",
             len(years), args.from_year, len(hub_papers), len(rows))
    try:
        gaz = Gazetteer.load(args.gazetteer_dir, args.gazetteer_vintage)
    except FileNotFoundError as e:
        log.warning("%s Writing no map points or distances.", e)
        gaz = None

    lab = {k: h["label"] for k, h in hubs.items()}
    hub_points = {}
    if gaz:
        for k, h in hubs.items():
            pt = gaz.city_point(h["city"], h["state"])
            if pt is None:
                log.warning("no Gazetteer point for hub %s (%s, %s)", h["label"], h["city"], h["state"])
            else:
                hub_points[k] = pt
        _write(out / "hub_coordinates.csv",
               [{"hub_id": k, "label": lab[k], "city": hubs[k]["city"], "state": hubs[k]["state"],
                 "lat": pt.lat, "lon": pt.lon, "gazetteer_name": pt.name, "geoid": pt.geoid,
                 "gazetteer_file": pt.kind, "gazetteer_vintage": args.gazetteer_vintage}
                for k, pt in sorted(hub_points.items(), key=lambda kv: lab[kv[0]])])

    parts, labels = parse_rows(rows, matcher, gaz)
    by_paper, unmatched = outreach_parts(parts)
    t = hub_tables(hub_papers, by_paper, unmatched, hubs, years, n_authors, labels, hub_points)

    _write(out / "hub_outreach_summary.csv", t["summary"])
    _write(out / "hub_outreach_by_year.csv", t["yearly"])
    _write(out / "hub_nonhub_states.csv", t["states"])
    _write(out / "hub_nonhub_states_by_year.csv", t["states_year"])
    if gaz:
        _write(out / "hub_nonhub_cities.csv", t["cities"])
    _write(out / "hub_nonhub_countries.csv", t["countries"])
    _write(out / "hub_nonhub_institutions.csv", t["edges"])
    _write(out / "hub_top_nonhub_institutions.csv", t["top"])
    _write(out / "nonhub_institutions.csv", t["institutions"])
    _write(out / "possible_hub_names.csv", possible_hub_names(t["institutions"], aliases))
    _write(out / "location_coverage.csv", coverage(parts, years))

    _write(out / "nonhub_affiliations.csv",
           [{"pmid": p.pmid, "position": p.position, "affil_order": p.affil_order, "part": p.part,
             "pub_year": years[p.pmid], "country": p.country, "state": p.state, "zip": p.zip,
             "city": p.city, "location_basis": p.basis,
             "lat": p.point.lat if p.point else None, "lon": p.point.lon if p.point else None,
             "point": p.point.name if p.point else None,
             "institution_key": p.inst_key,
             "institution": labels.get(p.inst_key) if p.inst_key else None,
             "institution_type": p.inst_type, "likely_missed_hub_id": p.missed_hub}
            for p in parts])

    text = {(p, pos, o): a for p, pos, o, a in rows}
    missed = Counter((text[(p.pmid, p.position, p.affil_order)], p.missed_hub)
                     for p in parts if p.missed_hub is not None and p.part == 0)
    _write(out / "likely_missed_hub_authors.csv",
           [{"affiliation": a, "hub_id": h, "hub_label": lab.get(h), "rows": n}
            for (a, h), n in missed.most_common()])

    # Hand-check sample: affiliation rows of non-hub authors on hub papers.
    last = {}
    for p in parts:
        last[(p.pmid, p.position, p.affil_order)] = p
    pool = sorted(k for k, p in last.items() if k[0] in hub_papers and p.missed_hub is None)
    pick = random.Random(SAMPLE_SEED).sample(pool, min(args.sample, len(pool)))
    _write(out / "location_check_sample.csv",
           [{"pmid": k[0], "position": k[1], "affil_order": k[2], "affiliation": text[k],
             "country": last[k].country, "state": last[k].state, "zip": last[k].zip,
             "city": last[k].city, "point": last[k].point.name if last[k].point else None,
             "institution": labels.get(last[k].inst_key) if last[k].inst_key else None,
             "institution_type": last[k].inst_type,
             "country_ok": "", "state_ok": "", "institution_ok": "", "type_ok": "", "note": ""}
            for k in sorted(pick)])

    s = t["summary"]
    med = lambda col: statistics.median(r[col] for r in s if r[col] is not None)
    log.info("hubs %d | median %% with non-hub co-author %.1f | %% international %.1f | "
             "%% within %d km %.1f", len(s), med("pct_with_nonhub_coauthor"),
             med("pct_international_of_located"), LOCAL_KM, med(f"pct_within_{LOCAL_KM}km_of_mapped"))


if __name__ == "__main__":
    main()

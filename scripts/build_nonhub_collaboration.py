#!/usr/bin/env python3
"""Measure each CTSA hub's collaboration with institutions that are not hubs.

A non-hub co-author is an author with a PubMed affiliation and no row in
pub_author_hubs. Their place (country, US state, ZIP) and a rough institution
name and type come from the affiliation text alone (affil_location.py,
affil_institution.py); no outside registry or gazetteer is used. A hub's
papers are those in pub_hubs (any tier), from --from-year on: before 2014
PubMed recorded only the first author's affiliation.

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
  hub_nonhub_countries.csv          hub x country
  hub_nonhub_institutions.csv       hub x non-hub institution (network edges)
  hub_top_nonhub_institutions.csv   each hub's 25 most frequent non-hub institutions
  nonhub_institutions.csv           every non-hub institution: type, place, hubs reached
  nonhub_affiliations.csv           one row per non-hub affiliation, parsed; join to
                                    author_affiliations.csv on pmid, position, affil_order
  location_coverage.csv             share of non-hub affiliations with a country, state, ZIP
  location_check_sample.csv         random affiliations with blank columns for a hand check
  likely_missed_hub_authors.csv     strings that match a hub once repaired
  possible_hub_names.csv            frequent non-hub US names that resemble a hub's

Usage:
    python scripts/build_nonhub_collaboration.py [--out-dir exports/nonhub_collaboration]
"""

import sys, os, csv, re, time, random, sqlite3, argparse, logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ncats.config import PROJECT_ROOT, NCATS_DB_PATH
from src.ncats.hubs import load_hubs
from src.ncats.hub_matching import HubMatcher, load_aliases, normalize
from src.ncats.affil_location import USA, STATES
from src.ncats.affil_institution import describe, TYPES

BIG_PAPER = 100      # authors
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
    part: int
    country: str | None
    state: str | None
    zip: str | None
    basis: str | None
    inst_key: str | None
    inst_name: str | None
    inst_type: str | None
    missed_hub: int | None

    @property
    def informative(self):
        return bool(self.country or self.inst_key)


def parse_rows(rows, matcher):
    """[Part] for each affiliation row (a row naming nothing still gets one
    Part, empty), plus the institution label for each key: its most common
    spelling."""
    cache, parts, spellings = {}, [], defaultdict(Counter)
    for pmid, pos, order, aff in rows:
        hit = cache.get(aff)
        if hit is None:
            hit = cache[aff] = (describe(aff), likely_hub(aff, matcher))
        described, missed = hit
        if not described:
            parts.append(Part(pmid, pos, order, 0, None, None, None, None, None, None, None, missed))
        for i, d in enumerate(described):
            loc, inst = d.location, d.institution
            parts.append(Part(pmid, pos, order, i, loc.country, loc.state, loc.zip, loc.basis,
                              inst and inst.key, inst and inst.name, inst and inst.type, missed))
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


def hub_tables(hub_papers, by_paper, unmatched, hubs, years, n_authors, labels):
    """All hub-level tables as lists of dicts."""
    paper_count = Counter()
    flags = defaultdict(Counter)                  # hub -> flag -> papers
    by_year = defaultdict(Counter)                # (hub, year) -> flag -> papers
    cells = {k: defaultdict(lambda: [set(), set(), set()]) for k in ("state", "country", "inst")}
    states_by_year = defaultdict(set)             # (hub, state, year) -> pmids
    inst_years = defaultdict(set)

    for pmid, hubs_on in hub_papers.items():
        year, big = years[pmid], n_authors.get(pmid, 0) >= BIG_PAPER
        ps = by_paper.get(pmid, [])
        authors = {p.position for p in ps}
        located = [p for p in ps if p.country]
        us = [p for p in located if p.country == USA]
        intl = [p for p in located if p.country != USA]
        types = {p.inst_type for p in ps if p.inst_type}
        for hub in hubs_on:
            home = hubs[hub]["state"]
            f = {"papers": 1,
                 "papers_with_unmatched_author": bool(unmatched.get(pmid)),
                 "papers_with_nonhub_coauthor": bool(authors),
                 "papers_nonhub_located": bool(located),
                 "papers_nonhub_us": bool(us),
                 "papers_nonhub_international": bool(intl),
                 "papers_nonhub_in_state": any(p.state == home for p in us),
                 "papers_nonhub_out_of_state": any(p.state and p.state != home for p in us),
                 **{f"papers_nonhub_{t}": t in types for t in TYPES}}
            paper_count[hub] += 1
            flags[hub].update({k: int(v) for k, v in f.items()})
            by_year[(hub, year)].update({k: int(v) for k, v in f.items()})
            for kind, key_of, subset in (("state", lambda p: p.state, us),
                                         ("country", lambda p: p.country, located),
                                         ("inst", lambda p: p.inst_key, ps)):
                for p in subset:
                    k = key_of(p)
                    if k:
                        cell = cells[kind][(hub, k)]
                        cell[0].add(pmid)
                        cell[1].add((pmid, p.position))
                        if not big:
                            cell[2].add(pmid)
            for p in us:
                if p.state:
                    states_by_year[(hub, p.state, year)].add(pmid)
            for p in ps:
                if p.inst_key:
                    inst_years[(hub, p.inst_key)].add(year)

    reach = defaultdict(lambda: defaultdict(set))   # hub -> kind -> keys (all / small papers)
    for kind in ("state", "country"):
        for (hub, k), (pm, _, small) in cells[kind].items():
            if kind == "country" and k == USA:
                continue
            reach[hub][kind].add(k)
            if small:
                reach[hub][kind + "_small"].add(k)

    inst_info = institution_info(cells["inst"], by_paper)
    top = {}
    for (hub, k), (pm, _, _) in cells["inst"].items():
        top.setdefault(hub, []).append((len(pm), k))

    summary = []
    for hub_id, h in sorted(hubs.items(), key=lambda kv: kv[1]["label"]):
        f = flags[hub_id]
        n = f["papers"]
        best = sorted(top.get(hub_id, []), key=lambda t: (-t[0], t[1]))[:1]
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
            "nonhub_states": len(reach[hub_id]["state"]),
            "nonhub_states_under_100_authors": len(reach[hub_id]["state_small"]),
            "nonhub_countries": len(reach[hub_id]["country"]),
            "nonhub_countries_under_100_authors": len(reach[hub_id]["country_small"]),
            **{f"papers_nonhub_{t}": f[f"papers_nonhub_{t}"] for t in TYPES},
            "nonhub_institutions": len(top.get(hub_id, [])),
            "top_nonhub_institution": labels.get(best[0][1]) if best else None,
            "top_nonhub_institution_papers": best[0][0] if best else 0,
        })

    yearly = [{"hub_id": hub, "label": hubs[hub]["label"], "year": year, **dict(c)}
              for (hub, year), c in sorted(by_year.items())]
    for row in yearly:
        for t in ("papers_with_unmatched_author", "papers_with_nonhub_coauthor", "papers_nonhub_located",
                  "papers_nonhub_us", "papers_nonhub_international", "papers_nonhub_in_state",
                  "papers_nonhub_out_of_state", *[f"papers_nonhub_{t}" for t in TYPES]):
            row.setdefault(t, 0)

    lab = {k: h["label"] for k, h in hubs.items()}
    home = {k: h["state"] for k, h in hubs.items()}
    states = [{"hub_id": hub, "hub_label": lab[hub], "hub_state": home[hub], "state": st,
               "state_name": STATES.get(st), "in_state": int(st == home[hub]), "papers": len(pm),
               "nonhub_authors": len(au), f"papers_under_{BIG_PAPER}_authors": len(small)}
              for (hub, st), (pm, au, small) in sorted(cells["state"].items())]
    states_year = [{"hub_id": hub, "hub_label": lab[hub], "state": st, "year": y, "papers": len(pm)}
                   for (hub, st, y), pm in sorted(states_by_year.items())]
    countries = [{"hub_id": hub, "hub_label": lab[hub], "country": c, "papers": len(pm),
                  "nonhub_authors": len(au), f"papers_under_{BIG_PAPER}_authors": len(small)}
                 for (hub, c), (pm, au, small) in sorted(cells["country"].items())]
    edges = []
    for (hub, k), (pm, au, small) in cells["inst"].items():
        info = inst_info[k]
        yrs = inst_years[(hub, k)]
        edges.append({"hub_id": hub, "hub_label": lab[hub], "institution_key": k,
                      "institution": labels.get(k, k), "type": info["type"],
                      "country": info["country"], "state": info["state"],
                      "papers": len(pm), "nonhub_authors": len(au),
                      f"papers_under_{BIG_PAPER}_authors": len(small),
                      "first_year": min(yrs), "last_year": max(yrs)})
    edges.sort(key=lambda e: (lab[e["hub_id"]], -e["papers"], e["institution_key"]))
    top_rows = []
    for hub in sorted(hubs, key=lambda k: lab[k]):
        ranked = [e for e in edges if e["hub_id"] == hub][:TOP_N]
        top_rows += [{"rank": i + 1, **e} for i, e in enumerate(ranked)]
    institutions = []
    hubs_of = defaultdict(set)
    for (hub, k) in cells["inst"]:
        hubs_of[k].add(hub)
    for k, info in inst_info.items():
        institutions.append({"institution_key": k, "institution": labels.get(k, k), **info,
                             "hubs_reached": len(hubs_of[k])})
    institutions.sort(key=lambda r: (-r["papers"], r["institution_key"]))
    return dict(summary=summary, yearly=yearly, states=states, states_year=states_year,
                countries=countries, edges=edges, top=top_rows, institutions=institutions)


def institution_info(inst_cells, by_paper):
    """{key: type, most common country and state, papers, non-hub authors}
    over hub papers."""
    places, types = defaultdict(Counter), defaultdict(Counter)
    pmids_of = defaultdict(set)
    for (_, k), (pm, _, _) in inst_cells.items():
        pmids_of[k] |= pm
    authors = defaultdict(set)
    for pmid, ps in by_paper.items():
        for p in ps:
            if p.inst_key and pmid in pmids_of.get(p.inst_key, ()):
                places[p.inst_key][(p.country, p.state)] += 1
                types[p.inst_key][p.inst_type] += 1
                authors[p.inst_key].add((pmid, p.position))
    out = {}
    for k, pm in pmids_of.items():
        located = [(c, s) for (c, s), _ in places[k].most_common() if c]
        country, state = located[0] if located else (None, None)
        out[k] = {"type": types[k].most_common(1)[0][0], "country": country, "state": state,
                  "papers": len(pm), "nonhub_authors": len(authors[k])}
    return out


def coverage(parts, years):
    """Share of non-hub affiliation rows with a country, US state and ZIP,
    overall and by year. A row counts once, by its last semicolon part."""
    last = {}
    for p in parts:
        last[(p.pmid, p.position, p.affil_order)] = p
    tally = defaultdict(Counter)
    for (pmid, _, _), p in last.items():
        for y in ("all", years[pmid]):
            t = tally[y]
            t["affiliations"] += 1
            t["with_country"] += bool(p.country)
            t["country_named"] += p.basis == "named"
            t["us"] += p.country == USA
            t["us_with_state"] += p.country == USA and bool(p.state)
            t["us_with_zip"] += p.country == USA and bool(p.zip)
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

    parts, labels = parse_rows(rows, matcher)
    by_paper, unmatched = outreach_parts(parts)
    t = hub_tables(hub_papers, by_paper, unmatched, hubs, years, n_authors, labels)

    _write(out / "hub_outreach_summary.csv", t["summary"])
    _write(out / "hub_outreach_by_year.csv", t["yearly"])
    _write(out / "hub_nonhub_states.csv", t["states"])
    _write(out / "hub_nonhub_states_by_year.csv", t["states_year"])
    _write(out / "hub_nonhub_countries.csv", t["countries"])
    _write(out / "hub_nonhub_institutions.csv", t["edges"])
    _write(out / "hub_top_nonhub_institutions.csv", t["top"])
    _write(out / "nonhub_institutions.csv", t["institutions"])
    _write(out / "possible_hub_names.csv", possible_hub_names(t["institutions"], aliases))
    _write(out / "location_coverage.csv", coverage(parts, years))

    _write(out / "nonhub_affiliations.csv",
           [{"pmid": p.pmid, "position": p.position, "affil_order": p.affil_order, "part": p.part,
             "pub_year": years[p.pmid], "country": p.country, "state": p.state, "zip": p.zip,
             "location_basis": p.basis, "institution_key": p.inst_key,
             "institution": labels.get(p.inst_key) if p.inst_key else None,
             "institution_type": p.inst_type, "likely_missed_hub_id": p.missed_hub}
            for p in parts])

    text = {(p, pos, o): a for p, pos, o, a in rows}
    missed = Counter((text[(p.pmid, p.position, p.affil_order)], p.missed_hub)
                     for p in parts if p.missed_hub is not None and p.part == 0)
    lab = {k: h["label"] for k, h in hubs.items()}
    _write(out / "likely_missed_hub_authors.csv",
           [{"affiliation": a, "hub_id": h, "hub_label": lab.get(h), "rows": n}
            for (a, h), n in missed.most_common()])

    # Hand-check sample: affiliation rows of non-hub authors on hub papers.
    pool = sorted({(p.pmid, p.position, p.affil_order) for p in parts
                   if p.pmid in hub_papers and p.missed_hub is None})
    pick = random.Random(SAMPLE_SEED).sample(pool, min(args.sample, len(pool)))
    last = {}
    for p in parts:
        last[(p.pmid, p.position, p.affil_order)] = p
    _write(out / "location_check_sample.csv",
           [{"pmid": k[0], "position": k[1], "affil_order": k[2], "affiliation": text[k],
             "country": last[k].country, "state": last[k].state, "zip": last[k].zip,
             "institution": labels.get(last[k].inst_key) if last[k].inst_key else None,
             "institution_type": last[k].inst_type,
             "country_ok": "", "state_ok": "", "institution_ok": "", "type_ok": "", "note": ""}
            for k in sorted(pick)])

    s = t["summary"]
    log.info("hubs %d | median pct with non-hub co-author %.1f | median pct international %.1f",
             len(s), sorted(r["pct_with_nonhub_coauthor"] or 0 for r in s)[len(s) // 2],
             sorted(r["pct_international_of_located"] or 0 for r in s)[len(s) // 2])


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build hub-to-hub collaboration networks from NCATS-linked papers.

Three networks, each a set of hubs per paper:

  coauthor_core   hubs with at least one author at the hub's own institution
                  (core tier in data/hub_aliases.csv). The conservative network.
  coauthor_broad  also counts authors at partner hospitals and institutes.
  cofunding       hubs whose CTSA awards (hub, KL2/TL1, K12/T32) the paper is
                  linked to in RePORTER. Needs no affiliations, so it covers
                  every year.

Co-authorship starts in 2014 by default: before then PubMed recorded only the
first author's affiliation, so most co-author hubs are unknown. Use
--coauthor-from to change it.

Link weights are given three ways. Full counting adds 1 per shared paper.
Fractional counting gives each pair on a paper with k hubs 1/(k-1), so a large
consortium paper contributes as much in total as a two-hub paper
(Perianes-Rodriguez, Waltman & van Eck 2016, J Informetrics 10:1178).
papers_under_<N>_hubs leaves out papers naming N or more hubs: national
consortium papers (N3C and the like) otherwise link nearly every pair and
carry most of the full-count weight.

Outputs (in --out-dir):
  nodes_<net>.csv, edges_<net>.csv, edges_by_year_<net>.csv
  vosviewer_map_<net>.txt, vosviewer_network_<net>.txt (+ _fractional)
  cross_hub_share_by_year.csv

Usage:
    python scripts/build_hub_network.py [--out-dir exports/hub_network]
"""

import sys, os, csv, argparse, logging
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ncats.schema import connect_ncats
from src.ncats.config import PROJECT_ROOT
from src.ncats.hubs import load_hubs, site_to_hub, is_ctsa_hub_award, is_ctsa_program_award

CONSORTIUM_HUBS = 10

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def _years(conn):
    return {pmid: year for pmid, year in conn.execute("""
        SELECT f.pmid, COALESCE(pm.pub_year, f.pub_year)
        FROM pub_author_fetch f LEFT JOIN pub_metrics pm USING(pmid)""") if year}


def _in_range(year, from_year, to_year):
    return year is not None and year >= from_year and (to_year is None or year <= to_year)


def coauthor_hub_sets(conn, broad, from_year, to_year=None):
    """{pmid: (hub set, year)} from author affiliations."""
    years = _years(conn)
    sets = defaultdict(set)
    sql = "SELECT pmid, hub_id FROM pub_hubs" + ("" if broad else " WHERE n_core > 0")
    for pmid, hub in conn.execute(sql):
        if _in_range(years.get(pmid), from_year, to_year):
            sets[pmid].add(hub)
    return {p: (s, years[p]) for p, s in sets.items()}


def cofunding_hub_sets(conn, to_hub, from_year, to_year=None):
    """{pmid: (hub set, year)} from RePORTER links to CTSA program awards."""
    years = _years(conn)
    sets = defaultdict(set)
    for pmid, ipf, code, num in conn.execute(
            "SELECT gp.pmid, g.ipf_code, g.activity_code, g.core_project_num "
            "FROM grant_pubs gp JOIN grants g USING(core_project_num)"):
        if ipf in to_hub and is_ctsa_program_award(code, num) \
                and _in_range(years.get(pmid), from_year, to_year):
            sets[pmid].add(to_hub[ipf])
    return {p: (s, years[p]) for p, s in sets.items()}


def pair_weights(sets):
    """(full, fractional) link weights per (hub_a, hub_b), hub_a < hub_b."""
    full, frac = Counter(), defaultdict(float)
    for hubs, _ in sets.values():
        if len(hubs) < 2:
            continue
        w = 1 / (len(hubs) - 1)
        for pair in combinations(sorted(hubs), 2):
            full[pair] += 1
            frac[pair] += w
    return full, frac


def hub_active_years(conn, hubs):
    """{hub_id: fiscal years in which a member site held a CTSA hub award}."""
    to_hub = site_to_hub(hubs)
    out = defaultdict(set)
    for ipf, code, num, fy in conn.execute(
            "SELECT g.ipf_code, g.activity_code, g.core_project_num, gy.fiscal_year "
            "FROM grants g JOIN grant_years gy USING(core_project_num) "
            "WHERE g.activity_code IN ('UL1','UM1')"):
        if ipf in to_hub and is_ctsa_hub_award(code, num):
            out[to_hub[ipf]].add(fy)
    return out


def write_vosviewer(nodes, edges, map_path, net_path):
    """VOSviewer map (tab-separated, header) and network (id id strength) files."""
    with open(map_path, "w") as fh:
        fh.write("id\tlabel\tweight<Papers>\tweight<Cross-hub papers>\n")
        for n in nodes:
            fh.write(f"{n['hub_id']}\t{n['label']}\t{n['papers']}\t{n['cross_hub_papers']}\n")
    with open(net_path, "w") as fh:
        for (a, b), w in sorted(edges.items()):
            fh.write(f"{a}\t{b}\t{round(w, 4) if isinstance(w, float) else w}\n")


def _write_csv(path, rows):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def build(name, sets, hubs, active, out_dir, nonhub_pmids=None):
    full, frac = pair_weights(sets)
    small, _ = pair_weights({p: v for p, v in sets.items() if len(v[0]) < CONSORTIUM_HUBS})

    by_year = defaultdict(lambda: [0, 0.0])
    for hubs_on_paper, year in sets.values():
        if len(hubs_on_paper) < 2:
            continue
        w = 1 / (len(hubs_on_paper) - 1)
        for a, b in combinations(sorted(hubs_on_paper), 2):
            by_year[(year, a, b)][0] += 1
            by_year[(year, a, b)][1] += w
    years_of = defaultdict(list)
    for (year, a, b) in by_year:
        years_of[(a, b)].append(year)

    papers, cross, nonhub = Counter(), Counter(), Counter()
    for pmid, (hubs_on_paper, _) in sets.items():
        for h in hubs_on_paper:
            papers[h] += 1
            cross[h] += len(hubs_on_paper) > 1
            if nonhub_pmids is not None:
                nonhub[h] += pmid in nonhub_pmids
    partners = defaultdict(set)
    strength = Counter()
    for (a, b), w in full.items():
        partners[a].add(b)
        partners[b].add(a)
        strength[a] += w
        strength[b] += w

    nodes = []
    for hub_id, h in sorted(hubs.items(), key=lambda kv: kv[1]["label"]):
        yrs = active.get(hub_id) or {None}
        row = {"hub_id": hub_id, "label": h["label"], "city": h["city"], "state": h["state"],
               "award_first_fy": min(yrs, key=lambda y: y or 0),
               "award_last_fy": max(yrs, key=lambda y: y or 0),
               "papers": papers[hub_id], "cross_hub_papers": cross[hub_id],
               "pct_cross_hub": round(100 * cross[hub_id] / papers[hub_id], 1) if papers[hub_id] else 0,
               "partner_hubs": len(partners[hub_id]), "link_strength": strength[hub_id]}
        if nonhub_pmids is not None:
            row["papers_with_nonhub_coauthor"] = nonhub[hub_id]
            row["pct_with_nonhub_coauthor"] = (
                round(100 * nonhub[hub_id] / papers[hub_id], 1) if papers[hub_id] else 0)
        nodes.append(row)

    lab = {k: h["label"] for k, h in hubs.items()}
    st = {k: h["state"] for k, h in hubs.items()}
    edges = [{"hub_a": a, "hub_b": b, "label_a": lab[a], "label_b": lab[b],
              "state_a": st[a], "state_b": st[b], "papers": w,
              "papers_fractional": round(frac[(a, b)], 4),
              f"papers_under_{CONSORTIUM_HUBS}_hubs": small[(a, b)],
              "first_year": min(years_of[(a, b)]), "last_year": max(years_of[(a, b)])}
             for (a, b), w in sorted(full.items(), key=lambda kv: -kv[1])]
    edges_year = [{"year": y, "hub_a": a, "hub_b": b, "label_a": lab[a], "label_b": lab[b],
                   "papers": v[0], "papers_fractional": round(v[1], 4),
                   "a_active": int(y in active.get(a, ())), "b_active": int(y in active.get(b, ()))}
                  for (y, a, b), v in sorted(by_year.items())]

    _write_csv(out_dir / f"nodes_{name}.csv", nodes)
    _write_csv(out_dir / f"edges_{name}.csv", edges)
    _write_csv(out_dir / f"edges_by_year_{name}.csv", edges_year)
    write_vosviewer(nodes, full, out_dir / f"vosviewer_map_{name}.txt",
                    out_dir / f"vosviewer_network_{name}.txt")
    write_vosviewer(nodes, frac, out_dir / f"vosviewer_map_{name}.txt",
                    out_dir / f"vosviewer_network_{name}_fractional.txt")

    multi = sum(len(s) > 1 for s, _ in sets.values())
    log.info("%-15s papers with a hub %6d | with 2+ hubs %6d (%.1f%%) | hub pairs %4d of %d "
             "(%d without consortium papers)", name, len(sets), multi, 100 * multi / len(sets),
             len(full), len(hubs) * (len(hubs) - 1) // 2, len(small))
    share = defaultdict(lambda: [0, 0])
    for s, y in sets.values():
        share[y][0] += 1
        share[y][1] += len(s) > 1
    return [{"network": name, "year": y, "papers_with_hub": v[0], "papers_2plus_hubs": v[1],
             "pct_2plus_hubs": round(100 * v[1] / v[0], 1)} for y, v in sorted(share.items())]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=PROJECT_ROOT / "exports" / "hub_network")
    ap.add_argument("--coauthor-from", type=int, default=2014)
    ap.add_argument("--cofunding-from", type=int, default=2012)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    conn = connect_ncats()
    hubs = load_hubs()
    active = hub_active_years(conn, hubs)
    # Papers with an author whose affiliation matches no hub at any tier.
    nonhub = {r[0] for r in conn.execute("""
        SELECT DISTINCT af.pmid FROM pub_author_affils af
        LEFT JOIN pub_author_hubs h ON h.pmid = af.pmid AND h.position = af.position
        WHERE h.pmid IS NULL""")}

    share = []
    share += build("coauthor_core", coauthor_hub_sets(conn, False, args.coauthor_from),
                   hubs, active, args.out_dir, nonhub)
    share += build("coauthor_broad", coauthor_hub_sets(conn, True, args.coauthor_from),
                   hubs, active, args.out_dir, nonhub)
    share += build("cofunding", cofunding_hub_sets(conn, site_to_hub(hubs), args.cofunding_from),
                   hubs, active, args.out_dir)
    _write_csv(args.out_dir / "cross_hub_share_by_year.csv", share)
    log.info("wrote %s", args.out_dir)
    conn.close()


if __name__ == "__main__":
    main()

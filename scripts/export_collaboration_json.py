#!/usr/bin/env python3
"""Export docs/data/collaboration.json for the dashboard's Collaboration tab.

The tab recomputes the hub network in the browser for whatever its toggles
describe (network type, counting, year range, hidden hubs, consortium papers),
so the export is per paper rather than per hub pair. One record per
NCATS-linked paper from 2012 on that has a hub author or cites a hub's CTSA
award, stored as parallel arrays:

  y  publication year
  c  hubs with at least one core-tier author (the hub's own institution)
  p  hubs whose authors are all partner-tier (affiliated hospitals)
  f  hubs whose CTSA program awards the paper cites in RePORTER (co-funding)
  s  the hub whose grants are the paper's only NCATS grant links, or -1. Lets
     the tab drop papers that are in the data only because they cite a hidden
     hub's grant (Yale cites its UL1 on nearly everything).

Hubs are referred to by their position in `hubs`. Each hub carries its
location (Census Gazetteer city point), CTSA award years, dashboard slug, and
outside-collaboration summary (scripts/build_nonhub_collaboration.py).

A second file, collaboration_institutions.json, holds the map's optional
institution layers, loaded only when they are switched on:
  partner institutions  affiliated hospitals and institutes in
                        data/hub_aliases.csv (MGH for Harvard), from any hub
                        author's affiliation that names one
  other non-hub         institutions of authors who match no hub, as parsed by
                        the non-hub analysis (src/ncats/affil_institution.py)
Each has a US map point (Census Gazetteer city), and the papers it appears on,
2014 on, as positions in collaboration.json's paper arrays. Only US
institutions with a located city can be mapped; other non-hub institutions
need at least MIN_INST_PAPERS papers.

Run after export_ncats_json.py, which writes the slugs this links to.

Usage:
    python scripts/export_collaboration_json.py
"""

import sys, os, json, logging
from collections import Counter, defaultdict
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ncats.schema import connect_ncats
from src.ncats.config import WEBSITE_DATA_DIR
from src.ncats.hubs import load_hubs, site_to_hub
from src.ncats.hub_matching import HubMatcher, load_aliases
from src.ncats.gazetteer import Gazetteer
from src.ncats.affil_institution import describe, institution_type
from src.ncats.affil_location import USA
from scripts.build_hub_network import _years, cofunding_hub_sets, hub_active_years, CONSORTIUM_HUBS
import scripts.build_nonhub_collaboration as nonhub

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

FROM_YEAR = 2012
COAUTHOR_RELIABLE_FROM = 2014
MIN_INST_PAPERS = 3
OUTREACH_FIELDS = ["papers_with_nonhub_coauthor", "pct_with_nonhub_coauthor",
                   "pct_international_of_located", "pct_in_state_of_us",
                   "pct_within_100km_of_mapped", "nonhub_states", "nonhub_countries",
                   "top_nonhub_institution", "top_nonhub_institution_papers"]


def sole_grant_hubs(conn, to_hub):
    """{pmid: hub_id} for papers whose every NCATS grant link is at one hub."""
    seen = defaultdict(set)
    for pmid, ipf in conn.execute(
            "SELECT gp.pmid, g.ipf_code FROM grant_pubs gp JOIN grants g USING(core_project_num)"):
        seen[pmid].add(to_hub.get(ipf, "non-hub"))
    return {p: next(iter(s)) for p, s in seen.items() if len(s) == 1 and "non-hub" not in s}


def nonhub_outreach(hubs, gaz, matcher):
    """Per-hub outside-collaboration figures (as in hub_outreach_summary.csv),
    plus the parsed non-hub affiliation parts by paper and institution labels."""
    conn = nonhub.connect_readonly()
    years, n_authors, hub_papers, rows = nonhub.load_inputs(conn, COAUTHOR_RELIABLE_FROM)
    conn.close()
    points = {k: pt for k, h in hubs.items()
              if (pt := gaz.city_point(h["city"], h["state"])) is not None} if gaz else {}
    parts, labels = nonhub.parse_rows(rows, matcher, gaz)
    by_paper, unmatched = nonhub.outreach_parts(parts)
    t = nonhub.hub_tables(hub_papers, by_paper, unmatched, hubs, years, n_authors, labels, points)
    summary = {int(r["hub_id"]): {k: r.get(k) for k in OUTREACH_FIELDS} for r in t["summary"]}
    return summary, by_paper, labels


def institution_layer(conn, gaz, matcher, by_paper, labels, layer_pos, hub_idx):
    """Partner and other non-hub institutions with a US map point, and the
    papers each appears on. layer_pos {pmid: position in the paper arrays}."""
    papers = defaultdict(set)              # key -> pmids
    points = defaultdict(Counter)          # key -> (lat, lon, city, state) -> count
    types = {}

    for pmid, parts in by_paper.items():
        if pmid not in layer_pos:
            continue
        for p in parts:
            if p.country == USA and p.point and p.inst_key:
                key = ("other", p.inst_key, None)
                papers[key].add(pmid)
                points[key][(p.point.lat, p.point.lon, p.city, p.state)] += 1
                types[key] = p.inst_type

    cache = {}
    for pmid, aff in conn.execute("""
            SELECT af.pmid, af.affiliation FROM pub_author_affils af
            JOIN (SELECT DISTINCT pmid, position FROM pub_author_hubs) h USING(pmid, position)"""):
        if pmid not in layer_pos:
            continue
        hit = cache.get(aff)
        if hit is None:
            found, pt = matcher.partners_found(aff), None
            if found:
                for d in describe(aff):
                    q = nonhub.map_point(gaz, d.location)
                    if q:
                        pt = (q.lat, q.lon, d.location.city, d.location.state)
                        break
            hit = cache[aff] = (found, pt)
        for name, hub in hit[0]:
            key = ("partner", name, hub)
            papers[key].add(pmid)
            if hit[1]:
                points[key][hit[1]] += 1

    keep = [k for k in papers if points[k] and (k[0] == "partner" or len(papers[k]) >= MIN_INST_PAPERS)]
    keep.sort(key=lambda k: (k[0] != "partner", -len(papers[k])))
    institutions, ids = [], {}
    for k in keep:
        lat, lon, city, state = points[k].most_common(1)[0][0]
        ids[k] = len(institutions)
        institutions.append({
            "name": k[1] if k[0] == "partner" else labels.get(k[1], k[1]),
            "kind": k[0], "type": types.get(k) or institution_type(k[1]),
            "city": (city or "").title(), "state": state,
            "lat": round(lat, 4), "lon": round(lon, 4),
            "hub": hub_idx.get(k[2]) if k[0] == "partner" else None,
            "papers": len(papers[k])})
    on_paper = defaultdict(list)
    for k in keep:
        for pmid in papers[k]:
            on_paper[layer_pos[pmid]].append(ids[k])
    rows = sorted(on_paper)
    return {"institutions": institutions, "rows": rows, "inst": [sorted(on_paper[r]) for r in rows]}


def build(conn, hubs, gaz, slugs, outreach):
    order = sorted(hubs, key=lambda k: hubs[k]["label"])
    idx = {h: i for i, h in enumerate(order)}
    active = hub_active_years(conn, hubs)

    hub_rows = []
    for h in order:
        pt = gaz.city_point(hubs[h]["city"], hubs[h]["state"]) if gaz else None
        yrs = sorted(active.get(h, ()))
        hub_rows.append({
            "id": h, "label": hubs[h]["label"], "city": hubs[h]["city"], "state": hubs[h]["state"],
            "lat": round(pt.lat, 4) if pt else None, "lon": round(pt.lon, 4) if pt else None,
            "award_first": yrs[0] if yrs else None, "award_last": yrs[-1] if yrs else None,
            "slug": slugs.get(h), "outreach": outreach.get(h)})

    years = _years(conn)
    core, partner = defaultdict(set), defaultdict(set)
    for pmid, hub, n_core in conn.execute("SELECT pmid, hub_id, n_core FROM pub_hubs"):
        (core if n_core > 0 else partner)[pmid].add(idx[hub])
    fund = {p: {idx[h] for h in s} for p, (s, _) in
            cofunding_hub_sets(conn, site_to_hub(hubs), FROM_YEAR).items()}
    sole = sole_grant_hubs(conn, site_to_hub(hubs))

    pmids = sorted(p for p in set(core) | set(partner) | set(fund)
                   if years.get(p) and years[p] >= FROM_YEAR)
    papers = {"y": [years[p] for p in pmids],
              "c": [sorted(core.get(p, ())) for p in pmids],
              "p": [sorted(partner.get(p, ())) for p in pmids],
              "f": [sorted(fund.get(p, ())) for p in pmids],
              "s": [idx.get(sole.get(p), -1) for p in pmids]}
    return {"generated": date.today().isoformat(),
            "from_year": FROM_YEAR, "coauthor_reliable_from": COAUTHOR_RELIABLE_FROM,
            "consortium_hubs": CONSORTIUM_HUBS,
            "n_papers": len(pmids), "hubs": hub_rows, "papers": papers}, pmids, idx


def main():
    conn = connect_ncats()
    hubs = load_hubs()
    try:
        gaz = Gazetteer.load()
    except FileNotFoundError as e:
        log.warning("%s Hubs will have no map coordinates.", e)
        gaz = None
    slugs = {}
    index_path = WEBSITE_DATA_DIR / "index.json"
    if index_path.exists():
        slugs = {s["ipf_code"]: s["slug"] for s in json.loads(index_path.read_text())["sites"]}
    else:
        log.warning("no %s; run export_ncats_json.py first for Site Detail links", index_path)
    matcher = HubMatcher(load_aliases())
    outreach, by_paper, labels = nonhub_outreach(hubs, gaz, matcher)
    data, pmids, hub_idx = build(conn, hubs, gaz, slugs, outreach)
    years = dict(zip(pmids, data["papers"]["y"]))
    layer_pos = {p: i for i, p in enumerate(pmids) if years[p] >= COAUTHOR_RELIABLE_FROM}
    layer = institution_layer(conn, gaz, matcher, by_paper, labels, layer_pos, hub_idx) if gaz else None
    conn.close()
    data["build"] = f"{data['generated']}-{data['n_papers']}"

    missing = [h["label"] for h in data["hubs"] if h["lat"] is None]
    if missing:
        log.warning("hubs without coordinates: %s", missing)
    out = WEBSITE_DATA_DIR / "collaboration.json"
    out.write_text(json.dumps(data, separators=(",", ":")))
    log.info("wrote %s: %d hubs, %d papers, %d KB", out, len(data["hubs"]), data["n_papers"],
             out.stat().st_size // 1024)
    if layer:
        layer.update({"build": data["build"], "from_year": COAUTHOR_RELIABLE_FROM,
                      "min_papers": MIN_INST_PAPERS})
        out2 = WEBSITE_DATA_DIR / "collaboration_institutions.json"
        out2.write_text(json.dumps(layer, separators=(",", ":")))
        kinds = Counter(i["kind"] for i in layer["institutions"])
        log.info("wrote %s: %d partner and %d other institutions on %d papers, %d KB", out2,
                 kinds["partner"], kinds["other"], len(layer["rows"]), out2.stat().st_size // 1024)


if __name__ == "__main__":
    main()

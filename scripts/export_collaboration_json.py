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
Each has a US map point and the papers it appears on, 2014 on, as positions
in collaboration.json's paper arrays. Only US institutions with a located city
can be mapped; other non-hub institutions need at least MIN_INST_PAPERS papers.
Spellings and sub-units of one non-hub institution are merged into one node
(src/ncats/institution_merge.py, with the curated data/institution_aliases.csv).

Map points, for hubs and institutions alike, are Census Gazetteer centroids:
the most common ZIP (ZCTA) in the affiliations when it lies near the city,
else the city's own point. ZIPs separate institutions in one city, such as
Northwestern on Chicago's lakefront and the University of Chicago in Hyde Park.

A third file, collaboration_papers.json, holds per-paper attributes for the
tab's extra filters and click-through, loaded only when first needed: PMID,
theme, research-article flag, RCR, translational class, funding types, linked
grants (with a grant and PI list for search), and the hubs of the first and
last authors.

Run after export_ncats_json.py, which writes the slugs this links to.

Usage:
    python scripts/export_collaboration_json.py [--merges-csv institution_merges.csv]
"""

import sys, os, re, csv, json, argparse, logging
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ncats.schema import connect_ncats
from src.ncats.config import WEBSITE_DATA_DIR
from src.ncats.hubs import load_hubs, site_to_hub, is_ctsa_hub_award
from src.ncats.hub_matching import HubMatcher, load_aliases
from src.ncats.gazetteer import Gazetteer
from src.ncats.affil_institution import describe, institution_type
from src.ncats.affil_location import USA
from src.ncats.institution_merge import MERGE_KM, km, load_institution_aliases, merge_institutions
from scripts.build_hub_network import _years, cofunding_hub_sets, hub_active_years, CONSORTIUM_HUBS
import scripts.build_nonhub_collaboration as nonhub
from scripts.export_themes import tri_class

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

FROM_YEAR = 2012
COAUTHOR_RELIABLE_FROM = 2014
MIN_INST_PAPERS = 3
ZIP_KM = 30              # a ZIP centroid farther than this from the city point is a typo
MIN_ZIP_VOTES = 2        # institutions; hubs need MIN_HUB_ZIP_VOTES
MIN_HUB_ZIP_VOTES = 20
_STATE_ZIP = re.compile(r"\b([A-Z]{2}),?\s+(\d{5})(?:-\d{4})?\b")
TRI_CODES = {"human": 0, "animal": 1, "molecular_cellular": 2, "mixed": 3}
FUNDING_BITS = {"hub": 1, "training": 2, "research": 4, "small_business": 8}
SMALL_BUSINESS = {"R41", "R42", "R43", "R44", "U43", "U44", "SB1"}
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


def place_of(points, zips, gaz, min_votes=MIN_ZIP_VOTES):
    """(lat, lon, city, state): the most common ZIP centroid among the
    affiliations when it is near the most common city point, else that city
    point. points: Counter{(lat, lon, city, state)}; zips: Counter{zip5}."""
    lat, lon, city, state = points.most_common(1)[0][0]
    for z, n in zips.most_common(3):
        if n < min_votes:
            break
        q = gaz.zip_point(z)
        if q and km((lat, lon), (q.lat, q.lon)) <= ZIP_KM:
            return q.lat, q.lon, city, state
    return lat, lon, city, state


def hub_points(conn, hubs, gaz):
    """{hub_id: (lat, lon)} from the ZIPs in the affiliations of authors at
    exactly one hub (its own institution), where the ZIP is in the hub's state."""
    zips = defaultdict(Counter)
    for aff, hub in conn.execute("""
            SELECT af.affiliation, h.hub_id FROM pub_author_affils af
            JOIN (SELECT pmid, position, MIN(hub_id) AS hub_id FROM pub_author_hubs
                  GROUP BY pmid, position HAVING COUNT(*) = 1 AND MIN(tier) = 'core') h
            USING(pmid, position)"""):
        for st, z in _STATE_ZIP.findall(aff or ""):
            if st == hubs[hub]["state"]:
                zips[hub][z] += 1
    out = {}
    for h, hub in hubs.items():
        pt = gaz.city_point(hub["city"], hub["state"])
        if pt:
            lat, lon, _, _ = place_of(Counter({(pt.lat, pt.lon, hub["city"], hub["state"]): 1}),
                                      zips[h], gaz, MIN_HUB_ZIP_VOTES)
            out[h] = (lat, lon)
    return out


def institution_layer(conn, gaz, matcher, by_paper, labels, layer_pos, hub_idx, aliases=()):
    """Partner and other non-hub institutions with a US map point, and the
    papers each appears on. layer_pos {pmid: position in the paper arrays}."""
    # Other non-hub institutions: one entry per name and place. A name seen in
    # cities more than MERGE_KM apart is a different campus or site in each.
    sites = defaultdict(lambda: {"pmids": set(), "points": Counter(), "zips": Counter(), "types": Counter()})
    centers = defaultdict(list)
    for pmid, parts in by_paper.items():
        if pmid not in layer_pos:
            continue
        for p in parts:
            if p.country == USA and p.point and p.inst_key:
                ll = (p.point.lat, p.point.lon)
                cs = centers[p.inst_key]
                j = next((j for j, c in enumerate(cs) if km(c, ll) <= MERGE_KM), None)
                if j is None:
                    cs.append(ll)
                    j = len(cs) - 1
                site = sites[(p.inst_key, j)]
                site["pmids"].add(pmid)
                site["points"][(*ll, p.city, p.state)] += 1
                if p.zip:
                    site["zips"][p.zip] += 1
                site["types"][p.inst_type] += 1
    keys = list(sites)
    entries = []
    for k in keys:
        lat, lon, _, state = sites[k]["points"].most_common(1)[0][0]
        entries.append({"label": labels.get(k[0], k[0]), "key": k[0], "state": state, "lat": lat, "lon": lon,
                        "weight": len(sites[k]["pmids"])})
    group_of, groups = merge_institutions(entries, aliases)
    merged = [{"pmids": set(), "points": Counter(), "zips": Counter(), "types": Counter()} for _ in groups]
    for e, gs in enumerate(group_of):
        for g in gs:
            for f in merged[g]:
                merged[g][f].update(sites[keys[e]][f])
    log.info("merged %d non-hub institution names and places into %d institutions", len(entries), len(groups))

    # Partner institutions, from hub authors' affiliations that name one.
    partners = defaultdict(lambda: {"pmids": set(), "points": Counter(), "zips": Counter()})
    cache = {}
    for pmid, aff in conn.execute("""
            SELECT af.pmid, af.affiliation FROM pub_author_affils af
            JOIN (SELECT DISTINCT pmid, position FROM pub_author_hubs) h USING(pmid, position)"""):
        if pmid not in layer_pos:
            continue
        hit = cache.get(aff)
        if hit is None:
            found, pt, z = matcher.partners_found(aff), None, None
            if found:
                for d in describe(aff):
                    q = nonhub.map_point(gaz, d.location)
                    if q:
                        pt, z = (q.lat, q.lon, d.location.city, d.location.state), d.location.zip
                        break
            hit = cache[aff] = (found, pt, z)
        for name, hub in hit[0]:
            rec = partners[(name, hub)]
            rec["pmids"].add(pmid)
            if hit[1]:
                rec["points"][hit[1]] += 1
                if hit[2]:
                    rec["zips"][hit[2]] += 1

    nodes = [("partner", name, hub, rec) for (name, hub), rec in partners.items() if rec["points"]]
    members = defaultdict(list)
    for e, gs in enumerate(group_of):
        for g in gs:
            members[g].append(e)
    for g, rec in enumerate(merged):
        rec["members"] = sorted(members[g], key=lambda e: -entries[e]["weight"])
    nodes += [("other", groups[g]["label"], None, rec) for g, rec in enumerate(merged)
              if rec["points"] and len(rec["pmids"]) >= MIN_INST_PAPERS]
    nodes.sort(key=lambda n: (n[0] != "partner", -len(n[3]["pmids"]), n[1]))
    institutions = []
    for kind, name, hub, rec in nodes:
        lat, lon, city, state = place_of(rec["points"], rec["zips"], gaz)
        institutions.append({
            "name": name, "kind": kind,
            "type": (rec["types"].most_common(1)[0][0] if kind == "other" and rec["types"] else None)
                    or institution_type(name),
            "city": (city or "").title(), "state": state,
            "lat": round(lat, 4), "lon": round(lon, 4),
            "hub": hub_idx.get(hub) if kind == "partner" else None,
            "papers": len(rec["pmids"])})
    # One name in several places (University of California): add the city.
    seen = Counter(d["name"] for d in institutions)
    for d in institutions:
        if seen[d["name"]] > 1:
            d["name"] = f"{d['name']} ({d['city']})"
    on_paper = defaultdict(list)
    for i, (_, _, _, rec) in enumerate(nodes):
        for pmid in rec["pmids"]:
            on_paper[layer_pos[pmid]].append(i)
    rows = sorted(on_paper)
    # For review: each mapped institution that joins several spellings or places.
    merges = [{"institution": d["name"], "city": d["city"], "state": d["state"], "papers": d["papers"],
               "spellings": len(rec["members"]),
               "joined": " | ".join(f"{entries[e]['label']} [{sites[keys[e]]['points'].most_common(1)[0][0][2] or ''}, "
                                    f"{entries[e]['state']}] ({entries[e]['weight']})" for e in rec["members"])}
              for d, (kind, _, _, rec) in zip(institutions, nodes) if kind == "other" and len(rec["members"]) > 1]
    return {"institutions": institutions, "rows": rows, "inst": [sorted(on_paper[r]) for r in rows],
            "_merges": merges}


def funding_group(activity_code, core_project_num):
    """hub, training (career and training awards), small_business, or research."""
    code = activity_code or ""
    if is_ctsa_hub_award(code, core_project_num):
        return "hub"
    if code in SMALL_BUSINESS:
        return "small_business"
    if code[:1] in ("K", "T", "F") or code == "R25":
        return "training"
    return "research"


def paper_attributes(conn, pmids, hubs, idx):
    """Per-paper attributes aligned with collaboration.json's paper arrays."""
    pos = {p: i for i, p in enumerate(pmids)}
    n = len(pmids)
    to_hub = site_to_hub(hubs)

    themes = conn.execute("SELECT theme_id, COALESCE(mesh_label, label), size FROM themes "
                          "ORDER BY size DESC").fetchall()
    tid = {t: k for k, (t, _, _) in enumerate(themes)}
    theme = [-1] * n
    for pmid, t in conn.execute("SELECT pmid, theme_id FROM pub_themes"):
        if pmid in pos and t in tid:
            theme[pos[pmid]] = tid[t]

    research, rcr10, tri = [-1] * n, [-1] * n, [-1] * n
    for pmid, is_res, rcr, h, a, m in conn.execute(
            "SELECT pmid, is_research, rcr, human, animal, molecular_cellular FROM pub_metrics"):
        if pmid not in pos:
            continue
        i = pos[pmid]
        if is_res is not None:
            research[i] = int(is_res)
        if rcr is not None:
            rcr10[i] = min(9999, round(rcr * 10))
        tri[i] = TRI_CODES.get(tri_class(h, a, m), -1)

    grant_rows = {num: (code, ipf, title, org) for num, code, ipf, title, org in conn.execute(
        "SELECT g.core_project_num, g.activity_code, g.ipf_code, g.title, s.org_name "
        "FROM grants g LEFT JOIN sites s USING(ipf_code)")}
    grant_list, gidx = [], {}
    grants, funding = [[] for _ in range(n)], [0] * n
    for pmid, num in conn.execute("SELECT pmid, core_project_num FROM grant_pubs ORDER BY core_project_num"):
        if pmid not in pos or num not in grant_rows:
            continue
        code, ipf, title, org = grant_rows[num]
        if num not in gidx:
            hub = to_hub.get(ipf)
            gidx[num] = len(grant_list)
            grant_list.append({"num": num, "code": code, "group": funding_group(code, num),
                               "hub": idx.get(hub) if hub is not None else None,
                               "org": hubs[hub]["label"] if hub is not None else (org or "").title(),
                               "title": (title or "")[:90]})
        i = pos[pmid]
        grants[i].append(gidx[num])
        funding[i] |= FUNDING_BITS[grant_list[gidx[num]]["group"]]

    by_pi = defaultdict(set)
    for name, num in conn.execute("SELECT i.full_name, gp.core_project_num FROM grant_pis gp "
                                  "JOIN investigators i USING(profile_id)"):
        if name and num in gidx:
            by_pi[name.strip().title()].add(gidx[num])
    pis = [{"name": k, "g": sorted(v)} for k, v in sorted(by_pi.items())]

    lead_core, lead_broad = [set() for _ in range(n)], [set() for _ in range(n)]
    for pmid, hub, tier in conn.execute("""
            SELECT h.pmid, h.hub_id, h.tier FROM pub_author_hubs h JOIN pub_author_fetch f USING(pmid)
            WHERE h.position = 1 OR h.position = f.n_authors"""):
        if pmid in pos and hub in idx:
            lead_broad[pos[pmid]].add(idx[hub])
            if tier == "core":
                lead_core[pos[pmid]].add(idx[hub])

    return {"pmid_delta": [p - q for p, q in zip(pmids, [0] + pmids[:-1])],
            "themes": [{"id": t, "label": label, "size": size} for t, label, size in themes],
            "theme": theme, "research": research, "rcr10": rcr10, "tri": tri,
            "funding_bits": FUNDING_BITS, "funding": funding,
            "grant_list": grant_list, "grants": grants, "pis": pis,
            "lead_core": [sorted(s) for s in lead_core], "lead_broad": [sorted(s) for s in lead_broad]}


def build(conn, hubs, gaz, slugs, outreach, points=None):
    order = sorted(hubs, key=lambda k: hubs[k]["label"])
    idx = {h: i for i, h in enumerate(order)}
    active = hub_active_years(conn, hubs)

    # NCATS award dollars across all awards at each hub's sites.
    to_hub = site_to_hub(hubs)
    dollars = defaultdict(float)
    for ipf, amount in conn.execute("SELECT ipf_code, total_award_amount FROM grants"):
        if ipf in to_hub and amount:
            dollars[to_hub[ipf]] += amount

    hub_rows = []
    for h in order:
        pt = (points or {}).get(h)
        if pt is None and gaz and (c := gaz.city_point(hubs[h]["city"], hubs[h]["state"])):
            pt = (c.lat, c.lon)
        yrs = sorted(active.get(h, ()))
        hub_rows.append({
            "id": h, "label": hubs[h]["label"], "city": hubs[h]["city"], "state": hubs[h]["state"],
            "lat": round(pt[0], 4) if pt else None, "lon": round(pt[1], 4) if pt else None,
            "award_first": yrs[0] if yrs else None, "award_last": yrs[-1] if yrs else None,
            "award_total": round(dollars.get(h, 0.0)),
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--merges-csv", type=Path,
                    help="also write the institution merges (spellings joined into one map node) for review")
    args = ap.parse_args()
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
    points = hub_points(conn, hubs, gaz) if gaz else None
    data, pmids, hub_idx = build(conn, hubs, gaz, slugs, outreach, points)
    years = dict(zip(pmids, data["papers"]["y"]))
    layer_pos = {p: i for i, p in enumerate(pmids) if years[p] >= COAUTHOR_RELIABLE_FROM}
    layer = (institution_layer(conn, gaz, matcher, by_paper, labels, layer_pos, hub_idx,
                               load_institution_aliases()) if gaz else None)
    attrs = paper_attributes(conn, pmids, hubs, hub_idx)
    conn.close()
    data["build"] = f"{data['generated']}-{data['n_papers']}"

    missing = [h["label"] for h in data["hubs"] if h["lat"] is None]
    if missing:
        log.warning("hubs without coordinates: %s", missing)
    out = WEBSITE_DATA_DIR / "collaboration.json"
    out.write_text(json.dumps(data, separators=(",", ":")))
    log.info("wrote %s: %d hubs, %d papers, %d KB", out, len(data["hubs"]), data["n_papers"],
             out.stat().st_size // 1024)
    attrs["build"] = data["build"]
    out3 = WEBSITE_DATA_DIR / "collaboration_papers.json"
    out3.write_text(json.dumps(attrs, separators=(",", ":")))
    log.info("wrote %s: %d themes, %d grants, %d PIs, %d KB", out3, len(attrs["themes"]),
             len(attrs["grant_list"]), len(attrs["pis"]), out3.stat().st_size // 1024)
    if layer:
        merges = layer.pop("_merges")
        if args.merges_csv:
            with open(args.merges_csv, "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(merges[0]))
                w.writeheader()
                w.writerows(merges)
            log.info("wrote %s: %d merged institutions", args.merges_csv, len(merges))
        layer.update({"build": data["build"], "from_year": COAUTHOR_RELIABLE_FROM,
                      "min_papers": MIN_INST_PAPERS})
        out2 = WEBSITE_DATA_DIR / "collaboration_institutions.json"
        out2.write_text(json.dumps(layer, separators=(",", ":")))
        kinds = Counter(i["kind"] for i in layer["institutions"])
        log.info("wrote %s: %d partner and %d other institutions on %d papers, %d KB", out2,
                 kinds["partner"], kinds["other"], len(layer["rows"]), out2.stat().st_size // 1024)


if __name__ == "__main__":
    main()

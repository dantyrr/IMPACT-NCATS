#!/usr/bin/env python3
"""List institution names to consider adding to data/hub_aliases.csv.

For each hub, takes the papers linked to that hub's own CTSA awards (hub,
KL2/TL1, K12/T32), whose first and last authors are mostly at the hub, and
counts the institution-like parts of their PubMed affiliation strings. The most
frequent parts are the names the hub's authors actually use. Each row shows
whether the current alias list already matches it, so a curation pass only
needs to look at the unmatched ones.

This is a curation aid. Matching itself uses only data/hub_aliases.csv.

Output:
    exports/hub_alias_candidates.csv

Usage:
    python scripts/suggest_hub_aliases.py [--top 30]
"""

import sys, os, csv, argparse, logging
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ncats.schema import connect_ncats
from src.ncats.config import PROJECT_ROOT
from src.ncats.hubs import load_hubs, site_to_hub, is_ctsa_program_award
from src.ncats.hub_matching import HubMatcher, load_aliases, institution_segments, ALIASES_CSV

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def hub_award_papers(conn, hubs):
    """{hub_id: set of PMIDs} linked to that hub's CTSA program awards."""
    to_hub = site_to_hub(hubs)
    out = defaultdict(set)
    for pmid, ipf, code, num in conn.execute(
            "SELECT gp.pmid, g.ipf_code, g.activity_code, g.core_project_num "
            "FROM grant_pubs gp JOIN grants g USING(core_project_num)"):
        if ipf in to_hub and is_ctsa_program_award(code, num):
            out[to_hub[ipf]].add(pmid)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=30, help="Candidates per hub")
    args = ap.parse_args()

    conn = connect_ncats()
    hubs = load_hubs()
    matcher = HubMatcher(load_aliases()) if ALIASES_CSV.exists() else None
    papers = hub_award_papers(conn, hubs)

    # First and last author affiliations, the authors most likely at the hub.
    affils = defaultdict(list)
    for pmid, aff in conn.execute("""
            SELECT af.pmid, af.affiliation FROM pub_author_affils af
            JOIN pub_author_fetch f ON f.pmid = af.pmid
            WHERE af.position = 1 OR af.position = f.n_authors"""):
        affils[pmid].append(aff)

    rows = []
    for hub_id, h in sorted(hubs.items(), key=lambda kv: kv[1]["label"]):
        counts = Counter()
        for pmid in papers.get(hub_id, ()):
            counts.update({s for a in affils.get(pmid, ()) for s in institution_segments(a)})
        n = len(papers.get(hub_id, ()))
        for seg, k in counts.most_common(args.top):
            hit = matcher.match(seg) if matcher else {}
            rows.append({"hub_id": hub_id, "label": h["label"], "segment": seg, "papers": k,
                         "share": round(k / n, 3) if n else 0,
                         "matched_hubs": ";".join(map(str, sorted(hit))),
                         "matches_this_hub": int(hub_id in hit)})

    out = PROJECT_ROOT / "exports" / "hub_alias_candidates.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    log.info("wrote %s (%d candidates for %d hubs)", out, len(rows), len(hubs))
    conn.close()


if __name__ == "__main__":
    main()

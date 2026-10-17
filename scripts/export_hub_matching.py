#!/usr/bin/env python3
"""Export author and paper hub assignments, plus quality checks on the matching.

Outputs (in --out-dir):
  paper_hubs.csv                 one row per paper x hub: tier, authors at the hub
  author_hubs.csv                one row per author x hub
  hub_self_match.csv             per hub: share of papers on its own CTSA awards
                                 whose first or last author matches that hub.
                                 Not pure recall (multi-site papers cite a hub's
                                 award with a lead author elsewhere), but a hub
                                 far below the others suggests missing aliases.
  unmatched_us_institutions.csv  most frequent institution names in US
                                 affiliations that match no hub, to check
                                 nothing that belongs to a hub is missed
  precision_sample.csv           random matched affiliations with the names
                                 that matched, and blank columns for review

Usage:
    python scripts/export_hub_matching.py --out-dir exports/hub_matching
"""

import sys, os, csv, re, random, argparse, logging
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ncats.schema import connect_ncats
from src.ncats.config import PROJECT_ROOT
from src.ncats.hubs import load_hubs
from src.ncats.hub_matching import HubMatcher, load_aliases, institution_segments
from scripts.suggest_hub_aliases import hub_award_papers

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

US = re.compile(r"\b(USA|U\.S\.A|United States)\b|\b[A-Z]{2},? \d{5}\b")
SAMPLE_SEED = 20261017


def _write(path, header, rows):
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    log.info("wrote %s", path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=PROJECT_ROOT / "exports" / "hub_matching")
    ap.add_argument("--sample", type=int, default=200)
    args = ap.parse_args()
    out = args.out_dir
    out.mkdir(parents=True, exist_ok=True)

    conn = connect_ncats()
    hubs = load_hubs()
    lab = {k: h["label"] for k, h in hubs.items()}
    matcher = HubMatcher(load_aliases())

    _write(out / "paper_hubs.csv",
           ["pmid", "pub_year", "hub_id", "hub_label", "tier", "n_authors", "n_core"],
           [(p, y, h, lab[h], t, n, nc) for p, y, h, t, n, nc in conn.execute("""
               SELECT ph.pmid, COALESCE(pm.pub_year, f.pub_year), ph.hub_id, ph.tier,
                      ph.n_authors, ph.n_core
               FROM pub_hubs ph JOIN pub_author_fetch f USING(pmid)
               LEFT JOIN pub_metrics pm USING(pmid) ORDER BY ph.pmid, ph.hub_id""")])
    _write(out / "author_hubs.csv", ["pmid", "position", "hub_id", "hub_label", "tier"],
           [(p, pos, h, lab[h], t) for p, pos, h, t in conn.execute(
               "SELECT pmid, position, hub_id, tier FROM pub_author_hubs ORDER BY 1, 2, 3")])

    # Self-match on each hub's own-award papers.
    lead_hubs = defaultdict(set)
    for pmid, hub in conn.execute("""
            SELECT h.pmid, h.hub_id FROM pub_author_hubs h JOIN pub_author_fetch f USING(pmid)
            WHERE h.position = 1 OR h.position = f.n_authors"""):
        lead_hubs[pmid].add(hub)
    lead_affiliated = {r[0] for r in conn.execute("""
            SELECT DISTINCT af.pmid FROM pub_author_affils af JOIN pub_author_fetch f USING(pmid)
            WHERE af.position = 1 OR af.position = f.n_authors""")}
    rows = []
    for hub, pmids in hub_award_papers(conn, hubs).items():
        pmids = [p for p in pmids if p in lead_affiliated]
        hit = sum(hub in lead_hubs.get(p, ()) for p in pmids)
        rows.append((hub, lab[hub], len(pmids), hit, round(100 * hit / len(pmids), 1) if pmids else ""))
    rows.sort(key=lambda r: (r[4] == "", r[4]))
    _write(out / "hub_self_match.csv",
           ["hub_id", "hub_label", "own_award_papers", "lead_author_at_hub", "pct"], rows)

    # Unmatched US institution names, and a random sample of matches.
    segs = Counter()
    matched = []
    for pmid, pos, aff in conn.execute("SELECT pmid, position, affiliation FROM pub_author_affils"):
        found = matcher.aliases_found(aff)
        if found:
            matched.append((pmid, pos, aff, found))
        elif US.search(aff):
            segs.update(set(institution_segments(aff)))
    _write(out / "unmatched_us_institutions.csv", ["institution_text", "author_affiliations"],
           segs.most_common(500))

    rng = random.Random(SAMPLE_SEED)
    sample = rng.sample(matched, min(args.sample, len(matched)))
    _write(out / "precision_sample.csv",
           ["pmid", "position", "affiliation", "matched_names", "hubs", "tiers",
            "reviewer_correct", "reviewer_note"],
           [(p, pos, aff, "; ".join(a for a, _, _ in f),
             "; ".join(dict.fromkeys(lab[h] for _, h, _ in f)),
             "; ".join(dict.fromkeys(t for _, _, t in f)), "", "")
            for p, pos, aff, f in sample])
    conn.close()


if __name__ == "__main__":
    main()

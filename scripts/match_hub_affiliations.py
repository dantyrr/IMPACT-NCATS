#!/usr/bin/env python3
"""Assign authors to CTSA hubs from their PubMed affiliation strings.

Uses only the curated names in data/hub_aliases.csv and the hub list in
data/ctsa_hubs.csv; no external institution registry. Each distinct
affiliation string is matched once. Results replace pub_author_hubs and
pub_hubs entirely, so the script is safe to re-run after editing the alias list.

Coverage follows PubMed: before about 2014 only the first author's affiliation
was recorded, so co-author hubs are mostly unknown for 2012-2013 papers.

Usage:
    python scripts/match_hub_affiliations.py
"""

import sys, os, logging
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ncats.schema import connect_ncats
from src.ncats.hubs import load_hubs, check_hubs_cover_awards
from src.ncats.hub_matching import HubMatcher, load_aliases, TIERS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def author_hubs(rows, matcher):
    """{(pmid, position): {hub_id: tier}} from (pmid, position, affiliation) rows.
    An author with several affiliations at one hub keeps the strongest tier."""
    cache = {}
    out = defaultdict(dict)
    for pmid, position, aff in rows:
        hits = cache.get(aff)
        if hits is None:
            hits = cache[aff] = matcher.match(aff)
        for hub_id, tier in hits.items():
            prev = out[(pmid, position)].get(hub_id)
            if prev is None or TIERS[tier] < TIERS[prev]:
                out[(pmid, position)][hub_id] = tier
    return out, len(cache)


def paper_hubs(by_author):
    """{(pmid, hub_id): [tier, n_authors, n_core]}"""
    out = {}
    for (pmid, _), hubs in by_author.items():
        for hub_id, tier in hubs.items():
            rec = out.setdefault((pmid, hub_id), [tier, 0, 0])
            if TIERS[tier] < TIERS[rec[0]]:
                rec[0] = tier
            rec[1] += 1
            rec[2] += tier == "core"
    return out


def main():
    conn = connect_ncats()
    hubs = load_hubs()
    check_hubs_cover_awards(conn, hubs)
    aliases = load_aliases()
    unknown = {a.hub_id for a in aliases if a.hub_id is not None} - set(hubs)
    if unknown:
        raise SystemExit(f"hub_aliases.csv names hubs not in ctsa_hubs.csv: {sorted(unknown)}")
    matcher = HubMatcher(aliases)
    log.info("%d hubs, %d aliases", len(hubs), len(aliases))

    rows = conn.execute("SELECT pmid, position, affiliation FROM pub_author_affils")
    by_author, n_distinct = author_hubs(rows, matcher)
    by_paper = paper_hubs(by_author)
    log.info("matched %d distinct affiliation strings", n_distinct)

    with conn:
        conn.execute("DELETE FROM pub_author_hubs")
        conn.execute("DELETE FROM pub_hubs")
        conn.executemany(
            "INSERT INTO pub_author_hubs (pmid, position, hub_id, tier) VALUES (?,?,?,?)",
            [(p, pos, h, t) for (p, pos), hs in by_author.items() for h, t in hs.items()])
        conn.executemany(
            "INSERT INTO pub_hubs (pmid, hub_id, tier, n_authors, n_core) VALUES (?,?,?,?,?)",
            [(p, h, *rec) for (p, h), rec in by_paper.items()])

    q = lambda sql: conn.execute(sql).fetchone()[0]
    n_aff_authors = q("SELECT COUNT(*) FROM (SELECT DISTINCT pmid, position FROM pub_author_affils)")
    log.info("authors with an affiliation   %8d", n_aff_authors)
    log.info("  matched to a hub            %8d (%.1f%%)", len(by_author),
             100 * len(by_author) / n_aff_authors)
    log.info("papers with >=1 hub author    %8d", q("SELECT COUNT(DISTINCT pmid) FROM pub_hubs"))
    log.info("papers with >=2 hubs          %8d", q(
        "SELECT COUNT(*) FROM (SELECT pmid FROM pub_hubs GROUP BY pmid HAVING COUNT(*) >= 2)"))
    log.info("papers with >=2 hubs, core    %8d", q(
        "SELECT COUNT(*) FROM (SELECT pmid FROM pub_hubs WHERE n_core > 0 "
        "GROUP BY pmid HAVING COUNT(*) >= 2)"))
    conn.close()


if __name__ == "__main__":
    main()

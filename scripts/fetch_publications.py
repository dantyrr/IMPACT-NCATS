#!/usr/bin/env python3
"""Fetch RePORTER publication links for every NCATS grant.

Usage:
    python scripts/fetch_publications.py
    python scripts/fetch_publications.py --hubs-only
    python scripts/fetch_publications.py --resume
"""

import sys, os, argparse, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ncats.schema import connect_ncats
from src.ncats.reporter_client import ReporterClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def ingest_pubs_for_grant(conn, core_project_num: str, pmids: list[int]) -> int:
    """Insert grant->PMID links. Returns the number of NEW rows."""
    inserted = 0
    for pmid in pmids:
        cur = conn.execute(
            "INSERT OR IGNORE INTO grant_pubs (core_project_num, pmid) VALUES (?,?)",
            (core_project_num, pmid),
        )
        inserted += cur.rowcount
    conn.commit()
    return inserted


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hubs-only", action="store_true",
                    help="Only fetch for UL1/UM1 hub awards")
    ap.add_argument("--resume", action="store_true",
                    help="Skip grants that already have links")
    args = ap.parse_args()

    conn = connect_ncats()
    q = "SELECT core_project_num FROM grants"
    where = []
    if args.hubs_only:
        where.append("is_hub_award = 1")
    if args.resume:
        where.append("core_project_num NOT IN (SELECT DISTINCT core_project_num FROM grant_pubs)")
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY core_project_num"

    cores = [r[0] for r in conn.execute(q)]
    log.info("Fetching publications for %d grants", len(cores))

    client = ReporterClient()
    total_new = 0
    for i, core in enumerate(cores, 1):
        try:
            pmids = client.fetch_publications(core)
        except Exception as e:
            log.error("FAILED %s: %s", core, e)
            continue
        total_new += ingest_pubs_for_grant(conn, core, pmids)
        if i % 50 == 0:
            log.info("[%d/%d] %d new links so far", i, len(cores), total_new)

    log.info("DONE. New links: %d", total_new)
    log.info("Total links: %s",
             conn.execute("SELECT COUNT(*) FROM grant_pubs").fetchone()[0])
    log.info("Distinct PMIDs: %s",
             conn.execute("SELECT COUNT(DISTINCT pmid) FROM grant_pubs").fetchone()[0])
    conn.close()


if __name__ == "__main__":
    main()

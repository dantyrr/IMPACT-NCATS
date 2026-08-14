#!/usr/bin/env python3
"""Populate pub_metrics.rcr from iCite for all grant-linked PMIDs.

Usage:
    python scripts/fetch_rcr.py
    python scripts/fetch_rcr.py --resume
"""

import sys, os, argparse, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ncats.schema import connect_ncats
from src.ncats.icite_client import IciteClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

CHUNK = 2000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume", action="store_true",
                    help="Skip PMIDs already present in pub_metrics")
    args = ap.parse_args()

    conn = connect_ncats()
    q = "SELECT DISTINCT pmid FROM grant_pubs"
    if args.resume:
        q += " WHERE pmid NOT IN (SELECT pmid FROM pub_metrics)"
    pmids = [r[0] for r in conn.execute(q)]
    log.info("Fetching RCR for %d PMIDs", len(pmids))

    client = IciteClient()
    done = 0
    for i in range(0, len(pmids), CHUNK):
        batch = pmids[i: i + CHUNK]
        rcr_map = client.fetch_rcr(batch)
        conn.executemany(
            "INSERT INTO pub_metrics (pmid, rcr) VALUES (?,?) "
            "ON CONFLICT(pmid) DO UPDATE SET rcr=excluded.rcr",
            [(p, rcr_map.get(p)) for p in batch],
        )
        conn.commit()
        done += len(batch)
        log.info("[%d/%d] RCR rows written", done, len(pmids))

    log.info("PMIDs with a non-null RCR: %s",
             conn.execute("SELECT COUNT(*) FROM pub_metrics WHERE rcr IS NOT NULL").fetchone()[0])
    conn.close()


if __name__ == "__main__":
    main()

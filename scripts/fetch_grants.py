#!/usr/bin/env python3
"""Fetch all NCATS grants FY2012-present into ncats.db.

Usage:
    python scripts/fetch_grants.py
    python scripts/fetch_grants.py --start-year 2020 --end-year 2026
"""

import sys, os, argparse, logging
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ncats.config import FIRST_FISCAL_YEAR
from src.ncats.schema import connect_ncats
from src.ncats.reporter_client import ReporterClient
from src.ncats.grant_ingest import ingest_projects

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-year", type=int, default=FIRST_FISCAL_YEAR)
    ap.add_argument("--end-year", type=int, default=date.today().year + 1)
    args = ap.parse_args()

    conn = connect_ncats()
    client = ReporterClient()
    totals = {"sites": 0, "grants": 0, "grant_years": 0, "investigators": 0}

    for fy in range(args.start_year, args.end_year + 1):
        records = client.fetch_projects(fy)
        if not records:
            log.info("FY%d: no records", fy)
            continue
        counts = ingest_projects(conn, records)
        for k in totals:
            totals[k] += counts[k]
        log.info("FY%d: +%s", fy, counts)

    log.info("DONE new rows: %s", totals)
    for label, q in [
        ("sites", "SELECT COUNT(*) FROM sites"),
        ("grants", "SELECT COUNT(*) FROM grants"),
        ("hub awards", "SELECT COUNT(*) FROM grants WHERE is_hub_award=1"),
        ("hub sites", "SELECT COUNT(DISTINCT ipf_code) FROM grants WHERE is_hub_award=1"),
        ("investigators", "SELECT COUNT(*) FROM investigators"),
    ]:
        log.info("%-14s %s", label, conn.execute(q).fetchone()[0])
    conn.close()


if __name__ == "__main__":
    main()

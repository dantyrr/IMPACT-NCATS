#!/usr/bin/env python3
"""Join ncats.db against impact.db and compute all metrics."""

import sys, os, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ncats.schema import connect_ncats, connect_impact_readonly
from src.ncats.metrics import (
    compute_n_linked_hubs, enrich_from_impact, compute_site_metrics,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

if __name__ == "__main__":
    conn = connect_ncats()
    impact = connect_impact_readonly()

    log.info("Computing hub linkage counts...")
    compute_n_linked_hubs(conn)

    log.info("Enriching from impact.db...")
    stats = enrich_from_impact(conn, impact)
    log.info("PMIDs: %d | matched in impact.db: %d (%.1f%%)",
             stats["total"], stats["matched"], stats["match_rate"] * 100)

    log.info("Computing site metrics...")
    n = compute_site_metrics(conn)
    log.info("site_metrics rows: %d", n)

    shared = conn.execute(
        "SELECT COUNT(*) FROM pub_metrics WHERE n_linked_hubs > 1").fetchone()[0]
    log.info("Publications shared across >1 hub: %d", shared)

    impact.close()
    conn.close()

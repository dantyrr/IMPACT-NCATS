#!/usr/bin/env python3
"""Identify CTSA hub sites and write data/ctsa_registry.json."""

import sys, os, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ncats.config import DATA_DIR
from src.ncats.schema import connect_ncats
from src.ncats.site_registry import mark_ctsa_hubs, export_registry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

if __name__ == "__main__":
    conn = connect_ncats()
    n_hubs = mark_ctsa_hubs(conn)
    entries = export_registry(conn, DATA_DIR / "ctsa_registry.json")
    log.info("CTSA hub sites: %d", n_hubs)
    log.info("Registry entries written: %d", len(entries))
    multi = [e for e in entries if len(e["core_project_nums"]) > 1]
    log.info("Hubs with multiple core projects (renewals): %d", len(multi))
    conn.close()

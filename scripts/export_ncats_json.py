#!/usr/bin/env python3
"""Export ncats.db to docs/data/ as static JSON."""

import sys, os, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ncats.config import WEBSITE_DATA_DIR
from src.ncats.schema import connect_ncats
from src.ncats.json_exporter import (
    export_index, export_sites, export_investigators, export_publications,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

if __name__ == "__main__":
    conn = connect_ncats()
    log.info("index.json -> %s", export_index(conn, WEBSITE_DATA_DIR))
    log.info("site files: %d", export_sites(conn, WEBSITE_DATA_DIR))
    log.info("publications.json -> %s", export_publications(conn, WEBSITE_DATA_DIR))
    log.info("investigator files: %d", export_investigators(conn, WEBSITE_DATA_DIR))
    conn.close()

#!/usr/bin/env python3
"""Create an empty ncats.db with the full schema."""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ncats.schema import connect_ncats
from src.ncats.config import NCATS_DB_PATH

if __name__ == "__main__":
    conn = connect_ncats()
    conn.close()
    print(f"Initialized {NCATS_DB_PATH}")

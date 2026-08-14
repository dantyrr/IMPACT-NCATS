"""CTSA site registry: hub identification keyed on org_ipf_code."""

import json
import re
import sqlite3
from pathlib import Path


def slugify(name: str) -> str:
    """Lowercase kebab-case slug, matching IMPACT journal-slug conventions.

    Apostrophes are dropped rather than treated as separators, so
    "St. Jude's" becomes "st-judes" and not "st-jude-s".
    """
    s = (name or "").lower()
    s = s.replace("'", "").replace("’", "")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"-{2,}", "-", s).strip("-")


def mark_ctsa_hubs(conn: sqlite3.Connection) -> int:
    """Flag every site holding a hub award, and set its slug and funded span.

    Because identity is the IPF code, a site with several renewal core
    projects collapses into exactly one hub row.
    """
    conn.execute("UPDATE sites SET is_ctsa_hub = 0")
    conn.execute(
        "UPDATE sites SET is_ctsa_hub = 1 "
        "WHERE ipf_code IN (SELECT DISTINCT ipf_code FROM grants WHERE is_hub_award = 1)"
    )
    conn.execute(
        "UPDATE sites SET "
        "  first_funded_year = ("
        "    SELECT MIN(gy.fiscal_year) FROM grant_years gy "
        "    JOIN grants g ON g.core_project_num = gy.core_project_num "
        "    WHERE g.ipf_code = sites.ipf_code), "
        "  last_funded_year = ("
        "    SELECT MAX(gy.fiscal_year) FROM grant_years gy "
        "    JOIN grants g ON g.core_project_num = gy.core_project_num "
        "    WHERE g.ipf_code = sites.ipf_code)"
    )
    # Slug per row (SQLite cannot call Python in a bulk UPDATE).
    for ipf, org in conn.execute("SELECT ipf_code, org_name FROM sites").fetchall():
        conn.execute("UPDATE sites SET slug=? WHERE ipf_code=?", (slugify(org), ipf))

    conn.commit()
    return conn.execute(
        "SELECT COUNT(*) FROM sites WHERE is_ctsa_hub = 1"
    ).fetchone()[0]


def export_registry(conn: sqlite3.Connection, path: Path) -> list[dict]:
    """Write ctsa_registry.json, preserving hand-edited hub_name values."""
    path = Path(path)
    existing = {}
    if path.exists():
        try:
            for e in json.loads(path.read_text()):
                if e.get("hub_name"):
                    existing[e["ipf_code"]] = e["hub_name"]
        except (json.JSONDecodeError, TypeError, KeyError):
            pass

    entries = []
    rows = conn.execute(
        "SELECT ipf_code, org_name, slug, city, state, "
        "       first_funded_year, last_funded_year "
        "FROM sites WHERE is_ctsa_hub = 1 ORDER BY org_name"
    ).fetchall()
    for ipf, org, slug, city, state, first, last in rows:
        cores = [r[0] for r in conn.execute(
            "SELECT core_project_num FROM grants "
            "WHERE ipf_code=? AND is_hub_award=1 ORDER BY core_project_num", (ipf,))]
        entries.append({
            "ipf_code": ipf,
            "org_name": org,
            "slug": slug,
            "hub_name": existing.get(ipf, (org or "").title()),
            "city": city,
            "state": state,
            "first_funded_year": first,
            "last_funded_year": last,
            "core_project_nums": cores,
        })

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2))
    return entries

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


def load_ipf_aliases(path: Path) -> dict:
    """Read the curated alias->canonical IPF map, ignoring comment keys."""
    path = Path(path)
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    return {int(k): int(v) for k, v in raw.items() if not k.startswith("_")}


def canonicalize_ipf_codes(conn: sqlite3.Connection, aliases: dict) -> int:
    """Repoint grants from alias IPF codes to their canonical site.

    An institution that re-registered with NIH holds several IPF codes over
    time. Left alone, one continuous hub appears as several sites whose slugs
    collide. Returns the number of grants moved.
    """
    moved = 0
    for alias, canonical in aliases.items():
        if alias == canonical:
            continue
        # Only move if the canonical site actually exists.
        exists = conn.execute(
            "SELECT 1 FROM sites WHERE ipf_code=?", (canonical,)
        ).fetchone()
        if not exists:
            continue
        cur = conn.execute(
            "UPDATE grants SET ipf_code=? WHERE ipf_code=?", (canonical, alias)
        )
        moved += cur.rowcount
        conn.execute("DELETE FROM sites WHERE ipf_code=?", (alias,))
    conn.commit()
    return moved


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

    # A duplicate slug would make two hubs write to the same JSON filename,
    # silently destroying one of them. Fail loudly instead.
    seen = {}
    for e in entries:
        if e["slug"] in seen:
            raise ValueError(
                f"Duplicate slug {e['slug']!r} for IPF codes "
                f"{seen[e['slug']]} and {e['ipf_code']}. If these are the same "
                f"institution, add an entry to data/ipf_aliases.json."
            )
        seen[e["slug"]] = e["ipf_code"]

    # Write hub_name back into the sites table. The JSON registry is the
    # curated source of truth, but export_index() reads the database, so the
    # two must agree or every site renders with a null name.
    for e in entries:
        conn.execute("UPDATE sites SET hub_name=? WHERE ipf_code=?",
                     (e["hub_name"], e["ipf_code"]))
    conn.commit()

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, indent=2))
    return entries

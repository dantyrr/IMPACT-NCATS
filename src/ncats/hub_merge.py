"""Show a hub held by several sites as one dashboard site, at export time.

data/ctsa_hubs.csv lists every site (IPF code) that has held each hub's award.
Most hubs are one site. Dartmouth is two: Dartmouth College held the UL1
(FY2013-2017) and Dartmouth-Hitchcock holds the UM1 (FY2024-). ncats.db keeps
them apart, because the collaboration analysis reads grants by IPF code, so
the merge happens only on the exporting connection.

merge_hub_sites() shadows sites, grants and site_metrics with TEMP tables.
SQLite resolves an unqualified table name to TEMP before MAIN, so every
exporter's SQL runs unchanged and nothing in ncats.db is modified. Call it
only on a connection that exports: writes through that connection to those
three tables land in the TEMP copies and are dropped on close.
"""

import logging

from src.ncats.hubs import HUBS_CSV, load_hubs
from src.ncats.metrics import compute_site_metrics
from src.ncats.site_registry import slugify

logger = logging.getLogger(__name__)


def merge_hub_sites(conn, hubs_path=HUBS_CSV) -> dict:
    """Fold each multi-site hub into one site. Returns {folded ipf: hub ipf}.

    The merged site keeps the hub's own IPF (its hub_id in the CSV) and takes
    the CSV label as its name and slug, the CSV city and state, and the span
    of all its members' funding.
    """
    hub_sites = {r[0] for r in conn.execute(
        "SELECT ipf_code FROM main.sites WHERE is_ctsa_hub = 1")}
    fold, display = {}, {}
    for hub_id, h in load_hubs(hubs_path).items():
        members = [m for m in h["members"] if m in hub_sites]
        if len(members) < 2:
            continue
        if hub_id not in members:
            raise ValueError(f"hub {hub_id} ({h['label']}) is not one of its own member sites")
        marks = ",".join("?" * len(members))
        orgs = [r[0] for r in conn.execute(
            f"SELECT org_name FROM main.sites WHERE ipf_code IN ({marks}) "
            f"ORDER BY first_funded_year", members)]
        display[hub_id] = (slugify(h["label"]), h["label"], "; ".join(orgs),
                           h["city"], h["state"], members)
        fold.update({m: hub_id for m in members if m != hub_id})
    if not fold:
        return {}

    conn.execute("CREATE TEMP TABLE site_fold (ipf_code INTEGER PRIMARY KEY, hub_ipf INTEGER)")
    conn.executemany("INSERT INTO site_fold VALUES (?, ?)", fold.items())

    cols = [r[1] for r in conn.execute("PRAGMA main.table_info(grants)")]
    select = ", ".join("COALESCE(f.hub_ipf, g.ipf_code) AS ipf_code" if c == "ipf_code"
                       else f"g.{c}" for c in cols)
    conn.execute(f"CREATE TEMP TABLE grants AS SELECT {select} FROM main.grants g "
                 f"LEFT JOIN site_fold f ON f.ipf_code = g.ipf_code")
    conn.execute("CREATE UNIQUE INDEX temp.tmp_grants_core ON grants(core_project_num)")
    conn.execute("CREATE INDEX temp.tmp_grants_ipf ON grants(ipf_code)")

    conn.execute("CREATE TEMP TABLE sites AS SELECT * FROM main.sites "
                 "WHERE ipf_code NOT IN (SELECT ipf_code FROM site_fold)")
    conn.execute("CREATE UNIQUE INDEX temp.tmp_sites_ipf ON sites(ipf_code)")
    for hub_id, (slug, name, orgs, city, state, members) in display.items():
        marks = ",".join("?" * len(members))
        first, last = conn.execute(
            f"SELECT MIN(first_funded_year), MAX(last_funded_year) FROM main.sites "
            f"WHERE ipf_code IN ({marks})", members).fetchone()
        conn.execute(
            "UPDATE temp.sites SET slug=?, hub_name=?, org_name=?, city=?, state=?, "
            "  first_funded_year=?, last_funded_year=? WHERE ipf_code=?",
            (slug, name, orgs, city, state, first, last, hub_id))
        logger.info("Merged sites %s into one dashboard site: %s", members, name)

    # Recompute per-site metrics over the merged grants. The TEMP table
    # shadows main.site_metrics, so compute_site_metrics writes it, not ncats.db.
    conn.execute("CREATE TEMP TABLE site_metrics AS SELECT * FROM main.site_metrics WHERE 0")
    compute_site_metrics(conn)
    return fold

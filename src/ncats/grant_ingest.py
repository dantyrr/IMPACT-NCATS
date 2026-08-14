"""Transform RePORTER project records into ncats.db rows."""

import logging
import sqlite3

from src.ncats.config import HUB_ACTIVITY_CODES, EXCLUDED_ACTIVITY_CODES

logger = logging.getLogger(__name__)


def prune_excluded_grants(conn: sqlite3.Connection) -> dict:
    """Remove already-ingested grants whose mechanism is now excluded.

    Lets a scope change take effect without re-fetching everything. Deletes the
    grants and their dependent rows, then drops any site left with no grants.
    Idempotent.
    """
    codes = tuple(EXCLUDED_ACTIVITY_CODES)
    marks = ",".join("?" * len(codes))
    cores = [r[0] for r in conn.execute(
        f"SELECT core_project_num FROM grants WHERE activity_code IN ({marks})", codes)]
    if not cores:
        return {"grants": 0, "links": 0, "sites": 0}

    cmarks = ",".join("?" * len(cores))
    links = conn.execute(
        f"DELETE FROM grant_pubs WHERE core_project_num IN ({cmarks})", cores).rowcount
    conn.execute(f"DELETE FROM grant_pis   WHERE core_project_num IN ({cmarks})", cores)
    conn.execute(f"DELETE FROM grant_years WHERE core_project_num IN ({cmarks})", cores)
    grants = conn.execute(
        f"DELETE FROM grants WHERE core_project_num IN ({cmarks})", cores).rowcount

    # site_metrics references sites, so it must go first or the delete below
    # trips the foreign key. It is fully recomputed by compute_site_metrics().
    conn.execute(
        "DELETE FROM site_metrics WHERE ipf_code NOT IN "
        "(SELECT DISTINCT ipf_code FROM grants)")

    # Sites and investigators that now have nothing attached.
    sites = conn.execute(
        "DELETE FROM sites WHERE ipf_code NOT IN (SELECT DISTINCT ipf_code FROM grants)"
    ).rowcount
    conn.execute(
        "DELETE FROM investigators WHERE profile_id NOT IN "
        "(SELECT DISTINCT profile_id FROM grant_pis)")
    # Publications no longer linked to any surviving grant.
    conn.execute(
        "DELETE FROM pub_metrics WHERE pmid NOT IN (SELECT DISTINCT pmid FROM grant_pubs)")
    conn.commit()
    logger.info("Pruned %d excluded grants, %d links, %d orphan sites",
                grants, links, sites)
    return {"grants": grants, "links": links, "sites": sites}


def ingest_projects(conn: sqlite3.Connection, records: list[dict]) -> dict:
    """Insert/refresh sites, grants, grant_years, investigators, grant_pis.

    Idempotent: award totals and FY ranges are recomputed from grant_years,
    never accumulated in place.
    """
    counts = {"sites": 0, "grants": 0, "grant_years": 0, "investigators": 0,
              "excluded": 0}
    touched_cores = set()

    for rec in records:
        org = rec.get("organization") or {}
        ipf = org.get("org_ipf_code")
        core = rec.get("core_project_num")
        if not ipf or not core:
            logger.warning("Skipping record with no IPF or core project: %s", core)
            continue

        if rec.get("activity_code") in EXCLUDED_ACTIVITY_CODES:
            counts["excluded"] += 1
            continue

        cur = conn.execute(
            "INSERT INTO sites (ipf_code, org_name, city, state) VALUES (?,?,?,?) "
            "ON CONFLICT(ipf_code) DO UPDATE SET org_name=excluded.org_name",
            (ipf, org.get("org_name"), org.get("org_city"), org.get("org_state")),
        )
        counts["sites"] += cur.rowcount

        activity = rec.get("activity_code")
        is_hub = 1 if activity in HUB_ACTIVITY_CODES else 0
        cur = conn.execute(
            "INSERT INTO grants (core_project_num, ipf_code, activity_code, title, is_hub_award) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(core_project_num) DO UPDATE SET "
            "  ipf_code=excluded.ipf_code, activity_code=excluded.activity_code",
            (core, ipf, activity, rec.get("project_title"), is_hub),
        )
        counts["grants"] += cur.rowcount

        cur = conn.execute(
            "INSERT OR IGNORE INTO grant_years "
            "(core_project_num, fiscal_year, project_num, award_amount) VALUES (?,?,?,?)",
            (core, rec.get("fiscal_year"), rec.get("project_num") or core,
             rec.get("award_amount") or 0),
        )
        counts["grant_years"] += cur.rowcount
        touched_cores.add(core)

        for pi in rec.get("principal_investigators") or []:
            pid = pi.get("profile_id")
            if not pid:
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO investigators "
                "(profile_id, full_name, first_name, last_name) VALUES (?,?,?,?)",
                (pid, (pi.get("full_name") or "").strip(),
                 pi.get("first_name"), pi.get("last_name")),
            )
            counts["investigators"] += cur.rowcount
            conn.execute(
                "INSERT OR IGNORE INTO grant_pis "
                "(core_project_num, profile_id, is_contact_pi) VALUES (?,?,?)",
                (core, pid, 1 if pi.get("is_contact_pi") else 0),
            )

    # Recompute rollups from grant_years so re-runs stay correct.
    for core in touched_cores:
        conn.execute(
            "UPDATE grants SET "
            "  total_award_amount = (SELECT COALESCE(SUM(award_amount),0) "
            "                        FROM grant_years WHERE core_project_num=?),"
            "  first_fy = (SELECT MIN(fiscal_year) FROM grant_years WHERE core_project_num=?),"
            "  last_fy  = (SELECT MAX(fiscal_year) FROM grant_years WHERE core_project_num=?) "
            "WHERE core_project_num=?",
            (core, core, core, core),
        )

    conn.commit()
    return counts

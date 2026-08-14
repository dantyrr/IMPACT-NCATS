#!/usr/bin/env python3
"""Validate ncats.db integrity. Exit code 1 if any check fails."""

import sys, os, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ncats.schema import connect_ncats

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

MATCH_RATE_FLOOR = 0.95


def run_checks(conn) -> list[tuple[str, bool, str]]:
    """Return [(check_name, passed, detail)]."""
    results = []

    def q(sql):
        return conn.execute(sql).fetchone()[0]

    total = q("SELECT COUNT(*) FROM pub_metrics")
    matched = q("SELECT COUNT(*) FROM pub_metrics WHERE in_impact_db=1")
    rate = matched / total if total else 0.0
    results.append((
        "impact_db_match_rate",
        rate >= MATCH_RATE_FLOOR,
        f"{matched}/{total} = {rate:.1%} (floor {MATCH_RATE_FLOOR:.0%})",
    ))

    orphan_pubs = q(
        "SELECT COUNT(*) FROM grant_pubs WHERE core_project_num NOT IN "
        "(SELECT core_project_num FROM grants)")
    results.append(("no_orphan_grant_pubs", orphan_pubs == 0,
                    f"{orphan_pubs} links to unknown grants"))

    orphan_grants = q(
        "SELECT COUNT(*) FROM grants WHERE ipf_code NOT IN "
        "(SELECT ipf_code FROM sites)")
    results.append(("no_orphan_grants", orphan_grants == 0,
                    f"{orphan_grants} grants with unknown site"))

    no_slug = q("SELECT COUNT(*) FROM sites WHERE is_ctsa_hub=1 AND (slug IS NULL OR slug='')")
    results.append(("all_hubs_have_slug", no_slug == 0,
                    f"{no_slug} hubs missing a slug"))

    no_name = q("SELECT COUNT(*) FROM sites WHERE is_ctsa_hub=1 "
                "AND (hub_name IS NULL OR hub_name='')")
    results.append(("all_hubs_have_name", no_name == 0,
                    f"{no_name} hubs missing a display name"))

    dup_slug = q(
        "SELECT COUNT(*) FROM (SELECT slug FROM sites WHERE is_ctsa_hub=1 "
        "GROUP BY slug HAVING COUNT(*)>1)")
    results.append(("hub_slugs_unique", dup_slug == 0,
                    f"{dup_slug} duplicated hub slugs"))

    bad_hub_count = q("SELECT COUNT(*) FROM pub_metrics WHERE n_linked_hubs < 0")
    results.append(("n_linked_hubs_sane", bad_hub_count == 0,
                    f"{bad_hub_count} negative hub counts"))

    return results


if __name__ == "__main__":
    conn = connect_ncats()
    results = run_checks(conn)
    failed = 0
    for name, passed, detail in results:
        log.info("%-24s %-6s %s", name, "PASS" if passed else "FAIL", detail)
        failed += 0 if passed else 1
    conn.close()
    if failed:
        log.error("%d check(s) failed", failed)
        sys.exit(1)
    log.info("All checks passed.")

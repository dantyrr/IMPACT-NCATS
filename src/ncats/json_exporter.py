"""Export ncats.db to static JSON for the frontend."""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _write(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")))
    return path


def export_index(conn, out_dir) -> Path:
    """Top-level index: hub site list plus portfolio-wide totals."""
    out_dir = Path(out_dir)
    sites = [
        {"ipf_code": r[0], "slug": r[1], "hub_name": r[2], "org_name": r[3],
         "city": r[4], "state": r[5],
         "first_funded_year": r[6], "last_funded_year": r[7]}
        for r in conn.execute(
            "SELECT ipf_code, slug, hub_name, org_name, city, state, "
            "       first_funded_year, last_funded_year "
            "FROM sites WHERE is_ctsa_hub=1 ORDER BY hub_name")
    ]
    payload = {
        "sites": sites,
        "total_sites": len(sites),
        "total_grants": conn.execute("SELECT COUNT(*) FROM grants").fetchone()[0],
        "total_publications": conn.execute(
            "SELECT COUNT(DISTINCT pmid) FROM grant_pubs").fetchone()[0],
        "total_award_amount": conn.execute(
            "SELECT COALESCE(SUM(total_award_amount),0) FROM grants").fetchone()[0],
    }
    return _write(out_dir / "index.json", payload)


def export_sites(conn, out_dir) -> int:
    """One JSON file per CTSA hub site."""
    out_dir = Path(out_dir)
    n = 0
    for ipf, slug, hub_name, org, city, state in conn.execute(
        "SELECT ipf_code, slug, hub_name, org_name, city, state "
        "FROM sites WHERE is_ctsa_hub=1"
    ).fetchall():
        metrics = [
            {"year": r[0], "activity_group": r[1], "pub_count": r[2],
             "research_count": r[3], "citation_count": r[4], "mean_rcr": r[5],
             "mean_journal_if": r[6], "award_total": r[7],
             "cost_per_pub": r[8], "cost_per_citation": r[9]}
            for r in conn.execute(
                "SELECT year, activity_group, pub_count, research_count, "
                "       citation_count, mean_rcr, mean_journal_if, award_total, "
                "       cost_per_pub, cost_per_citation "
                "FROM site_metrics WHERE ipf_code=? ORDER BY year, activity_group",
                (ipf,))
        ]
        grants = [
            {"core_project_num": r[0], "activity_code": r[1], "title": r[2],
             "first_fy": r[3], "last_fy": r[4], "total_award_amount": r[5],
             "is_hub_award": r[6]}
            for r in conn.execute(
                "SELECT core_project_num, activity_code, title, first_fy, last_fy, "
                "       total_award_amount, is_hub_award "
                "FROM grants WHERE ipf_code=? ORDER BY activity_code, core_project_num",
                (ipf,))
        ]
        _write(out_dir / "sites" / f"{slug}.json", {
            "ipf_code": ipf, "slug": slug, "hub_name": hub_name,
            "org_name": org, "city": city, "state": state,
            "metrics": metrics, "grants": grants,
        })
        n += 1
    return n


def export_investigators(conn, out_dir) -> int:
    """One JSON file per PI, listing their grants and publication totals."""
    out_dir = Path(out_dir)
    n = 0
    for pid, name in conn.execute(
        "SELECT profile_id, full_name FROM investigators"
    ).fetchall():
        grants = [
            {"core_project_num": r[0], "activity_code": r[1], "title": r[2],
             "total_award_amount": r[3], "is_contact_pi": r[4]}
            for r in conn.execute(
                "SELECT g.core_project_num, g.activity_code, g.title, "
                "       g.total_award_amount, gp.is_contact_pi "
                "FROM grant_pis gp JOIN grants g "
                "  ON g.core_project_num = gp.core_project_num "
                "WHERE gp.profile_id=?", (pid,))
        ]
        pub_count, cites = conn.execute(
            "SELECT COUNT(DISTINCT pm.pmid), COALESCE(SUM(pm.citation_count),0) "
            "FROM grant_pis gp "
            "JOIN grant_pubs gpub ON gpub.core_project_num = gp.core_project_num "
            "JOIN pub_metrics pm ON pm.pmid = gpub.pmid "
            "WHERE gp.profile_id=?", (pid,)).fetchone()
        _write(out_dir / "investigators" / f"{pid}.json", {
            "profile_id": pid, "full_name": name, "grants": grants,
            "pub_count": pub_count, "citation_count": cites,
        })
        n += 1
    return n

"""Export ncats.db to static JSON for the frontend."""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _write(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")))
    return path


def _prune_dir(directory: Path, keep: set) -> int:
    """Delete JSON files in `directory` whose stem is not in `keep`.

    Without this, a record removed from the database leaves its exported file
    behind, and the stale file keeps being uploaded and served indefinitely.
    Returns the number of files deleted.
    """
    directory = Path(directory)
    if not directory.exists():
        return 0
    removed = 0
    for path in directory.glob("*.json"):
        if path.stem not in keep:
            path.unlink()
            removed += 1
    if removed:
        logger.info("Pruned %d stale files from %s", removed, directory)
    return removed


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
    investigators = [
        {"profile_id": r[0], "full_name": r[1], "n_grants": r[2]}
        for r in conn.execute(
            "SELECT i.profile_id, i.full_name, COUNT(gp.core_project_num) "
            "FROM investigators i "
            "JOIN grant_pis gp ON gp.profile_id = i.profile_id "
            "GROUP BY i.profile_id, i.full_name "
            "ORDER BY i.full_name")
    ]
    payload = {
        "sites": sites,
        "investigators": investigators,
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
    written = set()
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
        written.add(slug)
        n += 1
    _prune_dir(out_dir / "sites", written)
    return n


def export_publications(conn, out_dir, top_n: int = 250, min_pubs: int = 25) -> Path:
    """Top papers plus per-site publication rankings.

    Powers the Publications tab, which answers 'which site has the highest
    RCR' and 'what are the top papers' without drilling into each site.

    `min_pubs` guards the site rankings: a site with a handful of papers can
    post an extreme mean RCR that means nothing. Sites below the threshold are
    still returned, flagged `below_threshold`, so the UI can exclude them by
    default without hiding their existence.
    """
    out_dir = Path(out_dir)

    def papers(order_by):
        rows = conn.execute(f"""
            SELECT pm.pmid, pm.title, pm.journal_name, pm.pub_year, pm.rcr,
                   pm.citation_count, pm.is_research, pm.n_linked_hubs
            FROM pub_metrics pm
            WHERE pm.in_impact_db = 1 AND {order_by} IS NOT NULL
            ORDER BY {order_by} DESC
            LIMIT ?""", (top_n,)).fetchall()
        out = []
        for pmid, title, journal, year, rcr, cites, is_res, n_hubs in rows:
            sites = [r[0] for r in conn.execute("""
                SELECT DISTINCT s.hub_name
                FROM grant_pubs gp
                JOIN grants g ON g.core_project_num = gp.core_project_num
                JOIN sites  s ON s.ipf_code = g.ipf_code
                WHERE gp.pmid = ? AND s.is_ctsa_hub = 1
                ORDER BY s.hub_name""", (pmid,))]
            out.append({
                "pmid": pmid, "title": title, "journal": journal, "year": year,
                "rcr": rcr, "citations": cites, "is_research": is_res,
                "n_linked_hubs": n_hubs, "sites": sites,
            })
        return out

    rankings = []
    for row in conn.execute("""
        SELECT s.slug, s.hub_name, s.state,
               COUNT(DISTINCT pm.pmid)                                   AS pub_count,
               AVG(pm.rcr)                                               AS mean_rcr,
               SUM(pm.citation_count)                                    AS citation_count,
               AVG(CAST(pm.citation_count AS REAL))                      AS mean_citations,
               COUNT(DISTINCT CASE WHEN pm.rcr IS NOT NULL THEN pm.pmid END) AS rcr_n
        FROM sites s
        JOIN grants g       ON g.ipf_code = s.ipf_code
        JOIN grant_pubs gp  ON gp.core_project_num = g.core_project_num
        JOIN pub_metrics pm ON pm.pmid = gp.pmid
        WHERE s.is_ctsa_hub = 1 AND pm.in_impact_db = 1
        GROUP BY s.slug, s.hub_name, s.state"""):
        slug, hub, state, pubs, mean_rcr, cites, mean_cites, rcr_n = row
        rankings.append({
            "slug": slug, "hub_name": hub, "state": state,
            "pub_count": pubs, "mean_rcr": mean_rcr,
            "citation_count": cites, "mean_citations": mean_cites,
            "rcr_n": rcr_n,
            "below_threshold": 1 if (rcr_n or 0) < min_pubs else 0,
        })
    rankings.sort(key=lambda r: (r["mean_rcr"] is None, -(r["mean_rcr"] or 0)))

    return _write(out_dir / "publications.json", {
        "top_by_rcr": papers("pm.rcr"),
        "top_by_citations": papers("pm.citation_count"),
        "site_rankings": rankings,
        "min_pubs_threshold": min_pubs,
    })


def export_investigators(conn, out_dir) -> int:
    """One JSON file per PI, listing their grants and publication totals."""
    out_dir = Path(out_dir)
    n = 0
    written = set()
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
        written.add(str(pid))
        n += 1
    _prune_dir(out_dir / "investigators", written)
    return n

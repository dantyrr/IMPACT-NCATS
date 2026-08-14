"""Join grant data against impact.db and compute site-level metrics."""

import logging
import sqlite3

logger = logging.getLogger(__name__)

MECHANISM_LETTERS = {"R", "K", "U", "T", "F", "P"}


def activity_group(activity_code: str) -> str:
    """Collapse an activity code to its NIH mechanism letter (R, K, U, T, F, P)."""
    if not activity_code:
        return "other"
    first = activity_code[0].upper()
    return first if first in MECHANISM_LETTERS else "other"


def compute_n_linked_hubs(conn: sqlite3.Connection) -> None:
    """Populate pub_metrics with every linked PMID and its distinct hub count.

    Counts distinct CTSA hub SITES, not grants: two awards at one hub is one hub.
    """
    conn.execute("""
        INSERT INTO pub_metrics (pmid, n_linked_hubs)
        SELECT gp.pmid,
               COUNT(DISTINCT CASE WHEN s.is_ctsa_hub = 1 THEN s.ipf_code END)
        FROM grant_pubs gp
        JOIN grants g ON g.core_project_num = gp.core_project_num
        JOIN sites  s ON s.ipf_code = g.ipf_code
        GROUP BY gp.pmid
        ON CONFLICT(pmid) DO UPDATE SET n_linked_hubs = excluded.n_linked_hubs
    """)
    conn.commit()


def enrich_from_impact(conn, impact_conn, batch_size: int = 5000) -> dict:
    """Pull journal, year, research flag, and citation count from impact.db.

    impact_conn is read-only. PMIDs absent from impact.db keep in_impact_db = 0.
    """
    pmids = [r[0] for r in conn.execute("SELECT pmid FROM pub_metrics ORDER BY pmid")]
    stats = {"total": len(pmids), "matched": 0}

    for i in range(0, len(pmids), batch_size):
        batch = pmids[i: i + batch_size]
        marks = ",".join("?" * len(batch))

        rows = impact_conn.execute(
            f"SELECT p.pmid, p.journal_id, j.name, p.pub_year, p.is_research, p.title, "
            f"       (SELECT COUNT(*) FROM citations c WHERE c.cited_pmid = p.pmid) "
            f"FROM papers p LEFT JOIN journals j ON j.id = p.journal_id "
            f"WHERE p.pmid IN ({marks})",
            batch,
        ).fetchall()

        conn.executemany(
            "UPDATE pub_metrics SET journal_id=?, journal_name=?, pub_year=?, "
            "  is_research=?, title=?, citation_count=?, in_impact_db=1 WHERE pmid=?",
            [(jid, jname, yr, isr, title, cites, pmid)
             for pmid, jid, jname, yr, isr, title, cites in rows],
        )
        stats["matched"] += len(rows)
        conn.commit()
        logger.info("enriched %d/%d", min(i + batch_size, len(pmids)), len(pmids))

    stats["match_rate"] = stats["matched"] / stats["total"] if stats["total"] else 0.0
    return stats


def compute_site_metrics(conn: sqlite3.Connection) -> int:
    """Aggregate publication metrics per (site, year, activity_group).

    Full credit: a paper shared across hubs counts once in EACH hub's totals.
    """
    conn.execute("DELETE FROM site_metrics")
    conn.execute("""
        INSERT INTO site_metrics (
            ipf_code, year, activity_group, pub_count, research_count,
            citation_count, mean_rcr, mean_journal_if, award_total)
        SELECT g.ipf_code,
               pm.pub_year,
               CASE WHEN SUBSTR(g.activity_code,1,1) IN ('R','K','U','T','F','P')
                    THEN SUBSTR(g.activity_code,1,1) ELSE 'other' END,
               COUNT(DISTINCT pm.pmid),
               COUNT(DISTINCT CASE WHEN pm.is_research=1 THEN pm.pmid END),
               SUM(pm.citation_count),
               AVG(pm.rcr),
               AVG(pm.journal_rolling_if),
               0
        FROM grant_pubs gp
        JOIN grants g   ON g.core_project_num = gp.core_project_num
        JOIN pub_metrics pm ON pm.pmid = gp.pmid
        WHERE pm.pub_year IS NOT NULL
        GROUP BY 1, 2, 3
    """)

    # Award dollars for the same (site, year, mechanism) slice.
    conn.execute("""
        UPDATE site_metrics SET award_total = COALESCE((
            SELECT SUM(gy.award_amount)
            FROM grant_years gy
            JOIN grants g2 ON g2.core_project_num = gy.core_project_num
            WHERE g2.ipf_code = site_metrics.ipf_code
              AND gy.fiscal_year = site_metrics.year
              AND (CASE WHEN SUBSTR(g2.activity_code,1,1) IN ('R','K','U','T','F','P')
                        THEN SUBSTR(g2.activity_code,1,1) ELSE 'other' END)
                  = site_metrics.activity_group
        ), 0)
    """)
    conn.execute("""
        UPDATE site_metrics
        SET cost_per_pub = CASE WHEN pub_count > 0
                                THEN award_total * 1.0 / pub_count END,
            cost_per_citation = CASE WHEN citation_count > 0
                                     THEN award_total * 1.0 / citation_count END
    """)
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM site_metrics").fetchone()[0]

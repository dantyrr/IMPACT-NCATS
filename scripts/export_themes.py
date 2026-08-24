#!/usr/bin/env python3
"""Export translational and thematic data: site JSON for the web tab, plus a
per-paper CSV for independent analysis.

Two outputs:
  docs/data/themes.json   - aggregates for the site (theme x year, theme x site,
                            translational mix per site and year)
  exports/*.csv           - per-paper and per-site tables for R/Python

Translational grouping follows the Triangle of Biomedicine (Weber 2013), which
NIH computes from MeSH. A paper is assigned to whichever vertex dominates its
mix; papers with no clear majority are reported as "mixed" rather than being
forced into a vertex.

Usage:
    python scripts/export_themes.py
"""

import sys, os, csv, json, logging
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ncats.schema import connect_ncats
from src.ncats.config import WEBSITE_DATA_DIR, PROJECT_ROOT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

EXPORT_DIR = PROJECT_ROOT / "exports"

# A paper counts as a vertex when that vertex holds at least this share of the
# mix. Below it, the paper is "mixed" - honest about genuinely hybrid work
# rather than assigning it on a rounding error.
VERTEX_THRESHOLD = 0.5


def tri_class(human, animal, mol):
    if human is None:
        return None
    h, a, m = human or 0, animal or 0, mol or 0
    best = max(h, a, m)
    if best < VERTEX_THRESHOLD:
        return "mixed"
    return "human" if best == h else ("animal" if best == a else "molecular_cellular")


def main():
    conn = connect_ncats()
    conn.create_function("tri_class", 3, tri_class)
    WEBSITE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    themes = [
        {"theme_id": r[0], "label": r[1], "top_terms": json.loads(r[2] or "[]"),
         "size": r[3]}
        for r in conn.execute(
            "SELECT theme_id, label, top_terms, size FROM themes ORDER BY size DESC")
    ]
    log.info("themes: %d", len(themes))

    # Theme x year, portfolio-wide.
    theme_year = [
        {"theme_id": r[0], "year": r[1], "n": r[2]}
        for r in conn.execute("""
            SELECT pt.theme_id, pm.pub_year, COUNT(*)
            FROM pub_themes pt JOIN pub_metrics pm ON pm.pmid = pt.pmid
            WHERE pm.pub_year IS NOT NULL
            GROUP BY 1, 2 ORDER BY 1, 2""")
    ]

    # Theme x site: which hubs work on what.
    theme_site = [
        {"theme_id": r[0], "slug": r[1], "n": r[2]}
        for r in conn.execute("""
            SELECT pt.theme_id, s.slug, COUNT(DISTINCT pt.pmid)
            FROM pub_themes pt
            JOIN grant_pubs gp ON gp.pmid = pt.pmid
            JOIN grants g ON g.core_project_num = gp.core_project_num
            JOIN sites s ON s.ipf_code = g.ipf_code
            WHERE s.is_ctsa_hub = 1
            GROUP BY 1, 2""")
    ]

    # Translational mix per site per year.
    trans_site_year = [
        {"slug": r[0], "year": r[1], "tri": r[2], "n": r[3],
         "mean_apt": r[4], "clinical": r[5], "cited_by_clinical": r[6]}
        for r in conn.execute("""
            SELECT s.slug, pm.pub_year,
                   tri_class(pm.human, pm.animal, pm.molecular_cellular),
                   COUNT(DISTINCT pm.pmid), AVG(pm.apt),
                   SUM(CASE WHEN pm.is_clinical=1 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN pm.clin_citations>0 THEN 1 ELSE 0 END)
            FROM pub_metrics pm
            JOIN grant_pubs gp ON gp.pmid = pm.pmid
            JOIN grants g ON g.core_project_num = gp.core_project_num
            JOIN sites s ON s.ipf_code = g.ipf_code
            WHERE s.is_ctsa_hub = 1 AND pm.human IS NOT NULL
              AND pm.pub_year IS NOT NULL
            GROUP BY 1, 2, 3""")
    ]

    # Portfolio-wide translational mix per year.
    trans_year = [
        {"year": r[0], "tri": r[1], "n": r[2], "mean_apt": r[3]}
        for r in conn.execute("""
            SELECT pm.pub_year,
                   tri_class(pm.human, pm.animal, pm.molecular_cellular),
                   COUNT(*), AVG(pm.apt)
            FROM pub_metrics pm
            WHERE pm.human IS NOT NULL AND pm.pub_year IS NOT NULL
            GROUP BY 1, 2 ORDER BY 1""")
    ]

    coverage = dict(conn.execute("""
        SELECT 'total', COUNT(*) FROM pub_metrics WHERE in_impact_db=1
        UNION ALL SELECT 'with_abstract', COUNT(*) FROM pub_text
            WHERE abstract IS NOT NULL AND abstract != ''
        UNION ALL SELECT 'with_mesh', COUNT(*) FROM pub_text WHERE has_mesh=1
        UNION ALL SELECT 'with_theme', COUNT(*) FROM pub_themes
        UNION ALL SELECT 'with_translational', COUNT(*) FROM pub_metrics
            WHERE human IS NOT NULL"""))

    # MeSH coverage per year, so any MeSH-based figure can be normalised against
    # the indexed subset instead of the whole corpus.
    mesh_by_year = [
        {"year": r[0], "total": r[1], "with_mesh": r[2]}
        for r in conn.execute("""
            SELECT pm.pub_year, COUNT(*), SUM(COALESCE(pt.has_mesh,0))
            FROM pub_metrics pm LEFT JOIN pub_text pt ON pt.pmid = pm.pmid
            WHERE pm.in_impact_db=1 AND pm.pub_year IS NOT NULL
            GROUP BY 1 ORDER BY 1""")
    ]

    payload = {
        "themes": themes,
        "theme_year": theme_year,
        "theme_site": theme_site,
        "trans_site_year": trans_site_year,
        "trans_year": trans_year,
        "mesh_by_year": mesh_by_year,
        "coverage": coverage,
        "vertex_threshold": VERTEX_THRESHOLD,
    }
    out = WEBSITE_DATA_DIR / "themes.json"
    out.write_text(json.dumps(payload, separators=(",", ":")))
    log.info("wrote %s (%.1f MB)", out, out.stat().st_size / 1e6)

    # ---- per-paper CSV for independent analysis ----
    papers_csv = EXPORT_DIR / "ctsa_publications.csv"
    rows = conn.execute("""
        SELECT pm.pmid, pm.pub_year, pm.title, pm.journal_name,
               pm.is_research, pm.citation_count, pm.rcr,
               pm.human, pm.animal, pm.molecular_cellular,
               tri_class(pm.human, pm.animal, pm.molecular_cellular),
               pm.apt, pm.is_clinical, pm.clin_citations,
               pm.n_linked_hubs,
               th.theme_id, t.label,
               pt.has_mesh, pt.mesh_terms,
               (SELECT GROUP_CONCAT(DISTINCT s.hub_name)
                  FROM grant_pubs gp
                  JOIN grants g ON g.core_project_num = gp.core_project_num
                  JOIN sites s ON s.ipf_code = g.ipf_code
                 WHERE gp.pmid = pm.pmid AND s.is_ctsa_hub = 1)
        FROM pub_metrics pm
        LEFT JOIN pub_themes th ON th.pmid = pm.pmid
        LEFT JOIN themes t ON t.theme_id = th.theme_id
        LEFT JOIN pub_text pt ON pt.pmid = pm.pmid
        WHERE pm.in_impact_db = 1
    """)
    header = ["pmid", "pub_year", "title", "journal", "is_research",
              "citations", "rcr", "human", "animal", "molecular_cellular",
              "triangle_class", "apt", "is_clinical", "clinical_citations",
              "n_linked_hubs", "theme_id", "theme_label", "has_mesh",
              "mesh_terms", "ctsa_sites"]
    n = 0
    with open(papers_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            r = list(r)
            # MeSH stored as a JSON array; a semicolon list is friendlier in R/Excel.
            if r[18]:
                try:
                    r[18] = "; ".join(json.loads(r[18]))
                except (ValueError, TypeError):
                    r[18] = ""
            w.writerow(r)
            n += 1
    log.info("wrote %s (%d rows, %.1f MB)", papers_csv, n,
             papers_csv.stat().st_size / 1e6)

    # ---- per-site x year x translational-class summary ----
    site_csv = EXPORT_DIR / "ctsa_site_translational.csv"
    with open(site_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["site", "slug", "state", "year", "triangle_class",
                    "papers", "mean_apt", "clinical_papers",
                    "papers_cited_by_clinical"])
        for r in conn.execute("""
            SELECT s.hub_name, s.slug, s.state, pm.pub_year,
                   tri_class(pm.human, pm.animal, pm.molecular_cellular),
                   COUNT(DISTINCT pm.pmid), AVG(pm.apt),
                   SUM(CASE WHEN pm.is_clinical=1 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN pm.clin_citations>0 THEN 1 ELSE 0 END)
            FROM pub_metrics pm
            JOIN grant_pubs gp ON gp.pmid = pm.pmid
            JOIN grants g ON g.core_project_num = gp.core_project_num
            JOIN sites s ON s.ipf_code = g.ipf_code
            WHERE s.is_ctsa_hub=1 AND pm.human IS NOT NULL AND pm.pub_year IS NOT NULL
            GROUP BY 1,2,3,4,5 ORDER BY 1,4,5"""):
            w.writerow(r)
    log.info("wrote %s", site_csv)

    # ---- theme x site x year ----
    theme_csv = EXPORT_DIR / "ctsa_theme_by_site_year.csv"
    with open(theme_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["theme_id", "theme_label", "site", "slug", "year", "papers"])
        for r in conn.execute("""
            SELECT th.theme_id, t.label, s.hub_name, s.slug, pm.pub_year,
                   COUNT(DISTINCT th.pmid)
            FROM pub_themes th
            JOIN themes t ON t.theme_id = th.theme_id
            JOIN pub_metrics pm ON pm.pmid = th.pmid
            JOIN grant_pubs gp ON gp.pmid = th.pmid
            JOIN grants g ON g.core_project_num = gp.core_project_num
            JOIN sites s ON s.ipf_code = g.ipf_code
            WHERE s.is_ctsa_hub=1 AND pm.pub_year IS NOT NULL
            GROUP BY 1,2,3,4,5 ORDER BY 1,3,5"""):
            w.writerow(r)
    log.info("wrote %s", theme_csv)

    log.info("coverage: %s", coverage)
    conn.close()


if __name__ == "__main__":
    main()

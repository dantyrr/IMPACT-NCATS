#!/usr/bin/env python3
"""Export author affiliations for collaboration analysis, plus affiliation
coverage by publication year.

Two outputs:
  exports/author_affiliations.csv     - one row per author x affiliation, for
                                        VOSviewer / R. An author with no
                                        affiliation gets a single row with a
                                        blank affiliation, so coverage can be
                                        measured from the file alone.
  exports/author_coverage_by_year.csv - the coverage table logged below

pub_year comes from pub_metrics (impact.db) and falls back to the year in the
PubMed record for papers impact.db does not hold.

Coverage counts named (person) authors only; a group author has no
affiliation by construction and would otherwise make every consortium paper
look incomplete. Each paper falls in exactly one class:
  all         every person author has at least one affiliation
  first_only  first author affiliated, no co-author is (2+ person authors)
  partial     some but not all, other than first_only
  none        no person author affiliated

Usage:
    python scripts/export_author_affiliations.py
"""

import sys, os, csv, logging
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ncats.schema import connect_ncats
from src.ncats.config import PROJECT_ROOT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

EXPORT_DIR = PROJECT_ROOT / "exports"
CLASSES = ("all", "first_only", "partial", "none")

YEAR_SQL = "COALESCE(pm.pub_year, f.pub_year)"

AFFIL_COLUMNS = ["pmid", "pub_year", "n_authors", "position", "last_name", "fore_name",
                 "initials", "collective_name", "orcid", "affil_order", "affiliation"]


def classify(n_person, n_affil, first_affil):
    if n_person == 0:
        return None
    if n_affil == n_person:
        return "all"
    if n_affil == 0:
        return "none"
    if n_affil == 1 and first_affil:
        return "first_only"
    return "partial"


def write_affiliations_csv(conn, path):
    cur = conn.execute(f"""
        SELECT a.pmid, {YEAR_SQL}, f.n_authors, a.position, a.last_name, a.fore_name,
               a.initials, a.collective_name, a.orcid, af.affil_order, af.affiliation
        FROM pub_authors a
        JOIN pub_author_fetch f ON f.pmid = a.pmid
        LEFT JOIN pub_metrics pm ON pm.pmid = a.pmid
        LEFT JOIN pub_author_affils af ON af.pmid = a.pmid AND af.position = a.position
        ORDER BY a.pmid, a.position, af.affil_order""")
    n = 0
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(AFFIL_COLUMNS)
        for row in cur:
            w.writerow(row)
            n += 1
    return n


def coverage_by_year(conn):
    """Per publication year: papers, mean authors, and the share in each class."""
    per_paper = conn.execute(f"""
        SELECT {YEAR_SQL}, f.n_authors,
               SUM(a.collective_name IS NULL),
               SUM(a.collective_name IS NULL AND EXISTS (
                   SELECT 1 FROM pub_author_affils x
                   WHERE x.pmid = a.pmid AND x.position = a.position)),
               MAX(a.position = 1 AND EXISTS (
                   SELECT 1 FROM pub_author_affils x
                   WHERE x.pmid = a.pmid AND x.position = 1))
        FROM pub_authors a
        JOIN pub_author_fetch f ON f.pmid = a.pmid
        LEFT JOIN pub_metrics pm ON pm.pmid = a.pmid
        GROUP BY a.pmid""")

    by_year = defaultdict(lambda: {"papers": 0, "authors": 0, **{c: 0 for c in CLASSES}})
    for year, n_authors, n_person, n_affil, first_affil in per_paper:
        cls = classify(n_person, n_affil, bool(first_affil))
        if cls is None:
            continue
        y = by_year[year]
        y["papers"] += 1
        y["authors"] += n_authors
        y[cls] += 1

    out = []
    for year in sorted(by_year, key=lambda y: (y is None, y)):
        y = by_year[year]
        row = {"pub_year": year, "papers": y["papers"],
               "mean_authors": round(y["authors"] / y["papers"], 2)}
        for c in CLASSES:
            row[f"n_{c}"] = y[c]
            row[f"pct_{c}"] = round(100 * y[c] / y["papers"], 1)
        out.append(row)
    return out


def main():
    conn = connect_ncats()
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    path = EXPORT_DIR / "author_affiliations.csv"
    n = write_affiliations_csv(conn, path)
    log.info("wrote %s (%d rows)", path, n)

    rows = coverage_by_year(conn)
    cov_path = EXPORT_DIR / "author_coverage_by_year.csv"
    with open(cov_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    log.info("wrote %s", cov_path)

    log.info("%-7s %7s %8s %7s %8s %8s %6s",
             "year", "papers", "authors", "all%", "first%", "partial%", "none%")
    for r in rows:
        log.info("%-7s %7d %8.1f %7.1f %8.1f %8.1f %6.1f",
                 r["pub_year"] or "unknown", r["papers"], r["mean_authors"],
                 r["pct_all"], r["pct_first_only"], r["pct_partial"], r["pct_none"])
    conn.close()


if __name__ == "__main__":
    main()

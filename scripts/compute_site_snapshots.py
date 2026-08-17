#!/usr/bin/env python3
"""Compute monthly rolling citation rates per CTSA site.

Mirrors IMPACT's journal rolling citation rate, applied to each site's linked
publications. See src/ncats/site_snapshots.py for the formula.

Usage:
    python scripts/compute_site_snapshots.py
    python scripts/compute_site_snapshots.py --start-year 2012
"""

import sys, os, argparse, logging
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ncats.schema import connect_ncats, connect_impact_readonly
from src.ncats.site_snapshots import month_index, compute_site_series

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

BATCH = 5000


def fetch_site_papers(impact, pmids):
    """(month_index, is_research) for papers with a known publication month."""
    out, no_month = [], 0
    for i in range(0, len(pmids), BATCH):
        b = pmids[i:i + BATCH]
        marks = ",".join("?" * len(b))
        for pmid, y, m, is_res in impact.execute(
            f"SELECT pmid, pub_year, pub_month, is_research FROM papers "
            f"WHERE pmid IN ({marks})", b
        ):
            if not y or not m:
                no_month += 1
                continue
            out.append((pmid, month_index(y, m), is_res or 0))
    return out, no_month


def fetch_citation_events(impact, pmid_month, pmids):
    """(cited_paper_month_index, citing_month_index) for each citation event."""
    events = []
    for i in range(0, len(pmids), BATCH):
        b = pmids[i:i + BATCH]
        marks = ",".join("?" * len(b))
        for cited, cy, cm in impact.execute(
            f"SELECT cited_pmid, citing_year, citing_month FROM citations "
            f"WHERE cited_pmid IN ({marks})", b
        ):
            if not cy or not cm:
                continue
            p = pmid_month.get(cited)
            if p is None:
                continue
            events.append((p, month_index(cy, cm)))
    return events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-year", type=int, default=2012)
    args = ap.parse_args()

    conn = connect_ncats()
    impact = connect_impact_readonly()

    first_idx = month_index(args.start_year, 1)
    today = date.today()
    last_idx = month_index(today.year, today.month)

    sites = conn.execute(
        "SELECT ipf_code, hub_name FROM sites WHERE is_ctsa_hub=1 ORDER BY hub_name"
    ).fetchall()
    log.info("Computing rolling rates for %d sites, %s-01 to %s",
             len(sites), args.start_year, f"{today.year}-{today.month:02d}")

    conn.execute("DELETE FROM site_month_snapshots")
    total_rows = 0

    for n, (ipf, hub) in enumerate(sites, 1):
        pmids = [r[0] for r in conn.execute(
            "SELECT DISTINCT gp.pmid FROM grant_pubs gp "
            "JOIN grants g ON g.core_project_num = gp.core_project_num "
            "WHERE g.ipf_code = ?", (ipf,))]
        if not pmids:
            continue

        papers, no_month = fetch_site_papers(impact, pmids)
        if not papers:
            continue
        pmid_month = {pmid: idx for pmid, idx, _ in papers}
        events = fetch_citation_events(impact, pmid_month, pmids)

        series = compute_site_series(
            [(idx, is_res) for _, idx, is_res in papers], events, first_idx, last_idx)

        conn.executemany(
            "INSERT INTO site_month_snapshots "
            "(ipf_code, snapshot_month, rate_12m, rate_24m, rate_5yr, "
            " paper_count, citation_count) VALUES (?,?,?,?,?,?,?)",
            [(ipf, r["snapshot_month"], r["rate_12m"], r["rate_24m"], r["rate_5yr"],
              r["paper_count"], r["citation_count"]) for r in series])
        conn.commit()
        total_rows += len(series)
        log.info("[%d/%d] %-45s papers=%-6d events=%-8d months=%d%s",
                 n, len(sites), hub[:45], len(papers), len(events), len(series),
                 f"  ({no_month} without a pub month)" if no_month else "")

    log.info("DONE. %d snapshot rows.", total_rows)
    row = conn.execute(
        "SELECT snapshot_month, ROUND(rate_24m,2), paper_count FROM site_month_snapshots "
        "WHERE rate_24m IS NOT NULL ORDER BY snapshot_month DESC LIMIT 1").fetchone()
    if row:
        log.info("Most recent snapshot: %s  rate_24m=%s  papers=%s", *row)
    impact.close()
    conn.close()


if __name__ == "__main__":
    main()

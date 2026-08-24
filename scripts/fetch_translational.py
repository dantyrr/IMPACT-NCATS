#!/usr/bin/env python3
"""Populate iCite translational-science measures for grant-linked publications.

Beyond RCR, iCite exposes NIH's own translational indicators, all derived from
MeSH and available for essentially every indexed paper:

  human / animal / molecular_cellular : Triangle of Biomedicine mix (Weber 2013)
  x_coord / y_coord                   : position within that triangle
  apt                                 : Approximate Potential to Translate,
                                        NIH's predicted probability the paper
                                        will later be cited by clinical trials
                                        or guidelines
  is_clinical                         : the paper is itself a clinical article
  clin_citations                      : how many clinical articles cite it

Usage:
    python scripts/fetch_translational.py
    python scripts/fetch_translational.py --resume
"""

import sys, os, argparse, logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ncats.schema import connect_ncats
from src.ncats.icite_client import IciteClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

CHUNK = 2000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume", action="store_true",
                    help="Skip PMIDs that already have a triangle mix stored")
    args = ap.parse_args()

    conn = connect_ncats()
    q = "SELECT DISTINCT pmid FROM grant_pubs"
    if args.resume:
        q += " WHERE pmid NOT IN (SELECT pmid FROM pub_metrics WHERE human IS NOT NULL)"
    pmids = [r[0] for r in conn.execute(q)]
    log.info("Fetching translational measures for %d PMIDs", len(pmids))

    client = IciteClient()
    done = 0
    for i in range(0, len(pmids), CHUNK):
        batch = pmids[i: i + CHUNK]
        recs = client.fetch_records(batch)
        conn.executemany(
            "INSERT INTO pub_metrics (pmid, rcr, human, animal, molecular_cellular, "
            "  tri_x, tri_y, apt, is_clinical, clin_citations) "
            "VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(pmid) DO UPDATE SET "
            "  rcr=excluded.rcr, human=excluded.human, animal=excluded.animal, "
            "  molecular_cellular=excluded.molecular_cellular, tri_x=excluded.tri_x, "
            "  tri_y=excluded.tri_y, apt=excluded.apt, "
            "  is_clinical=excluded.is_clinical, clin_citations=excluded.clin_citations",
            [(p,
              (recs.get(p) or {}).get("relative_citation_ratio"),
              (recs.get(p) or {}).get("human"),
              (recs.get(p) or {}).get("animal"),
              (recs.get(p) or {}).get("molecular_cellular"),
              (recs.get(p) or {}).get("x_coord"),
              (recs.get(p) or {}).get("y_coord"),
              (recs.get(p) or {}).get("apt"),
              1 if (recs.get(p) or {}).get("is_clinical") else 0,
              (recs.get(p) or {}).get("clin_citations", 0))
             for p in batch],
        )
        conn.commit()
        done += len(batch)
        log.info("[%d/%d] translational rows written", done, len(pmids))

    for label, q in [
        ("with triangle mix", "SELECT COUNT(*) FROM pub_metrics WHERE human IS NOT NULL"),
        ("with APT", "SELECT COUNT(*) FROM pub_metrics WHERE apt IS NOT NULL"),
        ("clinical articles", "SELECT COUNT(*) FROM pub_metrics WHERE is_clinical=1"),
        ("cited by clinical work", "SELECT COUNT(*) FROM pub_metrics WHERE clin_citations>0"),
    ]:
        log.info("%-24s %s", label, conn.execute(q).fetchone()[0])
    conn.close()


if __name__ == "__main__":
    main()

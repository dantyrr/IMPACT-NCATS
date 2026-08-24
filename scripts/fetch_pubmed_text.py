#!/usr/bin/env python3
"""Fetch abstracts, MeSH terms, keywords and publication types from PubMed.

impact.db keeps only bibliographic fields, and the PubMed baseline XML was
deleted after it was built, so the text needed for thematic analysis has to come
from EFetch.

Coverage is not uniform and this matters for any trend analysis. Measured on a
stratified sample of this corpus:

    era        abstract   MeSH
    2012-2018    96.0%    94.0%
    2019-2022    92.0%    84.7%
    2023-2026    94.0%    75.3%

NIH indexes MeSH with a lag, so raw MeSH counts decline in recent years for
reasons that have nothing to do with research activity. Abstract coverage is
effectively flat, which is why themes are derived from abstracts rather than
MeSH. `has_mesh` is stored per paper so any MeSH-based figure can be normalised
against the indexed subset rather than the whole corpus.

Usage:
    python scripts/fetch_pubmed_text.py
    python scripts/fetch_pubmed_text.py --resume
"""

import sys, os, time, json, argparse, logging
import xml.etree.ElementTree as ET
import urllib.request
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ncats.schema import connect_ncats
from src.ncats.config import PUBMED_API_KEY, PUBMED_EMAIL

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
BATCH = 200
# NCBI allows 10 requests/sec with a key, 3 without.
RATE = 10.0 if PUBMED_API_KEY else 3.0


def parse_articles(xml_bytes):
    """Yield one record per PubmedArticle in an EFetch response."""
    root = ET.fromstring(xml_bytes)
    for art in root.findall(".//PubmedArticle"):
        pmid_el = art.find(".//MedlineCitation/PMID")
        if pmid_el is None or not (pmid_el.text or "").isdigit():
            continue
        pmid = int(pmid_el.text)

        # Structured abstracts split across several AbstractText elements,
        # each optionally labelled (BACKGROUND, METHODS, ...).
        parts = []
        for a in art.findall(".//Abstract/AbstractText"):
            text = "".join(a.itertext()).strip()
            if not text:
                continue
            label = a.get("Label")
            parts.append(f"{label}: {text}" if label else text)
        abstract = " ".join(parts)

        mesh, major = [], []
        for mh in art.findall(".//MeshHeading"):
            d = mh.find("DescriptorName")
            if d is None or not d.text:
                continue
            mesh.append(d.text)
            if d.get("MajorTopicYN") == "Y":
                major.append(d.text)
            # A qualifier can be the major topic even when the descriptor is not.
            elif any(q.get("MajorTopicYN") == "Y" for q in mh.findall("QualifierName")):
                major.append(d.text)

        keywords = [k.text.strip() for k in art.findall(".//Keyword")
                    if k.text and k.text.strip()]
        pub_types = [p.text for p in art.findall(".//PublicationType") if p.text]

        yield {
            "pmid": pmid, "abstract": abstract,
            "mesh_terms": mesh, "major_mesh": major,
            "keywords": keywords, "pub_types": pub_types,
        }


def fetch_batch(pmids, attempts=4):
    """POST to EFetch. IDs go in the body since a GET URL would overflow."""
    params = {"db": "pubmed", "id": ",".join(map(str, pmids)), "retmode": "xml"}
    if PUBMED_API_KEY:
        params["api_key"] = PUBMED_API_KEY
    if PUBMED_EMAIL:
        params["email"] = PUBMED_EMAIL
    data = urllib.parse.urlencode(params).encode()

    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(
                urllib.request.Request(EFETCH, data=data), timeout=180
            ) as resp:
                return resp.read()
        except Exception as e:
            if attempt == attempts:
                log.error("batch failed after %d attempts: %s", attempts, e)
                return None
            time.sleep(2 ** attempt)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume", action="store_true",
                    help="Skip PMIDs already fetched")
    ap.add_argument("--limit", type=int, help="Stop after N PMIDs (for testing)")
    args = ap.parse_args()

    conn = connect_ncats()
    q = ("SELECT DISTINCT pmid FROM grant_pubs "
         "WHERE pmid IN (SELECT pmid FROM pub_metrics WHERE in_impact_db=1)")
    if args.resume:
        q += " AND pmid NOT IN (SELECT pmid FROM pub_text WHERE fetched=1)"
    pmids = [r[0] for r in conn.execute(q)]
    if args.limit:
        pmids = pmids[:args.limit]

    log.info("Fetching PubMed text for %d PMIDs (rate %.0f/s, batch %d)",
             len(pmids), RATE, BATCH)

    interval = 1.0 / RATE
    last = 0.0
    done = missing = 0

    for i in range(0, len(pmids), BATCH):
        batch = pmids[i: i + BATCH]

        elapsed = time.time() - last
        if elapsed < interval:
            time.sleep(interval - elapsed)
        last = time.time()

        raw = fetch_batch(batch)
        if raw is None:
            continue
        try:
            records = list(parse_articles(raw))
        except ET.ParseError as e:
            log.error("XML parse error at offset %d: %s", i, e)
            continue

        conn.executemany(
            "INSERT INTO pub_text (pmid, abstract, mesh_terms, major_mesh, "
            "  keywords, pub_types, has_mesh, fetched) VALUES (?,?,?,?,?,?,?,1) "
            "ON CONFLICT(pmid) DO UPDATE SET abstract=excluded.abstract, "
            "  mesh_terms=excluded.mesh_terms, major_mesh=excluded.major_mesh, "
            "  keywords=excluded.keywords, pub_types=excluded.pub_types, "
            "  has_mesh=excluded.has_mesh, fetched=1",
            [(r["pmid"], r["abstract"], json.dumps(r["mesh_terms"]),
              json.dumps(r["major_mesh"]), json.dumps(r["keywords"]),
              json.dumps(r["pub_types"]), 1 if r["mesh_terms"] else 0)
             for r in records],
        )
        # Record a row even for PMIDs PubMed returned nothing for, so --resume
        # does not retry them forever.
        returned = {r["pmid"] for r in records}
        absent = [p for p in batch if p not in returned]
        if absent:
            missing += len(absent)
            conn.executemany(
                "INSERT OR IGNORE INTO pub_text (pmid, fetched) VALUES (?,1)",
                [(p,) for p in absent])
        conn.commit()

        done += len(batch)
        if (i // BATCH) % 25 == 0 or done >= len(pmids):
            log.info("[%d/%d] fetched (%d not returned by PubMed)",
                     done, len(pmids), missing)

    tot = conn.execute("SELECT COUNT(*) FROM pub_text WHERE fetched=1").fetchone()[0]
    for label, sql in [
        ("with abstract", "SELECT COUNT(*) FROM pub_text WHERE abstract IS NOT NULL AND abstract!=''"),
        ("with MeSH", "SELECT COUNT(*) FROM pub_text WHERE has_mesh=1"),
        ("with keywords", "SELECT COUNT(*) FROM pub_text WHERE keywords NOT IN ('[]','') AND keywords IS NOT NULL"),
    ]:
        n = conn.execute(sql).fetchone()[0]
        log.info("%-16s %7d  (%.1f%% of %d)", label, n, 100 * n / tot if tot else 0, tot)
    conn.close()


if __name__ == "__main__":
    main()

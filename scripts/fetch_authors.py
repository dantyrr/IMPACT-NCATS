#!/usr/bin/env python3
"""Fetch every author, ORCID and affiliation of every NCATS-linked paper.

impact.db and pubmed_bulk.db keep only first and last author, and the PubMed
baseline XML was not kept, so the full byline has to come from EFetch. This is
the input for measuring collaboration between CTSA hubs.

Affiliation strings are stored exactly as PubMed records them, one row per
AffiliationInfo element. Matching them to institutions is a separate step.

PubMed recorded only the first author's affiliation before about 2014, so
papers from 2012-2013 will mostly lack co-author affiliations even after this
fetch. That is a property of the source, not a gap in the fetch.

InvestigatorList (named members of a collaborating group) is not part of the
byline and is not stored. A group author appears as one row with
collective_name set.

PMIDs are processed in a fixed shuffled order, so --limit gives a sample spread
across years rather than the oldest papers.

Usage:
    python scripts/fetch_authors.py --limit 2000   # trial run
    python scripts/fetch_authors.py --resume
"""

import sys, os, re, time, random, argparse, logging
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ncats.schema import connect_ncats
from scripts.fetch_pubmed_text import fetch_batch, BATCH, RATE

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

SHUFFLE_SEED = 20261017
ORCID_RE = re.compile(r"(\d{4})-?(\d{4})-?(\d{4})-?(\d{3}[\dX])$", re.IGNORECASE)


def normalize_orcid(raw):
    """Reduce the forms PubMed uses (bare, URL, unhyphenated) to 0000-0000-0000-000X."""
    m = ORCID_RE.search(re.sub(r"\s", "", raw or ""))
    if not m:
        return None
    return "-".join(m.groups()).upper()


def _text(el):
    """All text inside an element, including inline markup like <i>."""
    if el is None:
        return None
    return "".join(el.itertext()).strip() or None


def _year(date_el):
    if date_el is None:
        return None
    y = (date_el.findtext("Year") or "").strip()
    if y.isdigit():
        return int(y)
    # MedlineDate is free text such as "2013 Jan-Feb" or "2012-2013".
    m = re.search(r"\d{4}", date_el.findtext("MedlineDate") or "")
    return int(m.group(0)) if m else None


def _parse_author(a, position):
    return {
        "position": position,
        "last_name": _text(a.find("LastName")),
        "fore_name": _text(a.find("ForeName")),
        "initials": _text(a.find("Initials")),
        "collective_name": _text(a.find("CollectiveName")),
        "orcid": next((o for o in (normalize_orcid(i.text)
                                   for i in a.findall("Identifier[@Source='ORCID']"))
                       if o), None),
        "affiliations": [t for t in (_text(ai.find("Affiliation"))
                                     for ai in a.findall("AffiliationInfo")) if t],
    }


def parse_authors(xml_bytes):
    """Yield {pmid, pub_year, authors} for each article or book in an EFetch response."""
    root = ET.fromstring(xml_bytes)
    for art in root:
        if art.tag == "PubmedArticle":
            pmid_text = art.findtext("MedlineCitation/PMID")
            author_list = art.find("MedlineCitation/Article/AuthorList")
            pub_year = (_year(art.find("MedlineCitation/Article/Journal/JournalIssue/PubDate"))
                        or _year(art.find("MedlineCitation/Article/ArticleDate")))
        elif art.tag == "PubmedBookArticle":
            pmid_text = art.findtext("BookDocument/PMID")
            # A chapter's own authors sit on BookDocument; the Book carries the
            # volume's editors, who are not authors of the chapter.
            lists = art.findall("BookDocument/AuthorList") + art.findall("BookDocument/Book/AuthorList")
            author_list = next((l for l in lists if l.get("Type") != "editors"), None)
            pub_year = _year(art.find("BookDocument/Book/PubDate"))
        else:
            continue
        if not (pmid_text or "").strip().isdigit():
            continue

        authors = []
        for a in (author_list.findall("Author") if author_list is not None else []):
            # ValidYN="N" is PubMed's record of a name that was later corrected;
            # the corrected entry is also present.
            if a.get("ValidYN") == "N":
                continue
            authors.append(_parse_author(a, len(authors) + 1))

        yield {"pmid": int(pmid_text), "pub_year": pub_year, "authors": authors}


def store_batch(conn, requested, records):
    """Replace author rows for each returned PMID and mark every requested PMID
    as processed. Deleting before inserting keeps a re-fetch idempotent even when
    PubMed has since shortened or reordered an author list."""
    records = list({r["pmid"]: r for r in records}.values())
    returned = {r["pmid"] for r in records}
    keys = [(p,) for p in returned]
    with conn:
        conn.executemany("DELETE FROM pub_author_affils WHERE pmid=?", keys)
        conn.executemany("DELETE FROM pub_authors WHERE pmid=?", keys)
        conn.executemany(
            "INSERT INTO pub_authors (pmid, position, last_name, fore_name, initials, "
            "  collective_name, orcid) VALUES (?,?,?,?,?,?,?)",
            [(r["pmid"], a["position"], a["last_name"], a["fore_name"], a["initials"],
              a["collective_name"], a["orcid"])
             for r in records for a in r["authors"]])
        conn.executemany(
            "INSERT INTO pub_author_affils (pmid, position, affil_order, affiliation) "
            "VALUES (?,?,?,?)",
            [(r["pmid"], a["position"], k, text)
             for r in records for a in r["authors"]
             for k, text in enumerate(a["affiliations"], start=1)])
        conn.executemany(
            "INSERT INTO pub_author_fetch (pmid, returned, n_authors, pub_year) "
            "VALUES (?,1,?,?) ON CONFLICT(pmid) DO UPDATE SET returned=1, "
            "  n_authors=excluded.n_authors, pub_year=excluded.pub_year",
            [(r["pmid"], len(r["authors"]), r["pub_year"]) for r in records])
        # Record PMIDs PubMed returned nothing for, so --resume does not retry
        # them forever. OR IGNORE keeps an earlier successful fetch intact.
        absent = [(p,) for p in requested if p not in returned]
        conn.executemany(
            "INSERT OR IGNORE INTO pub_author_fetch (pmid, returned) VALUES (?,0)", absent)
    return len(returned), len(absent)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume", action="store_true",
                    help="Skip PMIDs already processed")
    ap.add_argument("--limit", type=int, help="Stop after N PMIDs (trial run)")
    args = ap.parse_args()

    conn = connect_ncats()
    pmids = [r[0] for r in conn.execute("SELECT DISTINCT pmid FROM grant_pubs ORDER BY pmid")]
    random.Random(SHUFFLE_SEED).shuffle(pmids)
    if args.resume:
        seen = {r[0] for r in conn.execute("SELECT pmid FROM pub_author_fetch")}
        pmids = [p for p in pmids if p not in seen]
    if args.limit:
        pmids = pmids[:args.limit]

    log.info("Fetching authors for %d PMIDs (rate %.0f/s, batch %d)",
             len(pmids), RATE, BATCH)

    interval = 1.0 / RATE
    last = 0.0
    done = missing = failed = 0
    start = time.time()

    for i in range(0, len(pmids), BATCH):
        batch = pmids[i: i + BATCH]

        elapsed = time.time() - last
        if elapsed < interval:
            time.sleep(interval - elapsed)
        last = time.time()

        # A failed or unparseable batch is left unmarked so --resume retries it.
        raw = fetch_batch(batch)
        if raw is None:
            failed += len(batch)
            continue
        try:
            records = list(parse_authors(raw))
        except ET.ParseError as e:
            log.error("XML parse error at offset %d: %s", i, e)
            failed += len(batch)
            continue

        _, absent = store_batch(conn, batch, records)
        missing += absent
        done += len(batch)
        if (i // BATCH) % 25 == 0 or i + BATCH >= len(pmids):
            rate = done / (time.time() - start)
            log.info("[%d/%d] fetched (%d not returned, %d failed) ~%.0f min left",
                     done, len(pmids), missing, failed,
                     (len(pmids) - done - failed) / rate / 60 if rate else 0)

    q = lambda sql: conn.execute(sql).fetchone()[0]
    log.info("processed PMIDs     %8d  (%d returned by PubMed)",
             q("SELECT COUNT(*) FROM pub_author_fetch"),
             q("SELECT COUNT(*) FROM pub_author_fetch WHERE returned=1"))
    log.info("authors             %8d  (%d with ORCID, %d collective)",
             q("SELECT COUNT(*) FROM pub_authors"),
             q("SELECT COUNT(*) FROM pub_authors WHERE orcid IS NOT NULL"),
             q("SELECT COUNT(*) FROM pub_authors WHERE collective_name IS NOT NULL"))
    log.info("affiliation strings %8d", q("SELECT COUNT(*) FROM pub_author_affils"))
    if failed:
        log.warning("%d PMIDs failed; re-run with --resume to retry them", failed)
    conn.close()


if __name__ == "__main__":
    main()

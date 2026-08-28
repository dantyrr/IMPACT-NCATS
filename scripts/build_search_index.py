#!/usr/bin/env python3
"""Build a static full-text search index over linked publications.

The site has no backend, so search has to run in the browser. Shipping the
abstracts themselves is not an option (228 MB), and a single combined index is
too heavy to load up front (~20 MB gzipped). Instead the postings are sharded by
the first two characters of each term and fetched on demand: the median shard is
about 1 KB, so a three-word query pulls a couple of kilobytes rather than the
whole index.

Two posting sets are kept per term:

  meta/  title, MeSH descriptors and author keywords
  abst/  abstract text

They are separate so a hit in the title or MeSH can be scored above a passing
mention in an abstract, without storing a weight against every posting.

A document store carries what the results table needs. It is columnar rather
than a list of objects (no repeated keys) and dictionary-encodes journals and
site names, which brings it to roughly 6 MB gzipped for 136k papers. It loads
once, when search is first used.

Outputs, all under docs/data/search/:
    manifest.json          shard list, doc count, field weights
    docs.json              columnar document store
    meta/<prefix>.json     postings for title/MeSH/keywords
    abst/<prefix>.json     postings for abstracts

Usage:
    python scripts/build_search_index.py
"""

import sys, os, re, json, logging, collections
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ncats.schema import connect_ncats
from src.ncats.config import WEBSITE_DATA_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

OUT = WEBSITE_DATA_DIR / "search"

# Function words plus the scaffolding of a structured abstract. These carry no
# topical signal and would otherwise dominate the largest shards.
STOP = set("""
a an the of and or in to for with on is are was were be been being by that this these those from as
at it its their they them there we our us he she his her which who whom whose has have had not no
nor than then so such into using used use both each per within across among when where while about
over under only very much many some any all one two three due new also can could may might will
would should study studies patients patient results conclusions conclusion background methods
method objective objectives purpose design significant significantly associated association between
during after before more most other others however therefore thus although though because if but
what how why does did do done here found find shows show shown suggest suggests including included
compared comparison versus vs group groups participants subjects cohort data analysis analyses
""".split())

TOKEN = re.compile(r"[a-z][a-z0-9]{2,}")
MIN_DF = 3          # a term must appear in at least this many documents
SHARD_CHARS = 2     # postings sharded on the first two characters of the term


def tokenize(text):
    return {t for t in TOKEN.findall((text or "").lower()) if t not in STOP}


def encode(ids):
    """Delta-encode ascending doc ids as hex, which roughly halves the payload."""
    out, prev = [], 0
    for i in ids:
        out.append(format(i - prev, "x"))
        prev = i
    return ",".join(out)


def write_shards(postings, subdir):
    """Group postings by term prefix and write one file per prefix."""
    shards = collections.defaultdict(dict)
    for term, ids in postings.items():
        shards[term[:SHARD_CHARS]][term] = encode(sorted(ids))

    d = OUT / subdir
    d.mkdir(parents=True, exist_ok=True)
    for existing in d.glob("*.json"):
        existing.unlink()          # stale shards would otherwise be served forever

    total = 0
    for prefix, terms in shards.items():
        # Prefixes are alphanumeric by construction, so they are safe filenames.
        path = d / f"{prefix}.json"
        path.write_text(json.dumps(terms, separators=(",", ":")))
        total += path.stat().st_size
    log.info("%s: %d shards, %d terms, %.1f MB on disk",
             subdir, len(shards), len(postings), total / 1e6)
    return sorted(shards)


def main():
    conn = connect_ncats()
    OUT.mkdir(parents=True, exist_ok=True)

    log.info("Loading corpus...")
    rows = conn.execute("""
        SELECT pm.pmid, pm.title, pm.pub_year, pm.journal_name,
               pm.citation_count, pm.rcr, pm.apt, pm.is_clinical,
               pm.human, pm.animal, pm.molecular_cellular,
               pt.abstract, pt.mesh_terms, pt.keywords,
               th.theme_id
        FROM pub_text pt
        JOIN pub_metrics pm ON pm.pmid = pt.pmid
        LEFT JOIN pub_themes th ON th.pmid = pt.pmid
        WHERE pm.in_impact_db = 1
        ORDER BY pm.pmid""").fetchall()
    log.info("documents: %d", len(rows))

    # Sites per paper, so results can be filtered by hub.
    site_of = collections.defaultdict(set)
    for pmid, slug in conn.execute("""
        SELECT DISTINCT gp.pmid, s.slug
        FROM grant_pubs gp
        JOIN grants g ON g.core_project_num = gp.core_project_num
        JOIN sites s ON s.ipf_code = g.ipf_code
        WHERE s.is_ctsa_hub = 1"""):
        site_of[pmid].add(slug)

    journals, journal_idx = [], {}
    slugs, slug_idx = [], {}

    def intern(value, store, index):
        if value not in index:
            index[value] = len(store)
            store.append(value)
        return index[value]

    meta_post = collections.defaultdict(list)
    abst_post = collections.defaultdict(list)

    docs = {"pmid": [], "title": [], "year": [], "journal": [], "cites": [],
            "rcr": [], "apt": [], "clinical": [], "tri": [], "theme": [], "sites": []}

    def tri_class(h, a, m):
        if h is None:
            return None
        best = max(h or 0, a or 0, m or 0)
        if best < 0.5:
            return 3                      # mixed
        return 0 if best == (h or 0) else (1 if best == (a or 0) else 2)

    for i, r in enumerate(rows):
        (pmid, title, year, journal, cites, rcr, apt, clinical,
         human, animal, mol, abstract, mesh, kw, theme) = r

        mesh_l = json.loads(mesh or "[]")
        kw_l = json.loads(kw or "[]")

        for t in tokenize(f"{title or ''} {' '.join(mesh_l)} {' '.join(kw_l)}"):
            meta_post[t].append(i)
        for t in tokenize(abstract or ""):
            abst_post[t].append(i)

        docs["pmid"].append(pmid)
        docs["title"].append((title or "")[:200])
        docs["year"].append(year)
        docs["journal"].append(intern(journal or "", journals, journal_idx))
        docs["cites"].append(cites or 0)
        docs["rcr"].append(None if rcr is None else round(rcr, 2))
        docs["apt"].append(None if apt is None else round(apt, 2))
        docs["clinical"].append(1 if clinical else 0)
        docs["tri"].append(tri_class(human, animal, mol))
        docs["theme"].append(theme)
        docs["sites"].append([intern(s, slugs, slug_idx)
                              for s in sorted(site_of.get(pmid, ()))])

    meta_post = {t: v for t, v in meta_post.items() if len(v) >= MIN_DF}
    abst_post = {t: v for t, v in abst_post.items() if len(v) >= MIN_DF}

    meta_shards = write_shards(meta_post, "meta")
    abst_shards = write_shards(abst_post, "abst")

    docs["journals"] = journals
    docs["slugs"] = slugs
    docs_path = OUT / "docs.json"
    docs_path.write_text(json.dumps(docs, separators=(",", ":")))
    log.info("docs.json: %.1f MB (%d journals, %d sites)",
             docs_path.stat().st_size / 1e6, len(journals), len(slugs))

    manifest = {
        "n_docs": len(rows),
        "shard_chars": SHARD_CHARS,
        "min_df": MIN_DF,
        "meta_shards": meta_shards,
        "abst_shards": abst_shards,
        "meta_terms": len(meta_post),
        "abst_terms": len(abst_post),
        # Title/MeSH/keyword hits outrank a passing mention in an abstract.
        "weights": {"meta": 3.0, "abst": 1.0},
        "stopwords": sorted(STOP),
        "tri_labels": ["human", "animal", "molecular_cellular", "mixed"],
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, separators=(",", ":")))
    log.info("manifest: %d meta shards, %d abstract shards",
             len(meta_shards), len(abst_shards))
    conn.close()


if __name__ == "__main__":
    main()

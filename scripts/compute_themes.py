#!/usr/bin/env python3
"""Derive research themes from publication abstracts by embedding + clustering.

Why abstracts rather than MeSH: NIH indexes MeSH with a multi-year lag, so MeSH
coverage in this corpus falls from 94% (2012-2018) to 75% (2023-2026). Any
MeSH-frequency trend therefore shows every theme declining in recent years for
purely administrative reasons. Abstract coverage is flat at 92-96%, so themes
built from abstracts give trend lines that reflect research activity rather than
indexing backlog.

Pipeline:
  1. embed  title + abstract with a biomedical sentence encoder
  2. reduce with UMAP (cosine) to a low-dimensional space
  3. cluster with HDBSCAN, which leaves genuinely unlike papers unassigned
     instead of forcing every paper into a theme
  4. label each cluster with class-based TF-IDF: terms that distinguish this
     cluster from the others, not merely terms that are frequent in it

Embeddings are cached to data/embeddings.npy so clustering can be re-run with
different parameters without paying for the encode again.

Usage:
    python scripts/compute_themes.py                      # full run
    python scripts/compute_themes.py --limit 5000         # quick trial
    python scripts/compute_themes.py --min-cluster-size 300
    python scripts/compute_themes.py --recluster          # reuse cached vectors
"""

import sys, os, json, argparse, logging, re
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from src.ncats.schema import connect_ncats
from src.ncats.config import DATA_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DEFAULT_MODEL = "NeuML/pubmedbert-base-embeddings"
EMB_PATH = DATA_DIR / "embeddings.npy"
PMID_PATH = DATA_DIR / "embedding_pmids.npy"

# Words that are frequent in biomedical abstracts but say nothing about topic.
# Without these, most cluster labels come out as "study patients results".
BOILERPLATE = {
    "study", "studies", "patients", "patient", "results", "conclusions",
    "background", "methods", "objective", "objectives", "purpose", "design",
    "significant", "significantly", "associated", "association", "compared",
    "conclusion", "findings", "data", "analysis", "research", "aim", "aims",
    "outcomes", "outcome", "using", "used", "use", "based", "may", "also",
    "however", "cohort", "group", "groups", "participants", "subjects",
    "increased", "decreased", "higher", "lower", "risk", "years", "year",
    "clinical", "trial", "trials", "health", "care", "effect", "effects",
    "treatment", "treated", "level", "levels", "high", "low", "total",
    "median", "mean", "ci", "95", "p", "n", "vs", "among", "including",
}


def load_corpus(conn, limit=None):
    """Papers with enough text to be embedded meaningfully."""
    q = """
        SELECT pt.pmid, pm.title, pt.abstract
        FROM pub_text pt
        JOIN pub_metrics pm ON pm.pmid = pt.pmid
        WHERE pt.abstract IS NOT NULL AND LENGTH(pt.abstract) > 200
        ORDER BY pt.pmid
    """
    if limit:
        q += f" LIMIT {int(limit)}"
    rows = conn.execute(q).fetchall()
    pmids = np.array([r[0] for r in rows], dtype=np.int64)
    # Title carries a lot of topical signal; abstract is truncated because the
    # encoder only reads the first few hundred tokens anyway.
    texts = [f"{(r[1] or '').strip()}. {(r[2] or '')[:1500]}" for r in rows]
    return pmids, texts


def embed(texts, model_name, batch_size=128):
    from sentence_transformers import SentenceTransformer
    import torch

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    log.info("Encoding %d documents with %s on %s", len(texts), model_name, device)
    model = SentenceTransformer(model_name, device=device)
    return model.encode(
        texts, batch_size=batch_size, show_progress_bar=True,
        convert_to_numpy=True, normalize_embeddings=True,
    ).astype(np.float32)


def cluster(vectors, min_cluster_size, n_components=5, seed=42):
    import umap
    import hdbscan

    log.info("UMAP: %d x %d -> %d dims", *vectors.shape, n_components)
    reduced = umap.UMAP(
        n_neighbors=15, n_components=n_components, min_dist=0.0,
        metric="cosine", random_state=seed, verbose=True,
    ).fit_transform(vectors)

    log.info("HDBSCAN: min_cluster_size=%d", min_cluster_size)
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=10,
        metric="euclidean",
        cluster_selection_method="eom",
        prediction_data=True,
    )
    labels = clusterer.fit_predict(reduced)
    probs = clusterer.probabilities_
    return labels, probs


def label_clusters(texts, labels, top_n=8):
    """Class-based TF-IDF: which terms set this cluster apart from the rest."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    ids = sorted({int(l) for l in labels if l != -1})
    if not ids:
        return {}

    # One pseudo-document per cluster.
    joined = {c: [] for c in ids}
    for text, lab in zip(texts, labels):
        if lab != -1:
            joined[int(lab)].append(text)
    docs = [" ".join(joined[c]) for c in ids]

    stop = "english"
    vec = TfidfVectorizer(
        stop_words=stop, max_features=60000, ngram_range=(1, 2),
        min_df=1, sublinear_tf=True,
    )
    matrix = vec.fit_transform(docs)
    vocab = np.array(vec.get_feature_names_out())

    out = {}
    for row, cid in enumerate(ids):
        scores = matrix[row].toarray().ravel()
        order = scores.argsort()[::-1]
        terms = []
        for idx in order:
            term = vocab[idx]
            # Drop boilerplate and pure numbers, including inside bigrams.
            words = term.split()
            if any(w in BOILERPLATE for w in words):
                continue
            if any(re.fullmatch(r"[\d.]+", w) for w in words):
                continue
            if len(term) < 3:
                continue
            terms.append(term)
            if len(terms) >= top_n:
                break
        out[cid] = terms
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--min-cluster-size", type=int, default=250)
    ap.add_argument("--recluster", action="store_true",
                    help="Reuse cached embeddings and only redo clustering")
    args = ap.parse_args()

    conn = connect_ncats()
    pmids, texts = load_corpus(conn, args.limit)
    log.info("Corpus: %d papers with an abstract over 200 characters", len(pmids))
    if len(pmids) < 100:
        log.error("Too few papers to cluster. Has fetch_pubmed_text.py finished?")
        sys.exit(1)

    if args.recluster and EMB_PATH.exists():
        vectors = np.load(EMB_PATH)
        cached_pmids = np.load(PMID_PATH)
        if len(cached_pmids) != len(pmids) or not np.array_equal(cached_pmids, pmids):
            log.warning("Cached embeddings do not match the current corpus; re-encoding")
            vectors = embed(texts, args.model)
            np.save(EMB_PATH, vectors); np.save(PMID_PATH, pmids)
        else:
            log.info("Reusing cached embeddings %s", vectors.shape)
    else:
        vectors = embed(texts, args.model)
        np.save(EMB_PATH, vectors)
        np.save(PMID_PATH, pmids)
        log.info("Cached embeddings to %s", EMB_PATH)

    labels, probs = cluster(vectors, args.min_cluster_size)
    n_themes = len({int(l) for l in labels if l != -1})
    n_noise = int((labels == -1).sum())
    log.info("Themes: %d | unassigned: %d (%.1f%%)",
             n_themes, n_noise, 100 * n_noise / len(labels))

    terms = label_clusters(texts, labels)

    conn.execute("DELETE FROM pub_themes")
    conn.execute("DELETE FROM themes")
    conn.executemany(
        "INSERT INTO pub_themes (pmid, theme_id, theme_prob) VALUES (?,?,?)",
        [(int(p), int(l), float(pr)) for p, l, pr in zip(pmids, labels, probs)
         if l != -1])
    sizes = {c: int((labels == c).sum()) for c in {int(l) for l in labels if l != -1}}
    conn.executemany(
        "INSERT INTO themes (theme_id, label, top_terms, size) VALUES (?,?,?,?)",
        [(c, ", ".join(terms.get(c, [])[:4]), json.dumps(terms.get(c, [])), sizes[c])
         for c in sorted(sizes)])
    conn.commit()

    log.info("Largest themes:")
    for cid, size, label in conn.execute(
        "SELECT theme_id, size, label FROM themes ORDER BY size DESC LIMIT 15"
    ):
        log.info("  %5d papers  [%3d]  %s", size, cid, label)
    conn.close()


if __name__ == "__main__":
    main()

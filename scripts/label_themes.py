#!/usr/bin/env python3
"""Give each theme a readable name from MeSH, and score how coherent it is.

Clusters were labelled with class-based TF-IDF, which selects the terms that
most *distinguish* a cluster. That optimises for contrast rather than
recognisability, so it surfaced rare acronyms and cohort names - "slicc, mrss,
npsle" for what is plainly lupus and rheumatoid arthritis, "masala" for a South
Asian cardiovascular cohort. Distinctive, but unreadable.

MeSH is a curated vocabulary of human-readable disease and method names, and we
already hold it for 124,532 papers. Scoring each descriptor by how enriched it
is inside a cluster relative to the rest of the corpus produces names a domain
reader recognises immediately.

Enrichment is log-odds weighted by sqrt(count), so a term must be both
disproportionately common in the cluster and attested often enough to trust; a
term appearing in three papers cannot name a thousand-paper theme.

Coherence is the share of the cluster's MeSH-indexed papers carrying its single
top descriptor. It is deliberately blunt and easy to explain: COVID-19 scores
79% (a tight cluster), while a food/obesity/eating-behaviour cluster scores 10%
(broad, and honest about it). TF-IDF terms are kept alongside as the fine detail.

Usage:
    python scripts/label_themes.py
"""

import sys, os, json, math, logging, collections

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ncats.schema import connect_ncats

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# Descriptors that index study population or design rather than subject matter.
# Without excluding these, most themes would be named "Humans, Female, Adult".
GENERIC = {
    "Humans", "Female", "Male", "Adult", "Middle Aged", "Aged", "Adolescent",
    "Child", "Young Adult", "Animals", "Mice", "Rats", "Retrospective Studies",
    "Prospective Studies", "Treatment Outcome", "Risk Factors", "Cohort Studies",
    "Surveys and Questionnaires", "Time Factors", "United States",
    "Aged, 80 and over", "Child, Preschool", "Infant", "Infant, Newborn",
    "Cross-Sectional Studies", "Longitudinal Studies", "Follow-Up Studies",
    "Reproducibility of Results", "Sensitivity and Specificity", "Pilot Projects",
    "Case-Control Studies", "Severity of Illness Index", "Predictive Value of Tests",
    "Randomized Controlled Trials as Topic", "Double-Blind Method", "Pregnancy",
}

MIN_SUPPORT = 5     # a descriptor must appear in at least this many papers
TOP_N = 5


def main():
    conn = connect_ncats()

    bg = collections.Counter()
    per_theme = collections.defaultdict(collections.Counter)
    theme_n = collections.Counter()
    n_bg = 0

    for tid, mesh, major in conn.execute("""
        SELECT pt.theme_id, ptx.mesh_terms, ptx.major_mesh
        FROM pub_themes pt JOIN pub_text ptx ON ptx.pmid = pt.pmid
        WHERE ptx.has_mesh = 1"""):
        # Prefer major topics; fall back to all descriptors when PubMed flagged none.
        terms = set(json.loads(major or "[]")) or set(json.loads(mesh or "[]"))
        terms -= GENERIC
        if not terms:
            continue
        theme_n[tid] += 1
        n_bg += 1
        for t in terms:
            bg[t] += 1
            per_theme[tid][t] += 1

    log.info("MeSH-indexed papers across themes: %d", n_bg)

    updates = []
    for tid, counts in per_theme.items():
        n = theme_n[tid]
        scored = []
        for term, ct in counts.items():
            if ct < MIN_SUPPORT:
                continue
            p_in = ct / n
            p_out = (bg[term] - ct + 1) / (n_bg - n + 1)
            scored.append((math.log(p_in / p_out) * math.sqrt(ct), term, ct))
        scored.sort(reverse=True)
        top = [(t, ct) for _, t, ct in scored[:TOP_N]]
        if not top:
            continue
        coherence = top[0][1] / n if n else 0.0
        updates.append((
            "; ".join(t for t, _ in top[:3]),
            json.dumps([{"term": t, "n": ct} for t, ct in top]),
            round(coherence, 4), n, tid,
        ))

    conn.executemany(
        "UPDATE themes SET mesh_label=?, mesh_terms=?, coherence=?, mesh_n=? "
        "WHERE theme_id=?", updates)
    conn.commit()
    log.info("labelled %d of %d themes",
             len(updates), conn.execute("SELECT COUNT(*) FROM themes").fetchone()[0])

    log.info("Most coherent themes:")
    for label, coh, size in conn.execute(
        "SELECT mesh_label, coherence, size FROM themes "
        "WHERE mesh_label IS NOT NULL ORDER BY coherence DESC LIMIT 8"):
        log.info("  %3.0f%%  %6d papers  %s", 100 * coh, size, label)

    log.info("Least coherent themes (broad or mixed):")
    for label, coh, size in conn.execute(
        "SELECT mesh_label, coherence, size FROM themes "
        "WHERE mesh_label IS NOT NULL ORDER BY coherence ASC LIMIT 5"):
        log.info("  %3.0f%%  %6d papers  %s", 100 * coh, size, label)

    conn.close()


if __name__ == "__main__":
    main()

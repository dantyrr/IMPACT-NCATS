"""Rolling citation rates per CTSA site, mirroring IMPACT's journal metric.

IMPACT computes a journal's rolling citation rate at month T as:

    citations received in the 12 months ending at T
    ------------------------------------------------
    research papers published in an N-month window
    ending 13 months before T (skip months optional)

Windows (from IMPACT's impact_calculator.compute_rolling_if):
    12-month : window=12, skip=0   -> papers 13-24 months before T
    24-month : window=24, skip=0   -> papers 13-36 months before T  (default)
    5-yr     : window=60, skip=12  -> papers 25-84 months before T

Here the same formula is applied to a CTSA site, treating the site's linked
publications the way IMPACT treats a journal's.

Rather than re-querying per month, each paper and each citation event is mapped
to the contiguous range of snapshot months it can influence, and those ranges
are accumulated with a difference array. That makes the whole series one pass
over the data instead of one query per month per window.
"""

import logging

logger = logging.getLogger(__name__)

# (name, paper_window_months, paper_skip_months)
WINDOWS = [
    ("rate_12m", 12, 0),
    ("rate_24m", 24, 0),
    ("rate_5yr", 60, 12),
]

CITATION_WINDOW = 12


def month_index(year: int, month: int) -> int:
    """Months since year 0. Lets window arithmetic be plain integer math."""
    return year * 12 + (month - 1)


def index_to_month(idx: int) -> str:
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def _paper_range(p: int, window: int, skip: int) -> tuple[int, int]:
    """Snapshot months whose paper window contains a paper published at index p.

    Paper window for target T spans [T - CITATION_WINDOW - skip - window + 1,
    T - CITATION_WINDOW - skip], so p is included when T is in
    [p + CITATION_WINDOW + skip, p + CITATION_WINDOW + skip + window - 1].
    """
    lo = p + CITATION_WINDOW + skip
    return lo, lo + window - 1


def compute_site_series(papers, citations, first_idx, last_idx) -> list[dict]:
    """Rolling rates for one site across [first_idx, last_idx].

    papers:    iterable of (month_index, is_research)
    citations: iterable of (cited_paper_month_index, citing_month_index)

    Citation events are passed with the *cited paper's* publication month so a
    single pass can decide which snapshots the event belongs to.
    """
    n = last_idx - first_idx + 2
    if n <= 0:
        return []

    # Difference arrays: research-paper counts per window, and citation counts.
    paper_diff = {name: [0] * (n + 1) for name, _, _ in WINDOWS}
    cite_diff = {name: [0] * (n + 1) for name, _, _ in WINDOWS}

    def bump(arr, lo, hi):
        lo = max(lo, first_idx)
        hi = min(hi, last_idx)
        if lo > hi:
            return
        arr[lo - first_idx] += 1
        arr[hi - first_idx + 1] -= 1

    for p_idx, is_research in papers:
        if not is_research:
            continue          # denominator is research papers only, as in IMPACT
        for name, window, skip in WINDOWS:
            lo, hi = _paper_range(p_idx, window, skip)
            bump(paper_diff[name], lo, hi)

    for p_idx, c_idx in citations:
        # The citing month must fall in the 12 months ending at T:
        #   T in [c_idx, c_idx + CITATION_WINDOW - 1]
        for name, window, skip in WINDOWS:
            plo, phi = _paper_range(p_idx, window, skip)
            lo = max(plo, c_idx)
            hi = min(phi, c_idx + CITATION_WINDOW - 1)
            bump(cite_diff[name], lo, hi)

    out = []
    running_p = {name: 0 for name, _, _ in WINDOWS}
    running_c = {name: 0 for name, _, _ in WINDOWS}
    for i in range(n - 1):
        idx = first_idx + i
        row = {"snapshot_month": index_to_month(idx)}
        for name, _, _ in WINDOWS:
            running_p[name] += paper_diff[name][i]
            running_c[name] += cite_diff[name][i]
            papers_n = running_p[name]
            row[name] = (running_c[name] / papers_n) if papers_n > 0 else None
            if name == "rate_24m":
                row["paper_count"] = papers_n
                row["citation_count"] = running_c[name]
        out.append(row)
    return out

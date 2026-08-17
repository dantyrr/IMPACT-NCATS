"""The rolling-rate formula must match IMPACT's, so these tests pin the exact
window boundaries rather than just checking that numbers come out."""

from src.ncats.site_snapshots import (
    month_index, index_to_month, _paper_range, compute_site_series,
)


def test_month_index_roundtrip():
    assert index_to_month(month_index(2020, 6)) == "2020-06"
    assert index_to_month(month_index(2020, 1)) == "2020-01"
    assert index_to_month(month_index(2019, 12)) == "2019-12"


def test_paper_window_offsets_match_impact():
    """Offsets follow IMPACT's CODE, not its docstring.

    impact_calculator computes paper_end = cite_start - 1 = T - 12 and
    paper_start = paper_end - (window - 1), so a 24-month window covers papers
    12-35 months before the target. IMPACT's docstring says "13-36", which is
    off by one from its own arithmetic; the code is what produced the published
    IMPACT numbers, so it is what this mirrors.
    """
    p = month_index(2020, 1)
    lo, hi = _paper_range(p, 24, 0)
    assert (lo - p, hi - p) == (12, 35)
    # 12-month window: papers 12-23 months before target
    lo, hi = _paper_range(p, 12, 0)
    assert (lo - p, hi - p) == (12, 23)
    # 5-yr yr2-6 (window=60, skip=12): papers 24-83 months before target
    lo, hi = _paper_range(p, 60, 12)
    assert (lo - p, hi - p) == (24, 83)


def test_rate_is_citations_over_research_papers():
    """One research paper, four citations inside the 12-month citation window
    while the paper is still inside the 24-month paper window."""
    p = month_index(2020, 1)
    target = p + 12                      # first month the paper counts
    papers = [(p, 1)]
    citations = [(p, target)] * 4        # all four cited in the target month
    series = compute_site_series(papers, citations, target, target)
    assert len(series) == 1
    assert series[0]["paper_count"] == 1
    assert series[0]["citation_count"] == 4
    assert series[0]["rate_24m"] == 4.0


def test_reviews_excluded_from_denominator():
    p = month_index(2020, 1)
    target = p + 12
    series = compute_site_series([(p, 0)], [(p, target)], target, target)
    # No research papers -> undefined rather than divide-by-zero.
    assert series[0]["paper_count"] == 0
    assert series[0]["rate_24m"] is None


def test_paper_outside_window_is_not_counted():
    p = month_index(2020, 1)
    papers = [(p, 1)]
    # 11 months after publication is one month too early for the paper window.
    early = p + 11
    assert compute_site_series(papers, [], early, early)[0]["paper_count"] == 0
    # 36 months after is one month too late for the 24-month window.
    late = p + 36
    assert compute_site_series(papers, [], late, late)[0]["paper_count"] == 0
    # The boundaries themselves are inside.
    assert compute_site_series(papers, [], p + 12, p + 12)[0]["paper_count"] == 1
    assert compute_site_series(papers, [], p + 35, p + 35)[0]["paper_count"] == 1


def test_citation_outside_12_month_window_is_not_counted():
    p = month_index(2020, 1)
    target = p + 12
    # Cited 12 months before the target: outside the 12-month citation window.
    stale = [(p, target - 12)]
    series = compute_site_series([(p, 1)], stale, target, target)
    assert series[0]["citation_count"] == 0
    assert series[0]["rate_24m"] == 0.0


def test_series_covers_every_month_in_range():
    p = month_index(2015, 1)
    series = compute_site_series([(p, 1)], [], month_index(2016, 1), month_index(2016, 12))
    assert [r["snapshot_month"] for r in series] == [f"2016-{m:02d}" for m in range(1, 13)]


def test_twelve_month_window_is_stricter_than_24():
    """A paper 30 months old is inside the 24-mo window but outside the 12-mo one."""
    p = month_index(2020, 1)
    target = p + 30
    series = compute_site_series([(p, 1)], [(p, target)], target, target)
    assert series[0]["rate_24m"] == 1.0
    assert series[0]["rate_12m"] is None

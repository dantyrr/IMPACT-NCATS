from unittest.mock import patch, MagicMock
from src.ncats.reporter_client import ReporterClient


def _resp(payload):
    m = MagicMock()
    m.json.return_value = payload
    m.raise_for_status.return_value = None
    return m


def test_fetch_projects_paginates_past_first_page():
    """total=1200 must produce 3 requests and 1200 records, not 500."""
    pages = [
        _resp({"meta": {"total": 1200},
               "results": [{"core_project_num": f"A{i}"} for i in range(500)]}),
        _resp({"meta": {"total": 1200},
               "results": [{"core_project_num": f"B{i}"} for i in range(500)]}),
        _resp({"meta": {"total": 1200},
               "results": [{"core_project_num": f"C{i}"} for i in range(200)]}),
    ]
    with patch("src.ncats.reporter_client.requests.post", side_effect=pages) as p:
        client = ReporterClient(rate_limit=1000)
        out = client.fetch_projects(2024)
    assert len(out) == 1200
    assert p.call_count == 3
    offsets = [c.kwargs["json"]["offset"] for c in p.call_args_list]
    assert offsets == [0, 500, 1000]


def test_fetch_projects_sends_ncats_and_fiscal_year():
    with patch("src.ncats.reporter_client.requests.post",
               return_value=_resp({"meta": {"total": 0}, "results": []})) as p:
        ReporterClient(rate_limit=1000).fetch_projects(2019)
    crit = p.call_args.kwargs["json"]["criteria"]
    assert crit["agencies"] == ["NCATS"]
    assert crit["fiscal_years"] == [2019]


def test_fetch_publications_returns_deduped_pmids():
    pages = [
        _resp({"meta": {"total": 3},
               "results": [{"pmid": 11}, {"pmid": 22}, {"pmid": 11}]}),
    ]
    with patch("src.ncats.reporter_client.requests.post", side_effect=pages):
        out = ReporterClient(rate_limit=1000).fetch_publications("UL1TR001881")
    assert sorted(out) == [11, 22]


def test_fetch_publications_pages_from_both_ends_past_offset_cap():
    """RePORTER rejects offset >= 10000, so a grant with more publications than
    that must be read ascending AND descending, then unioned."""
    def page(pmids, total=16281):
        return _resp({"meta": {"total": total},
                      "results": [{"pmid": p} for p in pmids]})

    # 20 asc pages of 500 (=10000), then 20 desc pages of 500.
    # PMIDs start at 1: pmid 0 is not real and is dropped by the null-guard.
    asc = [page(list(range(1 + i * 500, 1 + (i + 1) * 500))) for i in range(20)]
    desc = [page(list(range(50000 - (i + 1) * 500, 50000 - i * 500))) for i in range(20)]

    with patch("src.ncats.reporter_client.requests.post", side_effect=asc + desc) as p:
        out = ReporterClient(rate_limit=1000).fetch_publications("UL1TR001863")

    orders = [c.kwargs["json"].get("sort_order") for c in p.call_args_list]
    assert "asc" in orders and "desc" in orders, "must page from both ends"
    # No request may use an offset at or beyond the cap.
    assert all(c.kwargs["json"]["offset"] < 10000 for c in p.call_args_list)
    assert len(out) == 20000  # 10000 from each end, no overlap in this fixture


def test_fetch_publications_single_pass_when_under_cap():
    """A small grant must not trigger the second descending pass."""
    pages = [_resp({"meta": {"total": 2}, "results": [{"pmid": 1}, {"pmid": 2}]})]
    with patch("src.ncats.reporter_client.requests.post", side_effect=pages) as p:
        out = ReporterClient(rate_limit=1000).fetch_publications("UL1TR000001")
    assert sorted(out) == [1, 2]
    assert p.call_count == 1


def test_fetch_projects_stops_on_empty_results_guard():
    """A server that reports a huge total but returns nothing must not loop forever."""
    pages = [
        _resp({"meta": {"total": 99999}, "results": []}),
    ]
    with patch("src.ncats.reporter_client.requests.post", side_effect=pages) as p:
        out = ReporterClient(rate_limit=1000).fetch_projects(2024)
    assert out == []
    assert p.call_count == 1

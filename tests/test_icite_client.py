from unittest.mock import patch, MagicMock
from src.ncats.icite_client import IciteClient


def _resp(payload):
    m = MagicMock()
    m.json.return_value = payload
    m.raise_for_status.return_value = None
    return m


def test_chunks_at_200_pmids():
    pmids = list(range(1, 451))  # 450 -> 3 requests
    with patch("src.ncats.icite_client.requests.get",
               return_value=_resp({"data": []})) as g:
        IciteClient(rate_limit=1000).fetch_rcr(pmids)
    assert g.call_count == 3
    first = g.call_args_list[0].kwargs["params"]["pmids"]
    assert len(first.split(",")) == 200


def test_returns_rcr_by_pmid():
    payload = {"data": [
        {"pmid": 1, "relative_citation_ratio": 2.5},
        {"pmid": 2, "relative_citation_ratio": None},
    ]}
    with patch("src.ncats.icite_client.requests.get", return_value=_resp(payload)):
        out = IciteClient(rate_limit=1000).fetch_rcr([1, 2])
    assert out == {1: 2.5, 2: None}


def test_failed_batch_does_not_abort_run():
    import requests as rq
    with patch("src.ncats.icite_client.requests.get",
               side_effect=[rq.RequestException("boom"),
                            _resp({"data": [{"pmid": 300, "relative_citation_ratio": 1.1}]})]):
        out = IciteClient(rate_limit=1000).fetch_rcr(list(range(1, 201)) + [300])
    assert out == {300: 1.1}

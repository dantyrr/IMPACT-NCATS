"""Minimal iCite client for Relative Citation Ratio lookups."""

import time
import logging
import requests

from src.ncats.config import ICITE_BASE_URL, ICITE_RATE_LIMIT, ICITE_MAX_BATCH

logger = logging.getLogger(__name__)


class IciteClient:
    """Fetches RCR values. Batches at 200 PMIDs to avoid 414 errors."""

    def __init__(self, rate_limit: float = ICITE_RATE_LIMIT):
        self.min_interval = 1.0 / rate_limit
        self.last_request_time = 0.0

    def _wait(self):
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_request_time = time.time()

    def fetch_rcr(self, pmids: list[int]) -> dict:
        """Return {pmid: rcr_or_None}. A failed batch is logged and skipped."""
        out = {}
        for i in range(0, len(pmids), ICITE_MAX_BATCH):
            chunk = pmids[i: i + ICITE_MAX_BATCH]
            self._wait()
            try:
                resp = requests.get(
                    ICITE_BASE_URL,
                    params={"pmids": ",".join(str(p) for p in chunk),
                            "format": "json"},
                    timeout=120,
                )
                resp.raise_for_status()
                data = resp.json()
            except requests.RequestException as e:
                logger.error("iCite batch at offset %d failed: %s", i, e)
                continue
            for rec in data.get("data") or []:
                pmid = rec.get("pmid")
                if pmid is not None:
                    out[pmid] = rec.get("relative_citation_ratio")
        return out

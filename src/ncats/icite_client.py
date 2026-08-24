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

    # Fields kept from each iCite record. Beyond RCR these carry NIH's own
    # translational-science measures: the Triangle of Biomedicine mix
    # (human/animal/molecular_cellular), the Approximate Potential to Translate,
    # and whether the paper is or is cited by clinical work.
    TRANSLATIONAL_FIELDS = [
        "relative_citation_ratio", "human", "animal", "molecular_cellular",
        "x_coord", "y_coord", "apt", "is_clinical",
    ]

    def fetch_records(self, pmids: list[int]) -> dict:
        """Return {pmid: {field: value}} including translational measures.

        cited_by_clin arrives as a list of citing clinical PMIDs; only its
        length is kept, since the list itself can run to hundreds of entries
        and is not needed downstream.
        """
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
                if pmid is None:
                    continue
                row = {f: rec.get(f) for f in self.TRANSLATIONAL_FIELDS}
                cbc = rec.get("cited_by_clin")
                row["clin_citations"] = len(cbc) if isinstance(cbc, list) else 0
                out[pmid] = row
        return out

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

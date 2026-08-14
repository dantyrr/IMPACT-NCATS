"""NIH RePORTER v2 API client (projects + publications)."""

import time
import logging
import requests

from src.ncats.config import (
    REPORTER_PROJECTS_URL, REPORTER_PUBS_URL,
    REPORTER_RATE_LIMIT, REPORTER_PAGE_SIZE, AGENCY,
)

logger = logging.getLogger(__name__)

PROJECT_FIELDS = [
    "ProjectNum", "CoreProjectNum", "ActivityCode", "ProjectTitle",
    "Organization", "PrincipalInvestigators", "AwardAmount", "FiscalYear",
]


class ReporterClient:
    """Paginating, rate-limited client for the NIH RePORTER v2 API."""

    def __init__(self, rate_limit: float = REPORTER_RATE_LIMIT):
        self.min_interval = 1.0 / rate_limit
        self.last_request_time = 0.0

    def _wait(self):
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_request_time = time.time()

    def _paginate(self, url: str, criteria: dict, include_fields=None) -> list[dict]:
        """Fetch every page for a query. Returns the concatenated results."""
        results, offset = [], 0
        while True:
            payload = {
                "criteria": criteria,
                "offset": offset,
                "limit": REPORTER_PAGE_SIZE,
            }
            if include_fields:
                payload["include_fields"] = include_fields

            self._wait()
            resp = requests.post(url, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()

            batch = data.get("results") or []
            results.extend(batch)

            total = data.get("meta", {}).get("total", 0)
            offset += REPORTER_PAGE_SIZE

            # Guard: stop on an empty page even if `total` claims more,
            # so a bad total can never cause an infinite loop.
            if not batch or offset >= total:
                break
        return results

    def fetch_projects(self, fiscal_year: int) -> list[dict]:
        """All NCATS project records for one fiscal year."""
        criteria = {"agencies": [AGENCY], "fiscal_years": [fiscal_year]}
        out = self._paginate(REPORTER_PROJECTS_URL, criteria, PROJECT_FIELDS)
        logger.info("FY%s: %d project records", fiscal_year, len(out))
        return out

    def fetch_publications(self, core_project_num: str) -> list[int]:
        """All PMIDs linked to a core project, de-duplicated."""
        criteria = {"core_project_nums": [core_project_num]}
        rows = self._paginate(REPORTER_PUBS_URL, criteria)
        pmids = {r["pmid"] for r in rows if r.get("pmid")}
        logger.info("%s: %d linked PMIDs", core_project_num, len(pmids))
        return sorted(pmids)

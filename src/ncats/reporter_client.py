"""NIH RePORTER v2 API client (projects + publications)."""

import time
import logging
import requests

from src.ncats.config import (
    REPORTER_PROJECTS_URL, REPORTER_PUBS_URL,
    REPORTER_RATE_LIMIT, REPORTER_PAGE_SIZE, REPORTER_OFFSET_CAP, AGENCY,
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

    def _paginate(self, url: str, criteria: dict, include_fields=None,
                  sort_field=None, sort_order=None) -> tuple[list[dict], int]:
        """Fetch pages for a query, stopping at the API's offset cap.

        Returns (results, total). `total` is what the API claims exists, which
        may exceed what could actually be retrieved.
        """
        results, offset, total = [], 0, 0
        while True:
            payload = {
                "criteria": criteria,
                "offset": offset,
                "limit": REPORTER_PAGE_SIZE,
            }
            if include_fields:
                payload["include_fields"] = include_fields
            if sort_field:
                payload["sort_field"] = sort_field
                payload["sort_order"] = sort_order

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
            # Also stop before the API's hard offset cap, which returns HTTP 400.
            if not batch or offset >= total or offset >= REPORTER_OFFSET_CAP:
                break
        return results, total

    def fetch_projects(self, fiscal_year: int) -> list[dict]:
        """All NCATS project records for one fiscal year."""
        criteria = {"agencies": [AGENCY], "fiscal_years": [fiscal_year]}
        out, _ = self._paginate(REPORTER_PROJECTS_URL, criteria, PROJECT_FIELDS)
        logger.info("FY%s: %d project records", fiscal_year, len(out))
        return out

    def fetch_publications(self, core_project_num: str) -> list[int]:
        """All PMIDs linked to a core project, de-duplicated.

        RePORTER rejects offset >= 10,000 with HTTP 400, so a grant with more
        publications than that cannot be read in a single pass. Those are read
        twice — ascending by PMID and descending — and unioned, which covers up
        to 2x the cap. Grants exceeding even that are logged as incomplete
        rather than silently truncated.
        """
        criteria = {"core_project_nums": [core_project_num]}
        rows, total = self._paginate(REPORTER_PUBS_URL, criteria,
                                     sort_field="pmid", sort_order="asc")
        pmids = {r["pmid"] for r in rows if r.get("pmid")}

        if total > REPORTER_OFFSET_CAP:
            tail, _ = self._paginate(REPORTER_PUBS_URL, criteria,
                                     sort_field="pmid", sort_order="desc")
            pmids.update(r["pmid"] for r in tail if r.get("pmid"))
            if total > 2 * REPORTER_OFFSET_CAP:
                logger.warning(
                    "%s: %d publications exceeds twice the offset cap; "
                    "retrieved %d, so this grant is INCOMPLETE",
                    core_project_num, total, len(pmids))

        logger.info("%s: %d linked PMIDs (API total %d)",
                    core_project_num, len(pmids), total)
        return sorted(pmids)

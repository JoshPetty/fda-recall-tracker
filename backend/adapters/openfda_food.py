import time
from datetime import datetime, timedelta, timezone
import requests
import re

from backend.adapters.base import RecallSourceAdapter, RawRecord, CanonicalRecall

OPENFDA_URL = "https://api.fda.gov/food/enforcement.json"

UPC_PATTERN = re.compile(r"UPC[:\s]+(\d{10,14})")


class OpenFDAFoodAdapter(RecallSourceAdapter):
    source_name = "openfda_food"

    def fetch(self, since: datetime | None) -> list[RawRecord]:
        records = []
        skip = 0
        limit = 100
        search = f'report_date:[{since.strftime("%Y%m%d")} TO 99991231]' if since else None

        while True:
            params = {"limit": limit, "skip": skip}
            if search:
                params["search"] = search

            resp = self._get_with_retry(params)
            data = resp.json()
            results = data.get("results", [])
            if not results:
                break
            for r in results:
                records.append(RawRecord(source_id=r["recall_number"], payload=r))
            skip += limit
            if skip >= data.get("meta", {}).get("results", {}).get("total", 0):
                break
            time.sleep(0.3)
        return records

    def _get_with_retry(self, params, max_attempts=3):
        for attempt in range(1, max_attempts + 1):
            resp = requests.get(OPENFDA_URL, params=params, timeout=30)
            if resp.status_code < 500:
                resp.raise_for_status()
                return resp
            if attempt == max_attempts:
                resp.raise_for_status()
            time.sleep(2 ** attempt)

    def normalize(self, raw: RawRecord) -> CanonicalRecall:
        p = raw.payload
        return CanonicalRecall(
            source_id=p["recall_number"],
            brand=p.get("recalling_firm"),
            product_name=p.get("product_description", ""),
            hazard_description=p.get("reason_for_recall"),
            hazard_classification=p.get("classification"),
            status=p.get("status", "unknown").lower(),
            date_initiated=_parse_date(p.get("recall_initiation_date")),
            date_terminated=_parse_date(p.get("termination_date")),
            geographic_scope=p.get("distribution_pattern"),
            upcs=_extract_upcs(p),
        )


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _extract_upcs(payload: dict) -> list[str]:
    structured = payload.get("openfda", {}).get("upc", [])
    if structured:
        return structured
    desc = payload.get("product_description", "")
    return UPC_PATTERN.findall(desc)
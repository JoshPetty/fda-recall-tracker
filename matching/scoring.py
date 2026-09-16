from datetime import date


def brand_score(receipt_brand: str | None, recall_brand: str | None) -> float:
    if not receipt_brand or not recall_brand:
        return 0.0
    r, c = receipt_brand.lower().strip(), recall_brand.lower().strip()
    if r == c:
        return 1.0
    if r in c or c in r:
        return 0.5
    return 0.0


def date_proximity_score(
    purchase_date: date | None,
    recall_date_initiated: date | None,
    window_days: int = 180,
) -> float:
    if not purchase_date or not recall_date_initiated:
        return 0.0
    delta = abs((purchase_date - recall_date_initiated).days)
    if delta > window_days:
        return 0.0
    return 1.0 - (delta / window_days)


def combine_confidence(name_sim: float, brand: float, date_prox: float) -> float:
    # Weights are hand-set for MVP, not learned. Documented here deliberately:
    # name similarity carries the most weight since it's the only signal
    # guaranteed to exist on every candidate; brand and date are corroborating,
    # not load-bearing, since either can be missing without invalidating a match.
    return round(0.5 * name_sim + 0.3 * brand + 0.2 * date_prox, 4)
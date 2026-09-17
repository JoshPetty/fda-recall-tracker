from sqlalchemy import text

from backend.db.models import MatchCandidate, Recall, ReceiptItem
from backend.matching.upc_lookup import find_by_upc
from backend.matching.scoring import brand_score, date_proximity_score, combine_confidence
from sqlalchemy import text

from backend.db.models import MatchCandidate, Recall, ReceiptItem
from backend.matching.upc_lookup import find_by_upc
from backend.matching.scoring import brand_score, date_proximity_score, combine_confidence
SURFACE_THRESHOLD = 0.5
AUTO_CONFIRM_THRESHOLD = 0.85
FUZZY_SIMILARITY_FLOOR = 0.3


def match_receipt_item(session, item: ReceiptItem) -> list[MatchCandidate]:
    created = []

    # UPC exact path, always tried first, can return multiple recalls
    for recall_id in find_by_upc(session, item.upc):
        candidate = _upsert_candidate(
            session, item, recall_id,
            confidence=1.0,
            method="upc_exact",
            features={"upc": item.upc},
        )
        if candidate:
            created.append(candidate)

    # Fuzzy path, always runs too, even after a UPC hit (barcode misreads happen)
    session.execute(text("SET LOCAL pg_trgm.word_similarity_threshold = :t"), {"t": FUZZY_SIMILARITY_FLOOR})
    rows = session.execute(
        text("""
            SELECT id, brand, date_initiated,
                word_similarity(:query, product_name_normalized) AS name_sim
            FROM recalls
            WHERE :query <% product_name_normalized
            ORDER BY name_sim DESC
            LIMIT 20
        """),
        {"query": item.product_name_normalized},
    ).fetchall()

    for row in rows:
        brand = brand_score(item.brand_extracted, row.brand)
        date_prox = date_proximity_score(item.purchase_date, row.date_initiated)
        confidence = combine_confidence(row.name_sim, brand, date_prox)

        if confidence < SURFACE_THRESHOLD:
            continue

        candidate = _upsert_candidate(
            session, item, row.id,
            confidence=confidence,
            method="fuzzy",
            features={
                "name_sim": row.name_sim,
                "brand_match": brand,
                "date_proximity": date_prox,
                "query_normalized": item.product_name_normalized,
            },
        )
        if candidate:
            created.append(candidate)

    return created


def _upsert_candidate(session, item, recall_id, confidence, method, features) -> MatchCandidate | None:
    existing = (
        session.query(MatchCandidate)
        .filter_by(receipt_item_id=item.id, recall_id=recall_id)
        .first()
    )
    if existing:
        return None  # already recorded, skip (unique constraint would catch this anyway)

    status = "auto_confirmed" if confidence >= AUTO_CONFIRM_THRESHOLD else "pending_review"
    candidate = MatchCandidate(
        receipt_item_id=item.id,
        recall_id=recall_id,
        confidence=confidence,
        method=method,
        match_features=features,
        status=status,
    )
    session.add(candidate)
    session.flush()
    return candidate
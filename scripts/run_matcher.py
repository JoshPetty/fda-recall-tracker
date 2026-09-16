# scripts/run_matcher.py
from db.session import SessionLocal
from db.models import ReceiptItem, MatchCandidate
from matching.matcher import match_receipt_item

session = SessionLocal()

items = session.query(ReceiptItem).all()
for item in items:
    match_receipt_item(session, item)
    session.commit()

    candidates = session.query(MatchCandidate).filter_by(receipt_item_id=item.id).all()
    print(f"\n{item.raw_text!r}:")
    if not candidates:
        print("  no matches")
    for c in candidates:
        print(f"  -> recall={c.recall_id} confidence={c.confidence} method={c.method} status={c.status}")
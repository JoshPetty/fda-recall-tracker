# scripts/test_upc_lookup.py
from db.session import SessionLocal
from db.models import ReceiptItem
from matching.upc_lookup import find_by_upc

session = SessionLocal()

items = session.query(ReceiptItem).filter(ReceiptItem.upc.isnot(None)).all()
for item in items:
    matches = find_by_upc(session, item.upc)
    print(f"{item.raw_text!r} (upc={item.upc}) -> {matches}")
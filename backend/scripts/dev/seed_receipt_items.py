from datetime import date, datetime, timezone

from db.session import SessionLocal
from db.models import User, Receipt, ReceiptItem, Recall
from normalization.text_normalize import normalize_text

session = SessionLocal()

# NOTE: users.id has no server default (it must match a real auth.users.id,
# see cc71d2485e36) -- this was already true before the household removal,
# so this insert relies on the same pre-existing gap it always did.
user = User(email="test@example.com")
session.add(user)
session.flush()

receipt = Receipt(
    user_id=user.id,
    uploaded_by_user_id=user.id,
    image_s3_key="seed/fake.jpg",
    ocr_status="done",
    retention_expires_at=datetime.now(timezone.utc),
)
session.add(receipt)
session.flush()

sample_recalls = session.query(Recall).limit(5).all()
items = []

for r in sample_recalls:
    fake_text = r.product_name[:20].upper()  # crude, but realistic receipt-style truncation
    items.append(ReceiptItem(
        receipt_id=receipt.id,
        raw_text=fake_text,
        brand_extracted=r.brand,
        product_name_extracted=fake_text,
        product_name_normalized=normalize_text(fake_text),
        purchase_date=date.today(),
    ))

negatives = ["BANANAS", "WHOLE MILK GAL", "WONDER BREAD", "EGGS LG DOZ", "COFFEE GROUND 12OZ"]
for text in negatives:
    items.append(ReceiptItem(
        receipt_id=receipt.id,
        raw_text=text,
        product_name_extracted=text,
        product_name_normalized=normalize_text(text),
        purchase_date=date.today(),
    ))

session.add_all(items)
session.commit()
print(f"seeded {len(items)} receipt_items under receipt {receipt.id}")
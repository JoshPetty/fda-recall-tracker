from db.session import SessionLocal
from db.models import Recall
from normalization.text_normalize import normalize_text

session = SessionLocal()

recalls = session.query(Recall).all()
updated = 0
for r in recalls:
    new_normalized = normalize_text(r.product_name)
    if new_normalized != r.product_name_normalized:
        r.product_name_normalized = new_normalized
        updated += 1

session.commit()
print(f"recomputed {updated} of {len(recalls)} recalls")
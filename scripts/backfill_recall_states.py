from db.session import SessionLocal
from db.models import Recall, RecallState
from normalization.geo_parse import parse_geographic_scope

session = SessionLocal()

recalls = session.query(Recall).all()
updated = 0
nationwide = 0
parsed = 0
unparsed = 0

for r in recalls:
    result = parse_geographic_scope(r.geographic_scope)

    existing_codes = {
        code for (code,) in session.query(RecallState.state_code).filter_by(recall_id=r.id).all()
    }
    new_codes = set(result.state_codes)

    if (
        r.is_nationwide != result.is_nationwide
        or r.parse_status != result.parse_status
        or existing_codes != new_codes
    ):
        r.is_nationwide = result.is_nationwide
        r.parse_status = result.parse_status
        if existing_codes != new_codes:
            session.query(RecallState).filter_by(recall_id=r.id).delete()
            for code in new_codes:
                session.add(RecallState(recall_id=r.id, state_code=code))
        updated += 1

    if result.is_nationwide:
        nationwide += 1
    elif result.parse_status == "parsed":
        parsed += 1
    else:
        unparsed += 1

session.commit()
print(f"backfilled {updated} of {len(recalls)} recalls")
print(f"parsed: {parsed}, nationwide: {nationwide}, unparsed: {unparsed}")

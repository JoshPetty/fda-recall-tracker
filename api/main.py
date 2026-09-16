import uuid
from datetime import date, datetime, timedelta, timezone

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from jwt import PyJWKClient
from pydantic import BaseModel

from config import SUPABASE_URL
from db.models import Receipt, ReceiptItem, Recall, User
from db.session import SessionLocal
from matching.matcher import match_receipt_item
from normalization.text_normalize import normalize_text

# Sentinel `image_s3_key` marking the one reused "manual entries" receipt per
# household (see api/main.py POST /match), rather than creating a new
# receipts row per pasted item. `receipts.image_s3_key`/`retention_expires_at`
# are NOT NULL columns designed for photo receipts; there is no image here,
# so these are placeholders, not real S3/retention data.
MANUAL_ENTRY_IMAGE_KEY = "manual-entry"
MANUAL_ENTRY_RETENTION = timedelta(days=90)

if not SUPABASE_URL:
    raise RuntimeError("Missing SUPABASE_URL. Set it in .env (see .env for other vars).")

_jwks_client = PyJWKClient(f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://localhost:\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_current_user_id(authorization: str | None = Header(default=None)) -> uuid.UUID:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization.split(" ", 1)[1].strip()

    try:
        signing_key = _jwks_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256", "RS256"],
            audience="authenticated",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}") from exc

    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status_code=401, detail="Token missing subject")

    return uuid.UUID(sub)


class MatchRequest(BaseModel):
    text: str
    brand: str | None = None
    purchase_date: date | None = None


class MatchCandidateOut(BaseModel):
    recall_id: str
    confidence: float
    method: str
    match_features: dict
    recall_product_name: str | None = None


@app.post("/match", response_model=list[MatchCandidateOut])
def match(payload: MatchRequest, user_id: uuid.UUID = Depends(get_current_user_id)):
    if not payload.text.strip():
        raise HTTPException(status_code=422, detail="text must not be empty")

    session = SessionLocal()
    try:
        # household_id is looked up server-side from the verified JWT's user
        # id, never taken from the request body.
        user = session.query(User).filter_by(id=user_id).first()
        if user is None:
            raise HTTPException(
                status_code=403,
                detail="No household profile found for this account.",
            )

        receipt = (
            session.query(Receipt)
            .filter_by(household_id=user.household_id, image_s3_key=MANUAL_ENTRY_IMAGE_KEY)
            .first()
        )
        if receipt is None:
            receipt = Receipt(
                household_id=user.household_id,
                uploaded_by_user_id=user.id,
                image_s3_key=MANUAL_ENTRY_IMAGE_KEY,
                ocr_status="manual",
                retention_expires_at=datetime.now(timezone.utc) + MANUAL_ENTRY_RETENTION,
            )
            session.add(receipt)
            session.flush()

        item = ReceiptItem(
            receipt_id=receipt.id,
            raw_text=payload.text,
            brand_extracted=payload.brand,
            product_name_extracted=payload.text,
            product_name_normalized=normalize_text(payload.text),
            purchase_date=payload.purchase_date,
        )
        session.add(item)
        session.flush()

        candidates = match_receipt_item(session, item)

        recall_ids = [c.recall_id for c in candidates]
        recalls_by_id = {
            r.id: r
            for r in (
                session.query(Recall).filter(Recall.id.in_(recall_ids)).all()
                if recall_ids
                else []
            )
        }

        session.commit()

        return [
            MatchCandidateOut(
                recall_id=str(c.recall_id),
                confidence=float(c.confidence),
                method=c.method,
                match_features=c.match_features,
                recall_product_name=(
                    recalls_by_id[c.recall_id].product_name
                    if c.recall_id in recalls_by_id
                    else None
                ),
            )
            for c in candidates
        ]
    finally:
        session.close()

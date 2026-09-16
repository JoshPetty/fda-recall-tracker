from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class RawIngestion(Base):
    __tablename__ = "raw_ingestions"

    id = Column(BigInteger, primary_key=True)
    source = Column(Text, nullable=False)
    source_id = Column(Text, nullable=False)
    payload = Column(JSONB, nullable=False)
    content_hash = Column(Text, nullable=False)
    fetched_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index(
            "idx_raw_ingestions_source_id",
            "source",
            "source_id",
            text("fetched_at DESC"),
        ),
    )


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id = Column(BigInteger, primary_key=True)
    source = Column(Text, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at = Column(DateTime(timezone=True))
    status = Column(Text, nullable=False, server_default="running")
    records_fetched = Column(Integer)
    records_changed = Column(Integer)
    watermark = Column(DateTime(timezone=True))
    error_message = Column(Text)


class Recall(Base):
    __tablename__ = "recalls"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    source = Column(Text, nullable=False)
    source_id = Column(Text, nullable=False)
    brand = Column(Text)
    product_name = Column(Text, nullable=False)
    product_name_normalized = Column(Text, nullable=False)
    hazard_description = Column(Text)
    hazard_classification = Column(Text)
    status = Column(Text, nullable=False)
    date_initiated = Column(Date)
    date_terminated = Column(Date)
    geographic_scope = Column(Text)
    is_nationwide = Column(Boolean, nullable=False, server_default=text("false"))
    parse_status = Column(Text, nullable=False, server_default="unparsed")
    raw_ingestion_id = Column(BigInteger, ForeignKey("raw_ingestions.id"))
    content_hash = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("source", "source_id"),
        CheckConstraint("parse_status IN ('parsed', 'unparsed')", name="ck_recalls_parse_status"),
        Index(
            "idx_recalls_name_trgm",
            "product_name_normalized",
            postgresql_using="gin",
            postgresql_ops={"product_name_normalized": "gin_trgm_ops"},
        ),
        Index("idx_recalls_date_initiated", "date_initiated"),
    )


class RecallUpc(Base):
    __tablename__ = "recall_upcs"

    id = Column(BigInteger, primary_key=True)
    recall_id = Column(
        UUID(as_uuid=True), ForeignKey("recalls.id", ondelete="CASCADE"), nullable=False
    )
    upc = Column(Text, nullable=False)

    __table_args__ = (Index("idx_recall_upcs_upc", "upc"),)


class RecallState(Base):
    """One row per (recall, state) -- a recall can span multiple states."""

    __tablename__ = "recall_states"

    id = Column(BigInteger, primary_key=True)
    recall_id = Column(
        UUID(as_uuid=True), ForeignKey("recalls.id", ondelete="CASCADE"), nullable=False
    )
    state_code = Column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("recall_id", "state_code", name="uq_recall_states_recall_id_state_code"),
        Index("idx_recall_states_state_code", "state_code"),
    )


class RecallHistory(Base):
    __tablename__ = "recall_history"

    id = Column(BigInteger, primary_key=True)
    recall_id = Column(UUID(as_uuid=True), ForeignKey("recalls.id"), nullable=False)
    changed_fields = Column(JSONB, nullable=False)
    snapshot = Column(JSONB, nullable=False)
    changed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Household(Base):
    __tablename__ = "households"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    name = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class User(Base):
    """Profile table keyed off Supabase Auth.

    `id` is not server-generated: it's the same UUID as the corresponding
    `auth.users.id` row, set by the app (typically `auth.uid()`) when the
    profile is created on sign-up. Deleting the `auth.users` row cascades
    here.
    """

    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), primary_key=True)
    household_id = Column(UUID(as_uuid=True), ForeignKey("households.id"), nullable=False)
    email = Column(Text, nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Receipt(Base):
    __tablename__ = "receipts"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    household_id = Column(UUID(as_uuid=True), ForeignKey("households.id"), nullable=False)
    uploaded_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    image_s3_key = Column(Text, nullable=False)
    uploaded_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    ocr_status = Column(Text, nullable=False, server_default="pending")
    ocr_raw_text = Column(Text)
    extracted_at = Column(DateTime(timezone=True))
    retention_expires_at = Column(DateTime(timezone=True), nullable=False)


class ReceiptItem(Base):
    __tablename__ = "receipt_items"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    receipt_id = Column(
        UUID(as_uuid=True), ForeignKey("receipts.id", ondelete="CASCADE"), nullable=False
    )
    raw_text = Column(Text, nullable=False)
    brand_extracted = Column(Text)
    product_name_extracted = Column(Text, nullable=False)
    product_name_normalized = Column(Text, nullable=False)
    upc = Column(Text)
    quantity = Column(Numeric)
    unit_price = Column(Numeric)
    purchase_date = Column(Date)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index(
            "idx_receipt_items_name_trgm",
            "product_name_normalized",
            postgresql_using="gin",
            postgresql_ops={"product_name_normalized": "gin_trgm_ops"},
        ),
        Index("idx_receipt_items_upc", "upc"),
    )


class MatchCandidate(Base):
    __tablename__ = "match_candidates"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    receipt_item_id = Column(UUID(as_uuid=True), ForeignKey("receipt_items.id"), nullable=False)
    recall_id = Column(UUID(as_uuid=True), ForeignKey("recalls.id"), nullable=False)
    confidence = Column(Numeric, nullable=False)
    method = Column(Text, nullable=False)
    match_features = Column(JSONB, nullable=False)
    status = Column(Text, nullable=False, server_default="pending_review")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    reviewed_at = Column(DateTime(timezone=True))

    __table_args__ = (UniqueConstraint("receipt_item_id", "recall_id"),)


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    match_candidate_id = Column(
        UUID(as_uuid=True), ForeignKey("match_candidates.id"), nullable=False
    )
    channel = Column(Text, nullable=False, server_default="email")
    status = Column(Text, nullable=False, server_default="queued")
    dedupe_key = Column(Text, nullable=False, unique=True)
    attempts = Column(Integer, nullable=False, server_default="0")
    sent_at = Column(DateTime(timezone=True))
    error_message = Column(Text)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Job(Base):
    __tablename__ = "jobs"

    id = Column(BigInteger, primary_key=True)
    job_type = Column(Text, nullable=False)
    payload = Column(JSONB, nullable=False)
    status = Column(Text, nullable=False, server_default="queued")
    attempts = Column(Integer, nullable=False, server_default="0")
    run_after = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (Index("idx_jobs_pickup", "status", "run_after"),)

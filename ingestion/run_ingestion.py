import hashlib
import json
from datetime import datetime, timedelta, timezone

from adapters.openfda_food import OpenFDAFoodAdapter
from db.models import Recall, RawIngestion, RecallHistory, IngestionRun, RecallUpc, RecallState
from db.session import SessionLocal
from normalization.geo_parse import parse_geographic_scope
from normalization.text_normalize import normalize_text

SOURCE = "openfda_food"


def hash_payload(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def get_watermark(session) -> datetime | None:
    last_success = (
        session.query(IngestionRun)
        .filter_by(source=SOURCE, status="success")
        .order_by(IngestionRun.finished_at.desc())
        .first()
    )

    return last_success.watermark if last_success else None


def store_raw_if_changed(session, raw) -> RawIngestion | None:
    """Store a raw record if it is new or has changed."""
    new_hash = hash_payload(raw.payload)

    latest = (
        session.query(RawIngestion)
        .filter_by(source=SOURCE, source_id=raw.source_id)
        .order_by(RawIngestion.fetched_at.desc())
        .first()
    )

    if latest and latest.content_hash == new_hash:
        return None

    row = RawIngestion(
        source=SOURCE,
        source_id=raw.source_id,
        payload=raw.payload,
        content_hash=new_hash,
    )

    session.add(row)
    session.flush()

    return row


def diff_fields(old: Recall, new_canonical) -> dict:
    """Return only the fields that changed."""
    changed = {}

    fields = [
        "brand",
        "product_name",
        "hazard_description",
        "hazard_classification",
        "status",
        "date_initiated",
        "date_terminated",
        "geographic_scope",
    ]

    for field in fields:
        old_value = getattr(old, field)
        new_value = getattr(new_canonical, field)

        if old_value != new_value:
            changed[field] = [old_value, new_value]

    return changed


def sync_recall_states(session, recall, geographic_scope) -> bool:
    """Recompute `is_nationwide`/`parse_status`/`recall_states` for `recall`
    from `geographic_scope`. Returns True if anything changed.

    Takes `geographic_scope` as an explicit argument rather than reading
    `recall.geographic_scope`, the same way the normalized-name recompute
    below takes `canonical.product_name` rather than `existing.product_name`
    -- in the existing-recall path, `existing.geographic_scope` is still
    the *old* value at the point this is called (the field update happens
    later), so reading it here would silently parse stale text on the run
    where the location actually changed.

    Called unconditionally, independent of whether `geographic_scope`
    itself changed this run, so a fix to `parse_geographic_scope()` gets
    picked up on the next ingestion run instead of staying silently stale.
    """
    parsed = parse_geographic_scope(geographic_scope)

    existing_codes = {
        code for (code,) in session.query(RecallState.state_code).filter_by(recall_id=recall.id).all()
    }
    new_codes = set(parsed.state_codes)

    changed = (
        recall.is_nationwide != parsed.is_nationwide
        or recall.parse_status != parsed.parse_status
        or existing_codes != new_codes
    )

    if not changed:
        return False

    recall.is_nationwide = parsed.is_nationwide
    recall.parse_status = parsed.parse_status

    if existing_codes != new_codes:
        session.query(RecallState).filter_by(recall_id=recall.id).delete()
        for code in new_codes:
            session.add(RecallState(recall_id=recall.id, state_code=code))

    return True


def upsert_canonical(
    session,
    canonical,
    raw_ingestion_id: int,
    content_hash: str,
) -> bool:
    """Insert a new recall or update an existing changed recall."""

    existing = (
        session.query(Recall)
        .filter_by(
            source=SOURCE,
            source_id=canonical.source_id,
        )
        .first()
    )

    # Brand-new recall
    if existing is None:
        recall = Recall(
            source=SOURCE,
            source_id=canonical.source_id,
            brand=canonical.brand,
            product_name=canonical.product_name,
            product_name_normalized=normalize_text(
                canonical.product_name
            ),
            hazard_description=canonical.hazard_description,
            hazard_classification=canonical.hazard_classification,
            status=canonical.status,
            date_initiated=canonical.date_initiated,
            date_terminated=canonical.date_terminated,
            geographic_scope=canonical.geographic_scope,
            raw_ingestion_id=raw_ingestion_id,
            content_hash=content_hash,
        )

        session.add(recall)
        session.flush()

        for upc in canonical.upcs:
            session.add(
                RecallUpc(
                    recall_id=recall.id,
                    upc=upc,
                )
            )

        sync_recall_states(session, recall, canonical.geographic_scope)

        return True

    # Existing recall
    changed = diff_fields(existing, canonical)

    # Recompute normalized name unconditionally, independent of the
    # diff above, so a fix to normalize_text() itself gets picked up
    # on the next run instead of staying silently stale.
    new_normalized = normalize_text(canonical.product_name)
    normalized_changed = new_normalized != existing.product_name_normalized
    if normalized_changed:
        existing.product_name_normalized = new_normalized

    # Recompute geography the same way -- unconditionally, so a fix to
    # parse_geographic_scope() gets picked up on the next run too.
    geo_changed = sync_recall_states(session, existing, canonical.geographic_scope)

    if not changed and not normalized_changed and not geo_changed:
        return False

    # Save the previous version before updating it
    session.add(
        RecallHistory(
            recall_id=existing.id,
            changed_fields=changed,
            snapshot={
                "brand": existing.brand,
                "product_name": existing.product_name,
                "status": existing.status,
                "date_initiated": str(existing.date_initiated),
                "date_terminated": str(existing.date_terminated),
            },
        )
    )

    # Update the canonical recall
    for field, (_, new_value) in changed.items():
        setattr(existing, field, new_value)

    existing.raw_ingestion_id = raw_ingestion_id
    existing.content_hash = content_hash
    existing.updated_at = datetime.now(timezone.utc)

    return True

def main():
    session = SessionLocal()

    run = IngestionRun(
        source=SOURCE,
        status="running",
    )

    session.add(run)
    session.flush()

    try:
        # 1. Get the last successful watermark
        since = get_watermark(session) or (datetime.now(timezone.utc) - timedelta(days=365))

        # 2. Fetch records from openFDA
        adapter = OpenFDAFoodAdapter()
        raw_records = adapter.fetch(since)

        changed_count = 0
        latest_report_date = since

        # 3-4. Store raw records and update canonical recalls
        for raw in raw_records:
            stored = store_raw_if_changed(session, raw)

            # Nothing changed, so skip this record
            if stored is None:
                continue

            # Convert raw FDA data into our canonical format
            canonical = adapter.normalize(raw)

            # Insert/update recalls table
            changed = upsert_canonical(
                session,
                canonical,
                stored.id,
                stored.content_hash,
            )

            if changed:
                changed_count += 1

            # Track newest report date for the watermark
            report_date = raw.payload.get("report_date")

            if report_date:
                parsed = datetime.strptime(
                    report_date,
                    "%Y%m%d",
                ).replace(tzinfo=timezone.utc)

                if (
                    latest_report_date is None
                    or parsed > latest_report_date
                ):
                    latest_report_date = parsed

        # 5. Mark the run successful
        run.status = "success"
        run.finished_at = datetime.now(timezone.utc)
        run.records_fetched = len(raw_records)
        run.records_changed = changed_count
        run.watermark = latest_report_date

        session.commit()

        print(
            f"ingestion complete: "
            f"{len(raw_records)} fetched, "
            f"{changed_count} changed"
        )

    except Exception as e:
        session.rollback()

        run.status = "failed"
        run.finished_at = datetime.now(timezone.utc)
        run.error_message = str(e)

        session.add(run)
        session.commit()

        raise

    finally:
        session.close()


if __name__ == "__main__":
    main()
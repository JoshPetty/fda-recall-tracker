# Recall Monitor: Implementation Plan

> **Archived — describes the pre-pivot plan (Docker/K8s/Terraform/RDS direction).** Superseded by `STATUS.md` (repo root) for current state.

Constraints locked in: openFDA food enforcement only, email notifications only, one household, no mobile/SMS/dashboards, no LLM-as-matcher, no Kafka/RabbitMQ unless justified, Python/FastAPI/Postgres, 1-2 students.

---

## 1. Implementation Order

Build in this sequence. Each phase depends on the one before it.

1. **Schema + ingestion** (recalls only, no receipts yet). This is buildable and testable in total isolation against the real openFDA API.
2. **Matching engine against seeded receipt data.** Manually insert fake `receipt_items` rows by hand (SQL inserts, no OCR yet) and build/test the matcher against real ingested recalls. This is deliberate: the matcher is the hardest and most important part of the project. Prove it works before building the OCR/LLM plumbing that feeds it.
3. **Receipt pipeline** (upload, OCR, LLM extraction, validation) to replace the manual seeding from step 2.
4. **Async job wiring**: the two triggers, notification worker.
5. **API layer** (FastAPI endpoints wrapping what already works).
6. **Infra**: Docker, K8s, Terraform.
7. **Testing hardening + labeled matcher evaluation + observability.**

Don't touch until their phase: frontend polish, K8s, Terraform, notifications retry tuning, anything from the "later" feature list in the original scoping doc.

---

## 2. Database Schema

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============ INGESTION / RAW LAYER ============

CREATE TABLE raw_ingestions (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,               -- 'openfda_food'
    source_id TEXT NOT NULL,            -- source's own recall identifier
    payload JSONB NOT NULL,
    content_hash TEXT NOT NULL,         -- sha256 of payload, for change detection
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_raw_ingestions_source_id ON raw_ingestions (source, source_id, fetched_at DESC);

CREATE TABLE ingestion_runs (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running',   -- running | success | failed
    records_fetched INT,
    records_changed INT,
    watermark TIMESTAMPTZ,              -- last successfully processed source timestamp
    error_message TEXT
);

-- ============ CANONICAL LAYER ============

CREATE TABLE recalls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    brand TEXT,
    product_name TEXT NOT NULL,
    product_name_normalized TEXT NOT NULL,   -- lowercased, punctuation-stripped, abbreviations expanded
    hazard_description TEXT,
    hazard_classification TEXT,          -- Class I / II / III, taken directly from source, not derived
    status TEXT NOT NULL,                -- ongoing | terminated | rescinded
    date_initiated DATE,
    date_terminated DATE,
    geographic_scope TEXT,
    raw_ingestion_id BIGINT REFERENCES raw_ingestions(id),
    content_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (source, source_id)
);
CREATE INDEX idx_recalls_name_trgm ON recalls USING gin (product_name_normalized gin_trgm_ops);
CREATE INDEX idx_recalls_date_initiated ON recalls (date_initiated);

-- UPCs normalized out into their own table: a recall can list several,
-- and this gives you a fast, simple exact-match lookup path.
CREATE TABLE recall_upcs (
    id BIGSERIAL PRIMARY KEY,
    recall_id UUID NOT NULL REFERENCES recalls(id) ON DELETE CASCADE,
    upc TEXT NOT NULL
);
CREATE INDEX idx_recall_upcs_upc ON recall_upcs (upc);

CREATE TABLE recall_history (
    id BIGSERIAL PRIMARY KEY,
    recall_id UUID NOT NULL REFERENCES recalls(id),
    changed_fields JSONB NOT NULL,       -- {"status": ["ongoing", "terminated"], ...}
    snapshot JSONB NOT NULL,             -- full canonical row at time of change
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============ HOUSEHOLD / RECEIPTS ============

CREATE TABLE households (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id UUID NOT NULL REFERENCES households(id),
    email TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE receipts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    household_id UUID NOT NULL REFERENCES households(id),
    uploaded_by_user_id UUID NOT NULL REFERENCES users(id),
    image_s3_key TEXT NOT NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ocr_status TEXT NOT NULL DEFAULT 'pending',  -- pending | processing | done | failed
    ocr_raw_text TEXT,
    extracted_at TIMESTAMPTZ,
    retention_expires_at TIMESTAMPTZ NOT NULL     -- set at upload = now() + 90 days; job deletes image at this time
);

CREATE TABLE receipt_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    receipt_id UUID NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    raw_text TEXT NOT NULL,
    brand_extracted TEXT,
    product_name_extracted TEXT NOT NULL,
    product_name_normalized TEXT NOT NULL,
    upc TEXT,
    quantity NUMERIC,
    unit_price NUMERIC,
    purchase_date DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_receipt_items_name_trgm ON receipt_items USING gin (product_name_normalized gin_trgm_ops);
CREATE INDEX idx_receipt_items_upc ON receipt_items (upc);

-- ============ MATCHING ============

CREATE TABLE match_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    receipt_item_id UUID NOT NULL REFERENCES receipt_items(id),
    recall_id UUID NOT NULL REFERENCES recalls(id),
    confidence NUMERIC NOT NULL,
    method TEXT NOT NULL,                -- upc_exact | fuzzy
    match_features JSONB NOT NULL,       -- {"name_sim":0.82,"brand_match":true,"date_proximity":0.6,...}
    status TEXT NOT NULL DEFAULT 'pending_review',  -- auto_confirmed | pending_review | confirmed | dismissed
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reviewed_at TIMESTAMPTZ,
    UNIQUE (receipt_item_id, recall_id)
);

-- ============ NOTIFICATIONS ============

CREATE TABLE notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    match_candidate_id UUID NOT NULL REFERENCES match_candidates(id),
    channel TEXT NOT NULL DEFAULT 'email',
    status TEXT NOT NULL DEFAULT 'queued',   -- queued | sent | failed | failed_permanent
    dedupe_key TEXT NOT NULL UNIQUE,         -- sha256(user_id + match_candidate_id)
    attempts INT NOT NULL DEFAULT 0,
    sent_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============ JOB QUEUE (Postgres-backed, no broker) ============

CREATE TABLE jobs (
    id BIGSERIAL PRIMARY KEY,
    job_type TEXT NOT NULL,       -- ocr | extract | match_recall | match_receipt | notify
    payload JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',   -- queued | processing | done | failed
    attempts INT NOT NULL DEFAULT 0,
    run_after TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_jobs_pickup ON jobs (status, run_after);
```

**Raw vs canonical:** `raw_ingestions.payload` is the untouched source JSON, kept forever, append-only. `recalls` is the normalized, queryable, current-state table. Never write directly to `recalls` without going through normalization; never mutate `raw_ingestions`.

**Versioning/change detection:** each ingestion run compares the new `content_hash` for a `source_id` against the latest existing raw row. Unchanged: skip. Changed: insert new raw row, re-normalize, `UPSERT` into `recalls` via `ON CONFLICT (source, source_id) DO UPDATE`, diff old vs new canonical row, and if anything meaningful changed (status, dates, hazard classification), insert into `recall_history`.

**pg_trgm usage:** similarity queries look like:

```sql
SELECT id, product_name, similarity(product_name_normalized, :query) AS score
FROM recalls
WHERE product_name_normalized % :query
ORDER BY score DESC
LIMIT 20;
```

The `%` operator uses the trigram index and respects `pg_trgm.similarity_threshold` (set it explicitly per-query with `SET LOCAL pg_trgm.similarity_threshold = 0.3;` rather than relying on the global default).

---

## 3. Recall Ingestion Pipeline

**Flow:** openFDA API → raw insert (dedupe by hash) → normalize → canonical upsert → history diff → watermark update.

**Adapter pattern:**

```python
# adapters/base.py
from abc import ABC, abstractmethod
from datetime import datetime
from dataclasses import dataclass

@dataclass
class RawRecord:
    source_id: str
    payload: dict

@dataclass
class CanonicalRecall:
    source_id: str
    brand: str | None
    product_name: str
    hazard_description: str | None
    hazard_classification: str | None
    status: str
    date_initiated: datetime | None
    date_terminated: datetime | None
    geographic_scope: str | None
    upcs: list[str]

class RecallSourceAdapter(ABC):
    source_name: str

    @abstractmethod
    def fetch(self, since: datetime | None) -> list[RawRecord]:
        ...

    @abstractmethod
    def normalize(self, raw: RawRecord) -> CanonicalRecall:
        ...
```

`OpenFDAFoodAdapter(RecallSourceAdapter)` implements both. `fetch()` calls openFDA's food enforcement endpoint filtered by `report_date` (or `recall_initiation_date`) greater than `since`, paginating through results. `normalize()` maps openFDA's field names (`product_description`, `recalling_firm`, `classification`, `status`, `recall_initiation_date`, etc.) onto `CanonicalRecall`.

**Incremental ingestion:** `ingestion_runs.watermark` holds the last successfully processed date. Each run reads the last successful watermark, fetches only records after it, and advances it only on success. If a run fails partway, the watermark doesn't move, so the next run safely re-fetches the same window (idempotent thanks to the content-hash dedupe).

**Deduplication/idempotency:** two layers. Raw layer: skip insert if `content_hash` unchanged for that `source_id`. Canonical layer: `ON CONFLICT (source, source_id) DO UPDATE` means re-running ingestion never creates duplicate recall rows.

**Rescinded/expanded recalls:** openFDA doesn't delete records, it updates the `status` and sometimes other fields on the same `source_id`. Because normalize/upsert always re-maps the full record, a status change flows through automatically and gets caught by the history diff. No special-case code needed beyond the diff-and-log logic.

**Python project structure:**

```
recall_monitor/
  adapters/
    base.py
    openfda_food.py
  ingestion/
    run_ingestion.py       # entrypoint, called by CronJob
    dedupe.py
  normalization/
    text_normalize.py      # abbreviation expansion, punctuation stripping
  matching/
    matcher.py
    scoring.py
    upc_lookup.py
  receipts/
    ocr.py
    extraction.py
    validation.py
  notifications/
    notifier.py
    templates/
  jobs/
    queue.py                # enqueue/dequeue against the jobs table
    worker.py                # polling loop, dispatches by job_type
  api/
    main.py
    routers/
      receipts.py
      recalls.py
      matches.py
  db/
    models.py                # SQLAlchemy models
    session.py
  migrations/                # alembic
  tests/
    fixtures/
  config.py
```

---

## 4. Receipt Pipeline

**Flow:** upload → S3 → enqueue OCR job → OCR worker → enqueue extraction job → LLM extraction → validation → `receipt_items` rows → enqueue `match_receipt` job.

**OCR service:** AWS Textract's `AnalyzeExpense` API specifically, not generic Textract or Tesseract. It's purpose-built for receipts/invoices, already returns semi-structured key-value pairs (vendor, line items, totals) instead of raw text you'd have to parse yourself. This materially reduces what the LLM step has to do.

**Where the LLM belongs:** cleaning Textract's line-item output into your target schema. Retailers abbreviate wildly and inconsistently (`KRAFT MC&CHZ`, `KRFT MAC CHEESE 12OZ`), which is exactly the kind of format variance a fixed parser handles poorly and an LLM handles well. Give it Textract's structured line items, not raw OCR text, so it's cleaning rather than doing extraction from scratch.

**Where the LLM does NOT belong:** deciding whether a receipt item matches a recall. That's the matching engine's job (section 5), kept separate and rule-based on purpose.

**Expected LLM output schema** (enforce via structured output / function calling, validated against a pydantic model):

```python
class ExtractedItem(BaseModel):
    brand: str | None
    product_name: str
    quantity: float | None
    unit_price: float | None
    upc: str | None

class ExtractedReceipt(BaseModel):
    items: list[ExtractedItem]
    purchase_date: date | None
```

**Validation after extraction:** pydantic handles type/shape. Beyond that: reject items with empty `product_name`, flag `unit_price` outside a sane range (e.g. negative or > $500), flag `purchase_date` outside a sane range (e.g. future dates, dates more than a few years old). Failed validation doesn't silently drop the item, it's written to `receipt_items` with a flag (or a `needs_review` table) so nothing is lost, matching the false-negative-averse principle from the design doc.

---

## 5. Matching Engine

This is the part to get right. Concrete steps:

**Step 1, normalization.** Lowercase, strip punctuation, expand a hand-maintained abbreviation dictionary (`mc&chz` → `macaroni and cheese`, `chz` → `cheese`, etc.), strip unit/size tokens (`12oz`, `2ct`). Apply identically to both `recalls.product_name_normalized` and `receipt_items.product_name_normalized` so they're comparable.

**Step 2, UPC exact match, always tried first.**

```sql
SELECT recall_id FROM recall_upcs WHERE upc = :receipt_item_upc;
```

If found: `confidence = 1.0`, `method = 'upc_exact'`, done for that item. But still fall through to Step 3 as a secondary check (barcodes get OCR'd wrong sometimes), and if fuzzy also produces a high-confidence hit on a *different* recall, surface both rather than assuming the UPC match is exhaustive.

**Step 3, candidate generation (fuzzy path).** Trigram similarity query (shown in section 2) against `recalls.product_name_normalized`, threshold 0.3, top 20 candidates. This is blocking: cheap, index-backed, cuts the field down before the more expensive scoring step.

**Step 4, feature scoring.** For each candidate, compute:

- `name_sim`: trigram similarity score (0-1)
- `brand_match`: 1.0 if brands match exactly, 0.5 if fuzzy brand match, 0 otherwise
- `date_proximity`: 1.0 if purchase date falls within the recall's active window, decaying linearly to 0 over some window (e.g. 6 months) outside it

Combine with an explicit, hand-set weighted sum, not a trained model, for MVP:

```python
confidence = 0.5 * name_sim + 0.3 * brand_match + 0.2 * date_proximity
```

Document these weights in code comments and in your writeup. This is a real, honest v1 that you can defend ("weights chosen manually, replace with a learned scorer once labeled data exists" is a fine interview answer).

**Step 5, thresholds.**

- `confidence >= 0.85` → `status = 'auto_confirmed'` (still shown to the user, just pre-flagged, never silently acted on)
- `0.5 <= confidence < 0.85` → `status = 'pending_review'`
- `confidence < 0.5` → discard, don't write a row (but log the count for observability, section 11)

The 0.5 floor is intentionally low. False negatives are the costly failure mode here; a few extra pending-review notifications the user dismisses is cheap by comparison.

**Storing why a match was made:** `match_candidates.match_features` holds the full feature breakdown as JSON (`{"name_sim": 0.82, "brand_match": 1.0, "date_proximity": 0.6, "normalized_query": "...", "normalized_target": "..."}`). This is what makes the match explainable in a UI or in an interview: you can point at the exact row and say why it fired.

---

## 6. The Two Matching Triggers

Both async, both via the `jobs` table (no external broker). Neither runs synchronously in a request handler; neither is a scheduled poll, both are event-driven, enqueued immediately after the upstream write commits.

**New recall → search historical purchases:**
After the ingestion pipeline upserts a recall and detects it's new or materially changed, it enqueues `job_type = 'match_recall'` with `payload = {"recall_id": ...}`. The matching worker picks it up, runs the matcher (section 5) against *all* `receipt_items` (not just recent ones, a years-old purchase can still match a recall that was just expanded in scope), writes `match_candidates`, and for anything at or above the surfacing threshold, enqueues a `notify` job.

**New receipt → search historical recalls:**
After extraction writes `receipt_items`, enqueue `job_type = 'match_receipt'` with `payload = {"receipt_id": ...}`. The worker runs the matcher for each new item against *all* recalls (not just recent ones). Same downstream: `match_candidates`, then `notify` jobs as warranted.

Both job types are handled by the same matcher function with a different "which side is new" parameter, they're not two separate implementations.

---

## 7. Notifications

**Match → notification:** the `notify` job worker checks `notifications` for an existing row with `dedupe_key = sha256(user_id + match_candidate_id)`. If it exists, skip (already handled, whether sent or still queued). If not, render the email, attempt send, insert a `notifications` row.

**Preventing duplicates:** the unique constraint on `dedupe_key` is the actual guarantee, not just the check-then-insert, since two workers could race. Insert first (catch the unique-violation as "already being handled"), then send, then update status. Or send first and immediately insert with `sent_at` set, catching the rare unique-violation as a no-op (a duplicate email is a much smaller problem than a missed one, so slight preference toward "send then record" is defensible here).

**On delivery failure:** catch the exception, set `status = 'failed'`, increment `attempts`, and if `attempts < 3`, re-enqueue a retry job with `run_after = now() + backoff` (e.g. 5min, 30min, 2hr). After 3 failed attempts, set `status = 'failed_permanent'` and stop retrying automatically, log it for manual review. Don't retry forever on a permanently bad email address.

**Notification record shape:** as defined in the schema, `user_id`, `match_candidate_id`, `channel`, `status`, `dedupe_key`, `attempts`, `sent_at`, `error_message`. That's enough to answer "did this user get notified about this match" and "why did it fail" without joining through five tables.

---

## 8. Infrastructure

**What actually gets built:**

- **API**: one FastAPI service (Deployment, 1-2 replicas). Handles receipt upload, listing recalls, listing/confirming matches.
- **Postgres**: managed (RDS) provisioned via Terraform, or a StatefulSet in-cluster if you want the extra Terraform/K8s practice. Either is defensible; pick one and be explicit about the tradeoff (RDS = less to manage, StatefulSet = more IaC surface to demonstrate).
- **Ingestion**: one K8s CronJob, scheduled every 6-12 hours (openFDA doesn't update faster than that in practice), runs `run_ingestion.py` and exits.
- **Worker**: **one** Deployment running a polling loop against the `jobs` table (`SELECT ... FOR UPDATE SKIP LOCKED`), dispatching by `job_type` to OCR, extraction, matching, and notification handlers. Not three or four separate services. At this volume (one household, occasional uploads, a few hundred jobs a day at most) splitting these into separate deployments adds operational surface with no real benefit. Split later only if you can point to an actual bottleneck.
- **Queue**: the Postgres `jobs` table. Explicitly not Kafka, not RabbitMQ, not Redis. Those solve problems you don't have: this system's throughput is trivially low, and `SKIP LOCKED` polling is a well-understood, well-documented pattern that does the job. Adding a broker here would be complexity you can't defend in an interview, "why did you need Kafka for a few hundred jobs a day" doesn't have a good answer.
- **S3**: one bucket for receipt images, lifecycle rule enforcing the 90-day retention policy at the bucket level (not just app-level deletion logic, belt and suspenders).
- **Terraform**: provisions the K8s cluster (or at least namespace/deployments/cronjobs if using an existing cluster), RDS instance or Postgres StatefulSet manifest, the S3 bucket + lifecycle rule, IAM roles, SES configuration, secrets. This is real infrastructure, worth the Terraform effort.

**Final K8s object count:** 1 API Deployment, 1 Worker Deployment, 1 Ingestion CronJob, Postgres (RDS or StatefulSet), S3 bucket. That's it for MVP.

---

## 9. Repository Structure

```
recall-monitor/
  recall_monitor/          # Python package, structure as in section 3
  migrations/               # alembic
  tests/
    unit/
    integration/
    fixtures/               # saved raw openFDA payloads, saved receipt OCR outputs
    eval/                   # labeled matcher evaluation set + script (section 10)
  docker/
    api.Dockerfile
    worker.Dockerfile
    ingestion.Dockerfile
  k8s/
    api-deployment.yaml
    worker-deployment.yaml
    ingestion-cronjob.yaml
    (or a Helm chart if you want to demonstrate that too)
  terraform/
    main.tf
    rds.tf / postgres.tf
    s3.tf
    iam.tf
    ses.tf
  docker-compose.yml         # local dev: postgres + api + worker
  README.md
  pyproject.toml
```

---

## 10. Testing Strategy

- **Ingestion**: unit-test `adapter.normalize()` against saved real openFDA JSON fixtures (pull 10-15 real records once, commit them to `tests/fixtures/`). Assert correct field mapping. Unit-test the watermark/incremental logic with a mocked source.
- **Normalization**: unit tests for the abbreviation/punctuation pipeline, including edge cases (empty string, all-caps, unicode, numbers-only).
- **Database**: integration tests against a real test Postgres (docker-compose or testcontainers) verifying the upsert produces a `recall_history` row on change and no-ops on an unchanged re-run.
- **Matching**: this is the one that needs real rigor, see the labeled dataset approach below.
- **Receipt extraction**: unit tests feeding saved Textract outputs (a handful of real or realistic fixtures) through the LLM extraction step, asserting pydantic validation passes and catches malformed cases.
- **Notifications**: test the dedupe path directly (enqueue the same match twice, assert one email), and the failure/retry path with a mocked email client that raises.
- **End-to-end**: one or two integration tests running the full chain, a fixture recall ingested, a fixture receipt processed, asserting a `notifications` row lands with `status='sent'`.

**Labeled matcher evaluation dataset, concretely:**

1. Pull 30-50 real ingested recalls from your dev database.
2. Hand-write 40-60 synthetic `receipt_items` rows: some true positives (should match a specific recall), some true negatives (plausible grocery items that shouldn't match anything), and a handful of deliberately hard near-misses (same brand, different product; same product, different brand; close-but-wrong dates) to stress-test the scorer.
3. Store this as `tests/eval/labeled_matches.csv` with columns `receipt_item_text, expected_recall_id_or_null`.
4. Write `tests/eval/run_eval.py` that runs the matcher against every labeled item, compares predicted matches against expected, and prints precision/recall/F1.
5. Re-run this script any time you touch the scoring weights or thresholds. This becomes your actual evidence, in an interview, for "how do you know your matcher works," rather than "I tried a few examples and it looked right."

---

## 11. Observability / Data Quality

- `ingestion_runs` already gives you a queryable run history (rows fetched, rows changed, duration, errors). Don't build a separate metrics system for this, query the table.
- Structured (JSON) logging at each pipeline stage, minimum: ingestion run start/end with counts, matcher run with candidate counts and threshold hit rates, notification send/fail.
- Data quality check after each ingestion run: null-rate on required canonical fields (`product_name`, `status`), alert (log at ERROR level is enough for MVP, no need for a real alerting pipeline) if a run returns 0 records when it expected more than 0.
- Track the distribution of match confidences over time (even just a periodic query, no dashboard needed) so you can tell if your matcher's behavior is drifting as more recalls/receipts accumulate.
- Prometheus/Grafana: explicitly out of scope until the core pipeline is proven end to end. It's a nice addition if time remains, not a phase-1 dependency, don't let it become a distraction from the matcher itself.

---

## 12. Build Sequence

### Phase 0: Foundation
- [ ] Repo skeleton per section 9
- [ ] `docker-compose.yml` with Postgres, `pg_trgm` enabled
- [ ] Alembic migration for the full schema (section 2)
- **Done when:** `docker-compose up`, migration applies cleanly, all tables exist.
- **Test before moving on:** connect and manually insert/query one row in each table.
- **Don't build yet:** anything else.

### Phase 1: Recall ingestion
- [ ] `RecallSourceAdapter` base class + `OpenFDAFoodAdapter`
- [ ] `fetch()` against the real openFDA API, save 10-15 real responses as fixtures
- [ ] `normalize()` mapping raw → canonical, unit-tested against fixtures
- [ ] `run_ingestion.py`: fetch → hash-dedupe raw insert → normalize → canonical upsert → history diff → watermark update
- **Done when:** running the script against the real API populates `recalls` correctly, and running it twice in a row produces zero duplicate rows and zero spurious history entries.
- **Test before moving on:** unit tests on `normalize()`, one manual full run against live data, one re-run to confirm idempotency.
- **Don't build yet:** receipts, matching, API, infra.

### Phase 2: Matching engine (against seeded data)
- [ ] Text normalization pipeline + abbreviation dictionary
- [ ] Manually seed 15-20 fake `receipt_items` rows via direct SQL insert
- [ ] UPC exact match path
- [ ] Fuzzy candidate generation (`pg_trgm` query)
- [ ] Feature scoring + weighted confidence
- [ ] Thresholding into `match_candidates`
- [ ] Labeled eval dataset + `run_eval.py` (section 10), get a baseline precision/recall number
- **Done when:** the eval script runs and produces a defensible precision/recall on your labeled set, and you can explain every weight and threshold choice.
- **Test before moving on:** the eval script, plus manual spot-checks on a few `match_features` rows to confirm the explainability data is actually useful.
- **Don't build yet:** OCR, LLM extraction, notifications, infra.

### Phase 3: Receipt pipeline
- [ ] S3 upload flow (or local disk for pure local dev, swap later)
- [ ] Textract `AnalyzeExpense` integration
- [ ] LLM extraction step with the `ExtractedReceipt` pydantic schema
- [ ] Validation layer (reject/flag malformed items, never silently drop)
- [ ] Wire extracted items into `receipt_items`, replacing the manual seeding from Phase 2
- **Done when:** uploading a real receipt image produces correct `receipt_items` rows end to end, and the Phase 2 matcher runs against them unchanged.
- **Test before moving on:** unit tests against saved fixture OCR outputs, one manual real-receipt run.
- **Don't build yet:** async job wiring (this phase can still run synchronously/manually for testing), notifications.

### Phase 4: Async wiring + notifications
- [ ] `jobs` table + `SKIP LOCKED` worker polling loop
- [ ] Enqueue `match_recall` after ingestion, `match_receipt` after extraction
- [ ] `notify` job: dedupe check, email send (SES/SendGrid), retry/backoff, failure handling
- **Done when:** an end-to-end run (new recall ingested, or new receipt uploaded) results in a real email landing in your inbox with no manual steps.
- **Test before moving on:** the dedupe test (enqueue same match twice, confirm one email), the failure/retry test with a mocked client.
- **Don't build yet:** infra beyond `docker-compose`, frontend.

### Phase 5: API layer
- [ ] FastAPI endpoints: upload receipt, list recalls, list matches, confirm/dismiss match
- [ ] Minimal frontend or even just Swagger/OpenAPI docs as the "UI" for now
- **Done when:** you can drive the full flow (upload → see matches → confirm/dismiss) through the API without touching the database directly.
- **Test before moving on:** basic API integration tests for each endpoint.
- **Don't build yet:** anything beyond these four endpoints.

### Phase 6: Infra
- [ ] Dockerfiles for API, worker, ingestion
- [ ] K8s manifests: API Deployment, Worker Deployment, Ingestion CronJob
- [ ] Terraform: cluster/namespace, Postgres, S3 + lifecycle rule, IAM, SES
- **Done when:** the full system runs in a real (or local kind/minikube) cluster, provisioned from Terraform, not just docker-compose.
- **Test before moving on:** a real ingestion CronJob run in-cluster, a real receipt upload through the deployed API.
- **Don't build yet:** Prometheus/Grafana, anything from the "later" feature list.

### Phase 7: Hardening
- [ ] Expand the labeled eval dataset, re-tune weights/thresholds if precision/recall is weak
- [ ] Data quality checks + structured logging pass across all stages
- [ ] End-to-end integration tests
- [ ] README documenting architecture, schema, and the matcher's weighting rationale (this is your interview prep document as much as a README)

---

## Do This Today

1. `docker-compose.yml` with Postgres + `pg_trgm`, confirm it starts.
2. Write and run the Alembic migration for the schema in section 2.
3. Write `adapters/base.py` and `adapters/openfda_food.py`, call `fetch()` against the real openFDA API, save the raw JSON responses you get into `tests/fixtures/openfda_food/`.
4. Write `normalize()` against those fixtures, with a unit test asserting correct field mapping for at least 3 of them.
5. Write `run_ingestion.py` and run it for real: fetch, dedupe, normalize, upsert. Query `recalls` afterward and confirm real data landed correctly. Run it a second time and confirm zero duplicate rows.

Everything else waits until this works.

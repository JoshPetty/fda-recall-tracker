# adapters/

Isolation layer between "how a recall source's API/data actually looks" and
"what this codebase needs a recall to look like."

## Why this exists

Every recall source (openFDA food, later CPSC, later FSIS) has its own API
shape, field names, pagination, and quirks. Without this layer, that mess
leaks into ingestion, normalization, the database, everywhere. With it,
one adapter owns exactly one source's weirdness, and nothing outside this
folder needs to know that field is called `recalling_firm` instead of
`brand`, or that dates come back as `YYYYMMDD` strings.

Add a new source later, add one file here. Nothing else changes.

## Structure

- `base.py` — the contract every adapter implements. Two methods:
  - `fetch(since)`: hit the source's API, return raw records as-is
  - `normalize(raw)`: map one raw record onto the shared `CanonicalRecall` shape
- `openfda_food.py` — the openFDA food enforcement implementation of that
  contract. This is the only file that should know openFDA's field names.

## Rules

- `fetch()` returns raw data untouched. No cleanup, no interpretation, no
  guessing. That's `normalize()`'s job. Keeping them separate means you can
  always go back to a raw record and re-normalize it if your mapping logic
  changes or turns out to be wrong.
- `normalize()` never calls the network and never touches the database.
  Pure function: raw record in, `CanonicalRecall` in, `CanonicalRecall` out.
  That's what makes it trivially unit-testable against saved fixtures.
- Nothing outside `adapters/` should import from `requests` or know an
  openFDA field name exists. If you find yourself doing that in
  `ingestion/` or `matching/`, something's leaking and belongs back here.
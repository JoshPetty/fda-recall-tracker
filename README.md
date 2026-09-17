# Recall Monitor

Pulls the FDA's food recall feed, makes it searchable, and checks it against stuff you actually bought. That's it, that's the app.

## Why this exists

The openFDA enforcement feed is public, complete, and basically unusable to a normal person. It's free text, inconsistent formatting, no fuzzy matching, no "hey this affects you" layer on top. Nobody is going to read a government JSON feed to find out their noodles got recalled. So this project does the boring part (ingest, normalize, store) and the slightly less boring part (match a receipt line item or a typed product name against it) so a human never has to look at raw FDA data.

## What's been done so far

- Public recall browsing and search, no login needed, filterable by state. `frontend/recall-monitor-app/app/recalls/`.
- Type a product name, get back anything that might be it. `backend/api/main.py`, one endpoint, does the whole job.
- Ingestion that actually runs on a schedule-shaped design, keeps history of what changed, and re-derives structured location data out of garbage free text. `backend/ingestion/run_ingestion.py`.

Receipt photo scanning, email notifications, and an actual job queue are not built. The schema for jobs and notifications exists in `backend/db/models.py` waiting to write the code.

## Where things live

```
backend/                        Python: FastAPI, ingestion, matching, Alembic migrations
frontend/recall-monitor-app/    Expo app, nested inside this repo on purpose
STATUS.md                       what's actually done, what's pending, what's a lie
BACKEND.md                      real backend architecture writeup
FRONTEND.md                     real frontend architecture writeup
```


## Stack

Python, FastAPI, SQLAlchemy, Alembic, Postgres via Supabase (Auth, RLS, `pg_trgm`), Expo, React Native, Expo Router.

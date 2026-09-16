# Recall Monitor: Status

Last updated: after adding structured location data for recalls (`recall_states` + `is_nationwide`/`parse_status` on `recalls`, parsed out of the free-text `geographic_scope` field) and a state filter on recall browsing.

## Repo layout

Restructured (this session), file organization only, no logic changes:

- `recall-monitor-app` lives nested inside this repo, as a deliberate monorepo (see "Mobile app" below) — briefly split out to a sibling repo and reverted the same session, since backend and app share one schema and one status doc, and for a single-person project this size the coordination overhead of two repos outweighed the separation. Its brief sibling-repo history (one commit) was discarded, not merged, on revert.
- `scripts/` split into `scripts/ops/` (real, rerunnable, documented tools: `backfill_normalized_names.py`, `backfill_recall_states.py`) and `scripts/dev/` (exploratory/debug scripts: `fetch_fixtures.py`, `seed_receipt_items.py`, `run_matcher.py`, `check_upc_lookup.py` — renamed from `test_upc_lookup.py`, since it's a manual debug script, not a pytest test, and the old name risked pytest collecting and running it against the live Supabase database if `pytest` were ever invoked from the repo root instead of scoped to `tests/`).
- `recall-monitor-build-plan.md` moved to `docs/archive/recall-monitor-build-plan.md`, with a note at its top that it's superseded by this file.

## Stack

- Backend logic (ingestion + matching): Python, unchanged since Phase 1-2.
- Database: Supabase (managed Postgres). Migration complete, schema applied, in active use. Local Docker Postgres no longer in use.
- Connection: Supabase session pooler (`aws-0-us-east-1.pooler.supabase.com:5432`), not the direct connection endpoint (`db.<ref>.supabase.co`), because the direct endpoint resolves IPv6-only and this network environment has no outbound IPv6 route.
- Python code execution location: not yet decided/set up. Currently run manually from a local machine, not on any scheduled host.
- Mobile app: Expo, at `recall-monitor-app` (nested inside `recall-monitor` — a deliberate monorepo, see "Repo layout" above). An unrelated, unused scaffold that briefly sat at the sibling path `~/projects/recall-monitor-app` during this session's repo-layout experiment has been permanently moved aside to `~/projects/_unused-expo-scaffold-sep16` — don't confuse the two if that path ever gets reused. `create-expo-app` blank-typescript template, Expo SDK 57, Expo Router 57, TypeScript. NativeWind and `@react-native-community/netinfo` are still just targeted, not yet added.
- Backend API: FastAPI, at `api/main.py`. One endpoint so far (`POST /match`, see "Paste-text receipt flow" below). Run locally with `uvicorn api.main:app` (add `--reload` for dev); no deployment/infra yet, matches how ingestion is currently run manually.
- OCR: Tesseract (local), prototyped standalone (`receipts/ocr.py`), not wired into a pipeline. AWS Textract was evaluated and not used, after AWS account access issues.
- Auth: Supabase Auth magic-link sign-in wired into the Expo app (see "Auth (Expo app)" below). `users` table migration from standalone identity table to a profile table referencing `auth.users.id` is written and applied.

## Database

12 schema tables + `alembic_version`, applied to Supabase via the existing Alembic migration, unchanged from the original schema. `pg_trgm` extension confirmed enabled on Supabase. Both trigram GIN indexes (`recalls.product_name_normalized`, `receipt_items.product_name_normalized`) present.

Ingestion has been run against Supabase at least once, completed without error.

Database password was reset after being shared in a chat conversation.

**Migration `cc71d2485e36_users_reference_auth_users` applied** (`alembic upgrade head` completed without error). Drops the `gen_random_uuid()` server default on `users.id` and adds `fk_users_id_auth_users`: `public.users.id` → `auth.users.id` `ON DELETE CASCADE`. Ran `TRUNCATE TABLE users CASCADE` first (safe at this point, no real auth-tied users existed before this migration). Verified directly against `information_schema`: `users.id` has no default, and `fk_users_id_auth_users` exists on `public.users` referencing `auth.users`. `db/models.py`'s `User.id` matches (`ForeignKey("auth.users.id", ondelete="CASCADE")`, no server default).

**Migration `2f082500b25a_add_row_level_security_policies` is APPLIED.** Correction to the previous status here, which said it hadn't been run yet: checked `alembic_version` directly against Supabase while testing the new recall screens (below) and it's already at `2f082500b25a`, and `pg_class.relrowsecurity` is `true` on `recalls`. Not sure when/by whom it was applied since this file wasn't updated at the time — worth confirming nothing else changed out of band.

**Migration `1a0a76ba3dbc_grant_recalls_select_to_anon` is PENDING, NOT YET APPLIED — same as prior migrations, do not run this against Supabase without review.** Extends the existing `{table}_select_authenticated` policies on `recalls`, `recall_upcs`, `recall_history` (`2f082500b25a`, above) from `authenticated`-only to `authenticated, anon` via `ALTER POLICY ... TO`, so unauthenticated (public) requests can read these tables. Same read-only posture, no INSERT/UPDATE/DELETE for either role. This is what the newly-public recall browse/search screens (below) need in order to actually return data for a signed-out visitor — until this is applied, those screens render correctly but recall queries return `200` with an empty array (RLS silently filters all rows for `anon`, confirmed below).

What it does: enables RLS on every table in `public` (including `alembic_version`, for completeness) and adds a `public.current_household_id()` SQL helper (`SECURITY DEFINER`, looks up `household_id` from the `users` row matching `auth.uid()`) that the household-scoped policies share instead of repeating the join. Access by table:

- `households` — SELECT + UPDATE for members of that household. **No INSERT/DELETE policy**: a brand-new user has no `users` row yet at signup time, so there's no household to check an insert against. Household creation for onboarding isn't wired up yet — needs a deliberate design (e.g. a `SECURITY DEFINER` function, or done backend-side) before the app can self-serve new households. Tracked below under "Not started."
- `users` — SELECT + UPDATE scoped to your own household (so household members can see/edit each other's profile rows, matching the general household-scoped rule), plus INSERT restricted to `id = auth.uid()` (your own profile row on first sign-up). **No DELETE policy** — profile deletion should follow from deleting the `auth.users` row (cascades via the existing FK), not a direct client delete of just the profile row.
- `receipts` — full SELECT/INSERT/UPDATE/DELETE scoped to your household (`household_id = current_household_id()`).
- `receipt_items` — full read/write, household derived by joining up to the parent `receipts` row.
- `match_candidates` — full read/write, household derived by joining `receipt_items` → `receipts`.
- `notifications` — full read/write, household derived by joining to the owning `users` row (so any member of the household can see/manage a notification addressed to any member — matches how the requirements grouped this table with the household-scoped set, not a per-user-only restriction).
- `recalls`, `recall_upcs`, `recall_history` — SELECT-only for any authenticated user (public openFDA data); no INSERT/UPDATE/DELETE policy, so only the backend's service-role-equivalent connection (which bypasses RLS via table ownership) can write to them.
- `raw_ingestions`, `ingestion_runs`, `jobs`, `alembic_version` — RLS enabled, zero policies. `anon`/`authenticated` get no access at all; only a service-role/table-owner connection can touch them.

Not verified yet against a live household/receipt scenario (e.g. confirming a second household's user genuinely can't see the first household's receipts) — do that after applying, ideally before shipping any client feature that relies on RLS instead of the backend for isolation.

**Migration `66f2630fb756_add_recall_states` is PENDING, NOT YET APPLIED — same as prior migrations, do not run this against Supabase without review.** Adds structured location data on top of the existing free-text `recalls.geographic_scope`:

- `recalls.is_nationwide` (boolean, default `false`) and `recalls.parse_status` (text, default `'unparsed'`, `CHECK`-constrained to `'parsed'`/`'unparsed'`).
- `recall_states`: one row per `(recall_id, state_code)` pair — a recall can span multiple states, so this is the many-to-many join, not a column on `recalls`. `UNIQUE(recall_id, state_code)`, indexed on `state_code` for the app's filter. FK to `recalls.id` `ON DELETE CASCADE`.
- RLS: `recall_states` gets RLS enabled and one policy, `recall_states_select_public`, `SELECT` for `anon` and `authenticated` directly (`USING (true)`) — no INSERT/UPDATE/DELETE, matching `recall_upcs`'s read-only posture. Unlike `recall_upcs`/`recalls` (which started `authenticated`-only in `2f082500b25a` and only got `anon` added later in `1a0a76ba3dbc`), this one grants both roles from the start since recall browsing is already public by the time this migration was written.
- `db/models.py` updated to match (`Recall.is_nationwide`, `Recall.parse_status`, new `RecallState` model).

See "Ingestion pipeline" and "Recall browse/detail screens" below for how this gets populated and used.

## Ingestion pipeline

Unchanged in logic from before the Supabase migration: `adapters/openfda_food.py`. Fetch/normalize/upsert/watermark/history-diff behavior as previously documented. Re-verified working against Supabase, not just local Postgres.

**Structured location parsing (this session) — `normalization/geo_parse.py`, `ingestion/run_ingestion.py`.** `recalls.geographic_scope` is openFDA's free-text `distribution_pattern` field, and its format is inconsistent across records (plain "Nationwide.", "MD, VA", "Domestic: AZ, CA... Foreign: Not applicable.", full state names, bare city lists, etc — see the module docstring in `geo_parse.py` for the taxonomy). `parse_geographic_scope(text)` reads it into `ParsedGeography(is_nationwide, parse_status, state_codes)`:

- Nationwide language ("nationwide", "United States", "USA", "all 50 states", "throughout the U.S.") short-circuits to `is_nationwide=True` with no state extraction attempted, even if the text also happens to name a country or two (real example: a distribution list that says "Nationwide in the United States..." and separately lists foreign countries including "Georgia" — the nationwide check fires first, so "Georgia" the country never gets a chance to be misread as Georgia the state).
- Otherwise, state codes are read two ways: (1) exact, standalone, **all-caps** two-letter USPS abbreviations against a fixed 51-entry list (50 states + DC), and (2) full state names matched case-insensitively as whole words/phrases against the same list.
- **Required collision check #1 ("OR" vs. "or"):** abbreviation matching requires the all-caps form specifically so ordinary lowercase prose ("or") never matches — validated both by unit test and by running the parser against a real record from the live database containing the ordinary word "or" in a sentence (`"...No schools or institutional distribution."`) alongside a genuine state mention (the full word "Oregon" elsewhere in the same sentence): result correctly picked up `OR` (from "Oregon") and did not fire on the prose "or". Also checked every real all-caps 2-letter token in the current 1,357-row dataset that *isn't* a recognized state code (`PR`, `GU`, `US`, `VI` — territories/country abbreviation, not ordinary words) to confirm there's no other collision risk in the actual data.
- **Required collision check #2 ("Washington DC" vs. Washington state):** full-name matching would misread "Washington DC" as Washington *state* if not handled — "Washington,? D\.?C\.?" is rewritten to just "DC" before full-name matching runs, so it's read as the district. Verified against the real records in the data that write it this way (e.g. `"Washington DC, DE, GA, MD, NC, NJ, NY, PA, SC, VA."` → `DC, DE, GA, ...` with no spurious `WA`), and separately verified a record where both the district and the actual state legitimately appear still keeps both.
- Anything that doesn't match either pattern gets `parse_status='unparsed'` and no state codes — deliberately not guessed. Full-text unit tests for all of the above (including both collision cases) are in `tests/unit/test_geo_parse.py`.
- Extending abbreviation-only matching (what was explicitly asked for) to also cover full state names was a judgment call made after checking the real data: a large fraction of real `geographic_scope` values spell states out in full ("Texas", "distributed to the following states: Alabama, Arizona, ...") rather than abbreviating, and leaving those all as `unparsed` would have made the unparsed bucket mostly not-actually-unparseable data. Full names carry essentially none of the abbreviation collision risk (no common English word is "California"), and this was checked empirically against every occurrence of the more ambiguous-looking names (Washington, Georgia, Virginia, Jersey) in the live dataset before committing to it.
- Unrelated, pre-existing issue noticed while running the full test suite for this change: `tests/unit/test_openfda_food_adapter.py::test_normalize_with_multiple_upcs` fails on a timezone-aware vs. naive `datetime` comparison (`_parse_date` in `adapters/openfda_food.py` now returns tz-aware datetimes, the test asserts against a naive one). Not touched by this change, not fixed here — flagging since it showed up in the same `pytest` run as the new `test_geo_parse.py` tests (which all pass).
- `ingestion/run_ingestion.py`: new `sync_recall_states(session, recall, geographic_scope)`, called from both branches of `upsert_canonical` (new recall, and existing recall) — unconditionally, the same way `product_name_normalized` is unconditionally recomputed, so a future fix to the parser gets picked up on the next ingestion run instead of staying silently stale on old rows. Takes `geographic_scope` as an explicit argument rather than reading it off the ORM object, because in the existing-recall path the object's `geographic_scope` is still the *old* value at the point it's called (the field update happens later in that function) — reading it directly would have silently parsed stale text on the one run where the location actually changed. (Caught this while writing it, not after — flagging because it's the kind of bug that only shows up on a recall whose distribution area is later corrected/expanded, which is easy to miss in testing.)

**Backfill — `scripts/ops/backfill_recall_states.py`**, matching the shape of `scripts/ops/backfill_normalized_names.py`. **Not run against Supabase**, since it depends on `66f2630fb756` (above), which isn't applied yet — running it now would fail (`recall_states` doesn't exist, `recalls.is_nationwide`/`parse_status` don't exist). Two things stand in for "did I run it" until you apply the migration and this can run for real:
- Ran the actual parsing logic (`parse_geographic_scope`, unmodified) read-only against all 1,357 real `geographic_scope` values currently in the `recalls` table (via a plain `SELECT`, no writes) to get real numbers: **1,020 parsed, 309 nationwide, 28 unparsed** (75.2% / 22.8% / 2.1%). Spot-checked every distinct unparsed value (23 of them) — genuinely unparseable free text (e.g. "Products are sold directly to consumers via firm's online website.", city names with no state, "Puerto Rico" alone — a territory, correctly not treated as one of the 50 states).
- Separately smoke-tested the backfill script's actual write path (the delete-old/insert-new `recall_states` rows, `is_nationwide`/`parse_status` assignment) against a throwaway in-memory SQLite database seeded with real `geographic_scope` samples pulled read-only from Supabase — confirming the ORM writes work end to end, including both collision cases above, and that a second pass is a no-op (idempotent, 0 rows touched). This never touched Supabase.
- Once you've applied `66f2630fb756`, run `scripts/ops/backfill_recall_states.py` for real — it prints the same parsed/nationwide/unparsed breakdown as it runs.

## Matching engine

Unchanged in logic from before the Supabase migration: `matching/upc_lookup.py`, `matching/scoring.py`, `matching/matcher.py`. Not re-tested against Supabase specifically since the migration; last verified test run was against local Postgres with the 11-row seed set (5 fuzzy true positives, 5 negatives, 1 UPC-exact true positive with 5 correctly-returned duplicate-UPC candidates).

## Auth (Expo app)

- `lib/supabase.ts`: Supabase JS client, `AsyncStorage`-backed session persistence, `flowType: 'pkce'`, `detectSessionInUrl: false` (handled manually instead — see below). Reads `EXPO_PUBLIC_SUPABASE_URL` / `EXPO_PUBLIC_SUPABASE_ANON_KEY` from `.env`.
- `context/AuthContext.tsx`: `AuthProvider` + `useAuth()`. Loads the persisted session on mount, subscribes to `onAuthStateChange`, exposes `session`, `isLoading`, `signInWithMagicLink(email)`, `signOut()`. Listens for the magic-link deep link (`Linking.addEventListener('url')` + `getInitialURL()` for cold starts) and calls `exchangeCodeForSession`.
- `app/_layout.tsx`: wraps the app in `AuthProvider`; redirects into `/login` if unauthenticated and inside the `(app)` group, back to `/` if authenticated and sitting on `/login`. Now also carries an explicit `PUBLIC_ROUTE_SEGMENTS` allowlist (currently just `recalls`) checked before that redirect fires, as a second, explicit line of defense beyond just "this route isn't nested under `(app)`" — see "Public recall browsing" below for why.
- `app/login.tsx`: email input, "Send magic link" button, "check your email" confirmation state.
- `app/(app)/_layout.tsx`: protected route group, now gating only `scan.tsx` (the paste-text product-check screen) since the home screen and recall screens moved out — see below.
- `app/index.tsx`: home screen, now public (moved out of `(app)`). Signed out: recall-browsing copy, a "Browse recalls" link, and a "Sign in" link. Signed in: unchanged from before — email, "View recalls", "Check a product" (still gated, see below), sign out.
- Real `EXPO_PUBLIC_SUPABASE_ANON_KEY` (a Supabase publishable key, not the legacy `anon` key, though the env var name was kept as-is) has been put into `recall-monitor-app/.env`, replacing the earlier placeholder.

## Recall browse/detail screens (first real app screens)

`app/recalls/index.tsx` and `app/recalls/[id].tsx`, read-only, direct Supabase client queries (no new backend endpoint) against `recalls` and `recall_upcs`. List screen paginates 25 rows at a time via `.range()` (1,357 real rows in the table, confirmed below), ordered by `date_initiated` descending, with a "load more" on scroll. Detail screen shows the full recall record plus its UPCs (or "No UPCs on file."). Both have explicit loading and empty states. No insert/update/delete UI anywhere, matching the RLS design (client can't write to `recalls`).

Reviewed against the "Design constraints" section below and against the existing `login.tsx`/home screens: no violations found in either the pre-existing screens or the new ones (checked for gradients, pill-shaped buttons, emoji, em dashes, decorative animation).

**Public recall browsing (this session).** Moved `app/(app)/recalls/` to `app/recalls/`, out of the auth-gated `(app)` route group, so recall browsing/search works without an account. The paste-text "Check a product" screen (`app/(app)/scan.tsx`) and everything else under `(app)` is untouched and still gated exactly as before. `app/_layout.tsx`'s redirect logic was updated with an explicit `PUBLIC_ROUTE_SEGMENTS` allowlist (see "Auth (Expo app)" above) rather than relying only on the files no longer being nested under `(app)`. The home screen (`app/index.tsx`, also moved out of `(app)`) now renders different content for signed-out vs. signed-in visitors instead of being gated itself.

This relies on the new `1a0a76ba3dbc_grant_recalls_select_to_anon` migration (see "Database" above) to actually return data for signed-out requests — that migration is written but **not yet applied**, pending review.

**State filter (this session).** `app/recalls/index.tsx` now has a "Filter" control above the list: a plain button showing the current selection ("All states" by default), which opens a plain bordered list of options when tapped (no new dependency, e.g. no picker library — a manually-built list, consistent with the design constraints below and the existing plain-layout screens). Options: "All states" (default), "Nationwide", one entry per state code that actually appears in `recall_states` (fetched once on mount, so there's nothing to pick that would always come back empty), and "Unknown or other" (surfaces `parse_status = 'unparsed'` recalls rather than hiding them). Selecting a state issues an inner-joined query (`recalls.select('..., recall_states!inner(state_code)').eq('recall_states.state_code', code)`) so only recalls with a matching `recall_states` row come back; "Nationwide" and "Unknown or other" filter on `recalls.is_nationwide`/`parse_status` directly. Pagination resets to page 0 on every filter change.

**Testing:** `npx tsc --noEmit` and `npx expo export -p web` both pass with the filter added. Whether the filter actually *works* against real data is **not verified** — it depends on the `66f2630fb756_add_recall_states` migration (see "Database" above), which isn't applied yet, so `recall_states` doesn't exist in the live database right now. What was verified instead, driving the actual running app the same way as the signed-out check above:
- With no session, at `/recalls`: the filter button and options list render correctly, showing "All states" / "Nationwide" / "Unknown or other" with no state codes listed (expected — the `recall_states` fetch gets a real `404` from PostgREST, `"Could not find the table 'public.recall_states'"`, handled by the existing `if (statesError || !data) return;` guard, so it just leaves the state list empty rather than crashing).
- Selecting "Nationwide" updates the button label and issues the expected query (`.../recalls?...&is_nationwide=eq.true...`), which comes back as a real `400` from PostgREST (`"column recalls.is_nationwide does not exist"`) — rendered through the screen's existing error-text path, not a crash. This confirms the query-building code itself is wired correctly (right table, right column, right join syntax for the state case), and that it fails the same way the rest of this feature currently does: gracefully, waiting on the pending migration, not with a broken UI.
- Did not verify: actual filtered results rendering with real data once `recall_states` is populated (needs the migration applied plus `scripts/ops/backfill_recall_states.py` run for real) — do that once you've applied `66f2630fb756`.

**Testing:** could not complete a full click-through of the running app (home → recalls list → recall detail) as an authenticated user, because that requires clicking a magic-link email and I don't have access to the target inbox (`joshuapetty@live.com`) — same auth-flow blocker already logged above. Verified instead:
- `npx tsc --noEmit` passes clean.
- `npx expo export -p web` bundles successfully with the new routes included (no build errors).
- Confirmed via a direct Postgres connection (owner role) that `recalls` has 1,357 real rows and RLS is enabled.
- Ran the screens' exact queries (list, detail-by-id, UPCs-by-recall_id) against the live DB with the session role set to `authenticated` and `request.jwt.claim.sub` set to the one real `auth.users` row that exists (`joshuapetty@live.com`, no `public.users`/household row yet — irrelevant here since the `recalls`/`recall_upcs` policies only require `authenticated`, not a household match). All three returned real rows, e.g. recall id `bc062f21-b5bd-481a-9c72-3fe8683ba907` ("Outshine Fruit Bars Tangerine...", Class II, UPC `041548612041`).

This confirms the query/RLS path works for an authenticated session, but the actual login → navigate → render path inside the running app is still unverified end-to-end. Do that once the magic-link round trip (see "Not yet verified" above) is confirmed working.

**Signed-out verification (this session) — actually driven through the running app, not just reasoned about.** Unlike the authenticated flow above, this didn't need a real login, so it could be tested end-to-end for real: started `npx expo start --web`, and drove it with a headless Chromium via Playwright (installed fresh into the scratchpad; system shared libs it needed — `libnspr4`/`libnss3`/`libasound2t64` — weren't present and there's no root/sudo in this environment, so they were `apt-get download`'d as `.deb`s and extracted locally with `dpkg -x` rather than installed system-wide, then pointed at via `LD_LIBRARY_PATH`; no system changes made). No project skill covered running this app yet — worth `/run-skill-generator` next time.

- Navigated to `/` with no session: rendered the signed-out home copy ("Search and browse food recall records without an account...", "Browse recalls", "Sign in"), no redirect to `/login`, URL stayed at `/`. Screenshot confirmed visually.
- Navigated directly to `/recalls` with no session: URL stayed at `/recalls` (no redirect to `/login`), rendered "Recalls" / "No recalls found." — no crash, no error text. Confirms the `PUBLIC_ROUTE_SEGMENTS` exemption in `app/_layout.tsx` actually works, not just reads correctly.
- Captured the network response for the underlying Supabase REST call directly: `GET .../rest/v1/recalls?...` → `200`, body `[]`. This is RLS silently returning zero rows for the `anon` role rather than an error, which is exactly the expected pre-migration state — confirms the screen and the redirect logic are both correct, and that the remaining gap is purely the not-yet-applied `1a0a76ba3dbc` migration. No console errors either.
- Did not test the `/recalls/[id]` detail screen's rendered UI (only the list), and didn't re-test this after the migration is applied — worth a quick re-check once you've applied it, to confirm real rows actually render for a signed-out visitor, not just that the plumbing is correct.

**Verified so far, running via `npx expo start --web`:**
- App loads and correctly redirects to `/login` when unauthenticated.
- Submitting an email on the login screen successfully triggers `signInWithOtp` and the magic-link email is sent immediately.
- Clicking the emailed magic link returned the browser to `/login` rather than an authenticated screen — no `?code=` parameter was confirmed present or absent in the resulting URL before moving on to the next issue below.
- Supabase dashboard's Authentication → URL Configuration was updated (Site URL and Redirect URLs pattern added for `http://localhost:8081`) as a suspected fix for the above, on the theory that an un-allow-listed redirect URL causes Supabase to silently drop the auth code. Not yet re-tested after this change.
- Further magic-link attempts hit Supabase's built-in email provider's rate limit ("email rate limit exceeded"), which caps at 2 emails/hour project-wide on the default (non-custom-SMTP) email service. This blocked further testing this session.

**Not yet verified:** a full magic-link round trip actually landing on the authenticated home screen; whether the URL Configuration change actually fixes the redirect. (RLS is applied and behaving correctly — see the corrected note under "Database" above; this line used to say otherwise.)

**New discovery while testing the paste-text flow below:** a `households`/`users` row now exists for the real `auth.users` row (`joshuapetty@live.com`), named "Test Household" — the same naming convention as `scripts/dev/seed_receipt_items.py`'s throwaway household, so this was likely created by running that script (or something like it) against the real auth id rather than by an actual completed magic-link sign-up. Onboarding still isn't wired up client-side (see "Not started"); this row just happens to make household-scoped testing possible right now. Didn't touch it either way.

## Paste-text receipt flow (first backend API + first read/write app flow)

**Backend — `api/main.py`:**
- Single endpoint, `POST /match`. Body: `{ text: string, brand?: string, purchase_date?: string }`.
- Auth: verifies the `Authorization: Bearer <token>` header as a real Supabase-issued JWT — fetches Supabase's JWKS (`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`, `ES256`, confirmed reachable) via `PyJWKClient`, checks signature + `aud: authenticated`, reads `sub` as the user id. New `SUPABASE_URL` env var added to the root `.env` (not a secret, same value as the app's `EXPO_PUBLIC_SUPABASE_URL`) for this. The client never supplies `household_id` directly — it's looked up server-side from `users` using the verified user id, and a user with no `users` row yet gets a `403`.
- Receipt handling: reuses a single ongoing "manual entries" `receipts` row per household (looked up by a sentinel `image_s3_key = "manual-entry"`), rather than creating a new receipt per pasted item — picked as the simpler of the two options in the request. `receipts.image_s3_key`/`retention_expires_at` are `NOT NULL` columns designed for photo receipts; since there's no image here, they're filled with a placeholder key and a 90-day retention window (matching the documented image-retention convention even though nothing is actually being retained). `ocr_status` is set to a new `"manual"` value (no CHECK constraint on that column, so this is safe) to distinguish these from OCR'd receipts.
- Runs the existing `matching/matcher.py` (`match_receipt_item`), synchronously, direct call/response — no job queue, matching the MVP-first decision already made elsewhere.
- Response is a list of `{ recall_id, confidence, method, match_features, recall_product_name }` — `recall_product_name` is one field beyond what was asked for, added because the app screen needs something human-readable to display and this avoids a second round trip.
- New dependencies: `fastapi`, `uvicorn[standard]`, `pyjwt[crypto]`, `httpx` (dev/test only). Also backfilled `sqlalchemy`, `psycopg2-binary`, `python-dotenv` into `pyproject.toml`'s `dependencies`, which were already installed and in use but had never actually been listed there.
- Run locally: `source venv/bin/activate && uvicorn api.main:app --host 127.0.0.1 --port 8000`. CORS allows any `http://localhost:<port>` origin (covers Expo web's dev port) — dev-only, no production CORS story yet.

**Expo app — `app/(app)/scan.tsx`:** "Check a product" screen, linked from the home screen. Product-name text input (required) and brand text input (optional), submit button, calls `POST /match` on `EXPO_PUBLIC_API_URL` (new env var, defaults to `http://localhost:8000`, same physical-machine-only caveat as the rest of local dev) with the session's `access_token` as the bearer token. Shows each returned match (recall product name, confidence as a percentage, method) in a plain list, or "No match found." if empty. Checked against the design constraints below — no violations (same checks as the recall screens: gradients, pill buttons, emoji, em dashes, animation).

**Testing — real end-to-end match confirmed, but not through the actual running app/UI:**
- Same blocker as everywhere else in this file: completing a real login requires clicking a magic-link email I can't access, so I couldn't drive this through the actual Expo UI with a real bearer token.
- What I did instead: started the FastAPI server for real (`uvicorn`, confirmed serving on `127.0.0.1:8000`), then exercised the actual `/match` endpoint code (not a reimplementation) via `TestClient` with `get_current_user_id` overridden to the one real `auth.users` id — everything past that point (request parsing, household lookup, receipt reuse, the real matcher, response shape) ran for real against the live Supabase DB.
- Pasted `"OUTSHINE FRUIT BARS TANGERINE"` (a real product from a family already in `recalls`) with brand `"Dreyer's Grand Ice Cream Inc."` → got back exactly one match: recall id `bc062f21-b5bd-481a-9c72-3fe8683ba907` ("Outshine Fruit Bars Tangerine...", Class II), `method: "fuzzy"`, `name_sim: 1.0`, `confidence: 0.5`. Confidence is only 0.5 (not higher) because `brand_match` scored `0.0` — the recall's ingested brand text has a double space (`"Dreyer's Grand  Ice Cream Inc."`) that breaks the substring check in `matching/scoring.py`'s `brand_score`. Not a bug I introduced (matcher/scoring were explicitly to be left unchanged) — flagging as a pre-existing data-quality quirk worth a look later, not fixed here.
- Pasted `"WHOLE MILK GALLON"` as a negative control → correctly got back no matches.
- Confirmed the manual-entries receipt was reused (one `receipts` row, two `receipt_items`, one `match_candidates` row) rather than a new receipt per submission.
- Separately, against the real running server (genuine HTTP, no override): a request with no `Authorization` header and one with a garbage bearer token both correctly got `401`s — the JWKS/PyJWT verification wiring itself was exercised for real, just not with a genuine signed token.
- Deleted the test `receipts`/`receipt_items`/`match_candidates` rows afterward so no test data was left behind; left the pre-existing `households`/`users` row alone since I didn't create it.

**Not verified, needs you:** the actual screen, submitting a real paste, through a real logged-in session in the running app — needs either a completed magic-link login or a Supabase service-role key (not present in this environment) to mint a real session without one.

## Environment

- Native Node.js and npm installed directly in WSL (`/usr/bin/node`, `/usr/bin/npm`), not relying on the Windows-side Node install.
- WSL's `appendWindowsPath` interop setting disabled (`/etc/wsl.conf`, `[interop] appendWindowsPath = false`), so Windows executables are no longer reachable from inside WSL.
- npm global install prefix changed to `~/.npm-global` (user-owned), rather than the default `/usr` (root-owned), to allow global package installs without `sudo`.
- `python-dotenv` added to `config.py` so `.env` is actually loaded; previously `.env` existed but was unused.
- Physical-device testing (Expo Go via LAN or tunnel) has not been made to work in this environment: LAN mode fails due to WSL2 network isolation from the physical Wi-Fi network; Expo's built-in `--tunnel` (shared Ngrok) is currently rate-limited/unreliable per Expo's own open GitHub issue; a manual `netsh` port-forward plus firewall rule was set up but connection still timed out, and the network in use (Dartmouth Wi-Fi) may have client isolation enabled, untested against a different network due to phone hotspot reliability issues.
- Android emulator setup attempted, not completed: Android Studio installed, "Android Emulator hypervisor driver" (AEHD) installation failed (AEHD requires Hyper-V disabled; WSL2 requires Hyper-V/Virtual Machine Platform enabled, direct conflict). Windows Hypervisor Platform feature was enabled as an alternative acceleration path. Subsequent attempt to install the Android Emulator engine itself failed with "Package id emulator" unavailable for download, cause not yet determined (possibly network-related).
- Current working method for viewing the Expo app during development: web preview (`npx expo start --web`), confirmed actually usable this session (not just bundling cleanly, but interactively used to reach the login screen and submit the login form).
- A coding-agent session run from a Windows-side agent (Git Bash) hit the same UNC-path issue as earlier manual attempts: Windows-side `npx`/`npm` cannot target the project's WSL path directly. Workaround used: invoke WSL's native node/npm from Windows via `wsl.exe -e bash -lc "cd ~/projects/recall-monitor/... && <command>"`.
- Installing `react-native-web` + `react-dom` for Expo SDK 57 hit an npm peer-dependency conflict; resolved with `npm install --legacy-peer-deps`. Likely to recur on future `expo install` calls in this app.
- A prior diagnostic query intended to check `public.users`'s foreign keys returned zero rows due to a self-inflicted join bug (joining on `constraint_column_usage.table_schema`, which reports the *referenced* table's schema, not the constraint owner's), which briefly looked like a missing/misapplied foreign key. A corrected query confirmed the foreign key was actually present and correct all along; no schema fix was needed.

## Not started

- Applying/reviewing the `66f2630fb756_add_recall_states` migration (see "Database" above) — once applied, run `scripts/ops/backfill_recall_states.py` for real (only simulated/smoke-tested so far, see "Ingestion pipeline") and re-verify the state filter against real filtered results (only the pre-migration graceful-failure path has been verified so far, see "Recall browse/detail screens")
- Applying/reviewing the `1a0a76ba3dbc_grant_recalls_select_to_anon` migration (see "Database" above) — once applied, worth a quick re-check that real recall rows render for a signed-out visitor at `/recalls`, not just the empty-state plumbing already verified
- Confirming a full magic-link round trip after the redirect-URL config change (blocked on the email rate limit resetting, or setting up custom SMTP)
- Verifying cross-household isolation actually holds under the applied RLS migration (`2f082500b25a` — applied, see Database section, but the multi-household scenario itself hasn't been tested)
- A self-serve household-creation path for onboarding (blocked by the `households` table having no client-side INSERT policy — see Database section)
- End-to-end verification of the recall browse/detail screens and the paste-text "Check a product" screen inside the actually-running app (both blocked on the magic-link round trip, same as above) — see their respective sections above
- Receipt upload → OCR → LLM extraction → `receipt_items` pipeline (paste-text entry now exists as an alternative path into `receipt_items`/matching — see "Paste-text receipt flow" above)
- Notifications
- Async job wiring / two-directional matching triggers
- Labeled eval dataset
- Resolution of physical-device (LAN/tunnel) and emulator testing
- Custom SMTP setup (needed regardless of the rate-limit issue, since Supabase's built-in email service is explicitly not meant for production use)


## Design constraints (apply to all UI work)

- No purple gradients
- No pill-shaped buttons
- No fake reviews, testimonials, or fabricated metrics/numbers
- No vague hero/marketing copy ("Empower your..."), copy should be concrete and specific to what the screen actually does
- No emoji used as icons
- No em dashes in any UI copy
- Minimal to no scroll/entrance animations
- Remove any "Made with [AI tool]" badge/attribution if one gets added
- Prefer plain, functional layouts over decorative flourishes
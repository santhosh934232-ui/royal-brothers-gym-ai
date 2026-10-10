# Phase 6 Handoff — Smart Reminder Preferences and Eligibility Foundation

## Status and boundaries

Phase 6 implements the **preference persistence and deterministic eligibility foundation only**, using the supplied Phase 5 ZIP as the source. It adds two additive SQLite tables, a server-side service, an existing-database migration step, tests, and documentation. No live PythonAnywhere website or production database was accessed or modified.

**No emails were sent. No Gemini or other external API was called.** Phase 7 email delivery/retries/history, Phase 8 member settings UI/scheduling, and Phase 9 final integration/verification were not implemented. This report does not claim the full nine-phase project is verified.

## Verified existing membership model and conventions

Inspection of `schema/schema.sql`, `app/models.py`, `app/routes/membership_routes.py`, `app/routes/admin_routes.py`, `app/static/profile.js`, configuration, migration scripts, and existing test fixtures confirmed:

- The database is **SQLite** accessed through the compatibility helper in `app/extensions.py`; tests use isolated temporary SQLite databases from `tests.base`.
- `membership_requests` is the actual membership record. It has `user_id`, `plan_id`, `status` (`pending`, `active`, `rejected`), `request_date`, `start_date DATE`, and `end_date DATE`. The row references `users` and `membership_plans`.
- `membership_plans.duration_months` is an integer, but the reminder service does **not** reconstruct an expiry from it.
- The admin approval route sets status to `active`, sets `start_date = date.today()` (server-local date), and sets `end_date = start_date + timedelta(days=30 * duration_months)`. This existing rule is an approximation of calendar months; Phase 6 did not alter it.
- An active membership therefore means an admin-marked `status='active'` row with an effective, valid stored date range. `pending` and `rejected` rows are not eligible. The schema has no `cancelled` or `expired` status, no payment fact, no cancellation field, and no membership event/renewal table.
- There is no explicit renewal workflow. Existing request submission rejects a new request if any pending/active row is returned; an expired row can remain with `status='active'`. Phase 6 does not mutate or auto-expire that row.
- The approval route uses `date.today()` (server-local); stored membership dates are date-only values. No configured gym/business timezone exists in this project. Reminder computation is date-only and uses the supplied reference date's own calendar date (or server-local `date.today()` when omitted).
- Existing email delivery uses Flask-Mail in authentication routes, but the Phase 6 service does not import or call it.

## Database change and migration instructions

No existing table or row was altered. The minimum required persistence is:

1. `membership_reminder_preferences`: one row per member (`user_id` primary key/foreign key with `ON DELETE CASCADE`), `enabled` constrained to 0/1, and `created_at` / `updated_at` timestamps. The primary key prevents duplicate preference records.
2. `membership_reminder_lead_times`: normalized child rows for selected lead days; `(user_id, lead_days)` primary key prevents duplicates; foreign key cascades from preferences; a database check bounds stored days to 1–30.

For a fresh database, both tables are in `schema/schema.sql`. For an existing database, `schema/phase6_reminder_preferences.sql` creates them using `CREATE TABLE IF NOT EXISTS` within a SQLite transaction. `scripts/migrate_db.py` now includes this migration, backs up the existing database before applying missing tables, and verifies existing table row counts.

From the project root, **after a human has selected and backed up the intended non-production database**, the documented commands are:

```sh
python scripts/migrate_db.py --check
python scripts/migrate_db.py
```

Phase 6 tests only ran this migration against temporary test databases. No actual user database was migrated. Re-running when both reminder tables already exist is a no-op. This phase's changes do not require a schema reset or table drop.

## Reminder preference defaults and validation

- **Safe default is opt-in:** when no preference row exists, reminders are disabled. Returned defaults expose `[7, 3, 1]` as available choices, not as an enabled subscription.
- The default supported lead days are **7, 3, and 1**.
- The server-side allowlist can be configured using optional `MEMBERSHIP_REMINDER_ALLOWED_LEAD_DAYS`, e.g. `14,7,3,1`. Values must be unique integers between 1 and 30 and must include defaults 7, 3, and 1; invalid configuration stops app configuration instead of silently expanding policy. `.env.example` contains only a commented example.
- The service rejects invalid member IDs, non-boolean enabled values, non-integer lead values, duplicates, negative/zero/unsupported/over-30 values, and enabling with no lead days. A disabled preference may store an empty lead list.
- `save_reminder_preferences()` atomically upserts the unique per-member preference and replaces its lead rows. `get_reminder_preferences()` returns only that member's preference fields and timestamps. Both use a parameterized user ID and verify that the member exists.
- There is no Phase 6 HTTP preference route or UI. Any future member-facing route must derive its `user_id` from the authenticated server-side `session['user_id']`, never from a client-supplied ID. The existing member auth flow was not changed.

## Eligibility semantics and service API

New service: `app/services/membership_reminder_service.py`.

- `get_reminder_preferences(user_id)` reads one member's preferences, applies disabled defaults if absent, and returns a safe result envelope.
- `save_reminder_preferences(user_id, enabled, lead_days)` validates and atomically persists one member's settings. Callers must supply a trusted session-derived ID at a future route boundary.
- `evaluate_membership_for_reminders(membership, preferences, as_of)` is a pure deterministic evaluator with explanatory reason codes for tests and future integration.
- `get_eligible_reminders(as_of=None)` does a read-only SQLite scan and returns only IDs, dates, and lead days; no name/email/profile or other member contact details are returned.

Rules:

1. Only a membership row whose stored status is exactly `active` can qualify.
2. Start and end dates must both be valid ISO dates and `end_date >= start_date`. Missing, invalid, or reversed dates are excluded; the service does not infer dates from the plan duration.
3. `start_date` and `end_date` are treated as **inclusive calendar dates**, matching the profile's expiry-date presentation: a membership is effective when `start_date <= as_of <= end_date`; it is expired only when `as_of > end_date`. The database status remains unchanged.
4. A reminder is due only when `as_of == end_date - lead_days`. It is not a rolling window and there is no catch-up rule for missed dates in Phase 6.
5. A reminder must be enabled for that member and the lead day must be in the server-configured allowlist.
6. If multiple valid, currently effective active membership rows exist for one member, all are excluded as ambiguous. A malformed active row for that member also conservatively prevents a potentially duplicate reminder. Expired active rows alone do not create eligibility.
7. Repeated calls on the same day return the same eligibility. Phase 6 stores no send state, does not mark eligible reminders sent, and does not deduplicate delivery across calls; delivery history/retry semantics are deferred to Phase 7.
8. Date-only values avoid midnight/time-of-day comparisons. An explicit `date` is preferred; an explicit `datetime` contributes its own calendar date. Without one, `date.today()` follows the same server-local convention as existing activation code. Production timezone must be chosen and consistently supplied when scheduled work is designed.
9. Eligibility uses SQLite `mode=ro`. Invalid stored date strings are selected as text and rejected row-by-row so one malformed row does not abort an otherwise usable scan. Database errors return fixed safe messages without paths/SQL details.

## Files created or modified

**Created:**

- `app/services/membership_reminder_service.py`
- `schema/phase6_reminder_preferences.sql`
- `tests/test_phase6_membership_reminders.py`
- `PHASE_6_HANDOFF.md`

**Modified:**

- `schema/schema.sql` — append only the two Phase 6 tables.
- `scripts/migrate_db.py` — register the new idempotent migration and table names; keep backup-first/row-count checks.
- `app/config.py` — validate configurable allowed lead days.
- `.env.example` — commented optional configuration only; no credentials.
- `README.md` — migration and foundation instructions.
- `tests/test_phase3_friction_dashboard.py` — preserve its original Phase 3 schema-file baseline while allowing only the Phase 6 additive migration and asserting that migration contains the two expected `CREATE TABLE IF NOT EXISTS` statements.
- `FINAL_PROJECT_HANDOFF.md` — record Phase 6 status and provenance.

No route, `app/__init__.py`, authentication/login flow, membership approval rule, membership expiry calculation, email delivery, UI, scheduler, or dependency was changed.

## Tests actually run in Phase 6 development copy

- `python3 -m unittest tests.test_phase6_membership_reminders -v` — **19 passed, 0 failed**.
- `python3 -m unittest discover -s tests -v` — **317 passed, 0 failures, 0 errors** (`Ran 317 tests in 92.743s`, `OK`).

Focused coverage includes defaults, opt-in behavior, configurable allowlists and bounds, invalid/duplicate/unsupported values, member isolation, duplicate-row constraints, missing/invalid member records, migration backup/preservation/idempotency, each exact lead date, start/expiry boundaries, pending/rejected/expired/invalid records, ambiguous concurrent memberships, no database creation on missing DB, database failure envelopes, read-only row checks, and absence of email/Gemini calls. The initial full run exposed the Phase 3 schema inventory assertion; it was updated narrowly to recognize the required additive Phase 6 migration while retaining all original schema file expectations. The rerun passed.

The full existing suite emits **legacy** `datetime.utcnow()` deprecation warnings and existing `ResourceWarning` unclosed-file warnings from Phase 3 tests; the Phase 6 focused tests emitted no warnings, and the complete suite passed. No real email or external API was used.

**Fresh-extraction verification:** the final Phase 6 archive passed ZIP integrity validation. From its clean extraction, the focused Phase 6 module passed **19/19**, the full Python suite passed **317/317** (`OK`), and the existing Admin Assistant Node UI suite passed **19/19**. JavaScript syntax also passed. No live database, emails, or external API were used.

## Limitations and Phase 7/8 integration questions

- The application leaves an expired membership row marked `active`, and the existing membership request flow treats any `active` row as blocking a new request. Phase 6 does not change that legacy behavior. A product owner should decide how renewal is represented and whether/when a membership status should be changed before a delivery feature relies on it.
- The existing `30 × duration_months` activation calculation is the established current rule, but it is not true calendar-month arithmetic. Phase 6 consumes stored `end_date`; correcting business semantics would require an explicit separate decision and backfill strategy.
- The actual gym/business timezone is not configured. Existing activation uses server-local date; Phase 8/9 deployment must establish the schedule's reference timezone.
- No delivery history table exists by design. Phase 7 must define idempotency, retry/catch-up windows, concurrent job protection, and whether one delivery is tracked per member/request/lead date before sending any emails.
- Member settings authorization is not yet exposed via a route because Phase 8 owns the UI/integration. The future route must bind the target user to the signed-in member session and preserve CSRF/session protections.
- The service uses exact date matching; a missed target date is not later made eligible automatically. Phase 7 must decide whether to keep exact-day delivery or add bounded catch-up.
- The allowlist can add values through environment configuration within 1–30 days, always retaining 7/3/1. The schema supports that range; changing the 30-day hard maximum requires a schema migration.

## Handoff to later phases

- **Phase 7** may consume `get_eligible_reminders(as_of=business_local_date)`, but must design delivery history, idempotency, retry/catch-up, scheduling/locking, email privacy, and operational limits before sending anything. It must not infer factual membership dates or call Gemini.
- **Phase 8** may add authenticated member preference controls and scheduling only after deriving member identity from the session and validating the same service contract. Do not expose a client-controlled arbitrary `user_id`.
- **Phase 9** remains the separate final integration and complete project verification phase. Run its full applicable tests/package/browser/deployment review then; this Phase 6 run is not a substitute.

## Subsequent-phase note

This handoff records the state and test results **at the end of Phase 6**. Phase 7 later added the delivery ledger, mocked email sending service, and bounded retries described in `PHASE_7_HANDOFF.md`. Phase 7 did not add the Phase 8 member settings UI or scheduled-task integration, and did not change Phase 6 eligibility semantics or the historical test results above.


## Subsequent Phase 8 note

Phase 8 later added the Profile-page member controls and session-bound GET/PUT routes for the Phase 6 preferences, plus an explicit scheduler CLI that reuses the Phase 6 eligibility and Phase 7 delivery services. It did not change Phase 6's disabled-by-default, lead-time validation, exact-date, inclusive-expiry, or ambiguity rules. The Phase 8 dry-run reads the Phase 6 eligibility service only and does not mutate preference or delivery state. See `PHASE_8_HANDOFF.md` for the new route, external-scheduler invocation, tests, and deployment boundaries; the Phase 6 test counts above remain historical.
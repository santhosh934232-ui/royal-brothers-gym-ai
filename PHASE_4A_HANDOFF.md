# Phase 4A Handoff — Admin Assistant Data Service

## Scope completed

Implemented **Phase 4A only**: a deterministic, read-only backend service that returns a bounded set of approved aggregate metrics for a future admin assistant. No Gemini/LLM integration, Flask route, endpoint, UI, authentication change, schema change, migration, or dependency was added.

## Files inspected

- `app/models.py` — existing database access helpers and documented model fields.
- `app/extensions.py` — SQLite connection wrapper and established cursor/query pattern.
- `app/config.py` — database path and environment-based configuration.
- `schema/schema.sql` — actual project schema declarations.
- `app/services/friction_dashboard_service.py` and related service modules — service conventions and existing whitelist/privacy approach.
- `tests/base.py` and existing test modules — temporary SQLite fixture, test framework, and existing suite.
- `requirements.txt` — existing project dependencies.

The project uses direct SQL through `get_db_connection()` and a SQLite compatibility wrapper; it does **not** use SQLAlchemy ORM models. The service follows the existing database access pattern and uses only aggregate SELECT queries.

## Files created or changed

- **Created** `app/services/admin_assistant_data_service.py`.
- **Created** `tests/test_phase4a_admin_assistant_data_service.py`.
- **Created** `PHASE_4A_HANDOFF.md`.
- No existing project source files were changed.

## Schema fields and metrics used

Confirmed fields from `schema/schema.sql`:

- `users.is_verified` — aggregate total, verified, and unverified user-account counts.
- `membership_requests.status` — grouped request counts for `pending`, `active`, and `rejected`; any null/unexpected status is combined into `other_or_missing_status`.
- `membership_requests.id`, `membership_requests.plan_id`, `membership_plans.id`, and `membership_plans.plan_name` — aggregate request count by plan label, including plans with zero requests. Blank or null-like plan labels are represented as `Unspecified`; returned labels are plain-text cleaned and limited to 80 characters.

The service does not use contact messages, feedback, attendance, payment, workout/progress, user profile, or authentication data. Those are not needed for these Phase 4A metrics. It returns a JSON-friendly mapping with `schema_version`, `status`, `members`, and `membership_requests` keys. On database failure, it returns only a generic error code and message; it does not include exception details, SQL, or database paths.

## Privacy and read-only safeguards

- Queries select aggregate values only, not individual members or request rows.
- No names, email addresses, phone numbers, profile fields, contact text, credentials, hashes, token values, dates, or database IDs are returned.
- Only the listed approved output fields are assembled; query results are not passed through wholesale.
- The service performs only `SELECT` statements. It does not commit, insert, update, delete, initialize, or migrate data.
- Any database/query failure returns a fixed safe error envelope. Connection and cursor cleanup are attempted in `finally`.
- No live website or production database was accessed.

## Tests executed and actual results

- Focused tests: `python3 -m unittest tests.test_phase4a_admin_assistant_data_service -v` — **6 tests passed**.
- Complete suite: `python3 -m unittest discover -s tests -v` — **263 tests passed, 0 failures, 0 errors** (`Ran 263 tests in 87.038s`, `OK`).
- Dependencies already declared by `requirements.txt` were installed in the isolated sandbox because the initial focused test invocation found Flask-Mail missing. No requirements file or dependency declaration was changed.

Focused coverage includes aggregate correctness, empty tables, plans without requests and missing plan labels, privacy, unchanged database rows/schema, and safe database-error handling.

## Phase 4B integration guidance

Import `get_admin_summary` from `app.services.admin_assistant_data_service` in the future Phase 4B orchestration layer and call it server-side. Treat `status != "ok"` as unavailable data and do not send an error envelope to Gemini as facts. Pass only the returned aggregate mapping—not raw records or a direct database connection—to any future answer-generation component. Keep route authentication, output validation, prompt-injection boundaries, and response privacy controls in the later phase; this Phase 4A service deliberately creates no route or AI call.

## Limitations and remaining issues

- Counts describe all rows currently in the local application database. The member aggregates explicitly distinguish verified and unverified accounts; a later UI should label them clearly.
- Plan distribution labels come from `membership_plans.plan_name`, an admin-maintained catalog field. It is not member data, but Phase 4B should still treat the labels as untrusted text and should not use them as instructions.
- Attendance and payments are not present in the inspected schema and are intentionally not reported.
- No live or production database was used for validation.


## Phase 5 addendum — current database safety

The Phase 4A service originally issued only aggregate SELECT queries, but its then-default SQLite connector used `sqlite3.connect(path)`, which can implicitly create an empty database file when the configured path is missing. Phase 5 corrected that gap: `get_admin_summary()` now requests `get_db_connection(read_only=True)`, which uses SQLite URI `mode=ro`; missing files are not created and writes are denied by SQLite. Added regression tests cover missing-file non-creation, missing tables without file changes, and denied schema writes. The Phase 4A test counts above remain historical results from that earlier phase, not current totals.

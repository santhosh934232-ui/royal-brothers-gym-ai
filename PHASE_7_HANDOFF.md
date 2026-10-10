# Phase 7 Handoff — Reminder Email Delivery, Duplicate Prevention, and Retries

## Status and boundaries

Phase 7 adds a server-side delivery service for the Phase 6 opt-in membership reminders, a persistent delivery ledger, per-attempt history, an additive existing-database migration, tests, and documentation. The source was the completed Phase 6 ZIP, extracted into an isolated development copy.

**No real emails were sent.** All SMTP behavior in tests is mocked. No live PythonAnywhere website, production database, or external API was accessed. Phase 7 adds no public/bulk-send HTTP endpoint, member settings UI, scheduler, membership-status/date/payment mutation, or Phase 9 final integration. It does not generate reminder text with Gemini or another AI service.

## Verified source behavior reused

Inspection of the Phase 6 code confirmed:

- `membership_requests` is the membership record with `user_id`, `status`, `start_date`, and `end_date`. Status must be exactly `active`; end date is inclusive.
- `membership_reminder_preferences.enabled` is opt-in. No preference row means disabled. Lead-time choices are stored in `membership_reminder_lead_times` and checked against the Phase 6 server allowlist.
- `get_eligible_reminders(as_of=...)` is the authoritative exact-date eligibility source. Phase 7 does not recalculate dates from plan duration or change those rules.
- Existing SMTP configuration is Gmail at `smtp.gmail.com:465` with SSL, environment-based `MAIL_USERNAME` / `MAIL_PASSWORD`, `MAIL_DEFAULT_SENDER`, and a 10-second Flask-Mail timeout. No credential value is stored in this handoff.
- Existing verification/reset emails used `send_email()` in `app/routes/auth_routes.py`. That same helper is now in `app/services/email_service.py`; `auth_routes.send_email` remains an imported alias so existing flows keep the same API and raise-on-SMTP-failure behavior.

## Delivery service

New service: `app/services/membership_reminder_delivery_service.py`.

`process_membership_reminders(as_of=None, now=None)` requires an active Flask application context so it can use the configured Flask-Mail extension. It:

1. Obtains new due items only from Phase 6 `get_eligible_reminders()`.
2. Also loads previously recorded, due retry candidates without reading names or email addresses.
3. Claims each reminder in a SQLite `BEGIN IMMEDIATE` transaction. Under that write lock it revalidates that exactly one effective active membership matches the same member/request/expiry, the member remains opted in, and the selected lead is still present.
4. Resolves the current email and display name through the existing user-to-membership relationship only after the claim/revalidation.
5. Sends a deterministic plain-text message through the existing Flask-Mail helper. The subject includes the expiry date; the body is professional and avoids adding unverified business terms or plan/payment claims.
6. Records the attempt outcome and returns only safe status codes, IDs, expiry dates, lead days, and aggregate counts—never the recipient address, name, email body, or raw SMTP exception details.

Missing/blank/malformed email addresses are recorded as terminal failures and are not passed to SMTP. SMTP authentication and recipient-rejection errors are terminal. Transient or otherwise unclassified SMTP exceptions are recorded using fixed safe codes and may be retried.

## Persistence, deduplication, and concurrency

The additive Phase 7 migration is `schema/phase7_membership_reminder_delivery.sql`. Fresh databases also receive the tables from `schema/schema.sql`.

- `membership_reminder_deliveries` stores one logical delivery per `(user_id, membership_request_id, expiry_date, lead_days)`. This database `UNIQUE` constraint makes changed expiry dates and distinct lead values separate logical reminders while suppressing repeats of the same one.
- The delivery row stores status (`pending`, `sent`, `failed`), attempt count, retryability, reminder/retry-window dates, first/last/next attempt timestamps, a short claim lease, `sent_at`, and bounded safe failure code/reason.
- `membership_reminder_delivery_attempts` has one row per attempt number, with pending/sent/failed status, start/finish timestamps, and bounded safe failure code/reason.
- Both tables have foreign keys with cascade cleanup and indexes for retry lookup/history. SMTP credentials, API keys, email content, and raw exception details are not stored in delivery history.
- A transaction-safe SQLite claim and lease prevent two cooperating workers from sending the same currently claimed reminder concurrently. The uniqueness constraint remains the durable backstop. This claim behavior was tested with two concurrent service calls against the isolated SQLite database.

For an existing database, use the project's existing migration runner after a human selects and backs up the intended database:

```sh
python scripts/migrate_db.py --check
python scripts/migrate_db.py
```

The runner backs up the target before changes, applies repeatable `CREATE TABLE IF NOT EXISTS` scripts, and checks that pre-existing table row counts remain unchanged. Phase 7 migration tests used a temporary Phase 6 database, verified its existing opt-in preference rows survived, checked the backup, and reran the migration without another backup or duplicate tables. No real database was migrated.

## Retry policy and SMTP/database boundary

- Maximum: **3 total attempts**, including the first delivery attempt.
- After transient attempt 1 failure, the next attempt is eligible after **5 minutes**; after attempt 2, after **15 minutes**. No attempt occurs before `next_attempt_at`.
- A retry of an already-created reminder is allowed through the next calendar day after its exact reminder date, but never after the membership expiry date. The retry key must still match the current active membership, current opt-in, and selected lead time. This is retry handling for an existing exact-date reminder, not a new Phase 6 catch-up eligibility rule.
- Invalid email, SMTP authentication failure, and explicit SMTP recipient rejection do not retry. All failures stop after the maximum attempt count. A missing result-record write leaves the claim pending until its lease expires; that is surfaced as uncertain when observed.
- SQLite serializes the claim before SMTP, but SMTP acceptance and a local SQLite commit cannot be made atomic together. If SMTP accepts the email and the process/database fails before `sent` is durably recorded, a later stale-lease retry can send a duplicate. Conversely, the service cannot assert delivery merely because it invoked SMTP. Therefore this is **not guaranteed exactly-once email delivery**. The service exposes this boundary as `uncertain` and the handoff documents it rather than hiding it.
- Stored timestamp values follow the project’s existing naive-UTC convention. Eligibility/retry dates follow the caller-supplied Phase 6 calendar date (or server-local `date.today()` by default). The actual gym timezone remains unconfigured and must be chosen before Phase 8 scheduling.
- There is no scheduler in Phase 7. A future invocation mechanism must provide an app context, a deliberate business-local `as_of` date, and a cadence that can run retry attempts during the bounded retry window.

## Tests actually executed

**Focused Phase 7:** `python3 -m unittest tests.test_phase7_membership_reminder_delivery -v` — **19 passed, 0 failed**. Coverage includes eligible/opted-in sends, disabled and non-due cases, blank/invalid addresses, no repeated successful sends, independent lead and expiry keys, sequential non-overlapping memberships, overlap exclusion, failure history, retry backoff/window/limit, terminal authentication failure, concurrent claims/uniqueness, uncertain post-SMTP history writes, safe database failure, Phase 7 migration preservation/repeatability, and continued email-verification behavior. SMTP was always mocked.

**Focused Phase 6 regression:** `python3 -m unittest tests.test_phase6_membership_reminders -v` — **19 passed, 0 failed**. **Phase 3 schema inventory regression:** **1 passed** after extending its explicit allowlist from the Phase 6 migration to the Phase 6 and Phase 7 additive migration files. The previous Phase 6 preference and eligibility rules remain unchanged.

**Complete development-source suite:** `python3 -m unittest discover -s tests -v` — **336 passed, 0 failures, 0 errors** (`Ran 336 tests in 99.072s`, `OK`). **JavaScript/UI regression:** `node --check app/static/admin-assistant.js` passed and `node --test tests/phase4d_admin_assistant_ui.test.cjs` passed **19/19**. The full log contained legacy `datetime.utcnow()` deprecation warnings and existing `ResourceWarning` unclosed-file warnings; these did not fail the suite. Phase 7 SMTP tests use mocks and all Python tests use the isolated temporary database/fake test credentials.

**Fresh-extraction verification of the delivery ZIP:** ZIP integrity validation passed; the archive contained **133 files**, included the placeholder-only `.env.example`, and excluded `.env`, database files, bytecode/caches, virtual environments, dependency trees, and logs. From a clean extraction, `node --check app/static/admin-assistant.js` passed; the Admin Assistant Node UI suite passed **19/19**; the focused Phase 7 and Phase 6 suites each passed **19/19**; the updated Phase 3 schema inventory test passed **1/1**; and the complete Python suite passed **336/336** (`OK`). The full suite emitted 16 legacy `DeprecationWarning` lines and 34 existing `ResourceWarning` lines, with no failures. No real email, production database, live website, or external API was used. This remains Phase 7 verification only, not Phase 9 final project verification.

## Files created or modified in Phase 7

**Created:**

- `app/services/email_service.py`
- `app/services/membership_reminder_delivery_service.py`
- `schema/phase7_membership_reminder_delivery.sql`
- `tests/test_phase7_membership_reminder_delivery.py`
- `PHASE_7_HANDOFF.md`

**Modified:**

- `app/routes/auth_routes.py` — import the same sender helper from its shared service location.
- `schema/schema.sql` — add delivery and attempt-history tables to fresh setup.
- `scripts/migrate_db.py` — register Phase 7 tables/migration in backup-first runner.
- `tests/test_phase3_friction_dashboard.py` — preserve its Phase 3 schema baseline and permit only the explicit Phase 6/7 additive reminder migrations.
- `README.md`, `PHASE_6_HANDOFF.md`, and `FINAL_PROJECT_HANDOFF.md` — add Phase 7 documentation and status.

No new dependency was added.

## Handoff to Phase 8 and Phase 9

- Phase 8 may add member settings UI and scheduled-task integration. Any settings route must derive the member ID from the authenticated session, not a client-controlled ID. The scheduler should use the chosen gym-local timezone and call this service within an app context with a controlled cadence.
- The Phase 7 service currently returns per-item safe statuses and IDs; it is not an HTTP response contract. It should not be exposed as a public trigger or unauthenticated bulk-send endpoint.
- Review retry cadence, operational monitoring, and the SMTP/database uncertainty before production enablement. Test against a deliberately isolated non-production mail sink before any real deployment or real recipient use.
- Phase 9 remains the final end-to-end integration/regression/browser/deployment review after Phase 8. Phase 7 is not the full project verification.


## Subsequent Phase 8 note

Phase 8 later added member-facing preferences UI/API and the manually invoked `scripts/run_membership_reminders.py` command for an external scheduler. The command invokes `process_membership_reminders()` only when explicitly run, inside an application context; it does not change the Phase 7 delivery/message/retry/deduplication rules or start from app import, login, or a web request. Its dry-run uses only Phase 6 read-only eligibility and does not create delivery or successful-send records. The Phase 8 scheduler cadence must be frequent enough for the existing 5-/15-minute retry backoff, and the gym timezone must be selected operationally. Phase 7 counts above remain historical; see `PHASE_8_HANDOFF.md`.
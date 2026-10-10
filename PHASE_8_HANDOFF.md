# Phase 8 Handoff — Member Reminder Settings and Explicit Scheduler Entry Point

## Status and scope

Phase 8 uses the completed Phase 7 ZIP as source, extracted into a separate workspace at `/home/ubuntu/phase8-work/royal-brothers-gym`. It adds member-facing reminder settings, authenticated preference endpoints, a one-shot command suitable for an external scheduler, tests, and documentation. It reuses the existing Phase 6 preference/eligibility service and Phase 7 delivery service; neither service's date, message, SMTP, deduplication, retry, or history logic was duplicated or changed.

No production website, PythonAnywhere host, production database, or real mail recipient was accessed. Tests use the project fixture's temporary SQLite database and mocked email delivery. No live email or external API call was made. **Phase 9 was not started.**

## Member settings UI and API

The Profile page (`/profile.html`) contains a responsive **Membership Expiry Reminders** section. A member can opt in or out, select the lead days supported by the current server configuration (defaults are **7, 3, and 1**), revisit to see saved choices, and save with accessible success/validation/error feedback. Options are built as text-only DOM nodes from the server response; saved state is rendered from the API, not just retained in browser memory.

Routes, registered on the existing membership blueprint:

- `GET /api/membership/reminder-preferences`
- `PUT /api/membership/reminder-preferences`

Both require a valid positive-integer `session['user_id']`. The handler never uses a query/body `user_id`; unexpected fields (including a client-supplied ID) are rejected. A deleted member session is invalidated without erasing unrelated admin-session keys. A missing preference row continues to mean `enabled=false`; the GET does not create a row. The UI/API persist changes through the existing atomic Phase 6 `save_reminder_preferences()` and the PUT response performs a fresh read to report the post-commit stored values.

The PUT endpoint accepts only JSON, reads at most 4 KiB, requires exactly `enabled` and `lead_days`, validates the boolean/list shape, and delegates allowed-value/duplicate/empty-enabled checks to Phase 6. It requires an explicit exact same-origin `Origin` (scheme, host, and effective port); missing, malformed, or cross-origin Origin is rejected. This is deliberately stricter for this new write endpoint than the older project convention that permits absent Origin. Responses are `Cache-Control: no-store` and expose no member email/name/ID. There is no new authentication mechanism, dependency, schema table, or migration.

## Scheduler command and behavior

The external scheduler entry point is the explicit command:

```sh
python scripts/run_membership_reminders.py --dry-run
python scripts/run_membership_reminders.py
python scripts/run_membership_reminders.py --as-of YYYY-MM-DD
```

The script has a `__main__` guard and imports/creates the Flask application only after configuration preflight. It does not run when imported, when a Flask worker starts, during login, while rendering a dashboard, or in a normal HTTP request. A live invocation uses the existing application factory and calls `process_membership_reminders(as_of=...)` inside its Flask application context. Phase 6 remains the source of exact-date opt-in eligibility; Phase 7 remains responsible for message generation, SMTP, transactional per-reminder claims, deduplication, and its maximum three-attempt / 5- and 15-minute retry policy.

The command prints one privacy-safe JSON report and no recipient names, addresses, message bodies, database paths, or exception text. A live report includes Phase 7 `eligible_candidates`, `sent`, `failed`, `skipped`, `uncertain`, and `errors`; `attempted` is derived as `sent + failed + uncertain`, i.e. outcome/attempt records (including a previously interrupted claim that the service reconciles). It exits `0` on a clean run, `1` for runtime/database or partial delivery failure, and `2` for invalid date or missing required settings.

### Dry-run

`--dry-run` invokes only Phase 6 `get_eligible_reminders()` and opens SQLite in the service's read-only mode. It reports a count of exact-date Phase 6 eligible reminders, with attempted/sent/failed/skipped/uncertain/errors all zero. It does **not** call Phase 7, send email, inspect the delivery/retry ledger, deduplicate against earlier sends, or write a preference, delivery, attempt, or success record. Its eligibility count is therefore not a prediction of live sends: previously sent reminders and due Phase 7 retries are outside its scope. If the configured DB path is missing, read-only access fails safely and does not create the file.

## Configuration and external scheduler setup

A live run requires the existing app configuration: `SECRET_KEY`, `MAIL_USERNAME`, `MAIL_PASSWORD`, and `DATABASE_PATH` pointing to the intended SQLite database (or the existing project default). The existing Phase 7 Gmail SMTP settings remain in force. An optional `MEMBERSHIP_REMINDER_ALLOWED_LEAD_DAYS` may extend the supported leads within Phase 6's validation rules; defaults remain 7/3/1. The command loads the project's local `.env` if present, but no `.env` is included in the deliverable. Missing SMTP credentials stop a live invocation before app creation and are reported by variable name only. Dry-run does not require SMTP credentials; process-local placeholders and `MAIL_SUPPRESS_SEND` are used defensively and no sender is called.

No external task was created or deployed. An operator may configure a platform task/cron to execute the command from the project root, for example:

```cron
*/5 * * * * cd /path/to/project && /path/to/venv/bin/python scripts/run_membership_reminders.py
```

This is a pattern only; replace paths, install `requirements.txt`, inject the normal app/mail/database environment, and first test against a separate non-production DB and isolated mail sink. The host's local calendar date is used unless `--as-of YYYY-MM-DD` is supplied. The gym/business timezone is not configured in the repository and must be deliberately selected; when host and gym dates can differ, a small operator-managed wrapper should compute and pass the gym-local date. A cadence of five minutes or less is recommended to service Phase 7's existing five-/fifteen-minute backoff promptly; a once-daily schedule would not promptly honor that retry cadence. Monitor safe JSON summaries/nonzero exits. Phase 8 adds no scheduler-wide singleton lock; overlapping work is protected only by Phase 7's tested SQLite per-reminder claim/deduplication logic, not by a claim of global worker exclusivity.

## Tests actually executed on the final Phase 8 development source

- `python3 -m py_compile app/routes/membership_routes.py scripts/run_membership_reminders.py tests/test_phase8_membership_reminders.py` — passed.
- `python3 -m unittest tests.test_phase8_membership_reminders -v` — **18 passed, 0 failed**.
- `node --check app/static/profile.js`, `node --check app/static/membership-reminders.js`, and `node --check app/static/admin-assistant.js` — all passed.
- `node --test tests/*.test.cjs` — **23 passed, 0 failed** (19 existing Admin Assistant UI cases plus 4 Phase 8 reminder UI cases).
- `python3 -m unittest discover -s tests -v` — **354 passed, 0 failures, 0 errors** (`Ran 354 tests in 101.727s`, `OK`). This includes all existing Phase 6 eligibility/preference and Phase 7 delivery/deduplication/retry/history tests.

Phase 8 coverage includes session authorization, disabled defaults, persisted values, member isolation despite forged IDs, explicit same-origin checks, JSON/body/value validation, profile asset delivery, existing dashboard endpoints, dry-run no-send/no-write behavior, safe missing-SMTP preflight, safe DB errors and missing-database non-creation, repeated actual command invocations through the mocked-Email Phase 7 delivery service to verify persistent deduplication, and app/request non-autosend behavior. Existing Phase 7 tests continue to cover concurrent claims and retry limits.

The full suite emitted **16 `DeprecationWarning` lines** from existing `datetime.utcnow()` use and **34 `ResourceWarning` lines** from pre-existing unclosed files in older tests; the suite passed. The focused Phase 8 tests passed without `ResourceWarning`. No SMTP connection or external service was used.

## Clean-extraction ZIP verification

The Phase 8 ZIP passed `zipfile.testzip()` and was extracted into a newly emptied directory. The archive contained **138 files**; integrity was `OK`, and the archive inventory contained **0 forbidden entries** (`.env`, SQLite/database files, bytecode/cache, virtual environments, `node_modules`, logs, and temporary/backup files). `.env.example` contains placeholders only. On the clean extraction of the Phase 8 archive:

- Python compilation checks passed for the changed route, command, and test module.
- JavaScript syntax checks passed for `profile.js`, `membership-reminders.js`, and the pre-existing `admin-assistant.js`.
- `node --test tests/*.test.cjs` — **23 passed, 0 failed**.
- `python3 -m unittest tests.test_phase8_membership_reminders -v` — **18 passed, 0 failed**.
- `python3 -m unittest discover -s tests -v` — **354 passed, 0 failures, 0 errors** (`OK`).
- Full-run warning totals: **16 `DeprecationWarning`** and **34 `ResourceWarning`** lines, matching the legacy warning categories also present in the source run.

## Limitations and manual deployment steps

- The actual gym timezone, scheduler host, external task cadence, filesystem paths, and production environment variables have not been selected or inspected. Do that before deployment; do not infer timezone from this test session.
- Exercise `--dry-run` against a deliberately isolated non-production database first. Before any live send, use an isolated mail sink and verify sender configuration. No real delivery was tested.
- SMTP acceptance and SQLite status commit still cannot be atomic; the Phase 7 documented crash-gap uncertainty/possible duplicate remains.
- The dry-run is a Phase 6 eligibility count only, not a dry execution of retries or deduplication.
- The explicit Origin check compares against Flask's request host/scheme. A reverse-proxy deployment must correctly convey the external scheme/host, and this deployment setup was not inspected.
- Phase 8 is not Phase 9's final browser, full integration, deployment, or project verification.

## Files added or changed

**Added:** `app/static/membership-reminders.js`, `scripts/run_membership_reminders.py`, `tests/test_phase8_membership_reminders.py`, `tests/phase8_reminder_ui.test.cjs`, and this handoff.

**Changed:** `app/routes/membership_routes.py`, `app/static/profile.html`, `app/static/profile.js`, `app/static/profile.css`, `README.md`, `PHASE_6_HANDOFF.md`, `PHASE_7_HANDOFF.md`, and `FINAL_PROJECT_HANDOFF.md`.

No database schema, membership state/date/payment behavior, email templates, Phase 6/7 business rules, dependencies, production configuration, or live scheduler was changed. Stop here for Phase 8; Phase 9 is future work.

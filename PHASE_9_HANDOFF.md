# Phase 9 Handoff — Final Integration, Regression, and Release

## Status

**Phase 9 is complete on the Phase 8 source extracted at**
`/home/ubuntu/phase9-work/royal-brothers-gym`. The release candidate is
`Royal-Brothers-Gym-AI-Final.zip`. The work stayed within the existing
Friction Detector/Admin Insights, Admin Assistant, and Smart Reminder scope.
No feature was added beyond the audited integration repairs and release
verification.

**Safety boundary:** no live site, production database, production host, real
mail recipient, external scheduler, Gemini provider, or SMTP service was
accessed or configured. Tests use temporary SQLite databases and mock the AI
and email services.

## Phase 9 changes

1. **Profile membership-card XSS:** `app/static/profile.js` no longer builds
   membership markup with interpolated API values. Plan/status values and
   dates are assigned to text nodes; the status CSS class is allowlisted.
   A dependency-free mock-DOM test exercises hostile plan/status strings.
2. **Consistent supplied-Origin checks:** new `app/security.py` is the shared
   scheme/host/effective-port comparator. A Flask `before_request` guard now
   rejects any supplied cross-origin or malformed Origin on `POST`, `PUT`,
   `PATCH`, and `DELETE` across the app. Existing same-origin writes continue;
   the reminder-preference `PUT` still requires an explicit Origin. Optional
   `ProxyFix` support is enabled only by an operator-set `TRUSTED_PROXY_COUNT`
   (default `0`); the Admin Assistant's structured error response remains
   compatible.
3. **Legacy schema migration:** `scripts/migrate_db.py` now reads the additive
   changes in `schema/schema_updates.sql`, conditionally adds absent auth
   columns, and idempotently creates the verification-token table/index before
   applying fitness/reminder migrations. `--check` reports missing tables and
   columns without writes. The normal path remains backup-first and verifies
   row counts of pre-existing tables. A migration regression covers preview,
   application, preservation of a legacy user row, and repeat execution.
4. **Reminder lease uncertainty:** when an expired in-flight claim is
   reconciled, the persistent ledger still records the retryable `failed`
   status, but the current run now reports it as `uncertain` with the safe
   `attempt_interrupted` code. This correctly feeds the Phase 8 command's
   `uncertain` and `attempted` counts. A regression verifies that no second
   email is sent while the previous outcome is unresolved.
5. **Documentation consolidation:** README setup/migration instructions and
   friction feature status were corrected. The README and schema headers now
   direct existing databases through the repeatable migration runner. This
   handoff records final integration, test, package, and deployment caveats;
   `FINAL_PROJECT_HANDOFF.md` is the compact master index. Earlier phase
   handoffs remain as historical detail.

## Verification performed

- `python3 -m py_compile` on changed application, migration, and test modules —
  **passed**.
- `python3 -m unittest discover -s tests -v` on the source tree —
  **360 passed, 0 failures, 0 errors** (`Ran 360 tests in 104.884s`).
  Gemini and mail calls are mocked. The full run emitted 16 existing
  `DeprecationWarning` lines and 34 existing `ResourceWarning` lines; these did
  not fail tests.
- `node --check` for `profile.js`, `membership-reminders.js`, and
  `admin-assistant.js` — **passed**.
- `node --test tests/*.test.cjs` — **24 passed, 0 failed**, including the new
  XSS regression.
- Focused Phase 9 security/migration tests and the Phase 7 delivery module —
  **25 passed**.
- `Royal-Brothers-Gym-AI-Final.zip` — **142 files**, ZIP integrity `OK`, and
  **0 forbidden entries** (`.env`, database files,
  backups, caches/bytecode, virtual environments, `node_modules`, and logs).
  `.env.example` is present and contains placeholders only.
- The ZIP was extracted into a newly created temporary directory. From that
  clean extraction, compilation and JavaScript syntax checks passed, the full Python suite ran
  **360 passed, 0 failures, 0 errors**, and the Node suite ran
  **24 passed, 0 failed**. The extracted Python suite emitted the same 16
  existing `DeprecationWarning` and 34 `ResourceWarning` lines without
  failures.

## Migration and bootstrap notes

For a new **local** database, follow `README.md`: create a virtual environment,
install `requirements.txt`, copy `.env.example` to `.env`, initialize with
`schema/schema.sql`, create an admin with `python scripts/create_admin.py`,
and start with `python -m flask --app wsgi run`. The required local settings
are `SECRET_KEY`, `MAIL_USERNAME`, and `MAIL_PASSWORD`; `GEMINI_API_KEY` is
optional until a Gemini-backed feature is used. Never use production
credentials or data for these steps.

For an existing database, run `python scripts/migrate_db.py --check` and then
`python scripts/migrate_db.py` with `DATABASE_PATH` set to the intended
**non-production** file. Do not use the full schema as an upgrade script. The
newly added `is_verified` column defaults to `0`; an operator must decide
whether existing accounts should be grandfathered and, if so, perform that
policy change separately after backup. The migration intentionally makes no
such account-status decision.

## Known limitations and release/deployment checks

- **Origin validation is not a CSRF token.** Browser requests with a supplied
  Origin are checked consistently, but requests omitting Origin remain allowed
  for compatibility with existing non-browser clients. The reminder settings
  write endpoint is stricter and requires an explicit matching Origin. Review
  whether the deployment can move to required Origin or token-based CSRF after
  confirming all clients.
- **Reverse proxies and cookies:** `TRUSTED_PROXY_COUNT` defaults to `0` so
  forwarded headers are not trusted implicitly. Set it only to the verified
  number of hops in a trusted proxy chain; untrusted clients must not be able
  to reach the app directly when it is enabled. The local sandbox browser
  smoke test used one trusted proxy hop; no production proxy was inspected or
  configured. Production HTTPS, `Secure`/`SameSite` cookie policy,
  trusted-host validation, and secret rotation were not changed or verified.
- **Reminder time and scheduling:** the business IANA timezone and scheduler
  are not selected in the repository. Operators must choose them, pass the
  intended gym-local date where needed, test `--dry-run` against an isolated
  database, and test delivery with a mail sink before any live run.
- **SMTP/database crash gap:** a successful SMTP handoff and a local status
  commit cannot be atomic. A crash may leave an uncertain attempt eligible for
  retry and can produce a duplicate; exactly-once delivery is not promised.
  The `uncertain` result makes this visible but does not remove the tradeoff.
- **Runtime/browser/provider checks:** a temporary local demo account was used
  for desktop/mobile browser smoke checks against the extracted release; no
  real member data was used. Provider and mail calls remain mocked. No live
  provider test was performed. Deployment monitoring, rate limiting, and the
  inherited admin/session policies remain operator/security-review items.
- Existing `datetime.utcnow()` deprecations and older unclosed-response test
  `ResourceWarning`s remain outside this narrow release scope.

## Release archive contents and exclusions

The archive contains the full application, static assets, schemas, migration
and scheduler scripts, tests, README, and phase handoffs. It excludes `.env`,
SQLite/database files, backups, Python bytecode/caches, virtual environments,
`node_modules`, and logs. `.env.example` contains placeholders only.

See also: [README.md](README.md), [FINAL_PROJECT_HANDOFF.md](FINAL_PROJECT_HANDOFF.md),
[PHASE_8_HANDOFF.md](PHASE_8_HANDOFF.md), and the earlier per-phase handoffs.

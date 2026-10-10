# Royal Brothers Gym AI — Final Project Handoff (Phases 1–9)

## Release status

**Phases 1–9 are implemented and locally verified.** The final source is the
Phase 8 project ZIP extracted into this worktree, with Phase 9 integration
repairs and release documentation applied. The release package is
`Royal-Brothers-Gym-AI-Final.zip`.

The project is a Flask/SQLite gym-membership application with three in-scope
AI/reminder tracks: Member Journey Friction Detector/Admin Insights, the
read-only Admin Assistant, and opt-in Smart Reminder delivery. No unrelated AI
features or production deployment changes were made in Phase 9.

**Production boundary:** no live website, production database, production
credentials, real SMTP recipient, external scheduler, or live Gemini call was
accessed or configured. Automated tests use isolated temporary SQLite
instances and mocked providers.

## Feature status by phase

| Phase | Capability | Final state |
|---|---|---|
| 1 | Friction Detector analysis | Read-only aggregate counts and evidence-strength rules over contact messages and membership requests; no identifying details returned. |
| 2 | Gemini friction interpretation | Optional validated, evidence-linked interpretation from approved aggregates; never changes app data. |
| 3 | Admin friction page | Admin-only dashboard showing verified metrics and explicitly labelled AI interpretation; page loads do not call Gemini. |
| 4A–4D | Admin Assistant | Read-only aggregate data service, Gemini-backed answer service, session-protected API and dashboard chat UI. |
| 5 | Integration hardening | SQLite read-only analysis path, safe unsupported-metric behavior, exact supplied-Origin comparison and regressions. |
| 6 | Reminder foundation | Member opt-in/lead-time persistence and exact-date eligibility using stored membership end dates. |
| 7 | Reminder delivery | Flask-Mail/Gmail delivery service, persistent unique claims/history, bounded retries and uncertainty handling. |
| 8 | Member controls/scheduler | Profile settings, session-bound preference API and explicit one-shot scheduler CLI; no auto-run trigger. |
| 9 | Final integration/release | XSS/Origin/migration/lease fixes, consolidated documentation, full regression and fresh-extraction release checks. |

## Phase 9 integration changes

- Removed API-value interpolation from membership-card `innerHTML` rendering;
  plan/status/date fields are rendered as text and CSS status tokens are
  allowlisted.
- Added shared exact-origin validation and a global guard for supplied
  `Origin` headers on unsafe HTTP methods. Reminder preference updates continue
  requiring an explicit matching Origin. Optional forwarded-header trust is
  controlled by `TRUSTED_PROXY_COUNT` and defaults to zero; the Admin Assistant
  error contract remains compatible.
- Integrated the legacy auth schema changes from `schema/schema_updates.sql`
  into the backup-first, idempotent `scripts/migrate_db.py` runner. The runner
  conditionally adds missing columns, creates the verification-token table and
  index, applies the later additive migrations, and verifies pre-existing row
  counts.
- Changed expired reminder lease results to `uncertain` while retaining the
  current retryable persistent ledger state. This reflects that a previous
  SMTP attempt could already have been accepted.
- Corrected stale friction implementation claims in `README.md`, added new
  local bootstrap/migration steps, and updated canonical schema guidance.

Detailed Phase 9 changes, verification, and deployment caveats are in
[PHASE_9_HANDOFF.md](PHASE_9_HANDOFF.md). Earlier phase details remain in the
individual handoffs listed below.

## Local setup and database upgrades

For a brand-new **local** database: create/activate a virtual environment,
install `requirements.txt`, copy `.env.example` to `.env`, set a local
`SECRET_KEY` and non-empty mail configuration, initialize with
`schema/schema.sql`, create an admin with `python scripts/create_admin.py`,
and start with `python -m flask --app wsgi run`. `GEMINI_API_KEY` is optional
at startup. The complete, copyable steps are in `README.md`.

For an existing **non-production** database, use
`python scripts/migrate_db.py --check` and then `python scripts/migrate_db.py`
with the correct `DATABASE_PATH`. Do not initialize an existing database with
the full `schema/schema.sql`. If legacy accounts predate email verification,
`is_verified` defaults to `0`; any grandfathering decision must be made
separately by the operator after a backup. The migration does not change old
accounts to verified automatically.

## Verification evidence

On the final source tree:

- `python3 -m py_compile` on changed application, migration, and test files —
  passed.
- `python3 -m unittest discover -s tests -v` — **360 passed, 0 failures, 0
  errors** (`Ran 360 tests in 104.884s`).
- JavaScript syntax checks for `profile.js`, `membership-reminders.js`, and
  `admin-assistant.js` — passed.
- `node --test tests/*.test.cjs` — **24 passed, 0 failed**.
- Focused security/migration and reminder-delivery regressions — **24 passed**.
- The full Python run emitted 16 existing `DeprecationWarning` lines and 34
  existing `ResourceWarning` lines without failures.

Final ZIP integrity is `OK` (**142 files; 0 forbidden entries**). From a
fresh extraction, **360 Python tests** and **24 Node UI tests** passed; the
exact archive inventory and extraction evidence are recorded in the
[Phase 9 handoff](PHASE_9_HANDOFF.md).

## Known limitations and production handoff

- The global guard rejects a **supplied** mismatched/malformed Origin on
  `POST`/`PUT`/`PATCH`/`DELETE`; missing Origin remains allowed for existing
  non-browser compatibility. This is not a global CSRF token solution.
  Reassess required-Origin or token-based CSRF after confirming client
  compatibility.
- `TRUSTED_PROXY_COUNT` defaults to zero. If deployed behind a trusted proxy,
  set the exact hop count and ensure untrusted clients cannot bypass that proxy.
  Production trusted hosts, HTTPS, cookie `Secure`/`SameSite` policy, and
  secret management were not inspected. Configure and test them in deployment.
- The gym timezone and external scheduler are operator choices. Dry-run against
  an isolated DB and use a mail sink before enabling any live scheduler.
- SMTP success and a SQLite commit cannot be atomic. A stale/uncertain attempt
  can be retried and a duplicate email is possible; exactly-once delivery is
  not claimed.
- A local-only browser smoke review was performed with a seeded test account;
  no real Gemini request, live SMTP delivery, or production verification was
  performed in this release.
- Deployment-level rate limits and inherited admin/session policies remain
  separate operator/security-review work.

## Historical handoffs and contracts

- [Phase 1 audit](PHASE_1_AUDIT.md) and [Phase 1 handoff](PHASE_1_HANDOFF.md)
- [Phase 2 handoff](PHASE_2_HANDOFF.md)
- [Phase 3 handoff](PHASE_3_HANDOFF.md)
- [Phase 4A](PHASE_4A_HANDOFF.md), [4B](PHASE_4B_HANDOFF.md),
  [4C](PHASE_4C_HANDOFF.md), and [4D](PHASE_4D_HANDOFF.md) handoffs
- [Phase 5 handoff](PHASE_5_HANDOFF.md)
- [Phase 6 handoff](PHASE_6_HANDOFF.md)
- [Phase 7 handoff](PHASE_7_HANDOFF.md)
- [Phase 8 handoff](PHASE_8_HANDOFF.md)
- Service contracts: `docs/FRICTION_ANALYSIS_SERVICE.md`,
  `docs/FRICTION_INSIGHTS_SERVICE.md`, and `docs/FRICTION_DASHBOARD.md`

# Royal Brothers Fitness Gym

A full-stack gym membership website built with Flask (Python) and SQLite: member registration with email verification, secure login with brute-force lockout, membership plan requests, an admin dashboard, and a public contact form.

## Features

- **Member accounts** — registration, login/logout, profile editing, and a fixed gym avatar (member photo upload is not implemented)
- **Email verification** — new accounts are unverified until the user clicks a link sent via Gmail SMTP; unverified accounts cannot log in
- **Login security** — accounts are locked for 15 minutes after 5 consecutive failed password attempts
- **Forgot / reset password** — secure, time-limited, single-use reset links sent by email
- **Membership plans** — browse plans, request one, admin approves/rejects
- **Admin dashboard** — separate admin login, manage members (verified only), membership plans, membership requests, and contact messages, with live stats
- **Contact form** — public inquiry form, viewable/markable-as-read by admin
- **Security practices** — Werkzeug password hashing (no plaintext passwords anywhere), hashed single-use tokens for email verification/password reset, all secrets read from environment variables (nothing hardcoded)

## Local development: setup and bootstrap

From the project root, use Python 3.11+ and install the pinned dependencies:

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with a fresh `SECRET_KEY` and non-empty `MAIL_USERNAME` and
`MAIL_PASSWORD` values; Gmail SMTP delivery requires a Gmail App Password.
`GEMINI_API_KEY` is optional at startup and is needed only for Gemini-backed
features. Never put real credentials or a production database in the release
archive. To create a new local database, run this once from the project root:

```sh
python - <<'PY'
import os, sqlite3
from dotenv import load_dotenv
load_dotenv()
path = os.environ.get("DATABASE_PATH", "royal_brothers_gym.db")
with sqlite3.connect(path) as conn:
    with open("schema/schema.sql", encoding="utf-8") as schema:
        conn.executescript(schema.read())
print("Initialized local database")
PY
python scripts/create_admin.py
python -m flask --app wsgi run
```

The app opens the path in `DATABASE_PATH`, or `royal_brothers_gym.db` in the
project root when unset. Set `DATABASE_PATH` in `.env` before initialization
if you want another isolated path. `TRUSTED_PROXY_COUNT` defaults to `0`; set
it only to the exact number of trusted reverse-proxy hops when the app is
behind a proxy you control. Do not trust forwarded headers when clients can
reach the app directly. The admin script prompts for credentials.
For tests, run `python -m unittest discover -s tests -v` and `node --test
tests/*.test.cjs` from the project root; the Python tests use temporary
databases and mocked mail/AI services.

## Upgrading an existing database

Run the backup-first migration tool from the project root:

```sh
python scripts/migrate_db.py --check   # report only; changes nothing
python scripts/migrate_db.py           # backup, then apply missing schema
```

The runner now integrates the legacy `schema/schema_updates.sql` auth changes
idempotently, including missing email-verification/login-lockout columns and
the verification-token table, then applies the fitness and reminder table
migrations. It does not create a missing database and verifies that every
pre-existing table retains its row count. Use the runner rather than executing
`schema_updates.sql` directly against an unknown database. On older databases
that predate email verification, the new `is_verified` column defaults to `0`;
review and deliberately handle existing-account verification policy after a
backup—this migration does not silently verify accounts.

## Membership Smart Reminder eligibility foundation (Phase 6)

Membership reminders use the existing `membership_requests.status`, `start_date`, and `end_date` fields. No duration or expiry is reconstructed by the reminder service. Preferences are stored in `membership_reminder_preferences` plus the normalized `membership_reminder_lead_times` table; default supported lead times are 7, 3, and 1 days. The server-side allowlist can be extended through `MEMBERSHIP_REMINDER_ALLOWED_LEAD_DAYS` (unique values 1–30, retaining the defaults). No preference row means reminders are **disabled** (opt-in), with the default lead times available as choices. The service computes eligibility only on the exact calendar date `end_date - lead_days`, treats `end_date` as inclusive, excludes invalid/missing dates and ambiguous overlapping active memberships, and never sends email or changes membership rows.

Fresh databases built from `schema/schema.sql` include the preference tables. For an existing database, preview and apply the existing backup-first migration from the project root:

    python scripts/migrate_db.py --check
    python scripts/migrate_db.py

Phase 6 provides preference persistence and exact-date eligibility. Phase 8 adds the authenticated member settings UI/API; the route derives the member ID from `session["user_id"]`, not a client-supplied ID. See `PHASE_6_HANDOFF.md` for the original foundation contract and `PHASE_8_HANDOFF.md` for the current integration.

## Membership reminder email delivery (Phase 7)

`app/services/membership_reminder_delivery_service.py` consumes only Phase 6 eligible reminders, rechecks the member's current opt-in and lead selection, resolves the email from the existing `users` row, and sends a deterministic plain-text notice through the existing Flask-Mail/Gmail SMTP configuration. The `membership_reminder_deliveries` table uniquely identifies a member/membership/expiry/lead combination; `membership_reminder_delivery_attempts` preserves each attempt's status and bounded, non-sensitive failure reason. Concurrent workers serialize the claim with SQLite `BEGIN IMMEDIATE` before SMTP.

Transient failures are retried at most three total attempts (5-minute then 15-minute backoff), through the following calendar day or the membership expiry date, whichever comes first. Invalid addresses, SMTP authentication failures, and SMTP recipient rejections are terminal. SMTP acceptance and local SQLite commit cannot be atomic, so a process crash in that gap may cause a retry duplicate; the service does not claim exactly-once delivery. Phase 7 itself added no automatic trigger; Phase 8 adds only an explicitly invoked external-scheduler command. Existing-database migration is covered by the same backup-first commands above. See `PHASE_7_HANDOFF.md` for the precise result contract and limitations.

## Member reminder settings and external scheduler (Phase 8)

The Profile page now lets a signed-in member opt in/out and choose supported lead days (default choices: 7, 3, and 1). No preference row means disabled. `GET` and `PUT /api/membership/reminder-preferences` are session-bound; the API ignores query IDs, rejects client-supplied identity fields, validates all submitted values server-side, requires a matching explicit `Origin` on updates, and returns no-store responses. The settings UI is responsive and reloads server-persisted values after saving.

The only scheduled-task entry point is the explicit command below. It does **not** run at Flask import, app startup, login, dashboard render, or from a web request:

```sh
python scripts/run_membership_reminders.py --dry-run
python scripts/run_membership_reminders.py
python scripts/run_membership_reminders.py --as-of 2026-10-09
```

`--dry-run` calls the Phase 6 read-only exact-date eligibility service and reports the eligible count. It sends no email, does not call the Phase 7 delivery service, does not read the delivery/retry ledger, and writes no preference, attempt, or success record. Its count therefore does not account for prior sends or due retries. A live run requires `SECRET_KEY`, `MAIL_USERNAME`, and `MAIL_PASSWORD` plus the correctly selected `DATABASE_PATH`; missing SMTP settings fail before app creation. The command outputs privacy-safe JSON counts and returns a nonzero exit code for configuration/runtime or partial-delivery failures. `attempted` is derived from the Phase 7 `sent`, `failed`, and `uncertain` result counts.

For an external scheduler, first choose the gym's approved IANA timezone and configure the scheduler to use it; the repository does not define the business timezone. The default date follows the host's local date, so pass `--as-of YYYY-MM-DD` from a small operator-managed wrapper if the host timezone differs. Install the project requirements, set the app's normal environment (`SECRET_KEY`, `MAIL_USERNAME`, `MAIL_PASSWORD`, and `DATABASE_PATH`), and invoke the command from the project root, for example:

```cron
*/5 * * * * cd /path/to/project && /path/to/venv/bin/python scripts/run_membership_reminders.py
```

This example is only a pattern, not a deployment instruction: adjust paths and configure the platform timezone explicitly. A cadence of five minutes or less is needed to service the documented five- and fifteen-minute retry backoff promptly; the external scheduler should log the command's JSON summary and alert on nonzero exits. The Phase 7 database claim/deduplication protection remains in force for overlapping reminder attempts, but Phase 8 adds no scheduler-wide lock. Test first with an isolated database and mail sink. No live host, production database, or real recipient was accessed or configured here. See `PHASE_8_HANDOFF.md`.

## Fitness Progress Tracking (Step 5)

Members log weight entries (date, weight in kg, optional notes) on the Profile page, see their history,
basic trend info (change, lowest/highest/average, BMI from their Fitness Profile height) and a small chart,
and can edit or delete their own entries. API: `GET/POST /api/progress`, `PUT/DELETE /api/progress/<id>`.
No AI service is used. Run the tests with `python -m unittest discover -s tests -v`.

## AI Fitness Insights (Step 6)

On the Profile page, members can generate personalised insights (progress summary, weight trend,
consistency, workout recommendations, areas to improve, next steps) from their own Fitness Profile,
Workout Plan, Daily Plan and Progress history. API: `GET /api/insights`, `POST /api/insights/generate`.
Gemini only receives fitness numbers (no name, email, user id, free-text timing or progress notes) and its
output is validated. Insights are advice only: they never change progress entries or plans.

## Smart Workout Recommendations (Step 7)

On the Profile page, members can generate workout suggestions (exercises to focus on, intensity/volume
adjustments, recovery, areas needing attention, progression) from their own Fitness Profile, current Workout
Plan, recent Progress and saved AI Insight. API: `GET /api/workout-recommendations`,
`POST /api/workout-recommendations/generate`. Gemini only receives fitness data (no name, email, user id,
free-text timing or progress notes) and its output is validated. Suggestions only: the saved workout plan and
progress are never changed, and a failed generation keeps the previous recommendation.

## AI Nutrition Planner (Step 8)

On the Profile page, members can generate a general nutrition plan (daily calorie range, protein range,
hydration, meal suggestions, pre/post-workout nutrition, food choices) from their own Fitness Profile,
current Workout Plan, recent Progress and saved Workout Recommendation. API: `GET /api/nutrition-plan`,
`POST /api/nutrition-plan/generate`. Gemini only receives fitness data (no name, email, user id, free-text
timing or progress notes). Output is validated (calorie floor/range, protein g/kg bounds, hydration range;
extreme-diet or medical wording is rejected). It is general guidance, not medical advice: the profile,
workout plan and progress are never changed, and a failed generation keeps the previous nutrition plan.

## Member AI Dashboard (Step 9)

`dashboard.html` (linked from the Profile page) gives each member one overview: fitness goal, today's
workout/rest status and daily plan, latest weight and change, nutrition targets, the key workout
recommendation and the latest AI insight, each with a button to the detailed section on the Profile page.
API: `GET /api/dashboard` (read-only, logged-in member only). It summarises data the earlier steps already
saved, creates no new tables (no migration), never calls Gemini, and shows a friendly empty state for any
section that has no data yet.


## Admin AI Management (Step 10)

The existing admin dashboard has a new read-only **AI Management** tab (same admin login; no second admin
system). API: `GET /api/admin/ai/overview` (admin session required; members get 401). It shows whether the Gemini
API key is configured (a yes/no only; the key is never returned), the model name, and for each AI feature
(workout plans, daily plans, insights, workout recommendations, nutrition plans) the number of saved records and
the latest generation time. It never shows member content, never calls Gemini and has no edit or generate
controls. A table that is not migrated yet is shown as "Unavailable" instead of failing. No new tables, so no
migration is needed. An enable/disable switch was intentionally not added: it would need a new settings table and
changes to every Step 3-8 generation route.

## Member Journey Friction Detector and Admin Insights (Phases 1–3)

The friction feature is implemented end-to-end: a read-only detector
(`app/services/friction_analysis_service.py`) reports exact aggregate patterns
from contact messages and membership requests; a separate Gemini interpretation
service validates evidence-linked suggestions; and the admin-only
`/admin/friction-insights` page shows verified metrics and optional AI
interpretations. Names, emails, phone numbers, raw messages, and member IDs are
excluded from the aggregate/AI contract. Page loads do not call Gemini, and the
feature does not mutate membership, plans, messages, or send mail. Admin APIs:
`GET /api/admin/friction-insights` and
`POST /api/admin/friction-insights/generate`. See
`docs/FRICTION_ANALYSIS_SERVICE.md`, `docs/FRICTION_INSIGHTS_SERVICE.md`, and
`docs/FRICTION_DASHBOARD.md`. Provider calls are mocked in automated tests; no
live Gemini or production verification was performed as part of this release.

## Final integration status (Phase 9)

Phase 9 closes the local integration/regression/documentation/package work for
the three requested AI/reminder feature tracks. It includes safe profile-card
rendering, shared supplied-Origin checks, an idempotent legacy schema upgrade,
and correct `uncertain` reporting for stale reminder leases. The release ZIP
was tested after fresh extraction; details, exact test totals, known
limitations, and deployment checks are recorded in `PHASE_9_HANDOFF.md` and
`FINAL_PROJECT_HANDOFF.md`. No live site, production database, real recipient,
or external scheduler was accessed or configured.

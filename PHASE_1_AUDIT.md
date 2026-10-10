# PHASE 1 AUDIT — Member Journey Friction Detector

Audited from the uploaded ZIP (`royal-brothers-gym_ZIP_.zip`). Work was done only on a clean copy; the
uploaded files were never modified (the uploaded DB was opened `mode=ro`; its checksum and timestamp were
unchanged afterwards).

## 1. Existing architecture
- Flask 3.0.3 app factory `create_app()` in `app/__init__.py`; entry point `wsgi.py` (`gunicorn wsgi:app`, Python 3.11.9).
- 13 blueprints under `/api/...` (auth, membership, contact, admin, ai test, fitness, workout, daily, progress, insights, recommendations, nutrition, dashboard). `app/routes/reservation_routes.py` exists but is **not registered**.
- Static multi-page front end (`app/static/*.html/js/css`), no templating engine.
- DB: SQLite via `app/extensions.py::get_db_connection()` (MySQL-compat wrapper: `%s` placeholders, dict rows, datetime converters, `PRAGMA foreign_keys=ON`). SQL lives in `app/models.py` (970 lines).
- Config: `app/config.py` (reads `.env`; **raises at import if `SECRET_KEY`, `MAIL_USERNAME`, `MAIL_PASSWORD` are missing** — so anything under `app.*` needs them set).
- Gemini: `app/services/gemini_service.py` (`generate_text`, `is_configured`, `GeminiError`); model default `gemini-3.5-flash-lite`.
- Admin AI Management (Step 10): `GET /api/admin/ai/overview` + `models.get_ai_record_stats()` + a tab in `admin-dashboard.html` / `admin.js`. Read-only; **not changed**.
- Auth: members use `session["user_id"]`; admins use a separate `session["admin_id"]`, enforced by the `admin_login_required` decorator defined in `app/routes/admin_routes.py`. Phase 3 should reuse it.
- Migrations: `schema/schema.sql` (full), `schema/schema_updates.sql`, `schema/step2..8_*.sql`, `scripts/migrate_db.py` (backs up then adds AI tables). Admin created with `scripts/create_admin.py`.
- Tests: `unittest` (`python -m unittest discover -s tests`), shared `tests/base.py` (temp SQLite from `schema.sql`, fake env, Gemini mocked). Baseline before my changes: **117 tests, all passed**.

## 2. Actual relevant tables and columns (inspected from `schema.sql` and the uploaded DB)
| Table | Columns |
|---|---|
| `contact_messages` | id, name, phone, email, subject, message, is_read (0/1), created_at |
| `membership_requests` | id, user_id → users(id) ON DELETE CASCADE, plan_id → membership_plans(id), status CHECK IN ('pending','active','rejected'), request_date, start_date, end_date |
| `membership_plans` | id, plan_name, duration_months, price, features |
Other tables (users, admins, tokens, fitness/AI tables) exist but are out of scope and were not read.

Uploaded DB (row counts only): contact_messages 3 (all read; 2026-08-14 → 2026-10-07), membership_requests 3
(1 active, 2 rejected, 0 pending), membership_plans 3. Its schema matches `schema.sql` for these three tables.

## 3. Relationships
`membership_requests.user_id → users.id`, `membership_requests.plan_id → membership_plans.id`.
`contact_messages` has **no foreign key** to users or plans (only a free-text e-mail), so enquiries cannot be tied to requests.

## 4. Data suitable for friction detection
- Contact `subject` + `message` (free text) + `created_at` → recurring topics, time spans.
- `email` → only to count distinct senders (never output).
- `membership_requests.status` / `request_date` / `user_id` → status mix, aged pending rows, re-requests after rejection.
- `membership_plans.features` empty → possible information gap; `plan_id` joins → requests per plan.
- No existing classification logic existed to reuse (Gemini code is for member fitness plans only).

## 5. Not available (so not analysed)
Reply/resolution of a message (`is_read` ≠ answered); rejection reasons; status-change timestamps; cancellations/abandonment;
payments; expiry events; attendance; satisfaction; deleted requests (admins can delete them); non-English text understanding.

## 6. Must remain unchanged
All routes, templates/static pages, auth (member + admin), Gemini service, AI Management tab/route, schema files, migrations,
config and existing tests. **None were modified.**

## 7. Files added / modified
Added: `app/services/friction_analysis_service.py`, `scripts/run_friction_analysis.py`,
`tests/test_phase1_friction_analysis.py`, `docs/FRICTION_ANALYSIS_SERVICE.md`, `PHASE_1_AUDIT.md`, `PHASE_1_HANDOFF.md`.
Modified: `README.md` (one appended section). No application code, route, schema or existing test was edited.

## 8. Integration point
`app/services/` is the project's service location. Phase 3 can import `analyze_member_journey_friction` from an admin route
guarded by `admin_login_required`; the service itself has no Flask dependency.

## 9. Risks and limitations
- **Very small real dataset** (3 messages): the engine correctly reports `insufficient_data`; findings will only become meaningful as messages accumulate.
- Keyword rules are English-only and heuristic; unmatched text is "unclassified" rather than guessed. Rules should be reviewed against real messages.
- Thresholds (min messages, strength levels, pending age 7 days) are configurable analysis rules, not facts.
- The service opens its own read-only connection (`mode=ro` + `query_only`) instead of `get_db_connection()`, because the latter is read/write and creates a missing file. This is a deliberate safety deviation.
- **Security note:** the uploaded ZIP contained a real `.env` (Gmail app password, secret key), a `venv/`, the live-looking SQLite DB with contact messages containing personal data, and a DB backup. All were excluded from the output. Because they were shared outside your machine, consider rotating the Gmail app password, `SECRET_KEY` and Gemini key.

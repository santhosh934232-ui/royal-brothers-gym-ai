# PHASE 3 HANDOFF — Member Journey Friction Detector: Admin Dashboard Integration

## Status
Phase 3 complete (admin page, API, tests, docs). Not done by design: real Gemini API key setup and any real Gemini call,
anything beyond Phase 3. Work was done only in this AI development copy; the live website and its database were never touched.

## Baseline (before any Phase 3 change; Python 3.12.3, Flask 3.0.3 from requirements.txt)
185 tests run, 185 passed (117 original + 36 Phase 1 + 32 Phase 2).

## What was built
* **Navigation**: new sidebar link "Journey Friction Insights" in the existing admin dashboard (`admin-dashboard.html`).
* **Dedicated page**: `GET /admin/friction-insights`. Admin session required; anonymous and member sessions get HTTP 401 and a plain
  "Admin access required" page with no data. The HTML is stored in `app/admin_pages/` (outside `app/static`) so the public static route
  cannot serve it (tested: 404 via every static path).
* **Verified metrics**: `GET /api/admin/friction-insights[?since_days=30|90|180|365]` runs the Phase 1 analysis only. It never calls Gemini.
* **AI insights**: `POST /api/admin/friction-insights/generate` (JSON) calls the existing Phase 2 `generate_friction_insights()`; only when the
  admin clicks the button. Insufficient data / no findings => no Gemini call.
* **Adapter** `app/services/friction_dashboard_service.py`: input allow-list, field-by-field whitelisting, text sanitising, status mapping.
* Verified data (`VERIFIED DATA`) and AI text (`AI INTERPRETATION - possible, not proven`) are shown in separate, labelled blocks, with
  priority basis, limitations, information needed, warnings and the Phase 2 disclaimer.

## Files
Added: `app/services/friction_dashboard_service.py`, `app/routes/admin_pages_routes.py`, `app/admin_pages/friction-insights.html`,
`app/static/admin-friction-insights.js`, `tests/test_phase3_friction_dashboard.py`, `docs/FRICTION_DASHBOARD.md`, `PHASE_3_HANDOFF.md`.
Modified (verified by diff against the Phase 2 ZIP; no existing line was removed except the one noted):
* `app/routes/admin_routes.py` — additions only: imports, docstring route list, one new section with 2 routes. No existing route touched.
* `app/__init__.py` — import + `register_blueprint(admin_pages_bp, url_prefix="/admin")`.
* `app/static/admin-dashboard.html` — one sidebar `<a>` added.
* `app/static/admin.js` — **one line changed**: `initTabs` now selects `.admin-tab-btn[data-tab]` so the new link is not bound as a tab (otherwise a click would throw).
* `app/static/admin.css` — appended `fi-*` styles (existing design tokens only).
* `README.md` — one appended section.
Unchanged: Phase 1 and Phase 2 services, `gemini_service.py`, config, models, schema (no new/changed SQL files), `Procfile`, `requirements.txt`,
all existing tests, all other routes and pages.

## Security / privacy design
* Auth: same `admin_login_required` / `session["admin_id"]` as the rest of the admin area. A member session is not an admin session.
* No personal data in any response or in the Gemini prompt: no names, e-mails, phones, user ids, message text/subjects, matched keywords,
  example record ids, plan names, password hashes, API key, DB path or stack traces. Tests plant such values in the DB and assert absence
  in GET, POST, error responses, the page, the JS and the prompt sent to the (mocked) Gemini.
* Escaping: server removes control characters and `<` `>` from all text; the browser uses `textContent` only (test scans the JS for HTML-injection APIs);
  strict CSP on the page (no inline script, `script-src 'self'`, `frame-ancestors 'none'`); `no-store` caching.
* Input validation: `since_days` allow-list (ASCII digits only; found and fixed a bug during testing where Unicode digits were accepted); unknown/repeated
  parameters, non-JSON, wrong types, cross-site `Origin` rejected.
* Quota protection: one run at a time per admin + 30 s pause after any run that called Gemini.
* Read-only: no SQL writes, no mail, no schema change. Tests compare the full DB dump and the SQLite file SHA-256 before/after all calls, and assert an empty Flask-Mail outbox.

## Test results (actually run)
* Phase 3 tests: **72 run, 72 passed, 0 failed, 0 skipped** (admin access, member denial, logged-out denial, metrics states, AI insights, Gemini error mapping, retry limits,
  input validation, escaping, privacy, read-only, service-unit tests, regression).
* Full suite in the working folder: **257 run, 257 passed, 0 failed, 0 skipped** (185 existing + 72 new). Command: `python -m unittest discover -s tests -t .`
* Mutation checks: 12 deliberate breakages (removing either API guard, opening the page, disabling `<`/`>` stripping, leaking record ids, writing to the DB from the route,
  removing input validation / cross-site check / cooldown, leaking exception text, making GET call Gemini, falsifying a count) — each made at least one test fail; code restored afterwards.
* Browser-script check: the page script was run in jsdom (outside the project; not shipped) against mocked API responses for ready / AI configured and not / insufficient data / no findings /
  server error / network error / non-JSON / 401 / 429 / Gemini error / window selection, including hostile `<img onerror>` text: 23/23 checks passed (no element created, no script executed).
* Fresh-folder rerun of the final ZIP: ZIP extracted into a brand-new folder, brand-new virtualenv installed only from the extracted `requirements.txt`, run with an empty environment (`env -i`): **257 run, 257 passed, 0 failed, 0 skipped**. Repeated on the final ZIP (after this file was finalised) with the same result.

## How to run
```
pip install -r requirements.txt
python -m unittest tests.test_phase3_friction_dashboard -v     # Phase 3 only
python -m unittest discover -s tests -t .                      # everything
```
Tests use temp SQLite files and fake environment values; `.env` and any real DB are never read. Gemini is always mocked or unconfigured.
To see the page locally: create a local `.env` and DB as in README, create an admin (`scripts/create_admin.py`), log in at `/admin-login.html`, open the sidebar link.

## Known limitations / not tested
* **No real Gemini call** was made (no key by design). Real model output may be rejected by Phase 2's strict validation (one retry, then a safe `invalid_ai_output` message).
* **Not visually checked in a real browser**: layout/CSS were reviewed and DOM behaviour was tested in jsdom, but no screenshot/browser run was possible here. Mobile layout is untested.
* **Gunicorn timeout risk**: Gemini timeout is 20 s per call and Phase 2 may retry once (~40 s worst case); `Procfile` uses Gunicorn's default 30 s worker timeout, so a slow double attempt could be cut off
  by the server. Not changed here (deployment config is out of scope); decide at final integration (e.g. `--timeout 60`).
* Cooldown/in-flight guards are in process memory: per Gunicorn worker, reset on restart.
* Nothing is stored: every "Generate" recomputes and spends Gemini quota (only when data is sufficient). No history table (would need a schema change).
* Today's real data has only a few contact messages, so the page will most likely show `insufficient_data` until more enquiries exist (expected, safe behaviour).
* Insight quality is bounded by Phase 1's English keyword topics. Page and tests were not run on Python 3.11.9 specifically (3.12.3 used) or against the production DB.
* GET on the POST-only generate URL returns the app's normal static-catch-all 404 (same as other POST-only API routes), not 405.

## For the final integration phase
1. Put the real `GEMINI_API_KEY` in the local/hosted environment (never in code or the ZIP); run `python scripts/run_friction_insights.py` on a DB with >= 5 classifiable messages, then use the page.
2. Review `validation.issues` codes shown in server logs if real replies are rejected; tune the Phase 2 prompt / validators if needed.
3. Decide on the Gunicorn timeout and whether insight history/caching is wanted.

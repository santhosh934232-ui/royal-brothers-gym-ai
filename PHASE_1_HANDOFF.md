# PHASE 1 HANDOFF — Member Journey Friction Detector (Analysis Engine)

## Status
Phase 1 complete: audit, read-only engine, tests, docs. Phase 2 (Gemini) and Phase 3 (admin UI) are NOT started.

## What was implemented
`app/services/friction_analysis_service.py` — `analyze_member_journey_friction(db_path=None, conn=None, now=None, **overrides)`
returns one JSON-serialisable dict (contract: `docs/FRICTION_ANALYSIS_SERVICE.md`). Features: schema inspection, keyword topic
classification (11 topics, 3 unclassified reasons), exact de-duplicated counts, distinct-sender counts, time ranges,
transparent evidence-strength rules, friction findings with "supports / uncertain / limitations", insufficient-data and
partial/error states, read-only SQLite access, no PII in output. CLI: `scripts/run_friction_analysis.py`.

## Files
Added: `app/services/friction_analysis_service.py`, `scripts/run_friction_analysis.py`, `tests/test_phase1_friction_analysis.py`,
`docs/FRICTION_ANALYSIS_SERVICE.md`, `PHASE_1_AUDIT.md`, `PHASE_1_HANDOFF.md`. Modified: `README.md` (appended section).

## Schema findings
See `PHASE_1_AUDIT.md` §2–§5. Tables read: `contact_messages`, `membership_requests`, `membership_plans`.

## How to run the tests
From the project root (Python 3.11+; `pip install -r requirements.txt`):
    python -m unittest tests.test_phase1_friction_analysis -v      # Phase 1 only
    python -m unittest discover -s tests                            # everything
Tests use temp SQLite files; the real DB and `.env` are never touched.

## Exact test results (run in this environment, Python 3.12.3, Flask 3.1.3)
- Baseline before changes: 117 run, 117 passed.
- Phase 1 tests: **36 run, 36 passed, 0 failed, 0 skipped**.
- Full suite after changes: **153 run, 153 passed, 0 failed, 0 skipped**.
- Not run: nothing skipped. Not tested: real Gemini/SMTP (never used), the production DB, Python 3.11.9 specifically
  (this environment has 3.12.3), `gunicorn`/browser UI (no UI changed).
- Also executed once: the CLI against the uploaded DB (read-only) → `insufficient_data` (3 messages, 1 classified); DB checksum/timestamp unchanged.

## Known limitations / remaining work
English keyword rules; thresholds are tunable defaults; no reply tracking; contact↔account not linkable; no rejection
reasons/payments/expiry data; the topic rules have not been validated against a large real corpus (only 3 real messages exist).
Not done by design: Gemini interpretation, admin endpoint/tab, AI Admin Assistant, Smart Reminders.

## Continuing with Phase 2
1. Upload `Royal-Brothers-Gym-AI-Phase-1.zip` (create `.env` locally; build a DB from `schema/schema.sql`).
2. Read `docs/FRICTION_ANALYSIS_SERVICE.md`. Feed Gemini ONLY the dict from `analyze_member_journey_friction()` (already PII-free), via `gemini_service.generate_text`.
3. Instruct Gemini to copy counts/dates verbatim, label items "possible", never claim unsupported causes, and return a validated JSON schema; skip the call and return a fixed message when `insufficient_data.is_insufficient` is true.
4. Keep recommendations evidence-linked via `finding_id`. Do not modify the engine's counts. Add Phase 2 tests with Gemini mocked.

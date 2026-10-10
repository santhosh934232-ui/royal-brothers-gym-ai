# PHASE 2 HANDOFF — Gemini Insights Engine (Member Journey Friction Detector)

## Status
Phase 2 service, tests and docs are complete. The feature is NOT finished overall: no admin UI/route yet (Phase 3),
and the real Gemini API has not been called (no key was available).

## Baseline (before any Phase 2 change, run in this environment, Python 3.12.3)
153 tests run, 153 passed (117 original + 36 Phase 1).

## Files
Added: `app/services/friction_insights_service.py`, `scripts/run_friction_insights.py`,
`tests/test_phase2_friction_insights.py`, `docs/FRICTION_INSIGHTS_SERVICE.md`, `PHASE_2_HANDOFF.md`.
Modified: `README.md` (one appended section).
Unchanged (verified by file comparison against the Phase 1 ZIP): all other files, including Phase 1 service, `gemini_service.py`,
config, routes, schema and existing tests. `docs/FRICTION_ANALYSIS_SERVICE.md` did not need changes (Phase 1 interface is untouched).

## How Phase 1 connects to Gemini
`generate_friction_insights()` calls `analyze_member_journey_friction()` (or accepts its dict), builds `verified_facts` +
finding payloads from it, and calls the existing `gemini_service.generate_text(prompt, system_instruction=..., max_output_tokens=3000,
temperature=0.2)`. Model, key and timeout come from the existing `Config` (`GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_TIMEOUT_SECONDS`).
No second client/config. `GeminiError` is caught and mapped to a safe `error` object.

## Output schema
See `docs/FRICTION_INSIGHTS_SERVICE.md` (statuses `ok|insufficient_data|no_findings|error`; `verified_facts`; `insights[]` with
`facts` (verified) separate from `interpretation` (AI); `priority` computed by fixed rules from Phase 1 evidence strength).

## Privacy safeguards
Only aggregated counts, fixed labels, date ranges and code-authored rule text are sent. Tests prove names, e-mails, phones,
plan names, message text (including an injected "ignore all previous instructions" message), user ids, hashes and keywords are absent
from the prompt and the result. Insufficient data => no Gemini call.

## Error handling
Missing key, invalid key, quota, timeout, unavailable, empty response, unknown exception -> `status: error` with fixed safe
message (no secrets, traces or payloads). Malformed JSON / wrong types / missing fields / wrong counts / unknown finding ids /
unsupported numbers or claims -> insight dropped; none valid -> exactly one retry -> `invalid_ai_output`. Max 2 Gemini calls per run.

## Test results (actually run)
- Phase 2 tests: **32 run, 32 passed, 0 failed, 0 skipped**.
- Phase 1 tests: 36 run, 36 passed. Original tests: 117 run, 117 passed.
- Full suite after changes: **185 run, 185 passed, 0 failed, 0 skipped**.
- Mutation check: disabling the count-match and number checks made 4 tests fail (so those tests do detect regressions); code restored afterwards.
- CLI smoke test on an empty temp DB: returned `insufficient_data`, no Gemini call.
- Not tested: **a real Gemini API call (pending)**; live Python 3.11.9; production DB; any UI.
- To verify real Gemini yourself: put your key in your local `.env`, use a DB with at least 5 classifiable messages containing a repeated topic, run
  `python scripts/run_friction_insights.py`. Expect `status: ok`; if `error`, check `error.code` and `validation.issues`.

## Known limitations
- Real model behaviour is unverified; the strict wording/number validation may reject some real replies (one retry, then `invalid_ai_output`).
  Review `validation.issues` on first real runs and tune the prompt/`_UNSUPPORTED_CLAIM` if needed.
- No storage/caching/history: every call recomputes and spends Gemini quota (only when data is sufficient).
- The real uploaded database has only 3 contact messages, so today the feature would return `insufficient_data`.
- Insight quality is bounded by Phase 1 keyword topics (English only).
- Phase 1 request-based findings (pending aging, repeat after rejection) are always "weak" strength, so they get priority `low`.

## Instructions for Phase 3 (admin integration)
1. Add `GET /api/admin/friction-insights` (and optionally a separate POST to generate) in `app/routes/admin_routes.py` guarded by
   `@admin_login_required`; return `generate_friction_insights()` as JSON, using `result["error"]["http_status"]` for errors.
   Prefer POST-to-generate + a cheap GET for the Phase 1 analysis only, so page loads don't spend Gemini quota.
2. Add a tab next to "AI Management" in `admin-dashboard.html`/`admin.js`, following the existing pattern (all server text via `textContent`, never `innerHTML`).
3. Render `verified_facts` / `insights[].facts` as data and `interpretation` under an "AI interpretation – not proven" label; show `priority_basis`,
   `limitations`, `additional_data_needed`, `warnings`, and the disclaimer. No buttons that change requests/plans/messages.
4. Optional history table would need a schema file + `scripts/migrate_db.py` entry; decide first whether storage is wanted.
5. Add route tests (admin 401 for logged-out/member sessions, Gemini mocked, DB snapshot unchanged) and re-run the full suite (expect >= 185 passing).

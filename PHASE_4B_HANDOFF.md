# Phase 4B Handoff — Gemini Admin Answer Service

## Scope

Phase 4B adds a backend-only Gemini answer service over the existing Phase 4A aggregate data service. It does not add routes, endpoints, dashboard/chat UI, authentication changes, schema changes, migrations, tables, or dependencies. Phase 4C and 4D were not started.

## Files created

- `app/services/admin_assistant_answer_service.py` — question validation, Phase 4A integration, strict aggregate allowlist, grounded Gemini prompt, response checks, and safe error envelopes.
- `tests/test_phase4b_admin_assistant_answer_service.py` — isolated tests with mocked Gemini and controlled data.
- `PHASE_4B_HANDOFF.md` — this handoff.

No existing files were modified. The input was the Phase 4A ZIP supplied for this task; all work was done in a separate development copy.

## Architecture and public interface

Call `answer_admin_question(question)` from `app.services.admin_assistant_answer_service`. It accepts plain text up to 1,200 characters and returns a JSON-friendly mapping with one of three statuses:

- `ok`: includes an `answer` string.
- `insufficient_data`: includes an `answer` explaining that approved information is insufficient or private data is not available.
- `error`: includes a safe `error.code` and `error.message`.

The service validates input, checks Gemini configuration, calls `admin_assistant_data_service.get_admin_summary()`, validates and re-whitelists that response, then calls `gemini_service.generate_text()`. It does not query the database itself or pass through unknown data-service fields. It skips Gemini for private-data requests, Phase 4A failures, and a completely empty dataset.

## Gemini configuration and provider behavior

The service uses the existing `GEMINI_API_KEY`, `GEMINI_MODEL`, and `GEMINI_TIMEOUT_SECONDS` configuration through `gemini_service`. No API key is hardcoded or included in a prompt. The existing wrapper supplies the configured timeout (20 seconds in the current config) and normalizes provider failures; this service does not retry requests. No new dependency was needed.

Missing configuration returns a safe, actionable message identifying `GEMINI_API_KEY`. Authentication/permission failures, rate limits/quota exhaustion, timeouts, unavailable services/models, bad requests, empty responses, and unexpected failures map to fixed safe messages. Raw exception text, provider response details, and credentials are not returned.

## Privacy and prompt-injection controls

Only `members` aggregate counts and `membership_requests` aggregate counts/statuses/plan distribution are passed to Gemini. The outgoing object is reconstructed from an explicit key allowlist; unexpected keys and record lists are dropped. Plan labels are bounded and likely email/long-phone values are excluded. Common requests for member identities, contact details, credentials, private messages, or raw feedback are refused before reading data or calling Gemini.

The admin question and aggregate JSON are sent as explicitly untrusted content, separate from a system instruction that says they are data rather than instructions. The model receives no tools, database connection, executable code, or application functions. The answer is length-limited and numeric values are checked against numbers present in the approved aggregates; an unsupported numeric claim is converted to an `insufficient_data` response.

## Error behavior

Invalid/blank/oversized input returns `error / invalid_question`. A missing key returns `error / not_configured`. Phase 4A errors, malformed aggregate shapes, or unexpected data access failures return `error / data_unavailable`. Provider failures return safe error codes; empty or malformed model text returns `error / empty_response`. If the data set is empty or the model indicates that there is not enough data, the service returns `insufficient_data` rather than inventing an answer.

## Tests

New focused tests cover the valid flow and Phase 4A invocation, allowlist/privacy filtering, absent configuration, invalid questions, empty data, data-service errors, provider failures (including authorization, quota/rate-limit, timeout and other service errors), malformed output, private-data requests, email/phone/API-token values in questions, prompt injection, unsupported numerical claims, and safe handling of unexpected exceptions. All Gemini calls are mocked; no API key is required and tests do not use provider quota.

Validation run for this phase:

- Focused Phase 4B module: `python3 -m unittest tests.test_phase4b_admin_assistant_answer_service -v` — **14 tests passed**.
- Full suite: `python3 -m unittest discover -s tests -v` — **277 tests passed, 0 failures, 0 errors** (`Ran 277 tests in 87.382s`, `OK`).
- The complete suite is also run after extracting the final ZIP into a fresh directory; report that package-verification result in the delivery response.

## Limitations

Attendance, payment, revenue, contact-message content, and individual-member information are not available through the Phase 4A data contract and therefore cannot be answered. The numerical post-check catches unsupported numeric claims; it cannot formally prove every non-numerical statement generated by an LLM. The system instruction and restricted context reduce that risk, but downstream use should treat generated text as advisory and should not use it as an authorization or operational decision.

## Phase 4C integration guidance

Phase 4C may call `answer_admin_question(question)` from an authenticated admin-only route or assistant orchestration layer. Keep authentication and authorization outside this service; do not add a direct database query or pass member records to it. Preserve the structured `status` result, validate any client-supplied question at the boundary as well, and render the answer as text rather than trusted HTML. Surface `insufficient_data` and safe `error` results distinctly. Keep tests mocking `gemini_service.generate_text` so automated runs never require or spend Gemini quota.


## Phase 5 addendum — unavailable metrics

Phase 5 added a deterministic lexical guard for common unsupported metric categories (including attendance/check-ins, revenue/pricing, workouts/profile data, and unsupported time windows). Recognized requests return `insufficient_data` before database access or Gemini. The approved aggregate contract was not expanded. Because the guard is lexical rather than a complete semantic classifier, indirect or unrecognized phrasing may still reach the model; answers remain advisory. The focused/full test counts above are historical results from the earlier phase run; current Phase 5 counts are in `PHASE_5_HANDOFF.md` and `FINAL_PROJECT_HANDOFF.md`.

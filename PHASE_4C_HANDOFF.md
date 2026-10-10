# Phase 4C Handoff — Secure Admin Assistant API

## Scope and files

Added one admin-only JSON API route that delegates questions to the existing Phase 4B answer service. No dashboard or chat UI, JavaScript, Gemini implementation, database query, model, migration, schema change, login-flow change, or dependency was added. Phase 4D was not started.

- **Modified:** `app/routes/admin_routes.py` — added `POST /api/admin/assistant/ask`, request validation, safe response mapping, same-origin enforcement, and a per-admin in-memory cooldown.
- **Created:** `tests/test_phase4c_admin_assistant_api.py` — route tests that mock Phase 4B.
- **Created:** `PHASE_4C_HANDOFF.md` — this document.

The input was `Royal-Brothers-Gym-AI-Phase-4B.zip`; work took place in a separate development copy. Existing Phase 3, 4A, and 4B source functionality is retained.

## Endpoint and request/response contract

**Method and path:** `POST /api/admin/assistant/ask` (the app already mounts the admin blueprint at `/api/admin`).

The request must be JSON with exactly one property, `question`, containing a non-empty string no longer than 1,200 characters. Declared request bodies over 16 KiB are rejected before parsing. Unsupported content types, invalid JSON, non-object bodies, unknown keys, invalid question types, and empty questions receive safe JSON errors. The route calls `answer_admin_question(question)` only after authorization, origin, body, and question checks pass. It performs no direct database query and invokes no command or state-changing operation.

Example request:

```json
{"question":"How many verified accounts are there?"}
```

Example successful response (`200`):

```json
{"success":true,"status":"ok","answer":"There are 10 verified accounts."}
```

Example insufficient-data response (`200`):

```json
{"success":true,"status":"insufficient_data","answer":"There is not enough approved aggregate data to answer this question."}
```

Example safe service error (`503`):

```json
{"success":false,"status":"error","error":{"code":"not_configured","message":"The admin assistant is not configured. Contact the administrator."}}
```

All endpoint responses use `Cache-Control: no-store`. Answers remain JSON strings; the later UI must render them as text, not trusted HTML.

## Authentication and CSRF behavior

The route uses the existing `admin_login_required` decorator in `app/routes/admin_routes.py`. That established mechanism requires the signed Flask session's `admin_id`, populated by the existing admin login flow. Member sessions use `user_id`, so a member is rejected. Client-supplied fields such as `is_admin`, `role`, or `admin_id` are not used as authorization evidence. Authorization runs before request processing or Phase 4B invocation.

There is no global CSRF-token implementation in the inspected project. The route follows the existing admin friction-generation convention: `_same_origin_or_absent()` rejects a supplied `Origin` whose host differs from the request host; same-origin or absent `Origin` is accepted. No cookie or global CSRF settings were changed. The absent-Origin allowance preserves the existing API convention; browser clients should send the normal same-origin `Origin` header.

## Rate limiting and request bounds

The endpoint enforces a **30-second per-admin cooldown** and allows only one in-flight assistant call per admin per server process. An in-flight or cooldown rejection returns `429` and `Retry-After`. This mirrors the project's existing in-memory admin generation guard pattern. Like that existing pattern, state is process-local and resets on restart; it is not a distributed rate limiter. Invalid requests do not consume the cooldown or call the Phase 4B service.

The route rejects declared bodies over 16 KiB and questions over 1,200 characters. It does not change Flask's global request-size setting. The unsupported-method JSON response is `405` for recognized non-POST methods at this path.

## HTTP status mapping

| Condition | HTTP status |
|---|---:|
| Missing admin session | 401 |
| Cross-origin `Origin` | 403 |
| Malformed JSON, non-object, extra field, or invalid question | 400 |
| Declared body too large | 413 |
| Unsupported content type | 415 |
| Per-admin cooldown or in-flight request | 429 |
| Successful answer or insufficient-data result | 200 |
| Phase 4B not configured or aggregate data unavailable | 503 |
| Gemini timeout | 504 |
| Provider authorization/model/bad-response errors | 502 |
| Unexpected/internal service error | 500 |
| Unsupported method | 405 |

Provider and service response messages are not copied through from arbitrary exception text. The route maps known codes to fixed safe messages; unknown codes and malformed service results produce a generic `500` response.

## Tests and actual results

The focused module tests admin success, logged-out and member denial, spoofed client role fields, malformed/empty/non-string/oversized input, unknown request fields, malformed JSON, unsupported media types, oversized bodies, unsupported methods, same-origin/cross-origin/absent-Origin behavior, service status mapping, safe exception handling, malformed service responses, and rate limiting. All calls to the Phase 4B service are mocked; tests do not contact Gemini or use API quota.

- Focused: `python3 -m unittest tests.test_phase4c_admin_assistant_api -v` — **11 tests passed**.
- Full suite: `python3 -m unittest discover -s tests -v` — **288 tests passed, 0 failures, 0 errors** (`Ran 288 tests in 89.643s`, `OK`).
- The final packaged ZIP is extracted into a fresh directory and the complete suite is run from that copy; the delivery response reports that package-verification result.

## Limitations and security notes

The endpoint inherits the project’s existing session model and same-origin-or-absent CSRF convention; there is no CSRF token. The admin decorator verifies the session's `admin_id` key as the project currently does; it does not re-query the admins table on every request. The cooldown and in-flight guard are in-memory per process and are not shared across multiple workers or hosts. No broad global request-size limit was added; the endpoint checks declared length and enforces the narrower question limit.

## Phase 4D integration guidance

Phase 4D can call this endpoint only after the frontend has established an admin session through the existing admin login flow. Send same-origin JSON requests with the `question` field and rely on the server-side session cookie; never send a role/admin flag as proof of authority. Handle `401`, `403`, `429`, and service errors distinctly, including `Retry-After`; render `answer` using a text-only sink such as `textContent`. Do not add client-side API keys, expose provider errors, or permit question-driven state changes. Keep automated UI/API tests mocking the Phase 4B service and avoid real Gemini calls.


## Phase 5 addendum — current Origin validation

The Phase 4C implementation compared only the supplied Origin's network location to the request host. Phase 5 corrected this same-origin check to compare scheme, hostname, and effective port, normalize default ports, and reject malformed/non-HTTP(S) Origins; tests now cover cross-scheme, cross-port, explicit default-port, and malformed values. The helper is shared with the Phase 3 friction endpoint. The existing absent-Origin allowance is intentionally unchanged, and there is still no global CSRF token; this remains an unresolved risk, not a completed CSRF solution. The 11-test Phase 4C count above is historical; the current Phase 5 suite and results are recorded in `PHASE_5_HANDOFF.md`.

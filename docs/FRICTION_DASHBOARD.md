# Member Journey Friction Insights - Admin Dashboard (Phase 3)

Read-only admin feature. Reuses Phase 1 (`friction_analysis_service`), Phase 2 (`friction_insights_service`), the existing
admin session (`session["admin_id"]`, `admin_login_required`), `style.css` / `admin.css` and the existing admin sidebar.

## Files
| File | Role |
|---|---|
| `app/routes/admin_routes.py` | Two new routes in the existing admin blueprint (new section only; nothing existing edited) |
| `app/routes/admin_pages_routes.py` | Serves the admin-only HTML page (`/admin/friction-insights`) |
| `app/admin_pages/friction-insights.html` | Page markup. Lives OUTSIDE `app/static`, so the public static route can never serve it |
| `app/static/admin-friction-insights.js` | Page script. Renders every server string with `textContent` only |
| `app/static/admin.css` | Appended `fi-*` styles using existing design tokens |
| `app/static/admin-dashboard.html` | One sidebar link added |
| `app/static/admin.js` | `initTabs` selector narrowed to `.admin-tab-btn[data-tab]` so the new link is not treated as a tab |
| `app/services/friction_dashboard_service.py` | Input validation, field whitelisting, text sanitising (no DB, no Gemini, no writes) |
| `app/__init__.py` | Registers `admin_pages_bp` at `/admin` |

## Endpoints (all require an admin session)
| Method + path | Purpose | Gemini? |
|---|---|---|
| `GET /admin/friction-insights` | HTML page. 401 HTML "Admin access required" for anyone else | no |
| `GET /api/admin/friction-insights[?since_days=N]` | Verified metrics + findings (Phase 1 only) | **never** |
| `POST /api/admin/friction-insights/generate` body `{"since_days": N}` (JSON) | Validated AI insights (Phase 2) | only when data is sufficient and findings exist (max 2 calls) |

`since_days` allow-list: omitted / `null` / `"all"` or one of 30, 90, 180, 365. Anything else, unknown parameters or fields,
repeated parameters, non-JSON bodies -> 400/415. Cross-site `Origin` -> 403.

## Response states (`state`)
`ready` (GET only: findings exist, AI may be generated) · `ok` (POST: validated insights) · `insufficient_data` ·
`no_findings` · `error` (safe fixed message + `error.code`; HTTP 429/500/502/503/504 only).
Every response includes `success`, `readOnly: true`, `verified_facts`, `warnings`, `disclaimer`; `Cache-Control: no-store`.

## Safeguards
* **Admin only**: page and APIs check the admin session. Member sessions (`user_id`) are not admin sessions -> 401.
* **Whitelist**: the adapter rebuilds every object field by field; unknown keys from lower layers are dropped. Counts that are not
  real non-negative integers are shown as "Not available", never guessed.
* **No personal data**: no names, e-mails, phones, user ids, message text/subjects, matched keywords, example record ids, plan names,
  password hashes, API key, DB path or stack traces in any response or in the Gemini prompt.
* **Escaping**: control characters and `<` `>` are removed server-side from all text; the browser uses `textContent` only; the page is
  served with a strict CSP (no inline script, `script-src 'self'`, `frame-ancestors 'none'`).
* **Quota protection**: one run at a time per admin and a 30 s pause after any run that called Gemini
  (`FRICTION_GENERATE_COOLDOWN_SECONDS`, per process, in memory).
* **Read-only**: no SQL writes, no schema change, no e-mail; DB bytes proven unchanged by tests.

## Not covered here
Real Gemini calls and real API-key setup (end-of-project integration phase). History/storage of generated insights (would need a schema
change; not requested).

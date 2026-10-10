"""
Royal Brothers Fitness Gym - Admin Pages (Phase 3)

Serves admin-only HTML pages that must NOT be reachable through the public static
folder. The HTML lives in app/admin_pages/ (outside app/static, so the catch-all
static route can never serve it) and is returned only when an admin session exists.

Registered in app/__init__.py under url_prefix="/admin":
    GET /admin/friction-insights    Member Journey Friction Insights page (admin only)

Access rule is the same as the rest of the admin area: session["admin_id"] must be set.
A member session (session["user_id"]) is NOT an admin session, so members are denied,
exactly like logged-out visitors (HTTP 401 with a plain page; no data is included).
"""

import os

from flask import Blueprint, Response, session

admin_pages_bp = Blueprint("admin_pages_bp", __name__)

_PAGES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "admin_pages")

# Strict policy: only same-origin scripts, no inline script, no framing.
# Fonts / icon CSS come from the same CDNs the existing admin dashboard already uses.
_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' https://fonts.googleapis.com https://cdnjs.cloudflare.com; "
    "font-src https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)

_DENIED_HTML = """<!doctype html>
<html lang="en"><head><meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<meta name="robots" content="noindex, nofollow" />
<title>Admin access required | Royal Brothers Fitness Gym</title>
<link rel="stylesheet" href="/style.css" /><link rel="stylesheet" href="/admin.css" /></head>
<body class="admin-body"><div class="profile-status">Admin access required.
<a href="/admin-login.html" class="auth-link">Go to admin login</a></div></body></html>
"""


def _harden(resp):
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Content-Security-Policy"] = _CSP
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    return resp


@admin_pages_bp.route("/friction-insights", methods=["GET"])
def friction_insights_page():
    if "admin_id" not in session:
        return _harden(Response(_DENIED_HTML, status=401, mimetype="text/html"))
    with open(os.path.join(_PAGES_DIR, "friction-insights.html"), encoding="utf-8") as f:
        html = f.read()
    return _harden(Response(html, status=200, mimetype="text/html"))

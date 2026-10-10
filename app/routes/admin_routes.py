"""
Royal Brothers Fitness Gym - Admin Routes
Hidden admin login + full dashboard: manage members, membership plans,
membership requests, contact messages, and statistics.

Admin sessions are kept completely separate from user sessions
(session["admin_id"] vs session["user_id"]), so being logged in as a
user does NOT grant admin access, and vice versa.

Registered in app/__init__.py under url_prefix="/api/admin", so full paths are:
    POST /api/admin/login
    POST /api/admin/logout
    GET  /api/admin/dashboard/stats
    GET  /api/admin/ai/overview      (Step 10: read-only AI status and record counts)
    GET  /api/admin/friction-insights           (Phase 3: verified metrics only, NO Gemini call)
    POST /api/admin/friction-insights/generate  (Phase 3: validated AI insights, read-only)
    GET  /api/admin/members
    GET  /api/admin/plans
    POST /api/admin/plans
    PUT  /api/admin/plans/<id>
    DELETE /api/admin/plans/<id>
    GET  /api/admin/membership-requests
    POST /api/admin/membership-requests/<id>/status
    DELETE /api/admin/membership-requests/<id>
    GET  /api/admin/messages
    POST /api/admin/messages/<id>/read
"""

import threading
import time
from datetime import date, timedelta
from functools import wraps
from flask import Blueprint, request, session, jsonify, current_app
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash

from ..models import (
    get_admin_by_username,
    get_admin_by_id,
    get_all_users,
    get_all_plans,
    get_plan_by_id,
    create_plan,
    update_plan,
    delete_plan,
    get_plan_usage_count,
    get_all_membership_requests,
    get_membership_request_by_id,
    update_membership_request_status,
    delete_membership_request,
    get_all_contact_messages,
    mark_message_as_read,
    get_dashboard_stats,
    get_ai_record_stats,
)
from ..config import Config
from ..security import is_same_origin
from ..services.gemini_service import is_configured as gemini_is_configured
from ..services import friction_dashboard_service as friction_view
from ..services.friction_insights_service import generate_friction_insights
from ..services.admin_assistant_answer_service import answer_admin_question

admin_bp = Blueprint("admin_bp", __name__)


def admin_login_required(f):
    """Blocks access unless an admin is logged in (session has admin_id)."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "admin_id" not in session:
            return jsonify({"success": False, "message": "Admin login required."}), 401
        return f(*args, **kwargs)
    return wrapper


def get_request_data():
    if request.is_json:
        return request.get_json()
    return request.form


def _verify_admin_password(password):
    """Verifies the given plaintext password against the currently
    logged-in admin's stored hash. Used to gate all destructive delete
    actions behind a fresh password re-entry. Never logs the password
    itself -- only success/failure is ever recorded."""
    if not password:
        return False

    admin = get_admin_by_id(session.get("admin_id"))
    if not admin:
        return False

    return check_password_hash(admin["password_hash"], password)


# ============================================
# ADMIN LOGIN / LOGOUT
# ============================================

@admin_bp.route("/login", methods=["POST"])
def admin_login():
    data = get_request_data()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if not username or not password:
        return jsonify({"success": False, "message": "Username and password are required."}), 400

    admin = get_admin_by_username(username)

    if not admin or not check_password_hash(admin["password_hash"], password):
        return jsonify({"success": False, "message": "Invalid admin credentials."}), 401

    session["admin_id"] = admin["id"]
    session["admin_username"] = admin["username"]

    return jsonify({"success": True, "message": "Admin login successful."}), 200


@admin_bp.route("/logout", methods=["POST"])
def admin_logout():
    session.pop("admin_id", None)
    session.pop("admin_username", None)
    return jsonify({"success": True, "message": "Admin logged out."}), 200


@admin_bp.route("/me", methods=["GET"])
def admin_me():
    """Lets admin-dashboard.html check if an admin is currently logged in."""
    if "admin_id" not in session:
        return jsonify({"success": False, "message": "Not logged in."}), 401
    return jsonify({
        "success": True,
        "admin": {"id": session["admin_id"], "username": session["admin_username"]}
    }), 200


# ============================================
# DASHBOARD STATISTICS
# ============================================

@admin_bp.route("/dashboard/stats", methods=["GET"])
@admin_login_required
def dashboard_stats():
    stats = get_dashboard_stats()
    return jsonify({"success": True, "stats": stats}), 200


# ============================================
# AI MANAGEMENT OVERVIEW (Step 10)
# Strictly read-only: configuration status + counts/timestamps of saved
# AI records. No member content, no secrets, no generation, no edits.
# ============================================

# (stats key, display name, step, endpoint members use)
AI_FEATURES = [
    ("workout_plan", "AI Workout Plan", 3, "/api/workout-plan"),
    ("daily_plan", "AI Daily Planner", 4, "/api/daily-plan"),
    ("insight", "AI Fitness Insights", 6, "/api/insights"),
    ("recommendation", "Smart Workout Recommendations", 7, "/api/workout-recommendations"),
    ("nutrition_plan", "AI Nutrition Planner", 8, "/api/nutrition-plan"),
]


@admin_bp.route("/ai/overview", methods=["GET"])
@admin_login_required
def ai_overview():
    try:
        configured = gemini_is_configured()
    except Exception:
        configured = False

    try:
        records = get_ai_record_stats()
    except Exception:
        records = {}

    features = []
    for key, name, step, endpoint in AI_FEATURES:
        rec = records.get(key)
        features.append({
            "key": key,
            "name": name,
            "step": step,
            "endpoint": endpoint,
            "available": rec is not None,
            "records": rec["count"] if rec else None,
            "lastGenerated": rec["latest"] if rec else None,
        })

    return jsonify({
        "success": True,
        "service": {
            "configured": configured,
            "model": Config.GEMINI_MODEL if configured else None,
            "message": ("AI service is configured." if configured else
                        "Gemini API key is not configured. Member AI generation is unavailable until it is set."),
        },
        "features": features,
        "readOnly": True,
    }), 200


# ============================================
# MEMBER JOURNEY FRICTION INSIGHTS (Phase 3)
# Strictly read-only. Reuses the Phase 1 analysis service and the Phase 2
# Gemini insights service. Nothing here writes to the database, sends
# e-mail, or changes a member, request, plan or message. Responses go
# through friction_dashboard_service, which whitelists every field, so
# names, e-mails, phone numbers, raw message text, ids, keywords, plan
# names, hashes and secrets can never reach the browser.
# ============================================

# Gemini quota protection: one generation at a time per admin, and a short
# pause after any run that actually called Gemini. Page loads never call it.
FRICTION_GENERATE_COOLDOWN_SECONDS = 30
_friction_lock = threading.Lock()
_friction_in_flight = set()
_friction_last_call = {}


def _json_no_store(body, status=200, headers=None):
    resp = jsonify(body)
    resp.status_code = status
    resp.headers["Cache-Control"] = "no-store"
    for k, v in (headers or {}).items():
        resp.headers[k] = v
    return resp


def _same_origin_or_absent():
    """Allow absent Origin per the existing convention; otherwise require exact origin.

    Origin identity includes scheme, hostname, and effective port. Comparing
    only the host would incorrectly treat HTTP and HTTPS (or different ports)
    as the same origin.
    """
    origin = request.headers.get("Origin")
    if not origin:
        return True
    return is_same_origin(origin, request.host_url)


@admin_bp.route("/friction-insights", methods=["GET"])
@admin_login_required
def friction_insights_analysis():
    """Verified metrics only (Phase 1). Cheap: never calls Gemini."""
    unknown = set(request.args.keys()) - {"since_days"}
    if unknown or len(request.args.getlist("since_days")) > 1:
        return _json_no_store({"success": False, "message": "Unknown or repeated query parameter."}, 400)
    try:
        since_days = friction_view.parse_since_days(request.args.get("since_days"))
    except friction_view.InputError as e:
        return _json_no_store({"success": False, "message": str(e)}, 400)

    try:
        view = friction_view.build_analysis_view(since_days)
    except Exception as exc:  # never leak internals; log only the exception type
        current_app.logger.error("Friction analysis view failed (%s)", type(exc).__name__)
        view = friction_view.view_from_analysis(None, since_days)
        view["error"] = {"code": "unexpected_error", "message": "The analysis could not be loaded right now."}

    try:
        ai_configured = bool(gemini_is_configured())
    except Exception:
        ai_configured = False
    view["ai"] = {"configured": ai_configured}

    failed = view["state"] == "error"
    return _json_no_store({"success": not failed, "readOnly": True, **view}, 500 if failed else 200)


@admin_bp.route("/friction-insights/generate", methods=["POST"])
@admin_login_required
def friction_insights_generate():
    """Validated AI insights (Phase 2). Read-only; may call Gemini (max 2 calls)."""
    if not _same_origin_or_absent():
        return _json_no_store({"success": False, "message": "Cross-site requests are not allowed."}, 403)
    if not request.is_json:
        return _json_no_store({"success": False, "message": "Request must be JSON."}, 415)

    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        return _json_no_store({"success": False, "message": "Request body must be a JSON object."}, 400)
    if set(data.keys()) - {"since_days"}:
        return _json_no_store({"success": False, "message": "Unknown field in request."}, 400)
    try:
        since_days = friction_view.parse_since_days(data.get("since_days"))
    except friction_view.InputError as e:
        return _json_no_store({"success": False, "message": str(e)}, 400)

    admin_id = session.get("admin_id")
    with _friction_lock:
        if admin_id in _friction_in_flight:
            return _json_no_store(
                {"success": False, "message": "An insights run is already in progress. Please wait."}, 429,
                {"Retry-After": "5"})
        last = _friction_last_call.get(admin_id)
        if last is not None:
            elapsed = time.monotonic() - last
            if elapsed < FRICTION_GENERATE_COOLDOWN_SECONDS:
                wait = int(FRICTION_GENERATE_COOLDOWN_SECONDS - elapsed) + 1
                return _json_no_store(
                    {"success": False,
                     "message": f"Please wait {wait} second(s) before generating insights again.",
                     "retryAfterSeconds": wait}, 429, {"Retry-After": str(wait)})
        _friction_in_flight.add(admin_id)

    try:
        result = generate_friction_insights(analysis_overrides=friction_view.overrides_for(since_days))
        validation = result.get("validation") if isinstance(result, dict) else None
        if isinstance(validation, dict) and (validation.get("attempts") or 0) > 0:
            with _friction_lock:
                _friction_last_call[admin_id] = time.monotonic()
        payload, status = friction_view.clean_insights_result(result)
    except Exception as exc:
        current_app.logger.error("Friction insights route failed (%s)", type(exc).__name__)
        payload, status = friction_view.safe_error_payload(), 500
    finally:
        with _friction_lock:
            _friction_in_flight.discard(admin_id)

    payload["parameters"] = {"since_days": since_days}
    ok = status == 200 and payload.get("state") != "error"
    return _json_no_store({"success": ok, "readOnly": True, **payload}, status)


# ============================================
# ADMIN ASSISTANT API (Phase 4C)
# ============================================

ASSISTANT_QUESTION_MAX_CHARS = 1200
ASSISTANT_REQUEST_MAX_BYTES = 16 * 1024
ASSISTANT_ASK_COOLDOWN_SECONDS = 30
_assistant_lock = threading.Lock()
_assistant_in_flight = set()
_assistant_last_call = {}

_ASSISTANT_ERROR_RESPONSES = {
    "invalid_question": (400, "Enter a valid question containing at most 1200 characters."),
    "not_configured": (503, "The admin assistant is not configured. Contact the administrator."),
    "data_unavailable": (503, "Approved aggregate data is temporarily unavailable."),
    "invalid_key": (502, "The admin assistant could not be authorized. Contact the administrator."),
    "rate_limited": (429, "The AI service is busy or its quota is exhausted. Try again later."),
    "timeout": (504, "The admin assistant timed out. Try again later."),
    "unavailable": (503, "The admin assistant is temporarily unavailable."),
    "model_unavailable": (502, "The configured AI model is unavailable. Contact the administrator."),
    "bad_request": (502, "The AI service could not process this question."),
    "empty_response": (502, "The AI service returned no usable answer."),
    "unknown": (500, "The admin assistant could not complete the request."),
}


@admin_bp.route("/assistant/ask", methods=["POST", "GET", "PUT", "PATCH", "DELETE"])
@admin_login_required
def admin_assistant_ask():
    """Ask the read-only Phase 4B service; no question-driven actions occur."""
    if request.method != "POST":
        return _json_no_store({"success": False, "error": {
            "code": "method_not_allowed", "message": "Only POST is supported.",
        }}, 405, {"Allow": "POST"})
    if not _same_origin_or_absent():
        return _json_no_store({"success": False, "error": {
            "code": "cross_origin", "message": "Cross-site requests are not allowed.",
        }}, 403)

    # Bound JSON parsing by rejecting oversized declared bodies before parsing.
    if request.content_length is not None and request.content_length > ASSISTANT_REQUEST_MAX_BYTES:
        return _json_no_store({"success": False, "error": {
            "code": "request_too_large", "message": "Request body is too large.",
        }}, 413)
    if not request.is_json:
        return _json_no_store({"success": False, "error": {
            "code": "unsupported_media_type", "message": "Request must use a JSON content type.",
        }}, 415)

    try:
        data = request.get_json(silent=True)
    except RequestEntityTooLarge:
        return _json_no_store({"success": False, "error": {
            "code": "request_too_large", "message": "Request body is too large.",
        }}, 413)
    if not isinstance(data, dict):
        return _json_no_store({"success": False, "error": {
            "code": "invalid_json", "message": "Request body must be a valid JSON object.",
        }}, 400)
    if set(data) != {"question"}:
        return _json_no_store({"success": False, "error": {
            "code": "invalid_request", "message": "Request must contain only a question field.",
        }}, 400)

    question = data.get("question")
    if not isinstance(question, str):
        return _json_no_store({"success": False, "error": {
            "code": "invalid_question", "message": "Question must be a string.",
        }}, 400)
    question = question.strip()
    if not question:
        return _json_no_store({"success": False, "error": {
            "code": "invalid_question", "message": "Question must not be empty.",
        }}, 400)
    if len(question) > ASSISTANT_QUESTION_MAX_CHARS:
        return _json_no_store({"success": False, "error": {
            "code": "invalid_question", "message": "Question must not exceed 1200 characters.",
        }}, 400)

    admin_id = session.get("admin_id")
    with _assistant_lock:
        if admin_id in _assistant_in_flight:
            return _json_no_store({"success": False, "error": {
                "code": "rate_limited", "message": "An assistant request is already in progress. Please wait.",
            }}, 429, {"Retry-After": "5"})
        last = _assistant_last_call.get(admin_id)
        if last is not None:
            elapsed = time.monotonic() - last
            if elapsed < ASSISTANT_ASK_COOLDOWN_SECONDS:
                wait = int(ASSISTANT_ASK_COOLDOWN_SECONDS - elapsed) + 1
                return _json_no_store({"success": False, "error": {
                    "code": "rate_limited", "message": f"Please wait {wait} second(s) before asking again.",
                }}, 429, {"Retry-After": str(wait)})
        _assistant_in_flight.add(admin_id)
        # Record before execution so provider errors cannot be retried in a tight loop.
        _assistant_last_call[admin_id] = time.monotonic()

    try:
        result = answer_admin_question(question)
    except Exception:
        # Do not log or return question, answer, provider, or exception details.
        return _json_no_store({"success": False, "status": "error", "error": {
            "code": "unknown", "message": "The admin assistant could not complete the request.",
        }}, 500)
    finally:
        with _assistant_lock:
            _assistant_in_flight.discard(admin_id)

    if not isinstance(result, dict):
        return _json_no_store({"success": False, "status": "error", "error": {
            "code": "unknown", "message": "The admin assistant could not complete the request.",
        }}, 500)

    status = result.get("status")
    if status in ("ok", "insufficient_data"):
        answer = result.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            return _json_no_store({"success": False, "status": "error", "error": {
                "code": "unknown", "message": "The admin assistant could not complete the request.",
            }}, 500)
        return _json_no_store({"success": True, "status": status, "answer": answer}, 200)

    if status == "error":
        error = result.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        if not isinstance(code, str) or code not in _ASSISTANT_ERROR_RESPONSES:
            code = "unknown"
        http_status, safe_message = _ASSISTANT_ERROR_RESPONSES[code]
        return _json_no_store({"success": False, "status": "error", "error": {
            "code": code, "message": safe_message,
        }}, http_status)

    return _json_no_store({"success": False, "status": "error", "error": {
        "code": "unknown", "message": "The admin assistant could not complete the request.",
    }}, 500)


# ============================================
# MANAGE MEMBERS
# ============================================

@admin_bp.route("/members", methods=["GET"])
@admin_login_required
def manage_members():
    users = get_all_users()
    return jsonify({"success": True, "members": users}), 200


# ============================================
# MANAGE MEMBERSHIP PLANS
# ============================================

@admin_bp.route("/plans", methods=["GET"])
@admin_login_required
def manage_plans():
    plans = get_all_plans()
    return jsonify({"success": True, "plans": plans}), 200


@admin_bp.route("/plans", methods=["POST"])
@admin_login_required
def add_plan():
    data = get_request_data()
    plan_name = (data.get("plan_name") or "").strip()
    duration_months = data.get("duration_months")
    price = data.get("price")
    features = (data.get("features") or "").strip()

    if not all([plan_name, duration_months, price]):
        return jsonify({"success": False, "message": "Plan name, duration, and price are required."}), 400

    plan_id = create_plan(plan_name, duration_months, price, features)
    return jsonify({"success": True, "message": "Plan created.", "plan_id": plan_id}), 201


@admin_bp.route("/plans/<int:plan_id>", methods=["PUT"])
@admin_login_required
def edit_plan(plan_id):
    data = get_request_data()
    plan_name = (data.get("plan_name") or "").strip()
    duration_months = data.get("duration_months")
    price = data.get("price")
    features = (data.get("features") or "").strip()

    if not all([plan_name, duration_months, price]):
        return jsonify({"success": False, "message": "Plan name, duration, and price are required."}), 400

    update_plan(plan_id, plan_name, duration_months, price, features)
    return jsonify({"success": True, "message": "Plan updated."}), 200


@admin_bp.route("/plans/<int:plan_id>", methods=["DELETE"])
@admin_login_required
def remove_plan(plan_id):
    data = get_request_data()
    password = data.get("password") or ""

    if not _verify_admin_password(password):
        return jsonify({"success": False, "message": "Incorrect admin password."}), 401

    try:
        existing = get_plan_by_id(plan_id)
        if not existing:
            return jsonify({"success": False, "message": "Plan not found."}), 404

        usage_count = get_plan_usage_count(plan_id)
        if usage_count > 0:
            return jsonify({
                "success": False,
                "message": (
                    "This membership plan cannot be deleted because it is "
                    "already assigned to one or more membership requests."
                ),
            }), 400

        delete_plan(plan_id)
        return jsonify({"success": True, "message": "Plan deleted."}), 200

    except Exception:
        current_app.logger.exception(f"Failed to delete membership plan {plan_id}")
        return jsonify({
            "success": False,
            "message": "Something went wrong while deleting the plan. Please try again.",
        }), 500


# ============================================
# MANAGE MEMBERSHIP REQUESTS
# ============================================

@admin_bp.route("/membership-requests", methods=["GET"])
@admin_login_required
def manage_membership_requests():
    requests = get_all_membership_requests()
    return jsonify({"success": True, "requests": requests}), 200


@admin_bp.route("/membership-requests/<int:request_id>/status", methods=["POST"])
@admin_login_required
def change_membership_request_status(request_id):
    data = get_request_data()
    status = (data.get("status") or "").strip().lower()

    if status not in ("pending", "active", "rejected"):
        return jsonify({"success": False, "message": "Invalid status."}), 400

    existing = get_membership_request_by_id(request_id)
    if not existing:
        return jsonify({"success": False, "message": "Request not found."}), 404

    start_date = None
    expiry_date = None

    if status == "active":
        # Activating: set start date to today, expiry date based on the
        # plan's duration (e.g. 3 months -> today + 3 months).
        start_date = date.today()
        expiry_date = start_date + timedelta(days=30 * existing["duration_months"])

    update_membership_request_status(request_id, status, start_date, expiry_date)
    return jsonify({"success": True, "message": "Membership request updated."}), 200


@admin_bp.route("/membership-requests/<int:request_id>", methods=["DELETE"])
@admin_login_required
def remove_membership_request(request_id):
    data = get_request_data()
    password = data.get("password") or ""

    if not _verify_admin_password(password):
        return jsonify({"success": False, "message": "Incorrect admin password."}), 401

    try:
        existing = get_membership_request_by_id(request_id)
        if not existing:
            return jsonify({"success": False, "message": "Membership request not found."}), 404

        delete_membership_request(request_id)
        return jsonify({"success": True, "message": "Membership deleted."}), 200

    except Exception:
        current_app.logger.exception(f"Failed to delete membership request {request_id}")
        return jsonify({
            "success": False,
            "message": "Something went wrong while deleting the membership. Please try again.",
        }), 500


# ============================================
# CONTACT MESSAGES
# ============================================

@admin_bp.route("/messages", methods=["GET"])
@admin_login_required
def view_messages():
    messages = get_all_contact_messages()
    return jsonify({"success": True, "messages": messages}), 200


@admin_bp.route("/messages/<int:message_id>/read", methods=["POST"])
@admin_login_required
def read_message(message_id):
    mark_message_as_read(message_id)
    return jsonify({"success": True, "message": "Marked as read."}), 200

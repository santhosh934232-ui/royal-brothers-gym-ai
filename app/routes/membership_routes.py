"""
Royal Brothers Fitness Gym - Membership Routes
Lets the frontend fetch membership plans and lets logged-in users
request a plan (the "Get Started" workflow — Bug 3/6).

Registered in app/__init__.py under url_prefix="/api/membership", so full paths are:
    GET  /api/membership/plans
    GET  /api/membership/plans/<id>
    POST /api/membership/request
    GET  /api/membership/my-request
"""

import json
from functools import wraps
from flask import Blueprint, request, session, jsonify

from ..models import (
    get_all_plans,
    get_plan_by_id,
    create_membership_request,
    get_active_or_pending_request,
    get_latest_membership_request,
)
from ..services.membership_reminder_service import (
    ALLOWED_LEAD_DAYS,
    get_reminder_preferences,
    save_reminder_preferences,
)
from ..security import is_same_origin

membership_bp = Blueprint("membership_bp", __name__)


def login_required(f):
    """Blocks access unless the user is logged in (session has user_id)."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"success": False, "message": "Please log in first."}), 401
        return f(*args, **kwargs)
    return wrapper


# ============================================
# PLANS
# ============================================

@membership_bp.route("/plans", methods=["GET"])
def list_plans():
    plans = get_all_plans()
    return jsonify({"success": True, "plans": plans}), 200


@membership_bp.route("/plans/<int:plan_id>", methods=["GET"])
def get_plan(plan_id):
    plan = get_plan_by_id(plan_id)
    if not plan:
        return jsonify({"success": False, "message": "Plan not found."}), 404
    return jsonify({"success": True, "plan": plan}), 200


# ============================================
# MEMBERSHIP REQUEST ("Get Started" workflow)
# ============================================

@membership_bp.route("/request", methods=["POST"])
@login_required
def request_membership():
    data = request.get_json() if request.is_json else request.form
    plan_id = data.get("plan_id")

    if not plan_id:
        return jsonify({"success": False, "message": "Plan is required."}), 400

    plan = get_plan_by_id(plan_id)
    if not plan:
        return jsonify({"success": False, "message": "Selected plan does not exist."}), 404

    # Block duplicate requests (Bug 6) — only one active/pending at a time
    existing = get_active_or_pending_request(session["user_id"])
    if existing:
        if existing["status"] == "active":
            return jsonify({"success": False, "message": "You already have an active membership."}), 409
        return jsonify({"success": False, "message": "You already have a pending membership request."}), 409

    create_membership_request(session["user_id"], plan_id)

    return jsonify({
        "success": True,
        "message": "Your membership request has been submitted successfully. "
                    "Please visit Royal Brothers Fitness Gym to complete payment "
                    "and activate your membership."
    }), 201


@membership_bp.route("/my-request", methods=["GET"])
@login_required
def my_request():
    """Returns the user's latest membership request (any status),
    used by the Membership page (button states) and Profile page
    (membership card + expiry warning)."""
    latest = get_latest_membership_request(session["user_id"])
    return jsonify({"success": True, "request": latest}), 200


# ============================================
# MEMBER REMINDER PREFERENCES (Phase 8)
# ============================================

REMINDER_PREFERENCES_MAX_BYTES = 4096


def _reminder_json(payload, status=200):
    response = jsonify(payload)
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    response.headers["Vary"] = "Cookie"
    return response


def _reminder_session_user_id():
    if "user_id" not in session:
        return None
    user_id = session.get("user_id")
    if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
        session.pop("user_id", None)
        session.pop("user_name", None)
        return None
    return user_id


def _is_exact_same_origin():
    """Require an explicit matching Origin for preference changes."""
    supplied = request.headers.get("Origin")
    return bool(supplied) and is_same_origin(supplied, request.host_url)


def _preference_error(result):
    code = (result.get("error") or {}).get("code")
    if code == "member_not_found":
        session.pop("user_id", None)
        session.pop("user_name", None)
        return _reminder_json({
            "success": False,
            "error": {"code": "unauthenticated", "message": "Please log in again."},
        }, 401)
    if code == "invalid_preferences":
        return _reminder_json({
            "success": False,
            "error": {"code": "invalid_preferences", "message": "Choose valid reminder settings."},
        }, 400)
    return _reminder_json({
        "success": False,
        "error": {"code": "data_unavailable", "message": "Reminder settings are temporarily unavailable."},
    }, 503)


def _preference_payload(preferences):
    return {
        "success": True,
        "preferences": {
            "enabled": preferences["enabled"],
            "lead_days": preferences["lead_days"],
        },
        "supported_lead_days": sorted(ALLOWED_LEAD_DAYS, reverse=True),
    }


@membership_bp.route("/reminder-preferences", methods=["GET"])
def get_member_reminder_preferences():
    user_id = _reminder_session_user_id()
    if user_id is None:
        return _reminder_json({
            "success": False,
            "error": {"code": "unauthenticated", "message": "Please log in first."},
        }, 401)
    result = get_reminder_preferences(user_id)
    if result.get("status") != "ok":
        return _preference_error(result)
    return _reminder_json(_preference_payload(result["preferences"]))


@membership_bp.route("/reminder-preferences", methods=["PUT"])
def update_member_reminder_preferences():
    user_id = _reminder_session_user_id()
    if user_id is None:
        return _reminder_json({
            "success": False,
            "error": {"code": "unauthenticated", "message": "Please log in first."},
        }, 401)
    if not _is_exact_same_origin():
        return _reminder_json({
            "success": False,
            "error": {"code": "cross_origin", "message": "Use the profile page to update reminder settings."},
        }, 403)
    if request.content_length is not None and request.content_length > REMINDER_PREFERENCES_MAX_BYTES:
        return _reminder_json({
            "success": False,
            "error": {"code": "request_too_large", "message": "The settings request is too large."},
        }, 413)
    if request.mimetype != "application/json":
        return _reminder_json({
            "success": False,
            "error": {"code": "unsupported_media_type", "message": "Send reminder settings as JSON."},
        }, 415)
    try:
        raw = request.stream.read(REMINDER_PREFERENCES_MAX_BYTES + 1)
        if len(raw) > REMINDER_PREFERENCES_MAX_BYTES:
            return _reminder_json({
                "success": False,
                "error": {"code": "request_too_large", "message": "The settings request is too large."},
            }, 413)
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        payload = None
    if (not isinstance(payload, dict) or set(payload) != {"enabled", "lead_days"}
            or not isinstance(payload.get("enabled"), bool)
            or not isinstance(payload.get("lead_days"), list)):
        return _reminder_json({
            "success": False,
            "error": {"code": "invalid_preferences", "message": "Choose valid reminder settings."},
        }, 400)

    result = save_reminder_preferences(
        user_id, payload["enabled"], payload["lead_days"],
    )
    if result.get("status") != "ok":
        return _preference_error(result)

    # Return the persisted values, not merely the submitted client state.
    saved = get_reminder_preferences(user_id)
    if saved.get("status") != "ok":
        return _preference_error(saved)
    return _reminder_json(_preference_payload(saved["preferences"]))

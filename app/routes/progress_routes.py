"""
Royal Brothers Fitness Gym - Fitness Progress Routes (Step 5)
Logged-in members log and review THEIR OWN weight/progress entries.
The user id always comes from the login session -- any user id sent by
the client is ignored, and every query is scoped to the session user, so
another member's entry id behaves exactly like a non-existent one (404).
No AI service is used here.

Registered in app/__init__.py under url_prefix="/api/progress":
    GET    /api/progress           (entries, oldest first, plus summary)
    POST   /api/progress           {"entryDate": "YYYY-MM-DD", "weightKg": 70.5, "notes": "..."}
    PUT    /api/progress/<id>      (same body; edits the member's own entry)
    DELETE /api/progress/<id>
"""

import sqlite3
from datetime import date, datetime, timedelta

from flask import Blueprint, request, session, jsonify, current_app

from .membership_routes import login_required
from .fitness_routes import _to_number, WEIGHT_RANGE
from ..models import (
    get_user_by_id, get_fitness_profile,
    list_progress_entries, get_progress_entry, progress_date_exists,
    create_progress_entry, update_progress_entry, delete_progress_entry,
)

progress_bp = Blueprint("progress_bp", __name__)

MAX_NOTES_LENGTH = 300
MIN_DATE = date(2000, 1, 1)
STEADY_THRESHOLD_KG = 0.2  # changes smaller than this count as "steady"


def _validate(data):
    """Returns (clean_values_dict, error_message)."""
    raw_date = data.get("entryDate")
    if not isinstance(raw_date, str):
        return None, "Please choose the date of this entry."
    raw_date = raw_date.strip()
    try:
        # strptime accepts "2026-1-5"; require the exact YYYY-MM-DD form.
        entry_date = datetime.strptime(raw_date, "%Y-%m-%d").date()
        if len(raw_date) != 10:
            raise ValueError
    except ValueError:
        return None, "Date must be a valid date (YYYY-MM-DD)."
    # One day of slack so members ahead of UTC (e.g. India) can log "today".
    if entry_date > date.today() + timedelta(days=1):
        return None, "Date cannot be in the future."
    if entry_date < MIN_DATE:
        return None, "Date is too far in the past."

    weight = _to_number(data.get("weightKg"))
    if weight is None or not (WEIGHT_RANGE[0] <= weight <= WEIGHT_RANGE[1]):
        return None, f"Weight must be a number between {WEIGHT_RANGE[0]} and {WEIGHT_RANGE[1]} kg."

    notes_raw = data.get("notes")
    if notes_raw is not None and not isinstance(notes_raw, str):
        return None, "Notes must be text."
    notes = (notes_raw or "").strip()
    if len(notes) > MAX_NOTES_LENGTH:
        return None, f"Notes must be {MAX_NOTES_LENGTH} characters or fewer."

    return {
        "entry_date": entry_date.isoformat(),
        "weight_kg": round(weight, 1),
        "notes": notes or None,
    }, None


def _public(row):
    return {
        "id": row["id"],
        "entryDate": row["entry_date"],
        "weightKg": row["weight_kg"],
        "notes": row["notes"] or "",
    }


def _trend(change):
    if change is None:
        return None
    if abs(change) < STEADY_THRESHOLD_KG:
        return "steady"
    return "up" if change > 0 else "down"


def _summary(entries, height_cm):
    """Basic progress info from the member's entries (oldest first)."""
    if not entries:
        return {"count": 0}
    weights = [e["weight_kg"] for e in entries]
    first, latest = weights[0], weights[-1]
    total_change = round(latest - first, 1)
    out = {
        "count": len(entries),
        "startWeightKg": first,
        "latestWeightKg": latest,
        "latestDate": entries[-1]["entry_date"],
        "totalChangeKg": total_change,
        "trend": _trend(total_change) if len(entries) > 1 else None,
        "lowestKg": min(weights),
        "highestKg": max(weights),
        "averageKg": round(sum(weights) / len(weights), 1),
        "changeSincePreviousKg": round(latest - weights[-2], 1) if len(entries) > 1 else None,
        "bmi": None,
    }
    if height_cm:
        out["bmi"] = round(latest / ((height_cm / 100) ** 2), 1)
    return out


def _member_or_401():
    user = get_user_by_id(session["user_id"])
    if not user:
        session.clear()
        return None
    return user


def _auth_error():
    return jsonify({"success": False, "message": "Please log in first."}), 401


def _parse_entry_id(raw):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _not_found():
    return jsonify({"success": False, "message": "Progress entry not found."}), 404


def _payload_or_400():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None, (jsonify({"success": False, "message": "Invalid request."}), 400)
    clean, error = _validate(data)
    if error:
        return None, (jsonify({"success": False, "message": error}), 400)
    return clean, None


def _duplicate_date():
    return jsonify({
        "success": False,
        "message": "You already have an entry for that date. Edit it instead.",
    }), 409


def _save_failed(action, err):
    current_app.logger.error(
        f"[progress] {action} failed for user {session.get('user_id')}: {type(err).__name__}"
    )
    return jsonify({
        "success": False,
        "message": f"Could not {action} your progress entry right now. Please try again.",
    }), 500


@progress_bp.route("", methods=["GET"])
@login_required
def list_entries():
    if not _member_or_401():
        return _auth_error()
    user_id = session["user_id"]
    entries = list_progress_entries(user_id)
    profile = get_fitness_profile(user_id)
    return jsonify({
        "success": True,
        "entries": [_public(e) for e in entries],
        "summary": _summary(entries, profile["height_cm"] if profile else None),
        "goal": profile["fitness_goal"] if profile else None,
    }), 200


@progress_bp.route("", methods=["POST"])
@login_required
def add_entry():
    if not _member_or_401():
        return _auth_error()
    clean, err_response = _payload_or_400()
    if err_response:
        return err_response
    user_id = session["user_id"]
    if progress_date_exists(user_id, clean["entry_date"]):
        return _duplicate_date()
    try:
        new_id = create_progress_entry(user_id, **clean)
    except sqlite3.IntegrityError:  # lost a race on (user_id, entry_date)
        return _duplicate_date()
    except Exception as e:
        return _save_failed("save", e)
    return jsonify({
        "success": True,
        "message": "Progress entry added.",
        "entry": _public(get_progress_entry(user_id, new_id)),
    }), 201


@progress_bp.route("/<entry_id>", methods=["PUT"])
@login_required
def edit_entry(entry_id):
    if not _member_or_401():
        return _auth_error()
    entry_id = _parse_entry_id(entry_id)
    user_id = session["user_id"]
    if entry_id is None or not get_progress_entry(user_id, entry_id):
        return _not_found()
    clean, err_response = _payload_or_400()
    if err_response:
        return err_response
    if progress_date_exists(user_id, clean["entry_date"], exclude_id=entry_id):
        return _duplicate_date()
    try:
        changed = update_progress_entry(user_id, entry_id, **clean)
    except sqlite3.IntegrityError:
        return _duplicate_date()
    except Exception as e:
        return _save_failed("update", e)
    if not changed:
        return _not_found()
    return jsonify({
        "success": True,
        "message": "Progress entry updated.",
        "entry": _public(get_progress_entry(user_id, entry_id)),
    }), 200


@progress_bp.route("/<entry_id>", methods=["DELETE"])
@login_required
def remove_entry(entry_id):
    if not _member_or_401():
        return _auth_error()
    entry_id = _parse_entry_id(entry_id)
    if entry_id is None:
        return _not_found()
    try:
        deleted = delete_progress_entry(session["user_id"], entry_id)
    except Exception as e:
        return _save_failed("delete", e)
    if not deleted:
        return _not_found()
    return jsonify({"success": True, "message": "Progress entry deleted."}), 200

"""
Royal Brothers Fitness Gym - Fitness Profile Routes (Step 2)
Logged-in members create/read/update THEIR OWN fitness profile only.
The user id always comes from the login session -- any user_id sent by
the client is ignored.

Registered in app/__init__.py under url_prefix="/api/fitness-profile":
    GET /api/fitness-profile
    PUT /api/fitness-profile
"""

import math

from flask import Blueprint, request, session, jsonify, current_app

from .membership_routes import login_required
from ..models import get_user_by_id, get_fitness_profile, save_fitness_profile

fitness_bp = Blueprint("fitness_bp", __name__)

ALLOWED_GOALS = {"weight_loss", "muscle_gain", "strength", "endurance", "general_fitness"}
ALLOWED_EXPERIENCE = {"beginner", "intermediate", "advanced"}
HEIGHT_RANGE = (100, 250)
WEIGHT_RANGE = (30, 300)
MINUTES_RANGE = (15, 240)
MAX_TIMING_LENGTH = 100


def _to_number(value):
    """Returns a finite float, or None if value isn't a real number."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        num = float(str(value).strip()) if isinstance(value, str) else float(value)
    except (TypeError, ValueError):
        return None
    return num if math.isfinite(num) else None


def _validate(data):
    """Returns (clean_values_dict, error_message)."""
    goal = str(data.get("fitnessGoal") or "").strip().lower()
    if goal not in ALLOWED_GOALS:
        return None, "Please select a valid fitness goal."

    height = _to_number(data.get("heightCm"))
    if height is None or not (HEIGHT_RANGE[0] <= height <= HEIGHT_RANGE[1]):
        return None, f"Height must be a number between {HEIGHT_RANGE[0]} and {HEIGHT_RANGE[1]} cm."

    weight = _to_number(data.get("weightKg"))
    if weight is None or not (WEIGHT_RANGE[0] <= weight <= WEIGHT_RANGE[1]):
        return None, f"Weight must be a number between {WEIGHT_RANGE[0]} and {WEIGHT_RANGE[1]} kg."

    experience = str(data.get("workoutExperience") or "").strip().lower()
    if experience not in ALLOWED_EXPERIENCE:
        return None, "Please select a valid workout experience level."

    minutes = _to_number(data.get("availableMinutes"))
    if (minutes is None or minutes != int(minutes)
            or not (MINUTES_RANGE[0] <= minutes <= MINUTES_RANGE[1])):
        return None, (f"Available workout time must be a whole number of minutes "
                      f"between {MINUTES_RANGE[0]} and {MINUTES_RANGE[1]}.")

    timing_raw = data.get("collegeWorkTiming")
    if timing_raw is not None and not isinstance(timing_raw, str):
        return None, "College/work timing must be text."
    timing = (timing_raw or "").strip()
    if len(timing) > MAX_TIMING_LENGTH:
        return None, f"College/work timing must be {MAX_TIMING_LENGTH} characters or fewer."

    return {
        "fitness_goal": goal,
        "height_cm": round(height, 1),
        "weight_kg": round(weight, 1),
        "workout_experience": experience,
        "available_workout_minutes": int(minutes),
        "college_work_timing": timing or None,
    }, None


def _public(row):
    if not row:
        return None
    return {
        "fitnessGoal": row["fitness_goal"],
        "heightCm": row["height_cm"],
        "weightKg": row["weight_kg"],
        "workoutExperience": row["workout_experience"],
        "availableMinutes": row["available_workout_minutes"],
        "collegeWorkTiming": row["college_work_timing"] or "",
    }


def _current_member_or_401():
    user = get_user_by_id(session["user_id"])
    if not user:
        session.clear()
        return None
    return user


@fitness_bp.route("", methods=["GET"])
@login_required
def get_profile():
    if not _current_member_or_401():
        return jsonify({"success": False, "message": "Please log in first."}), 401
    row = get_fitness_profile(session["user_id"])
    return jsonify({"success": True, "profile": _public(row)}), 200


@fitness_bp.route("", methods=["PUT"])
@login_required
def save_profile():
    if not _current_member_or_401():
        return jsonify({"success": False, "message": "Please log in first."}), 401

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"success": False, "message": "Invalid request."}), 400

    clean, error = _validate(data)
    if error:
        return jsonify({"success": False, "message": error}), 400

    try:
        save_fitness_profile(session["user_id"], **clean)
    except Exception as e:
        current_app.logger.error(
            f"[fitness profile] save failed for user {session['user_id']}: {e}"
        )
        return jsonify({
            "success": False,
            "message": "Could not save your fitness profile right now. Please try again.",
        }), 500

    row = get_fitness_profile(session["user_id"])
    return jsonify({
        "success": True,
        "message": "Fitness profile saved.",
        "profile": _public(row),
    }), 200

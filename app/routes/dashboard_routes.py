"""
Royal Brothers Fitness Gym - Member AI Dashboard Routes (Step 9)
One read-only overview of everything the member already has from Steps 2-8.

Registered in app/__init__.py under url_prefix="/api/dashboard":
    GET /api/dashboard

Safety / design:
- Only the logged-in member's own data is read (user id comes from the session).
- Read-only: nothing is written, and Gemini is NEVER called here. Every section
  is a compact digest of what the existing features already saved, using the
  existing model getters and helpers (nothing is copied into a new table).
- The free-text college/work timing and progress notes are not included.
- A missing or unreadable section is returned as null, never as an error.
"""

import json

from flask import Blueprint, session, jsonify

from .membership_routes import login_required
from .workout_routes import _member_or_none
from .daily_routes import _suggested_day
from .progress_routes import _summary
from ..models import (
    get_fitness_profile, get_workout_plan, get_daily_plan, list_progress_entries,
    get_ai_insight, get_workout_recommendation, get_nutrition_plan,
)

dashboard_bp = Blueprint("dashboard_bp", __name__)

RECENT_WEIGHTS = 8


def _load(row, column):
    """Parses a saved AI JSON row; None if missing or unreadable."""
    if not row:
        return None
    try:
        data = json.loads(row[column])
        return data if isinstance(data, dict) else None
    except (ValueError, TypeError, KeyError):
        return None


def _first(items):
    return items[0] if isinstance(items, list) and items else None


def _profile_card(profile):
    if not profile:
        return None
    return {
        "goal": profile["fitness_goal"],
        "heightCm": profile["height_cm"],
        "weightKg": profile["weight_kg"],
        "experience": profile["workout_experience"],
        "availableMinutes": profile["available_workout_minutes"],
    }


def _workout_card(row):
    plan = _load(row, "plan_json")
    if not plan:
        return None
    try:
        days = plan["days"][:7]
        today_no = _suggested_day(row["created_at"])
        today = days[today_no - 1]
        return {
            "summary": plan.get("summary", ""),
            "trainingDays": sum(1 for d in days if not d["is_rest"]),
            "restDays": sum(1 for d in days if d["is_rest"]),
            "today": {
                "planDay": today_no,
                "day": today["day"],
                "focus": today["focus"],
                "isRest": bool(today["is_rest"]),
                "durationMinutes": today["duration_minutes"],
                "exerciseCount": len(today["exercises"]),
            },
        }
    except (KeyError, IndexError, TypeError):
        return None


def _daily_card(row, weekly_row):
    plan = _load(row, "plan_json")
    if not plan:
        return None
    try:
        suggested = _suggested_day(weekly_row["created_at"]) if weekly_row else None
        day_no = int(str(plan["plan_day"]).split()[-1])  # stored as "Day 3"
        return {
            "planDay": day_no,
            "focus": plan["focus"],
            "isRest": bool(plan["is_rest"]),
            "itemCount": len(plan["schedule"]),
            "matchesToday": suggested is not None and day_no == suggested,
            "generatedAt": str(row["created_at"]),
        }
    except (KeyError, TypeError, ValueError):
        return None


def _progress_card(entries, profile):
    if not entries:
        return None
    summary = _summary(entries, profile["height_cm"] if profile else None)
    summary["recentWeights"] = [
        {"date": e["entry_date"], "weightKg": e["weight_kg"]} for e in entries[-RECENT_WEIGHTS:]
    ]
    return summary


def _insight_card(row):
    ins = _load(row, "insight_json")
    if not ins:
        return None
    return {
        "summary": ins.get("summary", ""),
        "nextStep": _first(ins.get("next_steps")),
        "generatedAt": str(row["created_at"]),
    }


def _recommendation_card(row):
    rec = _load(row, "recommendation_json")
    if not rec:
        return None
    return {
        "summary": rec.get("summary", ""),
        "keyRecommendation": _first(rec.get("progression")) or _first(rec.get("exercises_to_focus")),
        "generatedAt": str(row["created_at"]),
    }


def _nutrition_card(row):
    plan = _load(row, "plan_json")
    if not plan:
        return None
    try:
        return {
            "summary": plan.get("summary", ""),
            "calories": {"min": plan["calories"]["min"], "max": plan["calories"]["max"]},
            "protein": {"min_g": plan["protein"]["min_g"], "max_g": plan["protein"]["max_g"]},
            "hydration": {"liters_min": plan["hydration"]["liters_min"],
                          "liters_max": plan["hydration"]["liters_max"]},
            "generatedAt": str(row["created_at"]),
        }
    except (KeyError, TypeError):
        return None


@dashboard_bp.route("", methods=["GET"])
@login_required
def view_dashboard():
    if not _member_or_none():
        return jsonify({"success": False, "message": "Please log in first."}), 401
    uid = session["user_id"]

    profile = get_fitness_profile(uid)
    weekly = get_workout_plan(uid)

    return jsonify({
        "success": True,
        "profile": _profile_card(profile),
        "workout": _workout_card(weekly),
        "daily": _daily_card(get_daily_plan(uid), weekly),
        "progress": _progress_card(list_progress_entries(uid), profile),
        "insight": _insight_card(get_ai_insight(uid)),
        "recommendation": _recommendation_card(get_workout_recommendation(uid)),
        "nutrition": _nutrition_card(get_nutrition_plan(uid)),
    }), 200

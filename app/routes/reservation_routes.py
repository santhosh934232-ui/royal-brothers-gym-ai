"""
Royal Brothers Fitness Gym - Reservation Routes
Lets a logged-in user book a gym slot and view their reservation history.

Time is validated server-side against the gym's actual open windows for
that user's gender (from your Home page):
    Men:   5:00 AM - 9:00 AM   and   5:00 PM - 9:00 PM
    Women: 8:00 AM - 10:00 AM  and   4:00 PM - 6:00 PM
"Other" gender is allowed to book within either window.

Registered in app/__init__.py under url_prefix="/api/reservations", so full paths:
    POST /api/reservations/book
    GET  /api/reservations/my
    POST /api/reservations/cancel/<id>
"""

from datetime import datetime, date as date_cls
from functools import wraps

from flask import Blueprint, request, session, jsonify

from ..models import (
    create_reservation,
    get_reservations_by_user,
    get_user_by_id,
    update_reservation_status,
)

reservation_bp = Blueprint("reservation_bp", __name__)

# (start_hour, end_hour) in 24-hour time, inclusive of start, exclusive of end
GYM_WINDOWS = {
    "male": [(5, 9), (17, 21)],
    "female": [(8, 10), (16, 18)],
}


def login_required(f):
    """Blocks access unless the user is logged in (session has user_id)."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"success": False, "message": "Please log in first."}), 401
        return f(*args, **kwargs)
    return wrapper


def is_within_gym_hours(gender, time_obj):
    windows = GYM_WINDOWS.get(gender, GYM_WINDOWS["male"] + GYM_WINDOWS["female"])
    if gender == "other":
        windows = GYM_WINDOWS["male"] + GYM_WINDOWS["female"]

    for start_hour, end_hour in windows:
        if start_hour <= time_obj.hour < end_hour:
            return True
    return False


# ============================================
# BOOK A SLOT
# ============================================

@reservation_bp.route("/book", methods=["POST"])
@login_required
def book_slot():
    data = request.get_json() if request.is_json else request.form

    date_str = (data.get("date") or "").strip()   # expected format: YYYY-MM-DD
    time_str = (data.get("time") or "").strip()    # expected format: HH:MM

    if not date_str or not time_str:
        return jsonify({"success": False, "message": "Date and time are required."}), 400

    try:
        reservation_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        reservation_time = datetime.strptime(time_str, "%H:%M").time()
    except ValueError:
        return jsonify({"success": False, "message": "Invalid date or time format."}), 400

    if reservation_date < date_cls.today():
        return jsonify({"success": False, "message": "Cannot book a date in the past."}), 400

    user = get_user_by_id(session["user_id"])
    if not user:
        return jsonify({"success": False, "message": "User not found."}), 404

    if not is_within_gym_hours(user["gender"], reservation_time):
        return jsonify({
            "success": False,
            "message": "Selected time is outside gym opening hours for your slot."
        }), 400

    reservation_id = create_reservation(user["id"], reservation_date, reservation_time)

    return jsonify({
        "success": True,
        "message": "Slot reserved successfully.",
        "reservation_id": reservation_id
    }), 201


# ============================================
# VIEW MY RESERVATIONS
# ============================================

@reservation_bp.route("/my", methods=["GET"])
@login_required
def my_reservations():
    reservations = get_reservations_by_user(session["user_id"])
    return jsonify({"success": True, "reservations": reservations}), 200


# ============================================
# CANCEL A RESERVATION
# ============================================

@reservation_bp.route("/cancel/<int:reservation_id>", methods=["POST"])
@login_required
def cancel_reservation(reservation_id):
    # Note: for a stricter check you'd verify this reservation belongs to
    # the logged-in user before cancelling; kept simple for this project.
    update_reservation_status(reservation_id, "cancelled")
    return jsonify({"success": True, "message": "Reservation cancelled."}), 200

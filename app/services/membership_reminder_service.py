"""Phase 6 membership-reminder preferences and deterministic eligibility.

This module never sends email, calls an external service, or changes a
membership record. Member-specific callers must derive ``user_id`` from the
verified login session; do not accept another member's ID from a client.
"""

from datetime import date, datetime, timedelta

from ..config import Config
from ..extensions import get_db_connection

SERVICE_VERSION = "1.0"
DEFAULT_LEAD_DAYS = tuple(Config.MEMBERSHIP_REMINDER_DEFAULT_LEAD_DAYS)
ALLOWED_LEAD_DAYS = frozenset(Config.MEMBERSHIP_REMINDER_ALLOWED_LEAD_DAYS)


def _valid_member_id(member_id):
    return (isinstance(member_id, int) and not isinstance(member_id, bool)
            and member_id > 0)


def _lead_times(value, enabled):
    if not isinstance(value, (list, tuple)):
        return None
    if any(not isinstance(item, int) or isinstance(item, bool) for item in value):
        return None
    if len(value) != len(set(value)) or any(item not in ALLOWED_LEAD_DAYS for item in value):
        return None
    if enabled and not value:
        return None
    return tuple(sorted(value, reverse=True))


def _safe_error(code="data_unavailable"):
    return {
        "status": "error",
        "error": {"code": code, "message": "Membership reminder data is temporarily unavailable."},
    }


def get_reminder_preferences(user_id):
    """Return a member's saved preferences or deterministic opt-in defaults.

    Missing preference row means reminders are disabled, with proposed
    7/3/1-day lead times available if the member later opts in. No account
    names, email addresses, or other personal data are returned.
    """
    if not _valid_member_id(user_id):
        return _safe_error("invalid_member_id")

    conn = cursor = None
    try:
        conn = get_db_connection(read_only=True)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id FROM users WHERE id = %s", (user_id,))
        if cursor.fetchone() is None:
            return _safe_error("member_not_found")

        cursor.execute(
            "SELECT enabled, created_at, updated_at FROM membership_reminder_preferences WHERE user_id = %s",
            (user_id,),
        )
        row = cursor.fetchone()
        if row is None:
            preferences = {"enabled": False, "lead_days": list(DEFAULT_LEAD_DAYS),
                           "created_at": None, "updated_at": None}
        else:
            enabled_value = row.get("enabled")
            if enabled_value not in (0, 1):
                return _safe_error("invalid_preference_data")
            cursor.execute(
                "SELECT lead_days FROM membership_reminder_lead_times WHERE user_id = %s ORDER BY lead_days DESC",
                (user_id,),
            )
            stored = [item["lead_days"] for item in cursor.fetchall()]
            normalized = _lead_times(stored, bool(enabled_value))
            if normalized is None:
                return _safe_error("invalid_preference_data")
            preferences = {"enabled": bool(enabled_value), "lead_days": list(normalized),
                           "created_at": row.get("created_at"), "updated_at": row.get("updated_at")}
        return {"status": "ok", "preferences": preferences}
    except Exception:
        return _safe_error()
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def save_reminder_preferences(user_id, enabled, lead_days):
    """Persist validated preferences for one existing member atomically.

    ``user_id`` must come from a trusted server-side member session at any
    future route boundary. The function deliberately provides no HTTP route.
    Allowed lead days are {1, 3, 7}; empty lead lists are allowed only while
    disabled. Repeated saves update the single preference row and replace
    its normalized child values in one SQLite transaction.
    """
    if not _valid_member_id(user_id):
        return _safe_error("invalid_member_id")
    if not isinstance(enabled, bool):
        return _safe_error("invalid_preferences")
    normalized = _lead_times(lead_days, enabled)
    if normalized is None:
        return _safe_error("invalid_preferences")

    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("SELECT id FROM users WHERE id = %s", (user_id,))
        if cursor.fetchone() is None:
            conn.rollback()
            return _safe_error("member_not_found")
        cursor.execute(
            """INSERT INTO membership_reminder_preferences (user_id, enabled)
               VALUES (%s, %s)
               ON CONFLICT(user_id) DO UPDATE SET
                 enabled = excluded.enabled,
                 updated_at = CURRENT_TIMESTAMP""",
            (user_id, int(enabled)),
        )
        cursor.execute("DELETE FROM membership_reminder_lead_times WHERE user_id = %s", (user_id,))
        for days in normalized:
            cursor.execute(
                "INSERT INTO membership_reminder_lead_times (user_id, lead_days) VALUES (%s, %s)",
                (user_id, days),
            )
        conn.commit()
        return {"status": "ok", "preferences": {"enabled": enabled, "lead_days": list(normalized)}}
    except Exception:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        return _safe_error()
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _as_date(value):
    """Accept date-only values and strict ISO date strings; reject bad dates."""
    if isinstance(value, datetime):
        # The application stores date-only values using its server-local
        # calendar date. For an aware datetime, the caller supplies the
        # intended business-local datetime and its calendar date is used.
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.isoformat() == value else None
    return None


def evaluate_membership_for_reminders(membership, preferences, as_of):
    """Pure eligibility evaluation for one membership; returns a reason.

    Existing membership semantics are: only status ``active`` with valid
    stored start/end dates can qualify. The end date is inclusive, matching
    the profile's calendar-date expiry display. A reminder is due only on
    the exact target date ``end_date - lead_days``. This function never
    recomputes dates from plan duration.
    """
    today = _as_date(as_of)
    if today is None:
        return {"eligible": False, "reason": "invalid_reference_date", "reminders": []}
    if not isinstance(membership, dict):
        return {"eligible": False, "reason": "invalid_membership", "reminders": []}
    if membership.get("status") != "active":
        return {"eligible": False, "reason": "not_active", "reminders": []}

    start = _as_date(membership.get("start_date"))
    expiry = _as_date(membership.get("end_date"))
    if start is None or expiry is None or expiry < start:
        return {"eligible": False, "reason": "invalid_membership_dates", "reminders": []}
    if today < start:
        return {"eligible": False, "reason": "not_started", "reminders": []}
    if today > expiry:
        return {"eligible": False, "reason": "expired", "reminders": []}
    if not isinstance(preferences, dict) or preferences.get("enabled") is not True:
        return {"eligible": False, "reason": "reminders_disabled", "reminders": []}

    leads = _lead_times(preferences.get("lead_days"), True)
    if leads is None:
        return {"eligible": False, "reason": "invalid_preferences", "reminders": []}
    request_id = membership.get("membership_request_id")
    user_id = membership.get("user_id")
    if not _valid_member_id(user_id) or not _valid_member_id(request_id):
        return {"eligible": False, "reason": "invalid_membership", "reminders": []}

    reminders = []
    for lead in leads:
        target = expiry - timedelta(days=lead)
        if today == target:
            reminders.append({
                "user_id": user_id,
                "membership_request_id": request_id,
                "expiry_date": expiry.isoformat(),
                "lead_days": lead,
                "reminder_date": target.isoformat(),
            })
    return {"eligible": bool(reminders), "reason": "eligible" if reminders else "not_due",
            "reminders": reminders}


def get_eligible_reminders(as_of=None):
    """Return eligible reminders for a date without mutating data.

    The membership end date comes only from membership_requests.end_date.
    Expired rows with status='active' are ineligible; no automatic status
    change is made. Multiple currently effective active membership rows for
    one member are treated as ambiguous and all are excluded. Missing/bad
    dates are excluded rather than reconstructed. Results contain only IDs,
    dates, and lead days; no member identity/contact fields.
    """
    today = _as_date(as_of) if as_of is not None else date.today()
    if today is None:
        return _safe_error("invalid_reference_date")

    conn = cursor = None
    try:
        conn = get_db_connection(read_only=True)
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """SELECT mr.id AS membership_request_id, mr.user_id, mr.status,
                      CAST(mr.start_date AS TEXT) AS start_date,
                      CAST(mr.end_date AS TEXT) AS end_date
               FROM membership_requests mr
               WHERE mr.status = 'active'
               ORDER BY mr.user_id, mr.id"""
        )
        rows = cursor.fetchall()
        cursor.execute(
            "SELECT user_id, enabled FROM membership_reminder_preferences WHERE enabled = 1"
        )
        enabled_users = {row["user_id"] for row in cursor.fetchall()}
        lead_map = {}
        if enabled_users:
            cursor.execute(
                "SELECT user_id, lead_days FROM membership_reminder_lead_times ORDER BY user_id, lead_days DESC"
            )
            for row in cursor.fetchall():
                lead_map.setdefault(row["user_id"], []).append(row["lead_days"])

        current_by_user = {}
        invalid_active_users = set()
        for row in rows:
            uid = row.get("user_id")
            start = _as_date(row.get("start_date"))
            expiry = _as_date(row.get("end_date"))
            if not _valid_member_id(uid):
                continue
            if start is None or expiry is None or expiry < start:
                invalid_active_users.add(uid)
                continue
            if start <= today <= expiry:
                current_by_user.setdefault(uid, []).append(row)

        output = []
        for uid in sorted(enabled_users):
            active = current_by_user.get(uid, [])
            if uid in invalid_active_users or len(active) != 1:
                continue
            row = active[0]
            result = evaluate_membership_for_reminders(
                row,
                {"enabled": True, "lead_days": lead_map.get(uid, [])},
                today,
            )
            output.extend(result["reminders"])
        return {"status": "ok", "as_of": today.isoformat(), "reminders": output}
    except Exception:
        return _safe_error()
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

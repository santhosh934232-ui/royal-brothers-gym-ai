"""Phase 7 reminder delivery, persistent deduplication, and bounded retries.

Eligibility remains owned by Phase 6. Delivery records are claimed inside a
SQLite BEGIN IMMEDIATE transaction before SMTP is called. SMTP and the local
SQLite database cannot participate in one atomic transaction, so the service
provides at-most-one concurrent active attempt and durable successful-send
suppression, not guaranteed exactly-once delivery after a process crash.
"""

import re
import smtplib
from datetime import date, datetime, timedelta, timezone
from email.utils import parseaddr

from flask import current_app, has_app_context

from ..extensions import get_db_connection
from .email_service import send_email
from .membership_reminder_service import get_eligible_reminders

MAX_ATTEMPTS = 3
RETRY_DELAYS_MINUTES = (5, 15)
CLAIM_LEASE_MINUTES = 2
RETRY_WINDOW_DAYS = 1

_SAFE_FAILURES = {
    "invalid_email": "The member email address is missing or invalid.",
    "smtp_authentication_failed": "SMTP authentication failed; check the configured mail credentials.",
    "smtp_recipient_rejected": "The configured SMTP server rejected the recipient address.",
    "smtp_delivery_failed": "The SMTP server did not confirm delivery.",
    "attempt_interrupted": "The previous delivery attempt did not finish recording a result.",
    "attempt_history_unavailable": "The delivery result could not be saved; delivery state is uncertain.",
}
_EMAIL_PATTERN = re.compile(r"^[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+$")


def _safe_error(code="data_unavailable"):
    return {
        "status": "error",
        "error": {"code": code, "message": "Reminder delivery data is temporarily unavailable."},
    }


def _as_date(value):
    if isinstance(value, datetime):
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


def _utc_now(value=None):
    if value is None:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    # Existing project timestamps are naive UTC; injected naive times follow
    # that established storage convention for deterministic tests.
    return value


def _safe_log(level, message, *args):
    if has_app_context():
        try:
            getattr(current_app.logger, level)(message, *args)
        except Exception:
            pass


def _email_is_valid(value):
    if not isinstance(value, str):
        return False
    address = value.strip()
    if not address or len(address) > 254 or "\r" in address or "\n" in address:
        return False
    display_name, parsed = parseaddr(address)
    if display_name or parsed != address or not _EMAIL_PATTERN.fullmatch(address):
        return False
    local, domain = address.rsplit("@", 1)
    return len(local) <= 64 and len(domain) <= 253 and ".." not in address


def _single_line_name(value):
    if not isinstance(value, str):
        return "Member"
    name = " ".join(value.split())[:100]
    return name or "Member"


def _message_for(expiry_date, full_name):
    expiry = _as_date(expiry_date)
    if expiry is None:
        raise ValueError("Invalid membership expiry date")
    name = _single_line_name(full_name)
    subject = f"Membership expiry reminder - {expiry.isoformat()}"
    body = (
        f"Hello {name},\n\n"
        "This is a reminder from Royal Brothers Fitness Gym that our records show "
        f"your membership expires on {expiry.strftime('%d %B %Y')}.\n\n"
        "For membership or renewal information, please contact the gym reception. "
        "If you have already renewed or believe this date is incorrect, please contact the gym.\n\n"
        "Regards,\nRoyal Brothers Fitness Gym\n"
    )
    return subject, body


def _key(reminder):
    try:
        user_id = reminder.get("user_id")
        request_id = reminder.get("membership_request_id")
        lead = reminder.get("lead_days")
        expiry = _as_date(reminder.get("expiry_date"))
        reminder_date = _as_date(reminder.get("reminder_date"))
    except AttributeError:
        return None
    if (not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0
            or not isinstance(request_id, int) or isinstance(request_id, bool) or request_id <= 0
            or not isinstance(lead, int) or isinstance(lead, bool) or not 1 <= lead <= 30
            or expiry is None or reminder_date is None
            or reminder_date != expiry - timedelta(days=lead)):
        return None
    return {
        "user_id": user_id,
        "membership_request_id": request_id,
        "expiry_date": expiry.isoformat(),
        "lead_days": lead,
        "reminder_date": reminder_date.isoformat(),
    }


def _candidate_key(reminder):
    return (reminder["user_id"], reminder["membership_request_id"],
            reminder["expiry_date"], reminder["lead_days"])


def _load_due_retries(today, now):
    """Fetch only due retry keys; no member contact data is read here."""
    conn = cursor = None
    try:
        conn = get_db_connection(read_only=True)
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """SELECT user_id, membership_request_id,
                      CAST(expiry_date AS TEXT) AS expiry_date,
                      lead_days, CAST(reminder_date AS TEXT) AS reminder_date
               FROM membership_reminder_deliveries
               WHERE CAST(retry_until_date AS TEXT) >= %s
                 AND ((status = 'failed' AND retryable = 1
                       AND attempt_count < %s AND next_attempt_at <= %s)
                      OR (status = 'pending' AND lease_until <= %s))
               ORDER BY next_attempt_at, id""",
            (today.isoformat(), MAX_ATTEMPTS, now, now),
        )
        return {"status": "ok", "reminders": cursor.fetchall()}
    except Exception as exc:
        _safe_log("error", "Reminder retry lookup failed (%s).", type(exc).__name__)
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


def _live_member_for_key(conn, key, today):
    """Revalidate Phase 6 date/status/overlap and current opt-in under lock."""
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """SELECT id AS membership_request_id, user_id, status,
                      CAST(start_date AS TEXT) AS start_date,
                      CAST(end_date AS TEXT) AS end_date
               FROM membership_requests WHERE user_id = %s AND status = 'active'
               ORDER BY id""",
            (key["user_id"],),
        )
        rows = cursor.fetchall()
        active_rows = []
        for row in rows:
            start = _as_date(row.get("start_date"))
            expiry = _as_date(row.get("end_date"))
            if start is None or expiry is None or expiry < start:
                return None
            if start <= today <= expiry:
                active_rows.append((row, expiry))
        if len(active_rows) != 1:
            return None
        row, expiry = active_rows[0]
        if (row["membership_request_id"] != key["membership_request_id"]
                or expiry.isoformat() != key["expiry_date"]):
            return None

        reminder_date = _as_date(key["reminder_date"])
        if reminder_date != expiry - timedelta(days=key["lead_days"]):
            return None
        retry_until = min(expiry, reminder_date + timedelta(days=RETRY_WINDOW_DAYS))
        if today < reminder_date or today > retry_until:
            return None

        cursor.execute(
            "SELECT enabled FROM membership_reminder_preferences WHERE user_id = %s",
            (key["user_id"],),
        )
        preference = cursor.fetchone()
        if not preference or preference.get("enabled") != 1:
            return None
        cursor.execute(
            "SELECT 1 AS selected FROM membership_reminder_lead_times WHERE user_id = %s AND lead_days = %s",
            (key["user_id"], key["lead_days"]),
        )
        if cursor.fetchone() is None:
            return None

        cursor.execute("SELECT full_name, email FROM users WHERE id = %s", (key["user_id"],))
        member = cursor.fetchone()
        if member is None:
            return None
        return {"full_name": member.get("full_name"), "email": member.get("email")}
    finally:
        cursor.close()


def _backoff_after(attempt_number):
    index = attempt_number - 1
    if 0 <= index < len(RETRY_DELAYS_MINUTES):
        return timedelta(minutes=RETRY_DELAYS_MINUTES[index])
    return None


def _claim_delivery(key, today, now):
    """Atomically claim a reminder identity before attempting SMTP."""
    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("BEGIN IMMEDIATE")
        identity = (key["user_id"], key["membership_request_id"],
                    key["expiry_date"], key["lead_days"])
        cursor.execute(
            """SELECT id, status, attempt_count, retryable, next_attempt_at,
                      lease_until, CAST(retry_until_date AS TEXT) AS retry_until_date
               FROM membership_reminder_deliveries
               WHERE user_id = %s AND membership_request_id = %s
                 AND expiry_date = %s AND lead_days = %s""",
            identity,
        )
        existing = cursor.fetchone()
        if existing and existing["status"] == "sent":
            conn.rollback()
            return {"status": "skipped", "code": "already_sent"}

        if existing and existing["status"] == "pending":
            lease_until = existing.get("lease_until")
            if lease_until is not None and lease_until > now:
                conn.rollback()
                return {"status": "skipped", "code": "attempt_in_progress"}
            # A crashed worker left an uncertain SMTP attempt. Record the
            # interruption and delay the next attempt; SMTP may have accepted
            # the prior message before that worker stopped.
            attempt_number = existing["attempt_count"]
            delay = _backoff_after(attempt_number)
            retryable = int(attempt_number < MAX_ATTEMPTS and delay is not None
                            and today.isoformat() <= existing["retry_until_date"])
            reason = _SAFE_FAILURES["attempt_interrupted"]
            cursor.execute(
                """UPDATE membership_reminder_delivery_attempts
                   SET status = 'failed', finished_at = %s,
                       failure_code = 'attempt_interrupted', failure_reason = %s
                   WHERE delivery_id = %s AND attempt_number = %s AND status = 'pending'""",
                (now, reason, existing["id"], attempt_number),
            )
            next_at = now + delay if retryable else None
            cursor.execute(
                """UPDATE membership_reminder_deliveries SET status = 'failed',
                   updated_at = %s, next_attempt_at = %s, lease_until = NULL,
                   retryable = %s, failure_code = 'attempt_interrupted', failure_reason = %s
                   WHERE id = %s AND status = 'pending'""",
                (now, next_at, retryable, reason, existing["id"]),
            )
            conn.commit()
            return {"status": "uncertain", "code": "attempt_interrupted"}

        if existing:
            attempt_count = existing["attempt_count"]
            if not existing["retryable"] or attempt_count >= MAX_ATTEMPTS:
                conn.rollback()
                return {"status": "skipped", "code": "retry_exhausted"}
            retry_until = _as_date(existing.get("retry_until_date"))
            if retry_until is None or today > retry_until:
                cursor.execute(
                    """UPDATE membership_reminder_deliveries SET retryable = 0,
                       next_attempt_at = NULL, updated_at = %s WHERE id = %s""",
                    (now, existing["id"]),
                )
                conn.commit()
                return {"status": "skipped", "code": "retry_window_expired"}
            next_at = existing.get("next_attempt_at")
            if next_at is not None and next_at > now:
                conn.rollback()
                return {"status": "skipped", "code": "retry_not_due"}

        member = _live_member_for_key(conn, key, today)
        if member is None:
            conn.rollback()
            return {"status": "skipped", "code": "no_longer_eligible"}

        lease_until = now + timedelta(minutes=CLAIM_LEASE_MINUTES)
        if existing is None:
            retry_until = min(_as_date(key["expiry_date"]),
                              _as_date(key["reminder_date"]) + timedelta(days=RETRY_WINDOW_DAYS))
            cursor.execute(
                """INSERT INTO membership_reminder_deliveries
                   (user_id, membership_request_id, expiry_date, lead_days,
                    reminder_date, retry_until_date, status, attempt_count, retryable,
                    created_at, updated_at, first_attempt_at, last_attempt_at, lease_until)
                   VALUES (%s,%s,%s,%s,%s,%s,'pending',1,1,%s,%s,%s,%s,%s)""",
                (*identity, key["reminder_date"], retry_until.isoformat(), now, now, now, now, lease_until),
            )
            delivery_id = cursor.lastrowid
            attempt_number = 1
        else:
            delivery_id = existing["id"]
            attempt_number = existing["attempt_count"] + 1
            cursor.execute(
                """UPDATE membership_reminder_deliveries SET status = 'pending',
                   attempt_count = %s, retryable = 1, updated_at = %s,
                   last_attempt_at = %s, next_attempt_at = NULL, lease_until = %s,
                   failure_code = NULL, failure_reason = NULL
                   WHERE id = %s AND status = 'failed'""",
                (attempt_number, now, now, lease_until, delivery_id),
            )
        cursor.execute(
            """INSERT INTO membership_reminder_delivery_attempts
               (delivery_id, attempt_number, status, started_at)
               VALUES (%s,%s,'pending',%s)""",
            (delivery_id, attempt_number, now),
        )
        conn.commit()
        return {"status": "claimed", "delivery_id": delivery_id,
                "attempt_number": attempt_number, "member": member}
    except Exception as exc:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        _safe_log("error", "Reminder delivery claim failed (%s).", type(exc).__name__)
        return {"status": "error", "code": "database_error"}
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


def _finish_attempt(delivery_id, attempt_number, now, status,
                    failure_code=None, failure_reason=None, retryable=False, next_at=None):
    conn = cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("BEGIN IMMEDIATE")
        if status == "sent":
            cursor.execute(
                """UPDATE membership_reminder_deliveries SET status = 'sent',
                   retryable = 0, updated_at = %s, sent_at = %s,
                   next_attempt_at = NULL, lease_until = NULL,
                   failure_code = NULL, failure_reason = NULL
                   WHERE id = %s AND status = 'pending'""",
                (now, now, delivery_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Delivery state changed before result was recorded")
            cursor.execute(
                """UPDATE membership_reminder_delivery_attempts
                   SET status = 'sent', finished_at = %s
                   WHERE delivery_id = %s AND attempt_number = %s AND status = 'pending'""",
                (now, delivery_id, attempt_number),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Attempt state changed before result was recorded")
        else:
            cursor.execute(
                """UPDATE membership_reminder_deliveries SET status = 'failed',
                   retryable = %s, updated_at = %s, next_attempt_at = %s,
                   lease_until = NULL, failure_code = %s, failure_reason = %s
                   WHERE id = %s AND status = 'pending'""",
                (int(retryable), now, next_at, failure_code, failure_reason, delivery_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Delivery state changed before result was recorded")
            cursor.execute(
                """UPDATE membership_reminder_delivery_attempts
                   SET status = 'failed', finished_at = %s,
                       failure_code = %s, failure_reason = %s
                   WHERE delivery_id = %s AND attempt_number = %s AND status = 'pending'""",
                (now, failure_code, failure_reason, delivery_id, attempt_number),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Attempt state changed before result was recorded")
        conn.commit()
        return True
    except Exception as exc:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        _safe_log("error", "Reminder attempt result write failed (%s).", type(exc).__name__)
        return False
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


def _failure_for(exc):
    if isinstance(exc, _InvalidEmail):
        return "invalid_email", _SAFE_FAILURES["invalid_email"], False
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return "smtp_authentication_failed", _SAFE_FAILURES["smtp_authentication_failed"], False
    if isinstance(exc, smtplib.SMTPRecipientsRefused):
        return "smtp_recipient_rejected", _SAFE_FAILURES["smtp_recipient_rejected"], False
    return "smtp_delivery_failed", _SAFE_FAILURES["smtp_delivery_failed"], True


class _InvalidEmail(ValueError):
    pass


def _result_item(key, status, code=None):
    item = {
        "membership_request_id": key["membership_request_id"],
        "expiry_date": key["expiry_date"],
        "lead_days": key["lead_days"],
        "status": status,
    }
    if code:
        item["code"] = code
    return item


def process_membership_reminders(as_of=None, now=None):
    """Send eligible messages and retry only previously due failures.

    Callers must provide an active Flask application context (for the shared
    Flask-Mail extension). New reminders come only from the unchanged Phase 6
    exact-date eligibility service. A failed delivery may be retried at most
    3 total attempts, after 5 then 15 minutes, and only through the next
    calendar day or expiry date, whichever comes first. Invalid addresses and
    SMTP authentication/recipient rejection failures are terminal.
    """
    if not has_app_context():
        return _safe_error("app_context_required")
    today = _as_date(as_of) if as_of is not None else date.today()
    now_utc = _utc_now(now)
    if today is None or now_utc is None:
        return _safe_error("invalid_reference_time")

    eligible = get_eligible_reminders(today)
    if eligible.get("status") != "ok":
        return _safe_error(eligible.get("error", {}).get("code", "eligibility_unavailable"))
    retries = _load_due_retries(today, now_utc)
    if retries.get("status") != "ok":
        return _safe_error("delivery_history_unavailable")

    candidates = {}
    for reminder in eligible.get("reminders", []):
        normalized = _key(reminder)
        if normalized is not None and normalized["reminder_date"] == today.isoformat():
            candidates[_candidate_key(normalized)] = normalized
    for reminder in retries.get("reminders", []):
        normalized = _key(reminder)
        if normalized is not None:
            candidates.setdefault(_candidate_key(normalized), normalized)

    results = []
    for identity in sorted(candidates):
        key = candidates[identity]
        claim = _claim_delivery(key, today, now_utc)
        if claim["status"] == "skipped":
            results.append(_result_item(key, "skipped", claim.get("code")))
            continue
        if claim["status"] == "error":
            results.append(_result_item(key, "error", claim.get("code")))
            continue
        if claim["status"] in {"failed", "uncertain"}:
            results.append(_result_item(key, claim["status"], claim.get("code")))
            continue

        delivery_id = claim["delivery_id"]
        attempt_number = claim["attempt_number"]
        member = claim["member"]
        try:
            if not _email_is_valid(member.get("email")):
                raise _InvalidEmail()
            subject, body = _message_for(key["expiry_date"], member.get("full_name"))
            send_email(member["email"].strip(), subject, body)
        except Exception as exc:
            code, reason, retryable = _failure_for(exc)
            delay = _backoff_after(attempt_number) if retryable and attempt_number < MAX_ATTEMPTS else None
            retry_until = min(_as_date(key["expiry_date"]),
                              _as_date(key["reminder_date"]) + timedelta(days=RETRY_WINDOW_DAYS))
            retryable = bool(delay is not None and today <= retry_until)
            next_at = now_utc + delay if retryable else None
            _safe_log("warning", "Membership reminder attempt failed: code=%s attempt=%s.",
                      code, attempt_number)
            saved = _finish_attempt(delivery_id, attempt_number, now_utc, "failed",
                                    code, reason, retryable, next_at)
            results.append(_result_item(key, "failed" if saved else "uncertain",
                                        code if saved else "attempt_history_unavailable"))
            continue

        if _finish_attempt(delivery_id, attempt_number, now_utc, "sent"):
            results.append(_result_item(key, "sent"))
        else:
            # SMTP returned success, but the local success update failed. The
            # pending lease will later become retryable, which can duplicate a
            # message that the SMTP server already accepted.
            results.append(_result_item(key, "uncertain", "attempt_history_unavailable"))

    summary = {"eligible_candidates": len(candidates), "sent": 0, "failed": 0,
               "skipped": 0, "uncertain": 0, "errors": 0}
    for item in results:
        if item["status"] in summary:
            summary[item["status"]] += 1
    return {"status": "ok", "as_of": today.isoformat(), "summary": summary,
            "results": results}

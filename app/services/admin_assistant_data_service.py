"""Read-only, privacy-preserving aggregate data for the future admin assistant.

This module deliberately exposes aggregate values only. It does not return member,
request, contact, authentication, or free-text records and makes no writes.
"""

from ..extensions import get_db_connection


SERVICE_VERSION = "1.0"
_REQUEST_STATUSES = ("pending", "active", "rejected")


def get_admin_summary():
    """Return approved aggregate gym metrics in a stable, JSON-friendly shape.

    Results are deterministic for a given database state. On any DB failure the
    method returns a safe error envelope; exception text and SQL are never exposed.
    """
    conn = None
    cursor = None
    try:
        # Use SQLite's read-only URI mode: if the configured database is
        # missing, a SELECT must not create a new empty database file.
        conn = get_db_connection(read_only=True)
        cursor = conn.cursor(dictionary=True)

        # Counts only; never select user identifiers or profile/authentication fields.
        cursor.execute(
            """SELECT
                   COALESCE(SUM(CASE WHEN is_verified = 1 THEN 1 ELSE 0 END), 0) AS verified,
                   COALESCE(SUM(CASE WHEN is_verified = 0 THEN 1 ELSE 0 END), 0) AS unverified,
                   COUNT(*) AS total
               FROM users"""
        )
        user_counts = cursor.fetchone() or {}

        # Restrict result categories to the statuses declared by the project schema.
        cursor.execute(
            """SELECT status, COUNT(*) AS request_count
               FROM membership_requests
               GROUP BY status"""
        )
        grouped_statuses = cursor.fetchall() or []
        request_status_counts = {status: 0 for status in _REQUEST_STATUSES}
        other_statuses = 0
        for row in grouped_statuses:
            status = row.get("status")
            count = _non_negative_int(row.get("request_count"))
            if status in request_status_counts:
                request_status_counts[status] = count
            else:
                other_statuses += count

        # Plan names are labels from the plan catalog, not member or request data.
        # Empty/missing labels are coalesced to a generic category.
        cursor.execute(
            """SELECT COALESCE(NULLIF(TRIM(mp.plan_name), ''), 'Unspecified') AS plan_name,
                      COUNT(mr.id) AS request_count
               FROM membership_plans AS mp
               LEFT JOIN membership_requests AS mr ON mr.plan_id = mp.id
               GROUP BY COALESCE(NULLIF(TRIM(mp.plan_name), ''), 'Unspecified')
               ORDER BY plan_name COLLATE NOCASE"""
        )
        plan_rows = cursor.fetchall() or []
        plan_distribution = [
            {
                "plan_name": _safe_plan_label(row.get("plan_name")),
                "request_count": _non_negative_int(row.get("request_count")),
            }
            for row in plan_rows
        ]

        total_requests = sum(request_status_counts.values()) + other_statuses
        result = {
            "schema_version": SERVICE_VERSION,
            "status": "ok",
            "members": {
                "total": _non_negative_int(user_counts.get("total")),
                "verified": _non_negative_int(user_counts.get("verified")),
                "unverified": _non_negative_int(user_counts.get("unverified")),
            },
            "membership_requests": {
                "total": total_requests,
                "by_status": request_status_counts,
                "other_or_missing_status": other_statuses,
                "plan_distribution": plan_distribution,
            },
        }
        return result
    except Exception:
        # Avoid leaking DB paths, SQL, exception details, or data through errors.
        return {
            "schema_version": SERVICE_VERSION,
            "status": "error",
            "error": {
                "code": "data_unavailable",
                "message": "Aggregated admin data is temporarily unavailable.",
            },
        }
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


def _non_negative_int(value):
    """Normalize database count values without permitting bools or negatives."""
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return parsed if parsed >= 0 else 0


def _safe_plan_label(value):
    """Use a bounded plain plan label; discard control characters and markup."""
    if not isinstance(value, str):
        return "Unspecified"
    label = " ".join(value.replace("<", "").replace(">", "").split())
    if not label:
        return "Unspecified"
    return label[:80]

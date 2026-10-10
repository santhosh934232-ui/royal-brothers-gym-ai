"""
Royal Brothers Fitness Gym - Member Journey Friction Analysis (Phase 1)

A reusable, READ-ONLY analysis engine. It looks at three existing tables:

    contact_messages     (subject, message, created_at, is_read, email)
    membership_requests  (user_id, plan_id, status, request_date)
    membership_plans     (plan_name, duration_months, price, features)

and returns one structured, JSON-serialisable dict (see
docs/FRICTION_ANALYSIS_SERVICE.md for the full result contract).

Design rules (these are enforced by tests/test_phase1_friction_analysis.py):

* Read-only: the database is opened with SQLite's ``mode=ro`` URI plus
  ``PRAGMA query_only = ON`` and only fixed SELECT statements are run. No SQL
  is ever built from user input.
* No external services: nothing here talks to Gemini or the network.
* Privacy: names, phone numbers, email addresses and raw message text never
  appear in the result. Message text is only read in memory to match topic
  keywords; the result carries counts, matched keywords, record ids and
  time ranges. An e-mail address is read only to count DISTINCT senders (it
  is hashed in memory with a throw-away random salt and never returned).
* Honest evidence: every finding states what the data directly supports and
  what stays uncertain. Frequent topic != proven problem.
* Counts come from Python/SQL over real rows. Each contact message is counted
  once (it receives exactly one primary topic or one "unclassified" reason).

This module is intentionally independent of Flask routes and templates. It
imports ``app.config`` lazily, only when no explicit database path is given.
"""

import hashlib
import os
import re
import secrets
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

SCHEMA_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Analysis parameters. These are tunable RULES, not statistics about the gym.
# They are echoed back in result["parameters"] so every output is explainable.
# ---------------------------------------------------------------------------
DEFAULT_PARAMETERS = {
    # Fewer classifiable contact messages than this => "insufficient_data".
    "min_messages_for_analysis": 5,
    # A topic needs at least this many messages to be reported as a finding.
    "min_messages_per_finding": 2,
    # Evidence strength rules for text topics (messages AND distinct senders).
    "moderate_min_messages": 3,
    "moderate_min_senders": 2,
    "strong_min_messages": 5,
    "strong_min_senders": 3,
    # A pending membership request older than this many days is counted.
    # (Counts a fact about request_date; it does NOT claim anyone was ignored.)
    "pending_age_days": 7,
    # Optional look-back window in days. None = use all records.
    "since_days": None,
    # Max example record ids kept per topic/finding.
    "max_example_ids": 5,
    # Message text longer than this is truncated before keyword matching.
    "max_text_chars": 5000,
}

KNOWN_REQUEST_STATUSES = ("pending", "active", "rejected")  # CHECK constraint in schema.sql

# Columns this feature needs. Anything absent is reported, never invented.
REQUIRED_COLUMNS = {
    "contact_messages": ("id", "subject", "message", "created_at", "is_read", "email"),
    "membership_requests": ("id", "user_id", "plan_id", "status", "request_date"),
    "membership_plans": ("id", "plan_name", "duration_months", "price", "features"),
}
# Columns that must exist for the source to be usable at all.
ESSENTIAL_COLUMNS = {
    "contact_messages": ("id", "subject", "message"),
    "membership_requests": ("id", "status"),
    "membership_plans": ("id",),
}

# ---------------------------------------------------------------------------
# Topic rules (keyword based, transparent, no AI).
# Patterns run on normalised text: lower-case, accents stripped, punctuation
# turned into spaces. Each pattern counts at most once per field.
# ---------------------------------------------------------------------------
TOPIC_RULES = [
    {
        "id": "membership_plans_pricing",
        "label": "Membership plans and pricing",
        "patterns": [
            r"\bpric\w*", r"\bfees?\b", r"\bcosts?\b", r"\bcharges?\b", r"\brates?\b",
            r"\bhow much\b", r"\bdiscounts?\b", r"\boffers?\b", r"\bpackages?\b",
            r"\bmembership plans?\b", r"\bmembership (?:details|options|duration)\b",
            r"\b(?:monthly|quarterly|yearly|annual|half yearly) (?:plan|membership|fee|package)\b",
            r"\bwhich plan\b", r"\bplan (?:details|options|duration|features|difference)\b",
        ],
        "interpretation": (
            "Prospective members may not find plan or price details clear enough on the site, "
            "or may simply be asking normal pre-sales questions."
        ),
    },
    {
        "id": "membership_request_process",
        "label": "Joining / membership request process",
        "patterns": [
            r"\bjoin\w*", r"\bregist\w*", r"\bsign ?ups?\b", r"\benrol\w*", r"\badmission\b",
            r"\bget started\b", r"\bmembership request\b", r"\brequest status\b",
            r"\bapprov\w*", r"\bpending\b", r"\bactivat\w*", r"\bbecome (?:a )?member\b",
            r"\bhow (?:to|do i|can i) (?:get|take|buy|apply)\b", r"\bapply\w*",
        ],
        "interpretation": (
            "Visitors may be unsure how to join or what happens after requesting a plan, "
            "or may simply be asking before they start."
        ),
    },
    {
        "id": "payment",
        "label": "Payment",
        "patterns": [
            r"\bpay\w*", r"\bupi\b", r"\bgpay\b", r"\bcash\b", r"\bcards?\b", r"\bemi\b",
            r"\binstal?lments?\b", r"\breceipts?\b", r"\binvoices?\b", r"\bonline payment\b",
        ],
        "interpretation": (
            "Payment steps (the site tells members to pay at the gym) may be unclear. "
            "The database stores no payment records, so payment status cannot be checked."
        ),
    },
    {
        "id": "renewal_cancellation_refund",
        "label": "Renewal, cancellation, freeze or refund",
        "patterns": [
            r"\bcancel\w*", r"\brefund\w*", r"\bfreez\w*", r"\bpause\w*", r"\bhold membership\b",
            r"\btransfer\w*", r"\bextend\w*", r"\bextension\b", r"\brenew\w*", r"\bexpir\w*",
        ],
        "interpretation": (
            "Members may lack information about changing or ending a membership. "
            "No cancellation or expiry data exists in the schema to confirm this."
        ),
    },
    {
        "id": "account_access",
        "label": "Account, login or e-mail verification",
        "patterns": [
            r"\blog ?in\b", r"\bsign in\b", r"\bpassword\b", r"\bverif\w*", r"\botp\b",
            r"\baccount\b", r"\blocked\b", r"\breset\b", r"\bunable to (?:log|sign|access)\b",
            r"\bcan ?not (?:log|sign|access)\b",
        ],
        "interpretation": (
            "Some users may struggle with registration, e-mail verification, login or password reset. "
            "Verification/reset outcomes are not recorded per user, so this cannot be confirmed."
        ),
    },
    {
        "id": "timings_availability",
        "label": "Gym timings and availability",
        "patterns": [
            r"\btimings?\b", r"\bhours\b", r"\bopen(?:ing)?\b", r"\bclos(?:e|ed|ing)\b",
            r"\bschedules?\b", r"\bslots?\b", r"\bbatch(?:es)?\b", r"\bholidays?\b",
            r"\bmorning\b", r"\bevening\b", r"\bsunday\b",
        ],
        "interpretation": "Opening hours or slot information may be hard to find.",
    },
    {
        "id": "trainers_classes",
        "label": "Trainers and classes",
        "patterns": [
            r"\btrainers?\b", r"\bpersonal training\b", r"\bcoach\w*", r"\binstructors?\b",
            r"\bzumba\b", r"\byoga\b", r"\bclass(?:es)?\b", r"\bpt\b",
        ],
        "interpretation": "Information about trainers or classes may be hard to find.",
    },
    {
        "id": "facilities_equipment",
        "label": "Facilities and equipment",
        "patterns": [
            r"\bequipments?\b", r"\bmachines?\b", r"\bcardio\b", r"\btreadmills?\b",
            r"\blockers?\b", r"\bshowers?\b", r"\bparking\b", r"\bfacilit\w*", r"\bweights?\b",
        ],
        "interpretation": "Facility or equipment details may be hard to find.",
    },
    {
        "id": "location_contact",
        "label": "Location and how to reach the gym",
        "patterns": [
            r"\baddress\b", r"\blocation\b", r"\bdirections?\b", r"\blocated\b",
            r"\bhow to reach\b", r"\blandmark\b", r"\bnearest\b",
        ],
        "interpretation": "Location details may be hard to find.",
    },
    {
        "id": "fitness_guidance",
        "label": "Workout / diet guidance",
        "patterns": [
            r"\bworkout plans?\b", r"\bdiet\w*", r"\bnutrition\w*", r"\bweight loss\b",
            r"\bmuscle\b", r"\bfat loss\b", r"\bbulk\w*", r"\bprotein\b",
        ],
        "interpretation": (
            "General fitness-advice questions; likely unrelated to joining. "
            "Kept separate from membership-plan topics on purpose."
        ),
    },
    {
        "id": "complaint_feedback",
        "label": "Complaints and feedback",
        "patterns": [
            r"\bcomplain\w*", r"\bfeedback\b", r"\bsuggestions?\b", r"\bunhappy\b",
            r"\bdisappoint\w*", r"\bdirty\b", r"\brude\b", r"\bnot working\b", r"\bbroken\b",
            r"\bpoor service\b",
        ],
        "interpretation": "Free-form complaints/feedback; the underlying cause needs manual reading.",
    },
]
TOPIC_BY_ID = {t["id"]: t for t in TOPIC_RULES}
_COMPILED = {t["id"]: [re.compile(p) for p in t["patterns"]] for t in TOPIC_RULES}

UNCLASSIFIED_REASONS = {
    "empty_text": "Subject and message were missing, empty or not text.",
    "no_topic_match": "Text present but no topic rule matched.",
    "ambiguous": "Two or more topics matched equally; not forced into one.",
}

SUBJECT_WEIGHT = 2  # a keyword in the subject counts double a keyword in the body


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------
def normalize_text(value, max_chars=DEFAULT_PARAMETERS["max_text_chars"]):
    """Lower-case, strip accents, turn punctuation into spaces, collapse spaces.
    Never raises: None, bytes, numbers or garbage become '' or a best-effort string."""
    if value is None:
        return ""
    if isinstance(value, (bytes, bytearray)):
        try:
            value = bytes(value).decode("utf-8", errors="ignore")
        except Exception:
            return ""
    if not isinstance(value, str):
        try:
            value = str(value)
        except Exception:
            return ""
    value = value[:max_chars]
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return value.strip()


def _field_hits(normalized_text, topic_id):
    """Return the list of keyword matches (strings) of one topic in one field."""
    hits = []
    for rx in _COMPILED[topic_id]:
        m = rx.search(normalized_text)
        if m:
            hits.append(m.group(0))
    return hits


def classify_text(subject, message, max_chars=DEFAULT_PARAMETERS["max_text_chars"]):
    """Classify ONE contact message into exactly one primary topic or one
    unclassified reason.

    Returns {"topic": id|None, "unclassified_reason": code|None, "keywords": [..]}.
    """
    subj = normalize_text(subject, max_chars)
    body = normalize_text(message, max_chars)
    if not subj and not body:
        return {"topic": None, "unclassified_reason": "empty_text", "keywords": []}

    scored = []
    for topic in TOPIC_RULES:
        tid = topic["id"]
        s_hits = _field_hits(subj, tid) if subj else []
        b_hits = _field_hits(body, tid) if body else []
        total = SUBJECT_WEIGHT * len(s_hits) + len(b_hits)
        if total:
            scored.append((total, len(s_hits), tid, sorted(set(s_hits + b_hits))))
    if not scored:
        return {"topic": None, "unclassified_reason": "no_topic_match", "keywords": []}

    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    best = scored[0]
    if len(scored) > 1 and (scored[1][0], scored[1][1]) == (best[0], best[1]):
        return {"topic": None, "unclassified_reason": "ambiguous", "keywords": []}
    return {"topic": best[2], "unclassified_reason": None, "keywords": best[3]}


def _parse_timestamp(value):
    """Parse a stored timestamp (text 'YYYY-MM-DD HH:MM:SS', ISO, date or datetime).
    Returns a naive datetime or None. Never raises."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    try:
        text = value.decode() if isinstance(value, (bytes, bytearray)) else str(value)
        text = text.strip()
        if not text:
            return None
        return datetime.fromisoformat(text.replace("Z", "")).replace(tzinfo=None)
    except Exception:
        return None


def _iso(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None


# ---------------------------------------------------------------------------
# Database access (read-only)
# ---------------------------------------------------------------------------
def open_readonly_connection(db_path):
    """Open the SQLite file read-only. Raises sqlite3.Error if it cannot be opened
    (a missing file is NOT created, unlike a normal sqlite3.connect)."""
    uri = Path(os.path.abspath(db_path)).as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA query_only = ON")
    conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
    conn.row_factory = sqlite3.Row
    return conn


def inspect_schema(conn):
    """Inspect which required tables/columns really exist. Pure read (PRAGMA)."""
    schema = {}
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    for table, wanted in REQUIRED_COLUMNS.items():
        if table not in tables:
            schema[table] = {"exists": False, "columns_found": [], "columns_missing": list(wanted),
                             "usable": False}
            continue
        # Table names here come from the fixed constant above, never from input.
        found = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        missing = [c for c in wanted if c not in found]
        usable = all(c in found for c in ESSENTIAL_COLUMNS[table])
        schema[table] = {"exists": True, "columns_found": [c for c in wanted if c in found],
                         "columns_missing": missing, "usable": usable}
    return schema


def _select(conn, table, schema_info, wanted_columns):
    """SELECT only the columns that exist. Fixed table/column names only."""
    cols = [c for c in wanted_columns if c in schema_info["columns_found"]]
    if not cols:
        return [], cols
    rows = conn.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
    return [dict(zip(cols, tuple(r))) for r in rows], cols


# ---------------------------------------------------------------------------
# Evidence strength (transparent rules)
# ---------------------------------------------------------------------------
def _text_strength(count, senders, p):
    if count < p["min_messages_per_finding"]:
        return "insufficient"
    if count >= p["strong_min_messages"] and senders >= p["strong_min_senders"]:
        return "strong"
    if count >= p["moderate_min_messages"] and senders >= p["moderate_min_senders"]:
        return "moderate"
    return "weak"


STRENGTH_RULES = (
    "Text topics: 'insufficient' = fewer than min_messages_per_finding messages; "
    "'strong' = at least strong_min_messages messages from at least strong_min_senders distinct senders; "
    "'moderate' = at least moderate_min_messages messages from at least moderate_min_senders distinct senders; "
    "otherwise 'weak' (e.g. repeats from a single sender). "
    "Strength measures how much data backs the COUNT, never whether a problem is proven."
)


def _sender_token(email, salt):
    """In-memory only: lets us count distinct senders without keeping addresses."""
    e = normalize_text(email, 320).replace(" ", "")
    if not e:
        return None
    return hashlib.sha256((salt + e).encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def _empty_result(params, now):
    return {
        "schema_version": SCHEMA_VERSION,
        "analysis_status": "ok",
        "generated_at": _iso(now),
        "parameters": dict(params),
        "strength_rules": STRENGTH_RULES,
        "data_sources": [],
        "summary": {},
        "topics": [],
        "unclassified": {"count": 0, "reasons": {}},
        "membership_requests": None,
        "membership_plans": None,
        "friction_findings": [],
        "insufficient_data": {"is_insufficient": False, "reasons": []},
        "warnings": [],
        "limitations": [
            "Contact messages have no reply/resolution field: 'is_read' only shows an admin marked it read, not that it was answered.",
            "Contact messages are not linked to user accounts or plans, so an enquiry cannot be tied to a membership request.",
            "membership_requests has only pending/active/rejected; there is no rejection reason, cancellation, payment or expiry-event data.",
            "Admins can delete membership requests, so deleted requests are invisible to this analysis.",
            "Topics come from keyword rules on English text; other languages, slang or typos fall into 'unclassified'.",
            "Attendance, workout completion, satisfaction and payment status are not stored and are not analysed.",
        ],
    }


def _warn(result, code, message):
    result["warnings"].append({"code": code, "message": message})


def analyze_member_journey_friction(db_path=None, conn=None, now=None, **overrides):
    """Run the full read-only analysis and return the result dict.

    db_path   path of a SQLite file (default: app Config.DB_PATH). Opened read-only.
    conn      optional already-open sqlite3 connection (used as is; the function
              still only issues SELECT/PRAGMA statements and never commits).
    now       datetime override (for tests); default datetime.utcnow().
    overrides any key of DEFAULT_PARAMETERS (e.g. since_days=30).

    This function never raises for database problems: it returns
    analysis_status == "error" with a generic message instead.
    """
    params = dict(DEFAULT_PARAMETERS)
    unknown = [k for k in overrides if k not in DEFAULT_PARAMETERS]
    params.update({k: v for k, v in overrides.items() if k in DEFAULT_PARAMETERS})
    now = now or datetime.utcnow()
    result = _empty_result(params, now)
    for k in unknown:
        _warn(result, "unknown_parameter", f"Ignored unknown parameter '{k}'.")

    own_conn = False
    try:
        if conn is None:
            if db_path is None:
                from ..config import Config  # lazy: keeps the module importable without env secrets
                db_path = Config.DB_PATH
            conn = open_readonly_connection(db_path)
            own_conn = True
        else:
            conn.execute("PRAGMA query_only = ON")  # best effort: refuse writes on this handle

        schema = inspect_schema(conn)
        result["schema_inspection"] = schema

        since = None
        if params["since_days"] is not None:
            try:
                since = now - timedelta(days=float(params["since_days"]))
            except (TypeError, ValueError):
                _warn(result, "invalid_since_days", "since_days was not a number; using all records.")
                params["since_days"] = None
                result["parameters"]["since_days"] = None

        contact_part = _analyze_contacts(conn, schema, params, since, result)
        requests_part = _analyze_requests(conn, schema, params, since, now, result)
        plans_part = _analyze_plans(conn, schema, requests_part, result)

        result["membership_requests"] = requests_part["public"] if requests_part else None
        result["membership_plans"] = plans_part["public"] if plans_part else None

        _build_findings(result, contact_part, requests_part, plans_part, params)
        _finalise_status(result, schema, params)
    except Exception as exc:  # database/query problems must never crash the caller
        result["analysis_status"] = "error"
        result["topics"], result["friction_findings"] = [], []
        result["warnings"].append({
            "code": "analysis_error",
            "message": f"Analysis could not be completed ({type(exc).__name__}). "
                       "Check that the database exists and has been set up from schema/schema.sql.",
        })
        result["insufficient_data"] = {"is_insufficient": True, "reasons": ["analysis_error"]}
    finally:
        if own_conn and conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return result


# ---------------------------------------------------------------------------
# Per-source analysis
# ---------------------------------------------------------------------------
def _source_entry(name, table, info, cols, examined, **extra):
    entry = {"source": name, "table": table, "available": bool(info["usable"]),
             "columns_used": cols, "columns_missing": info["columns_missing"],
             "records_examined": examined}
    entry.update(extra)
    return entry


def _analyze_contacts(conn, schema, params, since, result):
    info = schema["contact_messages"]
    if not info["usable"]:
        result["data_sources"].append(_source_entry("contact_messages", "contact_messages", info, [], 0))
        _warn(result, "source_unavailable",
              "contact_messages is missing or lacks id/subject/message; topic analysis was skipped.")
        return None

    rows, cols = _select(conn, "contact_messages", info,
                         ["id", "subject", "message", "created_at", "is_read", "email"])
    total_in_table = len(rows)
    salt = secrets.token_hex(8)  # throw-away; makes sender tokens non-reproducible
    max_ids = params["max_example_ids"]

    per_topic = defaultdict(lambda: {"ids": [], "senders": set(), "kw": Counter(), "times": [], "count": 0,
                                     "no_ts": 0, "unread": 0})
    unclassified = Counter()
    unclassified_ids = defaultdict(list)
    examined = no_ts = out_of_window = unread = 0
    all_times = []

    for row in rows:
        ts = _parse_timestamp(row.get("created_at")) if "created_at" in row else None
        if since is not None:
            if ts is None:
                no_ts += 1  # cannot be placed in the window: excluded, but reported
                out_of_window += 1
                continue
            if ts < since:
                out_of_window += 1
                continue
        examined += 1
        if ts is None:
            no_ts += 1
        else:
            all_times.append(ts)
        is_unread = ("is_read" in row) and not row.get("is_read")
        unread += 1 if is_unread else 0

        verdict = classify_text(row.get("subject"), row.get("message"), params["max_text_chars"])
        if verdict["topic"] is None:
            reason = verdict["unclassified_reason"]
            unclassified[reason] += 1
            if len(unclassified_ids[reason]) < max_ids:
                unclassified_ids[reason].append(row.get("id"))
            continue
        bucket = per_topic[verdict["topic"]]
        bucket["count"] += 1
        if len(bucket["ids"]) < max_ids:
            bucket["ids"].append(row.get("id"))
        token = _sender_token(row.get("email"), salt) if "email" in row else None
        if token:
            bucket["senders"].add(token)
        bucket["kw"].update(verdict["keywords"])
        if ts is None:
            bucket["no_ts"] += 1
        else:
            bucket["times"].append(ts)
        bucket["unread"] += 1 if is_unread else 0

    classified = sum(b["count"] for b in per_topic.values())
    result["data_sources"].append(_source_entry(
        "contact_messages", "contact_messages", info, cols, examined,
        records_in_table=total_in_table, records_excluded_by_time_window=out_of_window,
        records_without_valid_timestamp=no_ts))

    topics = []
    for tid, b in per_topic.items():
        times = sorted(b["times"])
        senders = len(b["senders"])
        strength = _text_strength(b["count"], senders, params)
        topics.append({
            "topic_id": tid,
            "label": TOPIC_BY_ID[tid]["label"],
            "source_type": "contact_messages",
            "record_count": b["count"],
            "share_of_examined_messages": round(b["count"] / examined, 4) if examined else None,
            "distinct_senders": senders if "email" in cols else None,
            "unread_count": b["unread"] if "is_read" in cols else None,
            "matched_keywords": [{"keyword": k, "count": c} for k, c in b["kw"].most_common(5)],
            "time_period": {
                "first_seen": _iso(times[0]) if times else None,
                "last_seen": _iso(times[-1]) if times else None,
                "records_without_timestamp": b["no_ts"],
                "supported": bool(times),
            },
            "evidence_strength": strength,
            "support_level": "directly_supported_count",
            "example_record_ids": b["ids"],
            "evidence_summary": _topic_evidence_text(TOPIC_BY_ID[tid]["label"], b["count"], senders,
                                                     times, "email" in cols),
        })
    topics.sort(key=lambda t: (-t["record_count"], t["topic_id"]))
    result["topics"] = topics

    result["unclassified"] = {
        "count": sum(unclassified.values()),
        "share_of_examined_messages": round(sum(unclassified.values()) / examined, 4) if examined else None,
        "reasons": {r: {"count": c, "description": UNCLASSIFIED_REASONS[r],
                        "example_record_ids": unclassified_ids[r]} for r, c in unclassified.items()},
    }

    period = {"first_seen": _iso(min(all_times)) if all_times else None,
              "last_seen": _iso(max(all_times)) if all_times else None,
              "supported": bool(all_times), "records_without_timestamp": no_ts,
              "window_days": params["since_days"]}
    result["summary"] = {
        "contact_messages_in_table": total_in_table,
        "contact_messages_examined": examined,
        "contact_messages_classified": classified,
        "contact_messages_unclassified": sum(unclassified.values()),
        "contact_messages_unread": unread if "is_read" in cols else None,
        "time_period": period,
    }
    if no_ts:
        _warn(result, "missing_timestamps", f"{no_ts} contact message(s) have a missing or unreadable created_at.")
    if examined and sum(unclassified.values()) / examined > 0.5:
        _warn(result, "high_unclassified_share",
              "More than half of the messages could not be assigned a topic; topic counts may under-represent reality.")
    return {"examined": examined, "classified": classified, "topics": {t["topic_id"]: t for t in topics}}


def _topic_evidence_text(label, count, senders, times, has_email):
    parts = [f"{count} contact message{'s' if count != 1 else ''} matched '{label}'"]
    if has_email:
        parts.append(f"from {senders} distinct sender{'s' if senders != 1 else ''}")
    text = " ".join(parts)
    if times:
        a, b = _iso(min(times))[:10], _iso(max(times))[:10]
        text += f", dated {a}" if a == b else f", dated {a} to {b}"
    return text + "."


def _analyze_requests(conn, schema, params, since, now, result):
    info = schema["membership_requests"]
    if not info["usable"]:
        result["data_sources"].append(_source_entry("membership_requests", "membership_requests", info, [], 0))
        _warn(result, "source_unavailable", "membership_requests is missing or lacks id/status; skipped.")
        return None
    rows, cols = _select(conn, "membership_requests", info,
                         ["id", "user_id", "plan_id", "status", "request_date"])
    in_table = len(rows)
    has_date = "request_date" in cols
    kept, no_ts, out_of_window = [], 0, 0
    for r in rows:
        ts = _parse_timestamp(r.get("request_date")) if has_date else None
        if since is not None and (ts is None or ts < since):
            out_of_window += 1
            continue
        if ts is None:
            no_ts += 1
        r["_ts"] = ts
        kept.append(r)

    by_status = Counter()
    unknown_status = 0
    for r in kept:
        st = r.get("status")
        if st in KNOWN_REQUEST_STATUSES:
            by_status[st] += 1
        else:
            unknown_status += 1
    pending_cut = now - timedelta(days=params["pending_age_days"])
    pending_old = [r for r in kept if r.get("status") == "pending" and r["_ts"] and r["_ts"] < pending_cut]
    pending_no_date = sum(1 for r in kept if r.get("status") == "pending" and not r["_ts"])

    # Users who requested again after a rejection (user ids stay internal).
    repeat_after_reject = 0
    users_with_multiple = 0
    if "user_id" in cols and has_date:
        per_user = defaultdict(list)
        for r in kept:
            if r.get("user_id") is not None and r["_ts"]:
                per_user[r["user_id"]].append(r)
        for reqs in per_user.values():
            reqs.sort(key=lambda x: (x["_ts"], x.get("id") or 0))
            if len(reqs) > 1:
                users_with_multiple += 1
            seen_reject = False
            for x in reqs:
                if seen_reject:
                    repeat_after_reject += 1
                    break
                if x.get("status") == "rejected":
                    seen_reject = True

    per_plan = Counter(r.get("plan_id") for r in kept if "plan_id" in cols and r.get("plan_id") is not None)
    times = sorted(r["_ts"] for r in kept if r["_ts"])
    result["data_sources"].append(_source_entry(
        "membership_requests", "membership_requests", info, cols, len(kept),
        records_in_table=in_table, records_excluded_by_time_window=out_of_window,
        records_without_valid_timestamp=no_ts))
    if no_ts:
        _warn(result, "missing_request_dates", f"{no_ts} membership request(s) have no readable request_date.")
    if unknown_status:
        _warn(result, "unknown_request_status",
              f"{unknown_status} membership request(s) have a status outside {list(KNOWN_REQUEST_STATUSES)}; not counted by status.")

    public = {
        "records_examined": len(kept),
        "by_status": {s: by_status.get(s, 0) for s in KNOWN_REQUEST_STATUSES},
        "unrecognised_status_count": unknown_status,
        "pending_older_than_days": {"threshold_days": params["pending_age_days"],
                                    "count": len(pending_old),
                                    "pending_without_request_date": pending_no_date},
        "users_with_multiple_requests": users_with_multiple if ("user_id" in cols and has_date) else None,
        "users_who_requested_again_after_rejection": repeat_after_reject if ("user_id" in cols and has_date) else None,
        "time_period": {"first_seen": _iso(times[0]) if times else None,
                        "last_seen": _iso(times[-1]) if times else None, "supported": bool(times)},
        "requests_per_plan_id": {str(k): v for k, v in sorted(per_plan.items())},
    }
    return {"public": public, "kept": len(kept), "per_plan": per_plan, "pending_old_ids":
            [r.get("id") for r in pending_old][:params["max_example_ids"]], "cols": cols}


def _analyze_plans(conn, schema, requests_part, result):
    info = schema["membership_plans"]
    if not info["usable"]:
        result["data_sources"].append(_source_entry("membership_plans", "membership_plans", info, [], 0))
        _warn(result, "source_unavailable", "membership_plans is missing or lacks id; skipped.")
        return None
    rows, cols = _select(conn, "membership_plans", info, ["id", "plan_name", "duration_months", "price", "features"])
    no_features = []
    if "features" in cols:
        no_features = [r["id"] for r in rows if not normalize_text(r.get("features"))]
    per_plan = requests_part["per_plan"] if requests_part else Counter()
    result["data_sources"].append(_source_entry("membership_plans", "membership_plans", info, cols, len(rows)))
    public = {
        "records_examined": len(rows),
        "plans_without_features_text": len(no_features) if "features" in cols else None,
        "plans_without_features_ids": no_features[:5],
        "requests_per_plan": [{"plan_id": r["id"], "plan_name": r.get("plan_name"),
                               "request_count": per_plan.get(r["id"], 0)} for r in rows] if requests_part else None,
        "orphan_request_plan_ids": sorted(set(per_plan) - {r["id"] for r in rows}) if requests_part else None,
    }
    return {"public": public, "no_features": len(no_features) if "features" in cols else None}


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------
_TEXT_UNCERTAIN = [
    "Whether the enquirers were actually confused, or just asking ordinary questions.",
    "Whether the answer is already available on the website.",
    "Whether the enquiry was answered ('is_read' is not a reply record).",
]
_TEXT_LIMITS = [
    "Keyword-rule classification; a message about two topics is counted once under its best-matching topic.",
    "Contact messages are not linked to a user account or plan.",
]


def _build_findings(result, contact, requests, plans, params):
    findings = []
    if contact:
        for t in contact["topics"].values():
            if t["record_count"] < params["min_messages_per_finding"]:
                continue
            tid = t["topic_id"]
            findings.append({
                "finding_id": f"repeated_topic:{tid}",
                "type": "repeated_contact_topic",
                "title": f"Repeated enquiries: {t['label']}",
                "topic_id": tid,
                "source_types": ["contact_messages"],
                "record_count": t["record_count"],
                "distinct_senders": t["distinct_senders"],
                "time_period": t["time_period"],
                "evidence_strength": t["evidence_strength"],
                "support_level": "possible_interpretation",
                "evidence_summary": t["evidence_summary"],
                "what_data_supports": [
                    f"{t['record_count']} contact messages were classified under this topic.",
                    "The count is exact for the records examined.",
                ],
                "possible_interpretation": TOPIC_BY_ID[tid]["interpretation"],
                "what_remains_uncertain": list(_TEXT_UNCERTAIN),
                "limitations": list(_TEXT_LIMITS),
                "example_record_ids": t["example_record_ids"],
            })

    if requests and requests["public"]["records_examined"]:
        pub = requests["public"]
        old = pub["pending_older_than_days"]
        if old["count"] > 0:
            findings.append({
                "finding_id": "pending_requests_aging",
                "type": "pending_membership_requests",
                "title": "Membership requests still pending after the threshold age",
                "topic_id": "membership_request_process",
                "source_types": ["membership_requests"],
                "record_count": old["count"],
                "distinct_senders": None,
                "time_period": pub["time_period"],
                "evidence_strength": "weak",
                "support_level": "possible_interpretation",
                "evidence_summary": (f"{old['count']} of {pub['records_examined']} membership requests have status "
                                     f"'pending' and a request_date older than {old['threshold_days']} days."),
                "what_data_supports": [
                    "These rows are status 'pending' and older than the configured threshold."],
                "possible_interpretation": "Requests may be waiting for admin action or for the member to visit and pay.",
                "what_remains_uncertain": [
                    "Whether anyone was delayed, ignored or abandoned the request; the schema has no status-change times.",
                    "The threshold is a configurable analysis parameter, not a service-level target."],
                "limitations": ["Pending is a normal state: the site tells members to visit the gym to pay and activate."],
                "example_record_ids": requests["pending_old_ids"],
            })
        again = pub["users_who_requested_again_after_rejection"]
        if again:
            findings.append({
                "finding_id": "requests_after_rejection",
                "type": "repeat_request_after_rejection",
                "title": "Members who submitted another request after a rejected one",
                "topic_id": "membership_request_process",
                "source_types": ["membership_requests"],
                "record_count": again,
                "distinct_senders": None,
                "time_period": pub["time_period"],
                "evidence_strength": "weak",
                "support_level": "possible_interpretation",
                "evidence_summary": f"{again} member(s) have a later request after a rejected request.",
                "what_data_supports": ["A rejected request exists with a later request from the same member."],
                "possible_interpretation": "Members may retry after a rejection, possibly because the reason was unclear.",
                "what_remains_uncertain": [
                    "Why the request was rejected (no reason is stored).",
                    "Whether the retry resolved the original problem."],
                "limitations": ["Matching uses user_id internally; no user identity is returned."],
                "example_record_ids": [],
            })

    if plans and plans["no_features"]:
        corroborated = bool(contact and contact["topics"].get("membership_plans_pricing", {}).get("record_count", 0)
                            >= params["min_messages_per_finding"])
        findings.append({
            "finding_id": "plans_missing_feature_text",
            "type": "plan_information_gap",
            "title": "Membership plans with no features description",
            "topic_id": "membership_plans_pricing",
            "source_types": ["membership_plans"] + (["contact_messages"] if corroborated else []),
            "record_count": plans["no_features"],
            "distinct_senders": None,
            "time_period": {"first_seen": None, "last_seen": None, "supported": False,
                            "records_without_timestamp": plans["no_features"]},
            "evidence_strength": "moderate" if corroborated else "weak",
            "support_level": "possible_interpretation",
            "evidence_summary": (f"{plans['no_features']} plan(s) have an empty features field"
                                 + ("; repeated plan/pricing enquiries also exist." if corroborated else ".")),
            "what_data_supports": ["The features column is empty for these plans."],
            "possible_interpretation": "Thin plan descriptions could prompt questions about what each plan includes.",
            "what_remains_uncertain": ["Whether the front end shows other details instead of this field.",
                                       "Whether any enquiry was actually caused by the missing text."],
            "limitations": ["membership_plans has no timestamps."],
            "example_record_ids": [],
        })

    findings.sort(key=lambda f: (-f["record_count"], f["finding_id"]))
    result["friction_findings"] = findings


def _finalise_status(result, schema, params):
    reasons = []
    usable = {k: v["usable"] for k, v in schema.items()}
    summary = result["summary"]
    classified = summary.get("contact_messages_classified", 0) if summary else 0
    examined = summary.get("contact_messages_examined", 0) if summary else 0

    if not usable["contact_messages"] and not usable["membership_requests"]:
        result["analysis_status"] = "error"
        reasons.append("no_usable_sources")
        _warn(result, "no_usable_sources", "Neither contact_messages nor membership_requests could be read.")
    else:
        if not all(usable.values()):
            result["analysis_status"] = "partial"
        if usable["contact_messages"] and classified < params["min_messages_for_analysis"]:
            reasons.append("too_few_classified_messages")
        if usable["contact_messages"] and examined == 0:
            reasons.append("no_contact_messages")
    if reasons and result["analysis_status"] in ("ok", "partial"):
        # Insufficient data does not hide what exists; it flags that conclusions are unreliable.
        if "too_few_classified_messages" in reasons or "no_contact_messages" in reasons:
            result["analysis_status"] = "insufficient_data" if result["analysis_status"] == "ok" else "partial"
            _warn(result, "insufficient_data",
                  f"Only {classified} contact message(s) could be classified; at least "
                  f"{params['min_messages_for_analysis']} are needed before topic counts are treated as reliable. "
                  "Counts below are exact but do not support conclusions.")
    result["insufficient_data"] = {"is_insufficient": bool(reasons), "reasons": reasons}
    if reasons and result["analysis_status"] in ("insufficient_data", "partial"):
        # Counts stay exact, but text-topic conclusions are marked unreliable.
        for f in result["friction_findings"]:
            if f["type"] == "repeated_contact_topic":
                f["evidence_strength"] = "insufficient"
                f.setdefault("notes", []).append(
                    "Overall number of classified messages is below min_messages_for_analysis.")

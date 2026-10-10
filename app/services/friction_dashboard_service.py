"""
Royal Brothers Fitness Gym - Friction Insights Dashboard Adapter (Phase 3)

Thin, READ-ONLY presentation layer between the admin routes and the existing
Phase 1 (friction_analysis_service) and Phase 2 (friction_insights_service) services.

It does three things and nothing else:

1. Validates request inputs against an allow-list (``parse_since_days``).
2. Builds a response from an explicit WHITELIST of fields. Anything the lower layers
   add in the future (ids, keywords, plan names, raw text, ...) is dropped by default.
3. Neutralises text: control characters and angle brackets are removed and length is
   capped, so AI-written strings can never form markup even if a consumer mishandled
   them. The browser additionally renders every string with ``textContent``.

No database writes, no e-mail, no business actions, no Gemini call in this module.
Counts, dates and statuses are only ever copied from the Phase 1/2 results; nothing is
computed or invented here.
"""

import re
from datetime import datetime

from .friction_analysis_service import analyze_member_journey_friction
from .friction_insights_service import (
    DISCLAIMER,
    GENERAL_TIPS,
    PRIORITY_BY_STRENGTH,
    PRIORITY_RULE,
    build_verified_facts,
    describe_missing_data,
)

VIEW_SCHEMA_VERSION = "1.0"

# Only these look-back windows may be requested (None = all available data).
ALLOWED_SINCE_DAYS = (30, 90, 180, 365)

# Per-field caps. The Phase 2 service already clips AI text; these are a second guard.
MAX_TEXT = 600
MAX_LIST_ITEMS = 8
MAX_INSIGHTS = 8

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u2028\u2029]")
_ANGLE_BRACKETS = re.compile(r"[<>]")
_SAFE_CODE = re.compile(r"^[a-z0-9_]{1,60}$")
_SAFE_ID = re.compile(r"^[a-z0-9_:\-]{1,80}$")

# HTTP statuses the dashboard is willing to relay for an AI/analysis failure.
_ALLOWED_ERROR_STATUSES = (429, 500, 502, 503, 504)


class InputError(ValueError):
    """Raised for invalid request input. The message is safe to show to the admin."""


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------
def parse_since_days(value):
    """Validate the optional look-back window. Returns None or one of ALLOWED_SINCE_DAYS.

    Accepts None / "" / "all" (no limit), an int, or a digit string. Booleans, floats,
    negative or unlisted numbers are rejected rather than coerced.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise InputError("since_days must be one of: all, 30, 90, 180, 365.")
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("", "all"):
            return None
        if not re.fullmatch(r"[0-9]{1,4}", text):  # ASCII only: \d would accept e.g. Arabic-Indic digits
            raise InputError("since_days must be one of: all, 30, 90, 180, 365.")
        value = int(text)
    if not isinstance(value, int) or value not in ALLOWED_SINCE_DAYS:
        raise InputError("since_days must be one of: all, 30, 90, 180, 365.")
    return value


def overrides_for(since_days):
    """Phase 1 keyword overrides for a validated window."""
    return {"since_days": since_days} if since_days else {}


# ---------------------------------------------------------------------------
# Sanitising helpers
# ---------------------------------------------------------------------------
def clean_text(value, limit=MAX_TEXT):
    """Return a plain, single-block string: no control chars, no < or >, capped length.

    Non-strings become "" (never str()-ed, so objects/exceptions cannot leak).
    """
    if not isinstance(value, str):
        return ""
    text = _CONTROL_CHARS.sub(" ", value)
    text = _ANGLE_BRACKETS.sub("", text)
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def clean_list(values, limit=MAX_TEXT, max_items=MAX_LIST_ITEMS):
    if not isinstance(values, (list, tuple)):
        return []
    out = []
    for v in values:
        t = clean_text(v, limit)
        if t:
            out.append(t)
        if len(out) >= max_items:
            break
    return out


def _count(value):
    """Counts must be real, non-negative ints; anything else is shown as 'not available'."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _period(tp):
    tp = tp if isinstance(tp, dict) else {}
    return {
        "first_seen": clean_text(tp.get("first_seen"), 40) or None,
        "last_seen": clean_text(tp.get("last_seen"), 40) or None,
        "supported": bool(tp.get("supported")),
    }


def _strength(value):
    return value if value in PRIORITY_BY_STRENGTH else None


def _code(value):
    return value if isinstance(value, str) and _SAFE_CODE.match(value) else None


def _warnings(items):
    out = []
    for w in items if isinstance(items, list) else []:
        if not isinstance(w, dict):
            continue
        code, msg = _code(w.get("code")), clean_text(w.get("message"), 400)
        if code and msg:
            out.append({"code": code, "message": msg})
    return out[:MAX_LIST_ITEMS]


# ---------------------------------------------------------------------------
# Whitelisted views
# ---------------------------------------------------------------------------
def _clean_verified_facts(facts):
    """Re-whitelist the Phase 2 ``verified_facts`` object (already PII-free)."""
    if not isinstance(facts, dict):
        return None
    cm = facts.get("contact_messages") or {}
    out = {
        "contact_messages": {
            "examined": _count(cm.get("examined")),
            "classified": _count(cm.get("classified")),
            "unclassified": _count(cm.get("unclassified")),
            "time_period": _period(cm.get("time_period")),
        },
        "topics": [],
        "membership_requests": None,
        "membership_plans": None,
    }
    for t in facts.get("topics") or []:
        if not isinstance(t, dict):
            continue
        out["topics"].append({
            "label": clean_text(t.get("label"), 120),
            "record_count": _count(t.get("record_count")),
            "distinct_senders": _count(t.get("distinct_senders")),
            "evidence_strength": t.get("evidence_strength")
            if t.get("evidence_strength") in ("insufficient", "weak", "moderate", "strong") else None,
            "time_period": _period(t.get("time_period")),
        })
    out["topics"] = out["topics"][:20]

    r = facts.get("membership_requests")
    if isinstance(r, dict):
        by_status = r.get("by_status") if isinstance(r.get("by_status"), dict) else {}
        older = r.get("pending_older_than_days") if isinstance(r.get("pending_older_than_days"), dict) else {}
        out["membership_requests"] = {
            "records_examined": _count(r.get("records_examined")),
            "by_status": {k: _count(by_status.get(k)) for k in ("pending", "active", "rejected")},
            "pending_older_than_days": {
                "threshold_days": _count(older.get("threshold_days")),
                "count": _count(older.get("count")),
            },
            "users_who_requested_again_after_rejection": _count(r.get("users_who_requested_again_after_rejection")),
            "time_period": _period(r.get("time_period")),
        }
    p = facts.get("membership_plans")
    if isinstance(p, dict):
        out["membership_plans"] = {
            "records_examined": _count(p.get("records_examined")),
            "plans_without_features_text": _count(p.get("plans_without_features_text")),
        }
    return out


def _clean_analysis_meta(meta):
    if not isinstance(meta, dict):
        return None
    return {
        "schema_version": clean_text(meta.get("schema_version"), 20) or None,
        "status": _code(meta.get("status")),
        "generated_at": clean_text(meta.get("generated_at"), 40) or None,
    }


def _clean_finding(f):
    return {
        "finding_id": f.get("finding_id") if isinstance(f.get("finding_id"), str) and _SAFE_ID.match(f["finding_id"]) else None,
        "title": clean_text(f.get("title"), 160),
        "source_types": clean_list(f.get("source_types"), 60, 4),
        "record_count": _count(f.get("record_count")),
        "distinct_senders": _count(f.get("distinct_senders")),
        "time_period": _period(f.get("time_period")),
        "evidence_strength": _strength(f.get("evidence_strength")) or "insufficient",
        "evidence_summary": clean_text(f.get("evidence_summary"), 300),
        "what_data_supports": clean_list(f.get("what_data_supports"), 300),
        "what_remains_uncertain": clean_list(f.get("what_remains_uncertain"), 300),
        "limitations": clean_list(f.get("limitations"), 300),
    }


def _general_tips():
    return [{"text": clean_text(t, 300), "scope": "general_not_about_this_gym", "ai_generated": False}
            for t in GENERAL_TIPS]


def _now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def build_analysis_view(since_days=None, *, db_path=None):
    """Run the Phase 1 analysis (read-only, NO Gemini) and return a sanitised view.

    ``state`` is one of:
      ready              enough data and at least one finding that could be interpreted by AI
      insufficient_data  not enough classifiable data; nothing is concluded
      no_findings        enough data but no pattern met the thresholds
      error              the analysis could not run (safe message only)
    """
    analysis = analyze_member_journey_friction(db_path=db_path, **overrides_for(since_days))
    return view_from_analysis(analysis, since_days)


def view_from_analysis(analysis, since_days=None):
    base = {
        "schema_version": VIEW_SCHEMA_VERSION,
        "generated_at": _now(),
        "parameters": {"since_days": since_days},
        "state": "error",
        "analysis": None,
        "verified_facts": None,
        "findings": [],
        "additional_data_needed": [],
        "general_suggestions": [],
        "warnings": [],
        "limitations": [],
        "error": None,
        "disclaimer": DISCLAIMER,
        "priority_rule": PRIORITY_RULE,
    }
    valid = (isinstance(analysis, dict) and isinstance(analysis.get("friction_findings"), list)
             and isinstance(analysis.get("topics"), list)
             and analysis.get("analysis_status") in ("ok", "insufficient_data", "partial", "error"))
    if not valid:
        base["error"] = {"code": "invalid_analysis",
                         "message": "The data analysis result was missing or in an unexpected format."}
        return base

    base["analysis"] = _clean_analysis_meta({
        "schema_version": analysis.get("schema_version"),
        "status": analysis.get("analysis_status"),
        "generated_at": analysis.get("generated_at"),
    })
    base["verified_facts"] = _clean_verified_facts(build_verified_facts(analysis))
    base["warnings"] = _warnings(analysis.get("warnings"))
    base["limitations"] = clean_list(analysis.get("limitations"), 300, 12)

    if analysis["analysis_status"] == "error":
        base["error"] = {"code": "analysis_failed",
                         "message": "The member data could not be analysed, so nothing is shown."}
        return base

    insuff = analysis.get("insufficient_data") if isinstance(analysis.get("insufficient_data"), dict) else {}
    if analysis["analysis_status"] == "insufficient_data" or insuff.get("is_insufficient"):
        base["state"] = "insufficient_data"
        base["additional_data_needed"] = clean_list(describe_missing_data(analysis), 300)
        base["general_suggestions"] = _general_tips()
        return base

    eligible = [f for f in analysis["friction_findings"]
                if isinstance(f, dict) and f.get("evidence_strength") in PRIORITY_BY_STRENGTH]
    base["findings"] = [_clean_finding(f) for f in eligible[:MAX_INSIGHTS]]
    base["state"] = "ready" if eligible else "no_findings"
    if not eligible:
        base["warnings"].append({
            "code": "no_repeated_patterns",
            "message": "Enough data was analysed, but no topic or request pattern met the threshold for a finding."})
    return base


def clean_insights_result(result):
    """Whitelist + sanitise a Phase 2 ``generate_friction_insights`` result for the browser.

    Returns (payload, http_status). Never raises; a malformed result becomes a safe error.
    """
    if not isinstance(result, dict) or result.get("status") not in ("ok", "insufficient_data", "no_findings", "error"):
        return _error_payload("unexpected_error", "The insights could not be generated right now."), 500

    status = result["status"]
    payload = {
        "schema_version": VIEW_SCHEMA_VERSION,
        "state": status,
        "generated_at": clean_text(result.get("generated_at"), 40) or _now(),
        "analysis": _clean_analysis_meta(result.get("analysis")),
        "verified_facts": _clean_verified_facts(result.get("verified_facts")),
        "insights": [],
        "general_suggestions": [],
        "additional_data_needed": clean_list(result.get("additional_data_needed"), 300),
        "warnings": _warnings(result.get("warnings")),
        "validation": _clean_validation(result.get("validation")),
        "error": None,
        "disclaimer": DISCLAIMER,
        "priority_rule": PRIORITY_RULE,
    }

    if status == "ok":
        for ins in (result.get("insights") or [])[:MAX_INSIGHTS]:
            cleaned = _clean_insight(ins)
            if cleaned:
                payload["insights"].append(cleaned)
        if not payload["insights"]:
            # Nothing survived the second whitelist: never show an "ok" with no content.
            return _error_payload("invalid_ai_output",
                                  "The AI response could not be validated, so no insights were produced."), 502
        for g in (result.get("general_suggestions") or [])[:3]:
            if isinstance(g, dict):
                t = clean_text(g.get("text"), 300)
                if t:
                    payload["general_suggestions"].append({
                        "text": t, "scope": "general_not_about_this_gym",
                        "ai_generated": bool(g.get("ai_generated"))})
        return payload, 200

    if status == "insufficient_data":
        payload["general_suggestions"] = _general_tips()
        return payload, 200

    if status == "no_findings":
        return payload, 200

    # status == "error"
    err = result.get("error") if isinstance(result.get("error"), dict) else {}
    http_status = err.get("http_status") if err.get("http_status") in _ALLOWED_ERROR_STATUSES else 500
    payload["error"] = {"code": _code(err.get("code")) or "unexpected_error",
                        "message": clean_text(err.get("message"), 300) or "The insights could not be generated right now."}
    return payload, http_status


def _clean_validation(v):
    v = v if isinstance(v, dict) else {}
    issues = [i for i in (v.get("issues") or []) if isinstance(i, str) and _SAFE_CODE.match(i)]
    return {
        "attempts": _count(v.get("attempts")) or 0,
        "issues": sorted(set(issues))[:20],
        "findings_offered": _count(v.get("findings_offered")),
        "insights_accepted": _count(v.get("insights_accepted")),
        "insights_rejected": _count(v.get("insights_rejected")),
    }


def _clean_insight(ins):
    if not isinstance(ins, dict):
        return None
    facts = ins.get("facts") if isinstance(ins.get("facts"), dict) else {}
    interp = ins.get("interpretation") if isinstance(ins.get("interpretation"), dict) else {}
    priority = ins.get("priority") if ins.get("priority") in ("high", "medium", "low") else None
    strength = _strength(ins.get("evidence_strength"))
    fid = ins.get("finding_id")
    hypothesis = clean_text(interp.get("friction_hypothesis"), 500)
    recommendation = clean_text(interp.get("recommendation"), 500)
    if not (priority and strength and isinstance(fid, str) and _SAFE_ID.match(fid) and hypothesis and recommendation):
        return None  # incomplete items are dropped, never "repaired" with invented text
    return {
        "finding_id": fid,
        "title": clean_text(ins.get("title"), 160),
        "source_types": clean_list(ins.get("source_types"), 60, 4),
        "facts": {
            "record_count": _count(facts.get("record_count")),
            "distinct_senders": _count(facts.get("distinct_senders")),
            "time_period": _period(facts.get("time_period")),
            "evidence_summary": clean_text(facts.get("evidence_summary"), 300),
            "what_data_supports": clean_list(facts.get("what_data_supports"), 300),
        },
        "interpretation": {
            "label": "AI interpretation - possible, not proven",
            "friction_hypothesis": hypothesis,
            "why_it_may_matter": clean_text(interp.get("why_it_may_matter"), 400),
            "recommendation": recommendation,
            "supporting_evidence": clean_list(interp.get("supporting_evidence"), 250, 4),
        },
        "priority": priority,
        "priority_basis": clean_text(ins.get("priority_basis"), 500),
        "evidence_strength": strength,
        "limitations": clean_list(ins.get("limitations"), 300),
        "information_needed": clean_list(ins.get("information_needed"), 200, 3),
    }


def _error_payload(code, message):
    return {
        "schema_version": VIEW_SCHEMA_VERSION,
        "state": "error",
        "generated_at": _now(),
        "analysis": None,
        "verified_facts": None,
        "insights": [],
        "general_suggestions": [],
        "additional_data_needed": [],
        "warnings": [],
        "validation": {"attempts": 0, "issues": [], "findings_offered": None,
                       "insights_accepted": None, "insights_rejected": None},
        "error": {"code": code, "message": message},
        "disclaimer": DISCLAIMER,
        "priority_rule": PRIORITY_RULE,
    }


def safe_error_payload(code="unexpected_error", message="The insights could not be generated right now."):
    """Public helper for routes: a fixed, safe error body."""
    return _error_payload(code, message)

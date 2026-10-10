#!/usr/bin/env python3
"""Explicit external-scheduler entrypoint for membership reminders.

Examples (from the project root):
  python scripts/run_membership_reminders.py --dry-run
  python scripts/run_membership_reminders.py --as-of 2026-10-09

This module performs no work when imported. Dry-run reads Phase 6 eligibility
only; it does not consult/update delivery history or call the email service.
"""

import argparse
import contextlib
import io
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_DRY_RUN_VALUES = {
    "SECRET_KEY": "phase8-dry-run-secret-not-used-for-authentication",
    "MAIL_USERNAME": "phase8-dry-run@example.invalid",
    "MAIL_PASSWORD": "phase8-dry-run-credential-not-used",
}


def _parse_iso_date(value):
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("Use a valid YYYY-MM-DD date.")
    if parsed.isoformat() != value:
        raise argparse.ArgumentTypeError("Use a valid YYYY-MM-DD date.")
    return parsed


def _load_environment(dry_run):
    load_dotenv(PROJECT_ROOT / ".env")
    if dry_run:
        # The project app factory requires these settings even though a dry run
        # never constructs or sends an email. These placeholders are used only
        # in this process when the operator has not configured the values.
        for key, placeholder in _DRY_RUN_VALUES.items():
            if not os.environ.get(key, "").strip():
                os.environ[key] = placeholder
        return []

    required = ("SECRET_KEY", "MAIL_USERNAME", "MAIL_PASSWORD")
    return [key for key in required if not os.environ.get(key, "").strip()]


def _create_app():
    # Delayed until after the environment preflight: app/config.py validates
    # required settings at import time.
    from app import create_app
    return create_app()


def _get_eligible_reminders(as_of):
    from app.services.membership_reminder_service import get_eligible_reminders
    return get_eligible_reminders(as_of=as_of)


def _process_reminders(as_of):
    from app.services.membership_reminder_delivery_service import process_membership_reminders
    return process_membership_reminders(as_of=as_of)


def run(*, dry_run=False, as_of=None, app_factory=None):
    """Run once and return ``(safe_report, exit_code)`` for CLI/tests."""
    if as_of is not None and not isinstance(as_of, date):
        return {"status": "error", "code": "invalid_reference_date"}, 2

    missing = _load_environment(dry_run)
    if missing:
        has_smtp_missing = any(key in missing for key in ("MAIL_USERNAME", "MAIL_PASSWORD"))
        return {
            "status": "error",
            "code": "smtp_configuration_missing" if has_smtp_missing else "app_configuration_missing",
            "missing_settings": missing,
        }, 2

    try:
        app = (app_factory or _create_app)()
    except Exception:
        return {"status": "error", "code": "app_initialization_failed"}, 1

    if dry_run:
        # Defense in depth: no email sender should be able to transmit from a
        # dry-run app context even if a later refactor accidentally calls it.
        app.config["MAIL_SUPPRESS_SEND"] = True

    try:
        with app.app_context():
            if dry_run:
                with contextlib.redirect_stdout(io.StringIO()):
                    eligible = _get_eligible_reminders(as_of=as_of)
                if not isinstance(eligible, dict) or eligible.get("status") != "ok":
                    candidate = (eligible.get("error") or {}).get("code") if isinstance(eligible, dict) else None
                    code = candidate if isinstance(candidate, str) and _SAFE_CODE.fullmatch(candidate) else "eligibility_unavailable"
                    return {"status": "error", "code": code}, 1
                reminders = eligible.get("reminders")
                if not isinstance(reminders, list):
                    return {"status": "error", "code": "eligibility_unavailable"}, 1
                return {
                    "status": "dry_run",
                    "as_of": eligible.get("as_of") or (as_of or date.today()).isoformat(),
                    "summary": {
                        "eligible": len(reminders),
                        "attempted": 0,
                        "sent": 0,
                        "failed": 0,
                        "skipped": 0,
                        "uncertain": 0,
                        "errors": 0,
                    },
                    "note": "Counts exact-date Phase 6 eligible reminders only; delivery history and retry candidates are not read.",
                }, 0

            with contextlib.redirect_stdout(io.StringIO()):
                result = _process_reminders(as_of=as_of)
            if not isinstance(result, dict) or result.get("status") != "ok":
                candidate = (result.get("error") or {}).get("code") if isinstance(result, dict) else None
                code = candidate if isinstance(candidate, str) and _SAFE_CODE.fullmatch(candidate) else "delivery_unavailable"
                return {"status": "error", "code": code}, 1
            raw = result.get("summary")
            if not isinstance(raw, dict):
                return {"status": "error", "code": "delivery_unavailable"}, 1
            counts = {}
            for key in ("eligible_candidates", "sent", "failed", "skipped", "uncertain", "errors"):
                value = raw.get(key, 0)
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    return {"status": "error", "code": "delivery_unavailable"}, 1
                counts[key] = value
            counts["attempted"] = counts["sent"] + counts["failed"] + counts["uncertain"]
            failed_run = any(counts[key] for key in ("failed", "uncertain", "errors"))
            report = {
                "status": "partial_failure" if failed_run else "ok",
                "as_of": result.get("as_of") or (as_of or date.today()).isoformat(),
                "summary": counts,
            }
            return report, 1 if failed_run else 0
    except Exception:
        # Do not print exception text, database paths, credentials, or member data.
        return {"status": "error", "code": "scheduler_run_failed"}, 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of", type=_parse_iso_date, default=None,
        help="reference calendar date in YYYY-MM-DD form (default: server-local date)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="read exact-date eligibility only; send no email and write no delivery history",
    )
    args = parser.parse_args(argv)
    report, exit_code = run(dry_run=args.dry_run, as_of=args.as_of)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())

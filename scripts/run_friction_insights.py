"""
Royal Brothers Fitness Gym - run the Gemini friction insights (Phase 2) from the command line.

Reads the database READ-ONLY (Phase 1 analysis), sends ONLY aggregated, privacy-safe evidence to Gemini
using the key in your local .env, validates the reply and prints the JSON result. Nothing is written.
This is the way to do the "real Gemini API" check: it needs GEMINI_API_KEY in your .env and enough data
(otherwise the result is 'insufficient_data' and Gemini is not called).

Usage (project root):
    python scripts/run_friction_insights.py
    python scripts/run_friction_insights.py --db path/to.db --since-days 90
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser(description="Gemini member-journey friction insights (read-only).")
    parser.add_argument("--db", help="SQLite file to analyse (default: configured database).")
    parser.add_argument("--since-days", type=float, help="Only analyse records from the last N days.")
    args = parser.parse_args()

    for name in ("SECRET_KEY", "MAIL_USERNAME", "MAIL_PASSWORD"):   # required by app.config; unused here
        os.environ.setdefault(name, "analysis-only-placeholder")

    from app.services.friction_insights_service import generate_friction_insights

    overrides = {"since_days": args.since_days} if args.since_days is not None else {}
    result = generate_friction_insights(db_path=args.db, analysis_overrides=overrides)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] != "error" else 1


if __name__ == "__main__":
    sys.exit(main())

"""
Royal Brothers Fitness Gym - run the Member Journey Friction analysis (Phase 1).

READ-ONLY. Opens the database with SQLite mode=ro, prints the aggregated JSON result
(no names, phones, e-mails or message text) and never writes anything.

Usage (from the project root):
    python scripts/run_friction_analysis.py                    # uses DATABASE_PATH / default DB
    python scripts/run_friction_analysis.py --db path/to.db    # explicit file
    python scripts/run_friction_analysis.py --since-days 90
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser(description="Read-only member journey friction analysis.")
    parser.add_argument("--db", help="SQLite file to analyse (default: configured database).")
    parser.add_argument("--since-days", type=float, help="Only analyse records from the last N days.")
    args = parser.parse_args()

    # app.config needs SECRET_KEY/MAIL_* in the environment (existing project rule). The analysis
    # itself does not use them, so harmless placeholders are supplied only if they are unset.
    for name in ("SECRET_KEY", "MAIL_USERNAME", "MAIL_PASSWORD"):
        os.environ.setdefault(name, "analysis-only-placeholder")

    from app.services.friction_analysis_service import analyze_member_journey_friction

    overrides = {"since_days": args.since_days} if args.since_days is not None else {}
    result = analyze_member_journey_friction(db_path=args.db, **overrides)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["analysis_status"] != "error" else 1


if __name__ == "__main__":
    sys.exit(main())

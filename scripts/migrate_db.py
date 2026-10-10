"""
Existing-database migration runner for Royal Brothers Fitness Gym.

Applies the legacy email-verification/login-lockout changes from
schema/schema_updates.sql plus the additive fitness and reminder migrations
listed below. The legacy SQL is interpreted idempotently: existing user
columns are left alone, while CREATE TABLE/INDEX IF NOT EXISTS statements are
safe to re-run.

Safety:
  - never creates a database: if the file is missing it stops
  - copies the database to <name>.backup-<timestamp> BEFORE changing it
  - verifies every pre-existing table has the same row count afterwards
  - --check reports required missing schema without changing anything

Run from the project root:
    python scripts/migrate_db.py
    python scripts/migrate_db.py --db /path/to/royal_brothers_gym.db
    python scripts/migrate_db.py --check
"""

import argparse
import os
import re
import sqlite3
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_UPDATES = "schema_updates.sql"
MIGRATIONS = [
    "step2_fitness_profile.sql", "step3_workout_plan.sql",
    "step4_daily_planner.sql", "step5_fitness_progress.sql",
    "step6_ai_insights.sql", "step7_workout_recommendations.sql",
    "step8_nutrition_plans.sql", "phase6_reminder_preferences.sql",
    "phase7_membership_reminder_delivery.sql",
]
NEW_TABLES = [
    "email_verification_tokens", "fitness_profiles", "workout_plans",
    "daily_plans", "progress_entries", "ai_insights",
    "workout_recommendations", "nutrition_plans",
    "membership_reminder_preferences", "membership_reminder_lead_times",
    "membership_reminder_deliveries", "membership_reminder_delivery_attempts",
]
ALTER_COLUMN_RE = re.compile(
    r"ALTER\s+TABLE\s+([A-Za-z_][A-Za-z0-9_]*)\s+ADD\s+COLUMN\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)\s+([^;]+);",
    re.IGNORECASE,
)
CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+.*?;",
    re.IGNORECASE | re.DOTALL,
)
CREATE_INDEX_RE = re.compile(
    r"CREATE\s+INDEX\s+IF\s+NOT\s+EXISTS\s+.*?;",
    re.IGNORECASE | re.DOTALL,
)


def resolve_db_path(cli_path):
    if cli_path:
        return os.path.abspath(cli_path)
    try:  # same lookup as app/config.py
        from dotenv import load_dotenv
        load_dotenv(os.path.join(ROOT, ".env"))
    except ImportError:
        pass
    return os.environ.get("DATABASE_PATH", os.path.join(ROOT, "royal_brothers_gym.db"))


def user_tables(conn):
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def row_counts(conn, tables):
    return {t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}


def legacy_schema_parts():
    """Read only the additive statements in the legacy schema update file."""
    path = os.path.join(ROOT, "schema", SCHEMA_UPDATES)
    with open(path, encoding="utf-8") as source_file:
        source = source_file.read()
    column_statements = list(ALTER_COLUMN_RE.finditer(source))
    create_statements = [match.group(0) for match in CREATE_TABLE_RE.finditer(source)]
    create_statements.extend(match.group(0) for match in CREATE_INDEX_RE.finditer(source))
    return column_statements, create_statements


def missing_legacy_columns(conn):
    columns = {}
    statements = legacy_schema_parts()[0]
    for match in statements:
        table, _column, _definition = match.groups()
        if table not in columns:
            columns[table] = {
                row[1] for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            }
    return [f"{table}.{column}" for table, column, _definition in
            (match.groups() for match in statements)
            if column not in columns[table]]


def apply_legacy_schema_updates(conn):
    """Apply schema_updates.sql without repeating existing ALTER TABLEs."""
    column_statements, create_statements = legacy_schema_parts()
    tables = set(user_tables(conn))
    for match in column_statements:
        table, column, definition = match.groups()
        if table not in tables:
            raise RuntimeError(f"legacy schema prerequisite missing: {table} table")
        current = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}
        if column not in current:
            conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {definition.strip()}')
    for statement in create_statements:
        conn.executescript(statement)
    conn.commit()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", help="path to the existing SQLite database file")
    ap.add_argument("--check", action="store_true", help="only report status; change nothing")
    args = ap.parse_args()

    db_path = resolve_db_path(args.db)
    print(f"Database: {db_path}")
    if not os.path.isfile(db_path):
        print("ERROR: database file not found. Nothing was created or changed.")
        return 1

    conn = sqlite3.connect(db_path)
    try:
        before_tables = user_tables(conn)
        missing_tables = [table for table in NEW_TABLES if table not in before_tables]
        if "users" not in before_tables:
            print("ERROR: this does not look like the gym database (no 'users' table). Stopping.")
            return 1
        missing_columns = missing_legacy_columns(conn)
        print(f"Existing tables: {', '.join(before_tables)}")
        if missing_tables:
            print(f"Missing tables: {', '.join(missing_tables)}")
        if missing_columns:
            print(f"Missing legacy columns: {', '.join(missing_columns)}")
        if not missing_tables and not missing_columns:
            print("OK: all required legacy, fitness, and reminder schema exists. Nothing to do.")
            return 0
        if args.check:
            print("--check given: no changes made.")
            return 0

        before_counts = row_counts(conn, before_tables)

        # Backup (consistent copy, even if the app is running) before any DDL.
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = f"{db_path}.backup-{stamp}"
        dest = sqlite3.connect(backup_path)
        try:
            conn.backup(dest)
        finally:
            dest.close()
        print(f"Backup written: {backup_path}")

        # 1. Legacy auth columns/token table/index from schema_updates.sql.
        apply_legacy_schema_updates(conn)
        print(f"Applied idempotent legacy updates: schema/{SCHEMA_UPDATES}")

        # 2. Additive feature migrations use CREATE TABLE IF NOT EXISTS.
        for name in MIGRATIONS:
            with open(os.path.join(ROOT, "schema", name), encoding="utf-8") as migration_file:
                conn.executescript(migration_file.read())
            print(f"Applied: schema/{name}")

        # 3. Verify all required tables/columns and preserve existing row counts.
        after_tables = user_tables(conn)
        problems = [table for table in NEW_TABLES if table not in after_tables]
        problems += [column for column in missing_legacy_columns(conn)]
        problems += [f"{table} (rows {before_counts[table]} -> {count})"
                     for table, count in row_counts(conn, before_tables).items()
                     if count != before_counts[table]]
        if problems:
            print("ERROR: verification failed:", problems)
            print(f"Restore from backup if needed: {backup_path}")
            return 1
        print("OK: required schema created; all pre-existing tables kept their row counts.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())

"""Focused tests for the Phase 4A admin assistant aggregate data service.

All database operations use the temporary SQLite fixture from tests.base.
"""

import contextlib
import io
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

import tests.base  # noqa: F401 -- sets fake environment before app imports
from tests.base import DB_PATH, AppTestCase, add_user
from app.config import Config
from app.extensions import get_db_connection
from app.services import admin_assistant_data_service as service


class AdminAssistantDataServiceTests(AppTestCase):
    def _sql(self, sql, params=()):
        conn = sqlite3.connect(DB_PATH)
        try:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def _snapshot(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )]
            rows = {
                table: conn.execute(f'SELECT * FROM "{table}" ORDER BY 1').fetchall()
                for table in tables
            }
            schema = conn.execute(
                "SELECT type, name, sql FROM sqlite_master ORDER BY type, name"
            ).fetchall()
            return rows, schema
        finally:
            conn.close()

    def test_aggregates_verified_users_statuses_and_plan_distribution(self):
        verified_id = add_user("verified@example.invalid", verified=1)
        add_user("unverified@example.invalid", verified=0)
        plan_a = self._sql(
            "INSERT INTO membership_plans (plan_name, duration_months, price, features) VALUES (?,?,?,?)",
            ("Monthly", 1, 100, "private plan data"),
        )
        plan_b = self._sql(
            "INSERT INTO membership_plans (plan_name, duration_months, price, features) VALUES (?,?,?,?)",
            ("Annual", 12, 900, "another private field"),
        )
        self._sql(
            "INSERT INTO membership_requests (user_id, plan_id, status) VALUES (?,?,?)",
            (verified_id, plan_a, "pending"),
        )
        self._sql(
            "INSERT INTO membership_requests (user_id, plan_id, status) VALUES (?,?,?)",
            (verified_id, plan_a, "active"),
        )
        self._sql(
            "INSERT INTO membership_requests (user_id, plan_id, status) VALUES (?,?,?)",
            (verified_id, plan_b, "rejected"),
        )

        result = service.get_admin_summary()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["members"], {"total": 2, "verified": 1, "unverified": 1})
        requests = result["membership_requests"]
        self.assertEqual(requests["total"], 3)
        self.assertEqual(requests["by_status"], {"pending": 1, "active": 1, "rejected": 1})
        self.assertEqual(requests["other_or_missing_status"], 0)
        self.assertEqual(requests["plan_distribution"], [
            {"plan_name": "Annual", "request_count": 1},
            {"plan_name": "Monthly", "request_count": 2},
        ])

    def test_empty_tables_return_zero_counts_and_empty_distribution(self):
        result = service.get_admin_summary()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["members"], {"total": 0, "verified": 0, "unverified": 0})
        self.assertEqual(result["membership_requests"]["total"], 0)
        self.assertEqual(result["membership_requests"]["by_status"], {
            "pending": 0, "active": 0, "rejected": 0,
        })
        self.assertEqual(result["membership_requests"]["plan_distribution"], [])

    def test_plan_without_requests_is_included_and_blank_name_is_generic(self):
        self._sql(
            "INSERT INTO membership_plans (plan_name, duration_months, price, features) VALUES (?,?,?,?)",
            ("  ", 1, 50, None),
        )
        result = service.get_admin_summary()
        self.assertEqual(result["membership_requests"]["plan_distribution"], [
            {"plan_name": "Unspecified", "request_count": 0},
        ])

    def test_sensitive_member_fields_and_individual_records_are_not_returned(self):
        user_id = add_user("private.person@example.invalid", verified=1)
        plan_id = self._sql(
            "INSERT INTO membership_plans (plan_name, duration_months, price, features) VALUES (?,?,?,?)",
            ("Basic", 1, 20, "DO_NOT_RETURN_FEATURES"),
        )
        self._sql(
            "INSERT INTO membership_requests (user_id, plan_id, status) VALUES (?,?,?)",
            (user_id, plan_id, "pending"),
        )
        payload = json.dumps(service.get_admin_summary(), sort_keys=True)
        for private_value in (
            "private.person@example.invalid", "Test private.person", "password_hash",
            "DO_NOT_RETURN_FEATURES", "user_id", "request_date", "profile_photo",
        ):
            self.assertNotIn(private_value, payload)
        self.assertNotIn('"user_id"', payload)
        self.assertNotIn('"plan_id"', payload)

    def test_service_does_not_change_database_rows_or_schema(self):
        user_id = add_user("readonly@example.invalid", verified=1)
        plan_id = self._sql(
            "INSERT INTO membership_plans (plan_name, duration_months, price, features) VALUES (?,?,?,?)",
            ("Read Only", 1, 30, None),
        )
        self._sql(
            "INSERT INTO membership_requests (user_id, plan_id, status) VALUES (?,?,?)",
            (user_id, plan_id, "pending"),
        )
        before = self._snapshot()
        result = service.get_admin_summary()
        after = self._snapshot()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(after, before)

    def test_database_error_is_safe_and_does_not_expose_exception_details(self):
        sentinel = "private-db-path-or-query-detail"
        with mock.patch.object(service, "get_db_connection", side_effect=RuntimeError(sentinel)):
            result = service.get_admin_summary()
        self.assertEqual(result, {
            "schema_version": service.SERVICE_VERSION,
            "status": "error",
            "error": {
                "code": "data_unavailable",
                "message": "Aggregated admin data is temporarily unavailable.",
            },
        })
        self.assertNotIn(sentinel, json.dumps(result))

    def test_missing_database_returns_safe_error_without_creating_file_or_logging_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_path = os.path.join(temp_dir, "not-created.db")
            output = io.StringIO()
            with mock.patch.object(Config, "DB_PATH", missing_path), contextlib.redirect_stdout(output):
                result = service.get_admin_summary()
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error"]["code"], "data_unavailable")
            self.assertFalse(os.path.exists(missing_path))
            self.assertNotIn(missing_path, output.getvalue())

    def test_missing_tables_fail_safely_without_modifying_existing_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "empty-existing.db")
            sqlite3.connect(path).close()
            before = Path(path).read_bytes()
            with mock.patch.object(Config, "DB_PATH", path):
                result = service.get_admin_summary()
            after = Path(path).read_bytes()
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error"]["code"], "data_unavailable")
            self.assertEqual(after, before)

    def test_read_only_connection_rejects_schema_writes(self):
        conn = get_db_connection(read_only=True)
        cursor = conn.cursor()
        try:
            with self.assertRaises(sqlite3.OperationalError):
                cursor.execute("CREATE TABLE phase5_write_probe (id INTEGER)")
        finally:
            cursor.close()
            conn.close()
        check_conn = sqlite3.connect(DB_PATH)
        try:
            table_names = {row[0] for row in check_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
        finally:
            check_conn.close()
        self.assertNotIn("phase5_write_probe", table_names)


if __name__ == "__main__":
    import unittest
    unittest.main()

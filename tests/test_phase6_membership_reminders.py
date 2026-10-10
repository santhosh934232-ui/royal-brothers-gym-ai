"""Phase 6 tests: preferences and date-only eligibility, with no delivery."""

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import contextlib
import io
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

import tests.base  # noqa: F401 -- installs isolated test config before app imports
from tests.base import AppTestCase, DB_PATH, add_user
from app.config import Config
from app.config import _reminder_lead_days
from app.services import membership_reminder_service as service

ROOT = Path(__file__).resolve().parents[1]


class MembershipReminderServiceTests(AppTestCase):
    def _sql(self, sql, params=()):
        conn = sqlite3.connect(DB_PATH)
        try:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def _membership(self, user_id, *, status="active", start="2026-01-01", end="2026-01-08"):
        plan_id = self._sql(
            "INSERT INTO membership_plans (plan_name, duration_months, price) VALUES (?,?,?)",
            ("Test Plan", 1, 100),
        )
        return self._sql(
            """INSERT INTO membership_requests
               (user_id, plan_id, status, start_date, end_date)
               VALUES (?,?,?,?,?)""",
            (user_id, plan_id, status, start, end),
        )

    def test_missing_preference_is_disabled_with_deterministic_default_leads(self):
        user_id = add_user("default@example.invalid")
        result = service.get_reminder_preferences(user_id)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["preferences"], {
            "enabled": False, "lead_days": [7, 3, 1],
            "created_at": None, "updated_at": None,
        })

    def test_invalid_and_missing_member_identifiers_are_safe(self):
        for value in (None, 0, -1, True, "1", 900000):
            with self.subTest(user_id=value):
                self.assertEqual(service.get_reminder_preferences(value)["status"], "error")
                self.assertEqual(service.save_reminder_preferences(value, True, [7])["status"], "error")

    def test_allowed_lead_days_are_configurable_with_documented_bounds(self):
        with mock.patch.dict(os.environ, {"MEMBERSHIP_REMINDER_ALLOWED_LEAD_DAYS": "14,7,3,1"}):
            self.assertEqual(_reminder_lead_days(), (14, 7, 3, 1))
        for invalid in ("", "7,7,3,1", "31,7,3,1", "7,3"):
            with self.subTest(value=invalid), mock.patch.dict(
                os.environ, {"MEMBERSHIP_REMINDER_ALLOWED_LEAD_DAYS": invalid}
            ):
                with self.assertRaises(RuntimeError):
                    _reminder_lead_days()

    def test_preference_values_are_validated_and_disabled_may_have_no_leads(self):
        user_id = add_user("validation@example.invalid")
        for enabled, leads in (
            (1, [7]), (False, "7"), (True, []), (True, [7, 7]),
            (True, [0]), (True, [-1]), (True, [30]), (True, ["7"]),
        ):
            with self.subTest(enabled=enabled, leads=leads):
                self.assertEqual(
                    service.save_reminder_preferences(user_id, enabled, leads)["status"], "error"
                )
        result = service.save_reminder_preferences(user_id, False, [])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["preferences"], {"enabled": False, "lead_days": []})

    def test_valid_preferences_are_sorted_and_repeated_save_does_not_duplicate_rows(self):
        user_id = add_user("save@example.invalid")
        first = service.save_reminder_preferences(user_id, True, [1, 7, 3])
        second = service.save_reminder_preferences(user_id, True, [3, 7, 1])
        self.assertEqual(first["preferences"], {"enabled": True, "lead_days": [7, 3, 1]})
        self.assertEqual(second["preferences"], first["preferences"])
        conn = sqlite3.connect(DB_PATH)
        try:
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM membership_reminder_preferences WHERE user_id=?", (user_id,)
            ).fetchone()[0], 1)
            self.assertEqual(conn.execute(
                "SELECT lead_days FROM membership_reminder_lead_times WHERE user_id=? ORDER BY lead_days DESC",
                (user_id,),
            ).fetchall(), [(7,), (3,), (1,)])
        finally:
            conn.close()
        saved = service.get_reminder_preferences(user_id)
        self.assertEqual(saved["preferences"]["enabled"], True)
        self.assertEqual(saved["preferences"]["lead_days"], [7, 3, 1])

    def test_preferences_are_isolated_by_member_and_fk_cleanup_is_configured(self):
        first = add_user("first@example.invalid")
        second = add_user("second@example.invalid")
        self.assertEqual(service.save_reminder_preferences(first, True, [3])["status"], "ok")
        self.assertFalse(service.get_reminder_preferences(second)["preferences"]["enabled"])
        self.assertEqual(service.get_reminder_preferences(first)["preferences"]["lead_days"], [3])
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("DELETE FROM users WHERE id=?", (first,))
            conn.commit()
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM membership_reminder_preferences WHERE user_id=?", (first,)
            ).fetchone()[0], 0)
        finally:
            conn.close()

    def test_pure_evaluation_matches_each_exact_configured_lead_day(self):
        membership = {"membership_request_id": 5, "user_id": 8, "status": "active",
                      "start_date": "2026-01-01", "end_date": "2026-01-08"}
        prefs = {"enabled": True, "lead_days": [7, 3, 1]}
        for lead in (7, 3, 1):
            with self.subTest(lead=lead):
                target = date(2026, 1, 8).toordinal() - lead
                result = service.evaluate_membership_for_reminders(
                    membership, prefs, date.fromordinal(target)
                )
                self.assertEqual(result["reason"], "eligible")
                self.assertEqual(len(result["reminders"]), 1)
                self.assertEqual(result["reminders"][0]["lead_days"], lead)
                self.assertEqual(result["reminders"][0]["expiry_date"], "2026-01-08")

    def test_outside_window_expiry_day_and_day_after_are_distinct(self):
        membership = {"membership_request_id": 2, "user_id": 1, "status": "active",
                      "start_date": "2026-01-01", "end_date": "2026-01-08"}
        prefs = {"enabled": True, "lead_days": [7, 3, 1]}
        not_due = service.evaluate_membership_for_reminders(membership, prefs, date(2026, 1, 2))
        expiry_day = service.evaluate_membership_for_reminders(membership, prefs, date(2026, 1, 8))
        expired = service.evaluate_membership_for_reminders(membership, prefs, date(2026, 1, 9))
        self.assertEqual(not_due["reason"], "not_due")
        self.assertEqual(expiry_day["reason"], "not_due")
        self.assertEqual(expired["reason"], "expired")

    def test_status_date_and_preference_guards(self):
        prefs = {"enabled": True, "lead_days": [7]}
        as_of = date(2026, 1, 1)
        for status, reason in (("pending", "not_active"), ("rejected", "not_active")):
            row = {"membership_request_id": 1, "user_id": 2, "status": status,
                   "start_date": "2026-01-01", "end_date": "2026-01-08"}
            self.assertEqual(service.evaluate_membership_for_reminders(row, prefs, as_of)["reason"], reason)
        row = {"membership_request_id": 1, "user_id": 2, "status": "active",
               "start_date": "2026-01-02", "end_date": "2026-01-08"}
        self.assertEqual(service.evaluate_membership_for_reminders(row, prefs, as_of)["reason"], "not_started")
        row["start_date"] = "bad-date"
        self.assertEqual(service.evaluate_membership_for_reminders(row, prefs, as_of)["reason"], "invalid_membership_dates")
        row["start_date"] = "2026-01-01"
        row["end_date"] = "2025-12-31"
        self.assertEqual(service.evaluate_membership_for_reminders(row, prefs, as_of)["reason"], "invalid_membership_dates")
        row["end_date"] = "2026-01-08"
        self.assertEqual(service.evaluate_membership_for_reminders(row, {"enabled": False, "lead_days": [7]}, as_of)["reason"], "reminders_disabled")
        self.assertEqual(service.evaluate_membership_for_reminders(row, prefs, "2026-01-01T00:00:00")["reason"], "invalid_reference_date")

    def test_datetime_reference_uses_its_own_calendar_date(self):
        row = {"membership_request_id": 1, "user_id": 2, "status": "active",
               "start_date": "2026-01-01", "end_date": "2026-01-08"}
        result = service.evaluate_membership_for_reminders(
            row, {"enabled": True, "lead_days": [7]},
            datetime(2026, 1, 1, 23, 59, tzinfo=timezone.utc),
        )
        self.assertTrue(result["eligible"])

    def test_database_eligibility_requires_opt_in_and_returns_ids_only(self):
        user_id = add_user("private.member@example.invalid")
        req_id = self._membership(user_id)
        self.assertEqual(service.get_eligible_reminders(date(2026, 1, 1))["reminders"], [])
        service.save_reminder_preferences(user_id, True, [7, 3, 1])
        result = service.get_eligible_reminders(date(2026, 1, 1))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["reminders"], [{
            "user_id": user_id, "membership_request_id": req_id,
            "expiry_date": "2026-01-08", "lead_days": 7, "reminder_date": "2026-01-01",
        }])
        serialized = str(result)
        self.assertNotIn("private.member", serialized)
        self.assertNotIn("email", serialized)

    def test_pending_rejected_expired_invalid_and_disabled_rows_are_excluded(self):
        user_ids = [add_user(f"state{i}@example.invalid") for i in range(5)]
        rows = [
            ("pending", "2026-01-01", "2026-01-08"),
            ("rejected", "2026-01-01", "2026-01-08"),
            ("active", "2025-01-01", "2025-01-08"),
            ("active", "not-a-date", "2026-01-08"),
            ("active", "2026-01-01", "2026-01-08"),
        ]
        for user_id, (status, start, end) in zip(user_ids, rows):
            self._membership(user_id, status=status, start=start, end=end)
            service.save_reminder_preferences(user_id, user_id == user_ids[-1], [7])
        result = service.get_eligible_reminders(date(2026, 1, 1))
        self.assertEqual([r["user_id"] for r in result["reminders"]], [user_ids[-1]])

    def test_overlapping_current_active_memberships_are_excluded_as_ambiguous(self):
        user_id = add_user("overlap@example.invalid")
        self._membership(user_id, end="2026-01-08")
        self._membership(user_id, end="2026-01-15")
        service.save_reminder_preferences(user_id, True, [7])
        self.assertEqual(service.get_eligible_reminders(date(2026, 1, 1))["reminders"], [])

    def test_no_duplicate_results_and_repeat_eligibility_is_not_marked_sent(self):
        user_id = add_user("repeat@example.invalid")
        req_id = self._membership(user_id)
        service.save_reminder_preferences(user_id, True, [7, 3, 1])
        first = service.get_eligible_reminders(date(2026, 1, 1))
        second = service.get_eligible_reminders(date(2026, 1, 1))
        self.assertEqual(first, second)
        self.assertEqual(len(first["reminders"]), 1)
        self.assertEqual(first["reminders"][0]["membership_request_id"], req_id)
        conn = sqlite3.connect(DB_PATH)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM membership_requests").fetchone()[0], 1)
        finally:
            conn.close()

    def test_preference_and_eligibility_database_failures_are_safe(self):
        sentinel = "private database detail"
        with mock.patch.object(service, "get_db_connection", side_effect=RuntimeError(sentinel)):
            pref = service.get_reminder_preferences(1)
            saved = service.save_reminder_preferences(1, True, [7])
            eligible = service.get_eligible_reminders(date(2026, 1, 1))
        for result in (pref, saved, eligible):
            self.assertEqual(result["status"], "error")
            self.assertNotIn(sentinel, str(result))

    def test_missing_database_is_not_created_by_preference_or_eligibility_reads(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = str(Path(temp_dir) / "missing.db")
            output = io.StringIO()
            with mock.patch.object(Config, "DB_PATH", missing), contextlib.redirect_stdout(output):
                pref = service.get_reminder_preferences(1)
                eligible = service.get_eligible_reminders(date(2026, 1, 1))
            self.assertEqual(pref["status"], "error")
            self.assertEqual(eligible["status"], "error")
            self.assertFalse(os.path.exists(missing))
            self.assertNotIn(missing, output.getvalue())

    def test_eligibility_is_read_only_and_makes_no_email_or_gemini_calls(self):
        user_id = add_user("readonly@example.invalid")
        self._membership(user_id)
        service.save_reminder_preferences(user_id, True, [7])
        conn = sqlite3.connect(DB_PATH)
        try:
            before = {
                table: conn.execute(f'SELECT * FROM "{table}" ORDER BY 1').fetchall()
                for table in ("membership_requests", "membership_reminder_preferences",
                              "membership_reminder_lead_times")
            }
        finally:
            conn.close()
        with mock.patch("app.mail.send") as send_mail, \
             mock.patch("app.services.gemini_service.generate_text") as generate:
            result = service.get_eligible_reminders(date(2026, 1, 1))
        self.assertEqual(result["status"], "ok")
        send_mail.assert_not_called()
        generate.assert_not_called()
        conn = sqlite3.connect(DB_PATH)
        try:
            after = {
                table: conn.execute(f'SELECT * FROM "{table}" ORDER BY 1').fetchall()
                for table in ("membership_requests", "membership_reminder_preferences",
                              "membership_reminder_lead_times")
            }
        finally:
            conn.close()
        self.assertEqual(after, before)

    def test_schema_database_constraints_enforce_allowed_unique_lead_values(self):
        user_id = add_user("constraint@example.invalid")
        service.save_reminder_preferences(user_id, True, [7])
        conn = sqlite3.connect(DB_PATH)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO membership_reminder_lead_times (user_id, lead_days) VALUES (?,?)",
                    (user_id, 7),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO membership_reminder_lead_times (user_id, lead_days) VALUES (?,?)",
                    (user_id, 31),
                )
        finally:
            conn.close()


class ReminderMigrationTests(unittest.TestCase):
    def test_migration_creates_tables_preserves_rows_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "legacy.db"
            full_schema = (ROOT / "schema" / "schema.sql").read_text(encoding="utf-8")
            marker = "-- ---------- MEMBERSHIP REMINDER PREFERENCES (Phase 6) ----------"
            self.assertIn(marker, full_schema)
            legacy_schema = full_schema.split(marker, 1)[0]
            conn = sqlite3.connect(db_path)
            conn.executescript(legacy_schema)
            conn.execute(
                "INSERT INTO users (full_name,email,password_hash,gender,is_verified) VALUES (?,?,?,?,?)",
                ("Migration Test", "migration@example.invalid", "hash", "other", 1),
            )
            conn.commit()
            before_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            conn.close()

            command = [sys.executable, str(ROOT / "scripts" / "migrate_db.py"), "--db", str(db_path)]
            first = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertIn("membership_reminder_preferences", first.stdout)
            self.assertTrue(list(Path(temp_dir).glob("legacy.db.backup-*")))

            conn = sqlite3.connect(db_path)
            try:
                tables = {row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )}
                self.assertIn("membership_reminder_preferences", tables)
                self.assertIn("membership_reminder_lead_times", tables)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], before_count)
            finally:
                conn.close()

            second = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertIn("Nothing to do", second.stdout)


if __name__ == "__main__":
    unittest.main()

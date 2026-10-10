"""Phase 8 preference UI/API and explicit scheduler integration tests.

All tests use the shared temporary SQLite database and fake mail settings.
No real SMTP or external service is used.
"""

import contextlib
import io
import json
import os
import sqlite3
import tempfile
from datetime import date
from unittest import mock

import tests.base  # noqa: F401 -- installs isolated test config before app imports
from tests.base import AppTestCase, DB_PATH, add_user
from app.config import Config
from app.routes import membership_routes
from scripts import run_membership_reminders as reminder_runner

PREFERENCES_URL = "/api/membership/reminder-preferences"


class MemberReminderPreferenceApiTests(AppTestCase):
    def _sql(self, sql, params=()):
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def _same_origin(self):
        return {"Origin": "http://localhost"}

    def test_preferences_require_member_session(self):
        client = self.app.test_client()
        self.assertEqual(client.get(PREFERENCES_URL).status_code, 401)
        self.assertEqual(client.put(PREFERENCES_URL, json={
            "enabled": True, "lead_days": [7],
        }, headers=self._same_origin()).status_code, 401)

    def test_get_returns_disabled_defaults_without_creating_a_row(self):
        user_id, client = self.member("defaults-phase8@example.invalid")
        response = client.get(PREFERENCES_URL)
        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        self.assertEqual(payload["preferences"], {"enabled": False, "lead_days": [7, 3, 1]})
        self.assertEqual(payload["supported_lead_days"], [7, 3, 1])
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        conn = sqlite3.connect(DB_PATH)
        try:
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) FROM membership_reminder_preferences WHERE user_id=?", (user_id,),
            ).fetchone()[0], 0)
        finally:
            conn.close()

    def test_save_is_persisted_and_get_returns_database_values(self):
        user_id, client = self.member("save-phase8@example.invalid")
        response = client.put(PREFERENCES_URL, json={
            "enabled": True, "lead_days": [1, 7],
        }, headers=self._same_origin())
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["preferences"], {"enabled": True, "lead_days": [7, 1]})
        saved = client.get(PREFERENCES_URL)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.get_json()["preferences"], {"enabled": True, "lead_days": [7, 1]})

        conn = sqlite3.connect(DB_PATH)
        try:
            self.assertEqual(conn.execute(
                "SELECT enabled FROM membership_reminder_preferences WHERE user_id=?", (user_id,),
            ).fetchone(), (1,))
            self.assertEqual(conn.execute(
                "SELECT lead_days FROM membership_reminder_lead_times WHERE user_id=? ORDER BY lead_days DESC",
                (user_id,),
            ).fetchall(), [(7,), (1,)])
        finally:
            conn.close()

    def test_each_member_can_only_read_or_change_their_own_preferences(self):
        user_a, client_a = self.member("member-a-phase8@example.invalid")
        user_b = add_user("member-b-phase8@example.invalid")
        client_b = self.login("member-b-phase8@example.invalid")
        saved_b = client_b.put(PREFERENCES_URL, json={
            "enabled": True, "lead_days": [3],
        }, headers=self._same_origin())
        self.assertEqual(saved_b.status_code, 200)

        own = client_a.get(PREFERENCES_URL + f"?user_id={user_b}")
        self.assertEqual(own.status_code, 200)
        self.assertEqual(own.get_json()["preferences"], {"enabled": False, "lead_days": [7, 3, 1]})
        forbidden_target = client_a.put(PREFERENCES_URL, json={
            "user_id": user_b, "enabled": True, "lead_days": [1],
        }, headers=self._same_origin())
        self.assertEqual(forbidden_target.status_code, 400)
        self.assertEqual(client_b.get(PREFERENCES_URL).get_json()["preferences"], {
            "enabled": True, "lead_days": [3],
        })
        self.assertGreater(user_a, 0)

    def test_invalid_json_fields_and_lead_choices_are_rejected(self):
        _, client = self.member("invalid-phase8@example.invalid")
        bad_payloads = (
            {"enabled": "true", "lead_days": [7]},
            {"enabled": True, "lead_days": []},
            {"enabled": True, "lead_days": [7, 7]},
            {"enabled": True, "lead_days": [30]},
            {"enabled": False, "lead_days": ["7"]},
            {"enabled": False, "lead_days": [True]},
            {"enabled": False, "lead_days": [], "extra": "field"},
        )
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                response = client.put(PREFERENCES_URL, json=payload, headers=self._same_origin())
                self.assertEqual(response.status_code, 400, response.get_json())
                self.assertEqual(response.get_json()["error"]["code"], "invalid_preferences")

        malformed = client.put(PREFERENCES_URL, data="{", content_type="application/json", headers=self._same_origin())
        self.assertEqual(malformed.status_code, 400)
        wrong_type = client.put(PREFERENCES_URL, data="{}", content_type="text/plain", headers=self._same_origin())
        self.assertEqual(wrong_type.status_code, 415)
        oversized = client.put(
            PREFERENCES_URL,
            data=b"x" * (membership_routes.REMINDER_PREFERENCES_MAX_BYTES + 1),
            content_type="application/json",
            headers=self._same_origin(),
        )
        self.assertEqual(oversized.status_code, 413)

    def test_preference_update_requires_explicit_exact_same_origin(self):
        _, client = self.member("origin-phase8@example.invalid")
        payload = {"enabled": True, "lead_days": [7]}
        missing = client.put(PREFERENCES_URL, json=payload)
        attacker = client.put(PREFERENCES_URL, json=payload, headers={"Origin": "https://attacker.invalid"})
        wrong_scheme = client.put(PREFERENCES_URL, json=payload, headers={"Origin": "https://localhost"})
        wrong_port = client.put(PREFERENCES_URL, json=payload, headers={"Origin": "http://localhost:5000"})
        same = client.put(PREFERENCES_URL, json=payload, headers=self._same_origin())
        self.assertEqual(missing.status_code, 403)
        self.assertEqual(attacker.status_code, 403)
        self.assertEqual(wrong_scheme.status_code, 403)
        self.assertEqual(wrong_port.status_code, 403)
        self.assertEqual(same.status_code, 200, same.get_json())

    def test_preference_responses_do_not_expose_member_identity(self):
        _, client = self.member("privacy-phase8@example.invalid")
        response = client.get(PREFERENCES_URL)
        body = response.get_data(as_text=True)
        self.assertNotIn("privacy-phase8", body)
        self.assertNotIn("user_id", body)
        self.assertNotIn("email", body)

    def test_profile_page_serves_the_preferences_panel_and_client_script(self):
        response = self.app.test_client().get("/profile.html")
        try:
            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
        finally:
            response.close()
        for needle in (
            'id="membershipReminderSection"',
            'id="reminderEnabled"',
            'id="reminderLeadTimeOptions"',
            "membership-reminders.js",
        ):
            self.assertIn(needle, html)
        script = self.app.test_client().get("/membership-reminders.js")
        try:
            self.assertEqual(script.status_code, 200)
            self.assertIn("/api/membership/reminder-preferences", script.get_data(as_text=True))
        finally:
            script.close()

    def test_existing_member_dashboard_and_membership_routes_still_work(self):
        _, client = self.member("dashboard-phase8@example.invalid")
        dashboard = client.get("/api/dashboard")
        self.assertEqual(dashboard.status_code, 200, dashboard.get_json())
        self.assertTrue(dashboard.get_json()["success"])
        self.assertEqual(client.get("/api/membership/my-request").status_code, 200)

    def test_normal_app_requests_never_invoke_delivery_or_email(self):
        _, client = self.member("no-autosend-phase8@example.invalid")
        with mock.patch(
            "app.services.membership_reminder_delivery_service.process_membership_reminders"
        ) as process, mock.patch("app.services.email_service.send_email") as send_email, \
             mock.patch("app.services.membership_reminder_delivery_service.send_email") as delivery_email:
            from app import create_app
            created_app = create_app()
            static_page = created_app.test_client().get("/profile.html")
            static_page.close()
            page = self.app.test_client().get("/profile.html")
            page.close()
            client.get(PREFERENCES_URL)
            client.put(PREFERENCES_URL, json={
                "enabled": True, "lead_days": [7],
            }, headers=self._same_origin())
        process.assert_not_called()
        send_email.assert_not_called()
        delivery_email.assert_not_called()


class ReminderSchedulerCommandTests(AppTestCase):
    def _sql(self, sql, params=()):
        conn = sqlite3.connect(DB_PATH)
        try:
            cursor = conn.execute(sql, params)
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def _add_due_reminder(self, user_id):
        plan_id = self._sql(
            "INSERT INTO membership_plans (plan_name, duration_months, price) VALUES (?,?,?)",
            ("Phase 8 test plan", 1, 100),
        )
        self._sql(
            "INSERT INTO membership_requests (user_id, plan_id, status, start_date, end_date) VALUES (?,?,?,?,?)",
            (user_id, plan_id, "active", "2026-01-01", "2026-01-08"),
        )
        from app.services.membership_reminder_service import save_reminder_preferences
        self.assertEqual(save_reminder_preferences(user_id, True, [7])["status"], "ok")

    def _table_counts(self):
        conn = sqlite3.connect(DB_PATH)
        try:
            tables = [row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )]
            return {table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] for table in tables}
        finally:
            conn.close()

    def test_dry_run_reports_exact_date_eligibility_without_delivery_or_database_writes(self):
        user_id = add_user("dryrun-phase8@example.invalid")
        self._add_due_reminder(user_id)
        before = self._table_counts()
        with mock.patch.object(reminder_runner, "_create_app", return_value=self.app), \
             mock.patch.object(reminder_runner, "_process_reminders") as process, \
             mock.patch("app.services.email_service.send_email") as send_email:
            report, exit_code = reminder_runner.run(dry_run=True, as_of=date(2026, 1, 1))
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["status"], "dry_run")
        self.assertEqual(report["summary"], {
            "eligible": 1, "attempted": 0, "sent": 0, "failed": 0,
            "skipped": 0, "uncertain": 0, "errors": 0,
        })
        self.assertNotIn("user_id", json.dumps(report))
        self.assertEqual(before, self._table_counts())
        process.assert_not_called()
        send_email.assert_not_called()

    def test_repeated_manual_runs_use_phase7_persistent_deduplication(self):
        user_id = add_user("repeat-cli-phase8@example.invalid")
        self._add_due_reminder(user_id)
        with mock.patch.object(reminder_runner, "_create_app", return_value=self.app), \
             mock.patch("app.services.membership_reminder_delivery_service.send_email") as send_email:
            first, first_code = reminder_runner.run(dry_run=False, as_of=date(2026, 1, 1))
            second, second_code = reminder_runner.run(dry_run=False, as_of=date(2026, 1, 1))
        self.assertEqual(first_code, 0)
        self.assertEqual(first["summary"]["sent"], 1)
        self.assertEqual(first["summary"]["attempted"], 1)
        self.assertEqual(second_code, 0)
        self.assertEqual(second["summary"]["skipped"], 1)
        self.assertEqual(second["summary"]["sent"], 0)
        self.assertEqual(send_email.call_count, 1)
        conn = sqlite3.connect(DB_PATH)
        try:
            self.assertEqual(conn.execute(
                "SELECT status, attempt_count FROM membership_reminder_deliveries",
            ).fetchall(), [("sent", 1)])
            self.assertEqual(conn.execute(
                "SELECT status FROM membership_reminder_delivery_attempts",
            ).fetchall(), [("sent",)])
        finally:
            conn.close()

    def test_dry_run_database_errors_are_safe_and_do_not_echo_private_details(self):
        with mock.patch.object(reminder_runner, "_create_app", return_value=self.app), \
             mock.patch(
                 "app.services.membership_reminder_service.get_db_connection",
                 side_effect=RuntimeError("/private/path/and-secret"),
             ):
            report, exit_code = reminder_runner.run(dry_run=True, as_of=date(2026, 1, 1))
        self.assertEqual(exit_code, 1)
        self.assertEqual(report, {"status": "error", "code": "data_unavailable"})
        self.assertNotIn("private", json.dumps(report))
        self.assertNotIn("secret", json.dumps(report))

    def test_dry_run_missing_database_is_not_created_and_report_is_safe(self):
        with tempfile.TemporaryDirectory(prefix="phase8-missing-db-") as directory:
            missing_path = os.path.join(directory, "not-created.sqlite3")
            with mock.patch.object(Config, "DB_PATH", missing_path), \
                 mock.patch.object(reminder_runner, "_create_app", return_value=self.app), \
                 contextlib.redirect_stdout(io.StringIO()) as captured:
                report, exit_code = reminder_runner.run(dry_run=True, as_of=date(2026, 1, 1))
            self.assertEqual(exit_code, 1)
            self.assertEqual(report, {"status": "error", "code": "data_unavailable"})
            self.assertFalse(os.path.exists(missing_path))
            self.assertEqual(captured.getvalue(), "")

    def test_real_run_requires_smtp_configuration_before_app_creation(self):
        with mock.patch.dict(os.environ, {"SECRET_KEY": "test"}, clear=True), \
             mock.patch.object(reminder_runner, "load_dotenv"), \
             mock.patch.object(reminder_runner, "_create_app") as create_app:
            report, exit_code = reminder_runner.run(dry_run=False, as_of=date(2026, 1, 1))
        self.assertEqual(exit_code, 2)
        self.assertEqual(report["code"], "smtp_configuration_missing")
        self.assertIn("MAIL_USERNAME", report["missing_settings"])
        self.assertIn("MAIL_PASSWORD", report["missing_settings"])
        create_app.assert_not_called()
        self.assertNotIn("test", json.dumps(report))

    def test_dry_run_does_not_require_smtp_secrets(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(reminder_runner, "load_dotenv"), \
             mock.patch.object(reminder_runner, "_create_app", return_value=self.app), \
             mock.patch.object(reminder_runner, "_get_eligible_reminders", return_value={
                 "status": "ok", "as_of": "2026-01-01", "reminders": [],
             }):
            report, exit_code = reminder_runner.run(dry_run=True, as_of=date(2026, 1, 1))
            self.assertEqual(os.environ["MAIL_USERNAME"], reminder_runner._DRY_RUN_VALUES["MAIL_USERNAME"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(report["status"], "dry_run")
        self.assertEqual(report["summary"]["eligible"], 0)

    def test_delivery_report_uses_service_counts_and_returns_nonzero_on_failures(self):
        service_result = {
            "status": "ok", "as_of": "2026-01-01",
            "summary": {"eligible_candidates": 4, "sent": 1, "failed": 1,
                        "skipped": 1, "uncertain": 1, "errors": 0},
        }
        with mock.patch.object(reminder_runner, "_create_app", return_value=self.app), \
             mock.patch.object(reminder_runner, "_process_reminders", return_value=service_result) as process:
            report, exit_code = reminder_runner.run(dry_run=False, as_of=date(2026, 1, 1))
        self.assertEqual(exit_code, 1)
        self.assertEqual(report["status"], "partial_failure")
        self.assertEqual(report["summary"], {
            "eligible_candidates": 4, "attempted": 3, "sent": 1, "failed": 1,
            "skipped": 1, "uncertain": 1, "errors": 0,
        })
        process.assert_called_once_with(as_of=date(2026, 1, 1))

    def test_invalid_reference_dates_are_rejected_by_argument_parser(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                reminder_runner.main(["--as-of", "2026-02-30", "--dry-run"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    import unittest
    unittest.main()

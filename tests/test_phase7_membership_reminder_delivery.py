"""Phase 7 delivery tests: temporary SQLite and mocked Flask-Mail only."""

import sqlite3
import smtplib
import threading
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

import tests.base  # noqa: F401 -- isolated test secrets/DB before app import
from tests.base import AppTestCase, DB_PATH, add_user
from app.services import membership_reminder_delivery_service as delivery
from app.services import membership_reminder_service as preferences


class ReminderDeliveryTests(AppTestCase):
    def _sql(self, query, params=()):
        conn = sqlite3.connect(DB_PATH)
        try:
            cur = conn.execute(query, params)
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def _member_and_membership(self, *, email="member@example.invalid", enabled=True,
                               leads=(7, 3, 1), start="2026-01-01", expiry="2026-01-08"):
        user_id = add_user(email)
        plan_id = self._sql(
            "INSERT INTO membership_plans (plan_name, duration_months, price) VALUES (?,?,?)",
            ("Monthly", 1, 100),
        )
        request_id = self._sql(
            """INSERT INTO membership_requests
               (user_id, plan_id, status, start_date, end_date)
               VALUES (?,?, 'active', ?, ?)""",
            (user_id, plan_id, start, expiry),
        )
        if enabled:
            saved = preferences.save_reminder_preferences(user_id, True, list(leads))
            self.assertEqual(saved["status"], "ok", saved)
        return user_id, request_id

    def _run(self, as_of, now=None):
        with self.app.app_context():
            return delivery.process_membership_reminders(as_of=as_of, now=now)

    def _table(self, table):
        conn = sqlite3.connect(DB_PATH)
        try:
            return conn.execute(f'SELECT * FROM "{table}" ORDER BY 1').fetchall()
        finally:
            conn.close()

    def test_opted_in_eligible_member_sends_and_records_attempt(self):
        user_id, request_id = self._member_and_membership()
        with mock.patch.object(delivery, "send_email") as send:
            result = self._run(date(2026, 1, 1), datetime(2026, 1, 1, 8))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["summary"]["sent"], 1)
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["status"], "sent")
        self.assertEqual(result["results"][0]["membership_request_id"], request_id)
        send.assert_called_once()
        address, subject, body = send.call_args.args
        self.assertEqual(address, "member@example.invalid")
        self.assertIn("2026-01-08", subject)
        self.assertIn("08 January 2026", body)
        self.assertNotIn(address, str(result))
        rows = self._table("membership_reminder_deliveries")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1:6], (user_id, request_id, "2026-01-08", 7, "2026-01-01"))
        self.assertEqual(rows[0][7], "sent")
        attempts = self._table("membership_reminder_delivery_attempts")
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0][2:4], (1, "sent"))

    def test_disabled_preferences_and_noneligible_date_do_not_send(self):
        self._member_and_membership(enabled=False)
        with mock.patch.object(delivery, "send_email") as send:
            disabled = self._run(date(2026, 1, 1), datetime(2026, 1, 1, 8))
            self.assertEqual(disabled["summary"]["eligible_candidates"], 0)
            self.assertEqual(self._table("membership_reminder_deliveries"), [])

        self._member_and_membership(email="notdue@example.invalid")
        with mock.patch.object(delivery, "send_email") as send:
            not_due = self._run(date(2026, 1, 2), datetime(2026, 1, 2, 8))
            self.assertEqual(not_due["summary"]["eligible_candidates"], 0)
            send.assert_not_called()
        self.assertEqual(self._table("membership_reminder_deliveries"), [])

    def test_invalid_email_is_recorded_terminally_without_smtp_or_private_detail(self):
        user_id, _ = self._member_and_membership(email="bad-address")
        self._sql("UPDATE users SET email = ? WHERE id = ?", ("not-an-email", user_id))
        with mock.patch.object(delivery, "send_email") as send:
            result = self._run(date(2026, 1, 1), datetime(2026, 1, 1, 8))
        send.assert_not_called()
        self.assertEqual(result["summary"]["failed"], 1)
        self.assertEqual(result["results"][0]["code"], "invalid_email")
        self.assertNotIn("not-an-email", str(result))
        row = self._table("membership_reminder_deliveries")[0]
        self.assertEqual(row[7], "failed")
        self.assertEqual(row[8], 1)
        self.assertEqual(row[9], 0)
        self.assertEqual(row[17], "invalid_email")
        self.assertEqual(self._table("membership_reminder_delivery_attempts")[0][3], "failed")

    def test_successful_reminder_is_not_sent_again_on_repeated_run(self):
        self._member_and_membership()
        with mock.patch.object(delivery, "send_email") as send:
            first = self._run(date(2026, 1, 1), datetime(2026, 1, 1, 8))
            second = self._run(date(2026, 1, 1), datetime(2026, 1, 1, 9))
        self.assertEqual(first["summary"]["sent"], 1)
        self.assertEqual(second["summary"]["skipped"], 1)
        self.assertEqual(second["results"][0]["code"], "already_sent")
        send.assert_called_once()
        self.assertEqual(len(self._table("membership_reminder_deliveries")), 1)
        self.assertEqual(len(self._table("membership_reminder_delivery_attempts")), 1)

    def test_each_selected_lead_time_has_its_own_identity(self):
        user_id, request_id = self._member_and_membership(leads=(7, 3), expiry="2026-01-15")
        with mock.patch.object(delivery, "send_email") as send:
            first = self._run(date(2026, 1, 8), datetime(2026, 1, 8, 8))
            second = self._run(date(2026, 1, 12), datetime(2026, 1, 12, 8))
        self.assertEqual(first["results"][0]["lead_days"], 7)
        self.assertEqual(second["results"][0]["lead_days"], 3)
        self.assertEqual(send.call_count, 2)
        rows = self._table("membership_reminder_deliveries")
        self.assertEqual(len(rows), 2)
        self.assertEqual({row[4] for row in rows}, {7, 3})
        self.assertTrue(all(row[1] == user_id and row[2] == request_id for row in rows))

    def test_changed_expiry_creates_a_distinct_reminder_not_a_false_duplicate(self):
        user_id, request_id = self._member_and_membership(expiry="2026-01-15", leads=(7,))
        with mock.patch.object(delivery, "send_email") as send:
            first = self._run(date(2026, 1, 8), datetime(2026, 1, 8, 8))
            self._sql("UPDATE membership_requests SET end_date = ? WHERE id = ?",
                      ("2026-01-22", request_id))
            second = self._run(date(2026, 1, 15), datetime(2026, 1, 15, 8))
        self.assertEqual(first["summary"]["sent"], 1)
        self.assertEqual(second["summary"]["sent"], 1)
        send.assert_has_calls([
            mock.call("member@example.invalid", mock.ANY, mock.ANY),
            mock.call("member@example.invalid", mock.ANY, mock.ANY),
        ])
        rows = self._table("membership_reminder_deliveries")
        self.assertEqual(len(rows), 2)
        self.assertEqual({row[3] for row in rows}, {"2026-01-15", "2026-01-22"})
        self.assertEqual({row[1] for row in rows}, {user_id})

    def test_later_nonoverlapping_membership_has_independent_delivery_identity(self):
        user_id, first_request = self._member_and_membership(expiry="2026-01-08", leads=(7,))
        with mock.patch.object(delivery, "send_email") as send:
            first = self._run(date(2026, 1, 1), datetime(2026, 1, 1, 8))
            plan_id = self._sql(
                "INSERT INTO membership_plans (plan_name, duration_months, price) VALUES (?,?,?)",
                ("Renewal", 1, 100),
            )
            second_request = self._sql(
                """INSERT INTO membership_requests
                   (user_id, plan_id, status, start_date, end_date)
                   VALUES (?,?, 'active', ?, ?)""",
                (user_id, plan_id, "2026-01-09", "2026-01-16"),
            )
            second = self._run(date(2026, 1, 9), datetime(2026, 1, 9, 8))
        self.assertEqual(first["summary"]["sent"], 1)
        self.assertEqual(second["summary"]["sent"], 1)
        self.assertEqual(send.call_count, 2)
        rows = self._table("membership_reminder_deliveries")
        self.assertEqual({row[2] for row in rows}, {first_request, second_request})
        self.assertTrue(all(row[1] == user_id for row in rows))

    def test_blank_email_is_treated_as_missing_without_smtp(self):
        user_id, _ = self._member_and_membership()
        self._sql("UPDATE users SET email = '' WHERE id = ?", (user_id,))
        with mock.patch.object(delivery, "send_email") as send:
            result = self._run(date(2026, 1, 1), datetime(2026, 1, 1, 8))
        send.assert_not_called()
        self.assertEqual(result["results"][0]["code"], "invalid_email")
        self.assertEqual(self._table("membership_reminder_deliveries")[0][7], "failed")

    def test_overlapping_memberships_do_not_send(self):
        user_id, _ = self._member_and_membership(expiry="2026-01-08", leads=(7,))
        plan_id = self._sql(
            "INSERT INTO membership_plans (plan_name, duration_months, price) VALUES (?,?,?)",
            ("Second", 1, 200),
        )
        self._sql(
            "INSERT INTO membership_requests (user_id, plan_id, status, start_date, end_date) VALUES (?,?,'active',?,?)",
            (user_id, plan_id, "2026-01-01", "2026-02-01"),
        )
        with mock.patch.object(delivery, "send_email") as send:
            result = self._run(date(2026, 1, 1), datetime(2026, 1, 1, 8))
        send.assert_not_called()
        self.assertEqual(result["summary"]["eligible_candidates"], 0)
        self.assertEqual(self._table("membership_reminder_deliveries"), [])

    def test_transient_smtp_failure_records_safe_history_and_retries_after_backoff(self):
        self._member_and_membership()
        private = "raw smtp failure details for example.invalid"
        first_time = datetime(2026, 1, 1, 8)
        with mock.patch.object(delivery, "send_email",
                               side_effect=[TimeoutError(private), None]) as send:
            failed = self._run(date(2026, 1, 1), first_time)
            early = self._run(date(2026, 1, 1), first_time + timedelta(minutes=4))
            sent = self._run(date(2026, 1, 1), first_time + timedelta(minutes=5))
        self.assertEqual(failed["summary"]["failed"], 1)
        self.assertEqual(failed["results"][0]["code"], "smtp_delivery_failed")
        self.assertNotIn(private, str(failed))
        self.assertEqual(early["results"][0]["code"], "retry_not_due")
        self.assertEqual(sent["summary"]["sent"], 1)
        self.assertEqual(send.call_count, 2)
        delivery_row = self._table("membership_reminder_deliveries")[0]
        self.assertEqual(delivery_row[7], "sent")
        self.assertEqual(delivery_row[8], 2)
        attempts = self._table("membership_reminder_delivery_attempts")
        self.assertEqual([(r[2], r[3]) for r in attempts], [(1, "failed"), (2, "sent")])
        self.assertEqual(attempts[0][6], "smtp_delivery_failed")
        self.assertLessEqual(len(attempts[0][7]), 160)

    def test_retry_queue_allows_bounded_retry_next_date_but_not_after_expiry(self):
        self._member_and_membership(expiry="2026-01-08", leads=(1,))
        # Lead-1 target is Jan 7; the allowed retry date is Jan 8 (expiry).
        first = datetime(2026, 1, 7, 8)
        with mock.patch.object(delivery, "send_email", side_effect=[TimeoutError(), None]) as send:
            failed = self._run(date(2026, 1, 7), first)
            retried = self._run(date(2026, 1, 8), first + timedelta(days=1))
            after_expiry = self._run(date(2026, 1, 9), first + timedelta(days=2))
        self.assertEqual(failed["summary"]["failed"], 1)
        self.assertEqual(retried["summary"]["sent"], 1)
        self.assertEqual(after_expiry["summary"]["eligible_candidates"], 0)
        self.assertEqual(send.call_count, 2)

    def test_retry_exhaustion_stops_after_three_total_attempts(self):
        self._member_and_membership()
        first = datetime(2026, 1, 1, 8)
        run_times = [first, first + timedelta(minutes=5), first + timedelta(minutes=20)]
        with mock.patch.object(delivery, "send_email", side_effect=TimeoutError("hidden")) as send:
            for attempt_at in run_times:
                result = self._run(date(2026, 1, 1), attempt_at)
                self.assertEqual(result["summary"]["failed"], 1)
            exhausted = self._run(date(2026, 1, 2), first + timedelta(days=1))
        self.assertEqual(send.call_count, 3)
        self.assertEqual(exhausted["summary"]["eligible_candidates"], 0)
        row = self._table("membership_reminder_deliveries")[0]
        self.assertEqual(row[8], 3)
        self.assertEqual(row[9], 0)
        self.assertEqual(len(self._table("membership_reminder_delivery_attempts")), 3)

    def test_authentication_failure_is_terminal_and_safe(self):
        self._member_and_membership()
        smtp_error = smtplib.SMTPAuthenticationError(535, b"sensitive server response")
        with mock.patch.object(delivery, "send_email", side_effect=smtp_error) as send:
            failed = self._run(date(2026, 1, 1), datetime(2026, 1, 1, 8))
            again = self._run(date(2026, 1, 1), datetime(2026, 1, 1, 9))
        self.assertEqual(failed["results"][0]["code"], "smtp_authentication_failed")
        self.assertNotIn("sensitive server response", str(failed))
        self.assertEqual(again["results"][0]["code"], "retry_exhausted")
        self.assertEqual(send.call_count, 1)
        self.assertEqual(self._table("membership_reminder_deliveries")[0][9], 0)

    def test_database_enforced_unique_key_and_transactional_claim_block_concurrent_duplicate(self):
        self._member_and_membership()
        send_started = threading.Event()
        release_send = threading.Event()
        errors = []

        def blocked_sender(*_args):
            send_started.set()
            if not release_send.wait(5):
                raise TimeoutError("test sender release timed out")

        def first_run():
            try:
                with self.app.app_context():
                    return delivery.process_membership_reminders(
                        date(2026, 1, 1), datetime(2026, 1, 1, 8)
                    )
            except Exception as exc:  # surfaced in the main test thread
                errors.append(type(exc).__name__)
                raise

        with mock.patch.object(delivery, "send_email", side_effect=blocked_sender) as send:
            with ThreadPoolExecutor(max_workers=2) as pool:
                future = pool.submit(first_run)
                self.assertTrue(send_started.wait(5))
                with self.app.app_context():
                    concurrent = delivery.process_membership_reminders(
                        date(2026, 1, 1), datetime(2026, 1, 1, 8, 0, 1)
                    )
                release_send.set()
                first = future.result(timeout=10)
        self.assertEqual(errors, [])
        self.assertEqual(first["summary"]["sent"], 1)
        self.assertEqual(concurrent["summary"]["skipped"], 1)
        self.assertEqual(send.call_count, 1)
        deliveries = self._table("membership_reminder_deliveries")
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0][7], "sent")
        attempts = self._table("membership_reminder_delivery_attempts")
        self.assertEqual(len(attempts), 1)
        conn = sqlite3.connect(DB_PATH)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    """INSERT INTO membership_reminder_deliveries
                       (user_id,membership_request_id,expiry_date,lead_days,reminder_date,
                        retry_until_date,status)
                       VALUES (?,?,?,?,?,?,'failed')""",
                    (deliveries[0][1], deliveries[0][2], deliveries[0][3], deliveries[0][4],
                     deliveries[0][5], deliveries[0][6]),
                )
        finally:
            conn.close()

    def test_smtp_success_but_history_write_failure_is_marked_uncertain(self):
        self._member_and_membership()
        with mock.patch.object(delivery, "send_email") as send, \
             mock.patch.object(delivery, "_finish_attempt", return_value=False):
            result = self._run(date(2026, 1, 1), datetime(2026, 1, 1, 8))
        send.assert_called_once()
        self.assertEqual(result["summary"]["uncertain"], 1)
        self.assertEqual(result["results"][0]["code"], "attempt_history_unavailable")
        row = self._table("membership_reminder_deliveries")[0]
        self.assertEqual(row[7], "pending")

    def test_expired_inflight_lease_is_reported_uncertain_not_failed(self):
        user_id, request_id = self._member_and_membership()
        started = datetime(2026, 1, 1, 7, 0)
        self._sql(
            """INSERT INTO membership_reminder_deliveries
               (user_id,membership_request_id,expiry_date,lead_days,reminder_date,
                retry_until_date,status,attempt_count,retryable,created_at,updated_at,
                first_attempt_at,last_attempt_at,lease_until)
               VALUES (?,?,?,?,?,?,'pending',1,1,?,?,?,?,?)""",
            (user_id, request_id, "2026-01-08", 7, "2026-01-01", "2026-01-02",
             started, started, started, started, started + timedelta(minutes=2)),
        )
        delivery_id = self._table("membership_reminder_deliveries")[0][0]
        self._sql(
            """INSERT INTO membership_reminder_delivery_attempts
               (delivery_id,attempt_number,status,started_at)
               VALUES (?,1,'pending',?)""",
            (delivery_id, started),
        )

        with mock.patch.object(delivery, "send_email") as send:
            result = self._run(date(2026, 1, 1), datetime(2026, 1, 1, 8))

        send.assert_not_called()
        self.assertEqual(result["summary"]["uncertain"], 1)
        self.assertEqual(result["summary"]["failed"], 0)
        self.assertEqual(result["results"][0]["status"], "uncertain")
        self.assertEqual(result["results"][0]["code"], "attempt_interrupted")
        self.assertEqual(self._table("membership_reminder_deliveries")[0][7], "failed")

    def test_history_lookup_database_failure_returns_safe_result_before_smtp(self):
        self._member_and_membership()
        with mock.patch.object(delivery, "get_db_connection", side_effect=RuntimeError("private path")), \
             mock.patch.object(delivery, "send_email") as send:
            result = self._run(date(2026, 1, 1), datetime(2026, 1, 1, 8))
        send.assert_not_called()
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "delivery_history_unavailable")
        self.assertNotIn("private path", str(result))

    def test_existing_verification_email_route_keeps_shared_sender_behavior(self):
        add_user("unverified@example.invalid", verified=0)
        client = self.app.test_client()
        with mock.patch("app.routes.auth_routes.send_email") as send:
            response = client.post("/api/auth/resend-verification",
                                  json={"email": "unverified@example.invalid"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["success"])
        send.assert_called_once()

    def test_shared_email_utility_uses_existing_flask_mail_configuration(self):
        from app.services import email_service
        with self.app.app_context(), mock.patch.object(email_service.mail, "send") as mail_send:
            email_service.send_email("test@example.invalid", "Subject", "Plain body")
        message = mail_send.call_args.args[0]
        self.assertEqual(message.recipients, ["test@example.invalid"])
        self.assertEqual(message.subject, "Subject")
        self.assertEqual(message.body, "Plain body")
        self.assertEqual(message.sender, self.app.config["MAIL_DEFAULT_SENDER"])


class ReminderDeliveryMigrationTests(unittest.TestCase):
    def test_phase7_migration_preserves_phase6_preferences_and_is_repeatable(self):
        root = Path(__file__).resolve().parents[1]
        schema_text = (root / "schema" / "schema.sql").read_text(encoding="utf-8")
        marker = "-- ---------- MEMBERSHIP REMINDER DELIVERY (Phase 7) ----------"
        self.assertIn(marker, schema_text)
        with tempfile.TemporaryDirectory(prefix="phase7-migration-") as temp_dir:
            db_path = Path(temp_dir) / "phase6-existing.db"
            conn = sqlite3.connect(db_path)
            conn.executescript(schema_text.split(marker, 1)[0])
            cur = conn.execute(
                "INSERT INTO users (full_name,email,password_hash,gender) VALUES (?,?,?,?)",
                ("Migration Member", "migration@example.invalid", "test-hash", "male"),
            )
            user_id = cur.lastrowid
            conn.execute(
                "INSERT INTO membership_reminder_preferences (user_id,enabled) VALUES (?,1)",
                (user_id,),
            )
            conn.execute(
                "INSERT INTO membership_reminder_lead_times (user_id,lead_days) VALUES (?,7)",
                (user_id,),
            )
            conn.commit()
            conn.close()

            command = [sys.executable, "scripts/migrate_db.py", "--db", str(db_path)]
            first = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertIn("Backup written:", first.stdout)
            backups = list(Path(temp_dir).glob("phase6-existing.db.backup-*"))
            self.assertEqual(len(backups), 1)

            conn = sqlite3.connect(db_path)
            names = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )}
            self.assertIn("membership_reminder_deliveries", names)
            self.assertIn("membership_reminder_delivery_attempts", names)
            self.assertEqual(conn.execute(
                "SELECT enabled FROM membership_reminder_preferences WHERE user_id=?", (user_id,)
            ).fetchone(), (1,))
            self.assertEqual(conn.execute(
                "SELECT lead_days FROM membership_reminder_lead_times WHERE user_id=?", (user_id,)
            ).fetchall(), [(7,)])
            conn.close()

            second = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertIn("Nothing to do.", second.stdout)
            self.assertEqual(len(list(Path(temp_dir).glob("phase6-existing.db.backup-*"))), 1)


if __name__ == "__main__":
    unittest.main()

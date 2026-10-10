"""Phase 9 integration regressions: shared Origin policy and safe migrations."""

import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.base import AppTestCase, ROOT


class SharedOriginProtectionTests(AppTestCase):
    def test_supplied_cross_origin_is_rejected_for_multiple_state_changing_routes(self):
        client = self.app.test_client()
        requests = [
            ("post", "/api/auth/logout"),
            ("put", "/api/membership/reminder-preferences"),
            ("post", "/api/membership/request"),
            ("post", "/api/admin/plans"),
        ]
        for method, path in requests:
            with self.subTest(method=method, path=path):
                response = getattr(client, method)(path, headers={"Origin": "https://attacker.example"})
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.get_json()["message"], "Cross-site requests are not allowed.")

    def test_same_origin_is_allowed_and_missing_origin_keeps_legacy_client_compatibility(self):
        client = self.app.test_client()
        same_origin = client.post("/api/auth/logout", headers={"Origin": "http://localhost"})
        self.assertEqual(same_origin.status_code, 200)
        legacy_client = client.post("/api/auth/logout")
        self.assertEqual(legacy_client.status_code, 200)

    def test_opaque_and_malformed_origins_are_rejected(self):
        client = self.app.test_client()
        for origin in ("null", "http://localhost:bad", "http://localhost/path"):
            with self.subTest(origin=origin):
                response = client.post("/api/auth/logout", headers={"Origin": origin})
                self.assertEqual(response.status_code, 403)


class TrustedProxyOriginTests(unittest.TestCase):
    def test_opt_in_trusted_proxy_restores_external_origin_for_comparison(self):
        from app import create_app
        from app.config import Config

        with mock.patch.object(Config, "TRUSTED_PROXY_COUNT", 1):
            app = create_app()
        response = app.test_client().post(
            "/api/auth/logout",
            headers={
                "Origin": "https://gym.example",
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "gym.example",
            },
        )
        self.assertEqual(response.status_code, 200, response.get_json())


class LegacySchemaMigrationTests(unittest.TestCase):
    def _make_legacy_db(self, path):
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE admins (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password_hash TEXT);
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                gender TEXT NOT NULL,
                google_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                profile_photo TEXT
            );
            CREATE TABLE membership_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_name TEXT NOT NULL,
                duration_months INTEGER NOT NULL,
                price NUMERIC NOT NULL,
                features TEXT
            );
            CREATE TABLE membership_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                plan_id INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                start_date DATE,
                end_date DATE
            );
            CREATE TABLE contact_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, phone TEXT,
                email TEXT, subject TEXT, message TEXT, is_read INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE password_reset_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
                token_hash TEXT UNIQUE, expires_at DATETIME,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute(
            "INSERT INTO users (full_name,email,password_hash,gender) VALUES (?,?,?,?)",
            ("Legacy Member", "legacy@example.invalid", "preserved-hash", "other"),
        )
        conn.commit()
        conn.close()

    def test_check_is_read_only_and_apply_integrates_legacy_updates_idempotently(self):
        with tempfile.TemporaryDirectory(prefix="phase9-schema-") as temp_dir:
            db_path = Path(temp_dir) / "legacy.db"
            self._make_legacy_db(db_path)
            command = [sys.executable, str(Path(ROOT) / "scripts" / "migrate_db.py"), "--db", str(db_path)]

            preview = subprocess.run(command + ["--check"], cwd=ROOT, capture_output=True,
                                     text=True, timeout=30)
            self.assertEqual(preview.returncode, 0, preview.stdout + preview.stderr)
            self.assertIn("Missing legacy columns:", preview.stdout)
            self.assertIn("email_verification_tokens", preview.stdout)
            conn = sqlite3.connect(db_path)
            try:
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
                self.assertNotIn("email_verification_tokens", tables)
                self.assertNotIn("is_verified", columns)
            finally:
                conn.close()

            applied = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(applied.returncode, 0, applied.stdout + applied.stderr)
            self.assertIn("schema/schema_updates.sql", applied.stdout)
            self.assertTrue(list(Path(temp_dir).glob("legacy.db.backup-*")))
            conn = sqlite3.connect(db_path)
            try:
                user = conn.execute(
                    "SELECT full_name,email,password_hash,is_verified,failed_login_attempts,lockout_until FROM users"
                ).fetchone()
                self.assertEqual(user, ("Legacy Member", "legacy@example.invalid", "preserved-hash", 0, 0, None))
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertIn("email_verification_tokens", tables)
                self.assertIn("membership_reminder_deliveries", tables)
            finally:
                conn.close()

            repeated = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
            self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
            self.assertIn("Nothing to do", repeated.stdout)
            self.assertEqual(len(list(Path(temp_dir).glob("legacy.db.backup-*"))), 1)


if __name__ == "__main__":
    unittest.main()

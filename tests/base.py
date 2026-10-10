"""Shared test setup: temporary SQLite DB built from schema/schema.sql,
fake environment secrets (the real .env is never read or modified), and
helpers to create/log in members. Gemini is always mocked."""

import os
import sqlite3
import tempfile
import unittest
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP = tempfile.mkdtemp(prefix="rbg-test-")
DB_PATH = os.path.join(_TMP, "test.db")

# Must be set BEFORE `app` is imported (app/config.py reads them at import).
os.environ.update({
    "SECRET_KEY": "test-secret-key",
    "MAIL_USERNAME": "test@example.com",
    "MAIL_PASSWORD": "test-password",
    "DATABASE_PATH": DB_PATH,
    "GEMINI_API_KEY": "",
})

from werkzeug.security import generate_password_hash  # noqa: E402
from app import create_app  # noqa: E402

PASSWORD = "Passw0rd!x"


def build_db(path=DB_PATH):
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    with open(os.path.join(ROOT, "schema", "schema.sql"), encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()


def add_user(email, verified=1):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "INSERT INTO users (full_name, email, password_hash, gender, is_verified) VALUES (?,?,?,?,?)",
        ("Test " + email.split("@")[0], email, generate_password_hash(PASSWORD), "male", verified),
    )
    conn.commit()
    uid = cur.lastrowid
    conn.close()
    return uid


class AppTestCase(unittest.TestCase):
    def setUp(self):
        build_db()
        self.app = create_app()
        self.app.config["TESTING"] = True

    def login(self, email):
        client = self.app.test_client()
        r = client.post("/api/auth/login", json={"loginEmail": email, "loginPassword": PASSWORD})
        self.assertEqual(r.status_code, 200, r.get_json())
        return client

    def member(self, email="a@example.com"):
        uid = add_user(email)
        return uid, self.login(email)

    @staticmethod
    def today():
        return date.today().isoformat()

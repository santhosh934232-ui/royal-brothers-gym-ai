"""Step 5 tests: Fitness Progress Tracking. No Gemini involved."""

import os
import sqlite3
import subprocess
import sys
from datetime import date, timedelta
from unittest import mock

from tests.base import AppTestCase, add_user, build_db, ROOT, DB_PATH, _TMP


class ProgressApiTests(AppTestCase):
    def entry(self, **kw):
        body = {"entryDate": self.today(), "weightKg": 72.5, "notes": "Felt good"}
        body.update(kw)
        return body

    # ----- access control -----
    def test_all_endpoints_require_login(self):
        c = self.app.test_client()
        self.assertEqual(c.get("/api/progress").status_code, 401)
        self.assertEqual(c.post("/api/progress", json=self.entry()).status_code, 401)
        self.assertEqual(c.put("/api/progress/1", json=self.entry()).status_code, 401)
        self.assertEqual(c.delete("/api/progress/1").status_code, 401)

    def test_member_cannot_see_edit_or_delete_others_entries(self):
        _, a = self.member("a@example.com")
        _, b = self.member("b@example.com")
        eid = a.post("/api/progress", json=self.entry()).get_json()["entry"]["id"]

        self.assertEqual(b.get("/api/progress").get_json()["entries"], [])
        self.assertEqual(b.put(f"/api/progress/{eid}", json=self.entry(weightKg=99)).status_code, 404)
        self.assertEqual(b.delete(f"/api/progress/{eid}").status_code, 404)
        # Untouched for the owner
        entries = a.get("/api/progress").get_json()["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["weightKg"], 72.5)

    def test_client_supplied_user_id_is_ignored(self):
        uid_a, a = self.member("a@example.com")
        uid_b, b = self.member("b@example.com")
        a.post("/api/progress", json=dict(self.entry(), userId=uid_b, user_id=uid_b))
        self.assertEqual(len(a.get("/api/progress").get_json()["entries"]), 1)
        self.assertEqual(len(b.get("/api/progress").get_json()["entries"]), 0)

    # ----- create / read / update / delete -----
    def test_add_list_edit_delete_flow(self):
        _, c = self.member()
        r = c.post("/api/progress", json=self.entry())
        self.assertEqual(r.status_code, 201)
        eid = r.get_json()["entry"]["id"]
        self.assertEqual(r.get_json()["entry"]["notes"], "Felt good")

        r = c.put(f"/api/progress/{eid}", json=self.entry(weightKg=71.9, notes=""))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["entry"]["weightKg"], 71.9)
        self.assertEqual(r.get_json()["entry"]["notes"], "")

        self.assertEqual(c.delete(f"/api/progress/{eid}").status_code, 200)
        self.assertEqual(c.get("/api/progress").get_json()["entries"], [])
        self.assertEqual(c.delete(f"/api/progress/{eid}").status_code, 404)

    def test_duplicate_date_rejected_on_add_and_edit(self):
        _, c = self.member()
        d1 = self.today()
        d2 = (date.today() - timedelta(days=3)).isoformat()
        c.post("/api/progress", json=self.entry(entryDate=d1))
        e2 = c.post("/api/progress", json=self.entry(entryDate=d2)).get_json()["entry"]["id"]
        self.assertEqual(c.post("/api/progress", json=self.entry(entryDate=d1)).status_code, 409)
        self.assertEqual(c.put(f"/api/progress/{e2}", json=self.entry(entryDate=d1)).status_code, 409)
        # Editing an entry while keeping its own date is fine
        self.assertEqual(c.put(f"/api/progress/{e2}", json=self.entry(entryDate=d2, weightKg=70)).status_code, 200)

    def test_two_members_may_log_same_date(self):
        _, a = self.member("a@example.com")
        _, b = self.member("b@example.com")
        self.assertEqual(a.post("/api/progress", json=self.entry()).status_code, 201)
        self.assertEqual(b.post("/api/progress", json=self.entry()).status_code, 201)

    # ----- validation -----
    def test_validation_errors(self):
        _, c = self.member()
        future = (date.today() + timedelta(days=10)).isoformat()
        bad_bodies = [
            self.entry(weightKg=29.9), self.entry(weightKg=300.1), self.entry(weightKg="abc"),
            self.entry(weightKg=None), self.entry(weightKg=True), self.entry(weightKg=float("inf")),
            self.entry(weightKg="nan"),
            self.entry(entryDate=""), self.entry(entryDate="2026-13-45"), self.entry(entryDate="not-a-date"),
            self.entry(entryDate="2026-1-5"), self.entry(entryDate=future), self.entry(entryDate="1999-12-31"),
            self.entry(entryDate=20260101), self.entry(notes="x" * 301), self.entry(notes=123),
        ]
        for body in bad_bodies:
            r = c.post("/api/progress", json=body)
            self.assertEqual(r.status_code, 400, (body, r.get_json()))
            self.assertFalse(r.get_json()["success"])
        self.assertEqual(c.get("/api/progress").get_json()["entries"], [])

    def test_malformed_body_and_ids(self):
        _, c = self.member()
        self.assertEqual(c.post("/api/progress", data="nope", content_type="text/plain").status_code, 400)
        self.assertEqual(c.post("/api/progress", json=[1, 2]).status_code, 400)
        self.assertEqual(c.put("/api/progress/abc", json=self.entry()).status_code, 404)
        self.assertEqual(c.delete("/api/progress/-5").status_code, 404)
        self.assertEqual(c.put("/api/progress/99999", json=self.entry()).status_code, 404)

    def test_boundary_weights_and_rounding(self):
        _, c = self.member()
        d = [(date.today() - timedelta(days=i)).isoformat() for i in range(3)]
        self.assertEqual(c.post("/api/progress", json=self.entry(entryDate=d[0], weightKg=30)).status_code, 201)
        self.assertEqual(c.post("/api/progress", json=self.entry(entryDate=d[1], weightKg=300)).status_code, 201)
        r = c.post("/api/progress", json=self.entry(entryDate=d[2], weightKg="70.46"))
        self.assertEqual(r.get_json()["entry"]["weightKg"], 70.5)

    def test_notes_stored_as_plain_text_not_interpreted(self):
        _, c = self.member()
        note = "<script>alert(1)</script>'; DROP TABLE users;--"
        r = c.post("/api/progress", json=self.entry(notes=note))
        self.assertEqual(r.status_code, 201)
        self.assertEqual(c.get("/api/progress").get_json()["entries"][0]["notes"], note)
        self.assertEqual(c.get("/api/auth/me").status_code, 200)  # users table intact

    # ----- summary / trend -----
    def test_empty_summary(self):
        _, c = self.member()
        data = c.get("/api/progress").get_json()
        self.assertEqual(data["summary"], {"count": 0})

    def test_summary_trend_and_ordering(self):
        _, c = self.member()
        c.put("/api/fitness-profile", json={
            "fitnessGoal": "weight_loss", "heightCm": 170, "weightKg": 80,
            "workoutExperience": "beginner", "availableMinutes": 45})
        for days_ago, w in [(0, 78.0), (14, 80.0), (7, 79.0)]:  # inserted out of order
            c.post("/api/progress", json=self.entry(
                entryDate=(date.today() - timedelta(days=days_ago)).isoformat(), weightKg=w))
        data = c.get("/api/progress").get_json()
        self.assertEqual([e["weightKg"] for e in data["entries"]], [80.0, 79.0, 78.0])  # oldest first
        s = data["summary"]
        self.assertEqual(s["count"], 3)
        self.assertEqual(s["startWeightKg"], 80.0)
        self.assertEqual(s["latestWeightKg"], 78.0)
        self.assertEqual(s["totalChangeKg"], -2.0)
        self.assertEqual(s["changeSincePreviousKg"], -1.0)
        self.assertEqual((s["lowestKg"], s["highestKg"], s["averageKg"]), (78.0, 80.0, 79.0))
        self.assertEqual(s["trend"], "down")
        self.assertEqual(s["bmi"], round(78 / 1.7 ** 2, 1))
        self.assertEqual(data["goal"], "weight_loss")

    def test_single_entry_summary_and_no_profile_bmi(self):
        _, c = self.member()
        c.post("/api/progress", json=self.entry())
        s = c.get("/api/progress").get_json()["summary"]
        self.assertEqual(s["count"], 1)
        self.assertIsNone(s["trend"])
        self.assertIsNone(s["changeSincePreviousKg"])
        self.assertIsNone(s["bmi"])

    # ----- safe errors -----
    def test_db_failure_returns_safe_500_without_internals(self):
        _, c = self.member()
        with mock.patch("app.routes.progress_routes.create_progress_entry",
                        side_effect=RuntimeError("secret /path/to/db.sqlite")):
            r = c.post("/api/progress", json=self.entry())
        self.assertEqual(r.status_code, 500)
        self.assertNotIn("secret", r.get_data(as_text=True))

    def test_does_not_call_gemini(self):
        _, c = self.member()
        with mock.patch("app.services.gemini_service.generate_text") as g:
            c.post("/api/progress", json=self.entry())
            c.get("/api/progress")
            g.assert_not_called()

    def test_deleting_member_cascades_entries(self):
        uid, c = self.member()
        c.post("/api/progress", json=self.entry())
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM users WHERE id = ?", (uid,))
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM progress_entries").fetchone()[0]
        conn.close()
        self.assertEqual(n, 0)


class ProgressFrontendAndMigrationTests(AppTestCase):
    def test_profile_page_has_progress_section(self):
        html = self.app.test_client().get("/profile.html").get_data(as_text=True)
        for needle in ('id="progressSection"', 'id="progressForm"', "profile.js"):
            self.assertIn(needle, html)
        js = self.app.test_client().get("/profile.js").get_data(as_text=True)
        self.assertIn("initProgressTracker", js)

    def test_migration_adds_table_keeps_data_and_is_rerunnable(self):
        # Simulate an existing Step-4 database: current schema minus progress_entries.
        path = os.path.join(_TMP, "existing.db")
        build_db(path)
        conn = sqlite3.connect(path)
        conn.execute("DROP TABLE progress_entries")
        conn.execute("INSERT INTO users (full_name,email,password_hash,gender,is_verified) VALUES ('x','x@e.com','h','male',1)")
        conn.commit()
        conn.close()

        script = os.path.join(ROOT, "scripts", "migrate_db.py")
        run = lambda *a: subprocess.run([sys.executable, "-I", script, "--db", path, *a],
                                        capture_output=True, text=True)
        r = run("--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("progress_entries", r.stdout)  # reported missing, nothing changed
        conn = sqlite3.connect(path)
        self.assertIsNone(conn.execute("SELECT 1 FROM sqlite_master WHERE name='progress_entries'").fetchone())
        conn.close()

        r = run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        conn = sqlite3.connect(path)
        self.assertIsNotNone(conn.execute("SELECT 1 FROM sqlite_master WHERE name='progress_entries'").fetchone())
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)
        conn.close()
        self.assertEqual(run().returncode, 0)  # idempotent

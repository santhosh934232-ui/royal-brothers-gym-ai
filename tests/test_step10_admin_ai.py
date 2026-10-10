"""Step 10 tests: Admin AI Management (read-only). Gemini is never called and no real key is used."""

import json
import sqlite3
from unittest import mock

from werkzeug.security import generate_password_hash

from tests.base import DB_PATH, PASSWORD
from tests.test_step8_nutrition import good_plan
from tests.test_step9_dashboard import DashboardBase
from tests.test_steps_1_to_4 import PROFILE, fake_weekly_plan
from app.config import Config

URL = "/api/admin/ai/overview"
FAKE_KEY = "AIzaSyFAKE-KEY-FOR-TESTS-0123456789"


class AdminAiBase(DashboardBase):
    ADMIN_PASSWORD = "AdminPass#42"

    def admin(self):
        conn = sqlite3.connect(DB_PATH)
        conn.execute("INSERT OR IGNORE INTO admins (username, password_hash) VALUES (?, ?)",
                     ("boss", generate_password_hash(self.ADMIN_PASSWORD)))
        conn.commit(); conn.close()
        c = self.app.test_client()
        r = c.post("/api/admin/login", json={"username": "boss", "password": self.ADMIN_PASSWORD})
        self.assertEqual(r.status_code, 200)
        return c

    def snapshot(self):
        data = super().snapshot()
        conn = sqlite3.connect(DB_PATH)
        data["admins"] = conn.execute("SELECT * FROM admins ORDER BY id").fetchall()
        conn.close()
        return data

    @staticmethod
    def by_key(data):
        return {f["key"]: f for f in data["features"]}


class AdminAiAuthTests(AdminAiBase):
    def test_logged_out_is_rejected(self):
        r = self.app.test_client().get(URL)
        self.assertEqual(r.status_code, 401)
        self.assertNotIn("features", r.get_json())

    def test_member_session_is_not_admin(self):
        _, c = self.everything()
        r = c.get(URL)
        self.assertEqual(r.status_code, 401)
        self.assertNotIn("features", r.get_json())

    def test_admin_session_is_not_a_member_session(self):
        a = self.admin()
        self.assertEqual(a.get(URL).status_code, 200)
        for member_url in ("/api/dashboard", "/api/nutrition-plan", "/api/insights"):
            self.assertEqual(a.get(member_url).status_code, 401, member_url)

    def test_existing_admin_endpoints_unchanged(self):
        a = self.admin()
        self.assertEqual(a.get("/api/admin/me").status_code, 200)
        self.assertEqual(a.get("/api/admin/dashboard/stats").status_code, 200)
        self.assertEqual(self.app.test_client().get("/api/admin/dashboard/stats").status_code, 401)


class AdminAiContentTests(AdminAiBase):
    def test_counts_and_latest_timestamps(self):
        _, a = self.everything("a@example.com")
        _, b = self.member("b@example.com")
        b.put("/api/fitness-profile", json=PROFILE)
        with mock.patch("app.routes.workout_routes.generate_text", return_value=fake_weekly_plan()):
            b.post("/api/workout-plan/generate")
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE workout_plans SET created_at='2030-01-02 03:04:05' WHERE user_id=2")
        conn.commit()
        latest = conn.execute("SELECT MAX(created_at) FROM nutrition_plans").fetchone()[0]
        conn.close()
        d = self.admin().get(URL).get_json()
        f = self.by_key(d)
        self.assertEqual({k: v["records"] for k, v in f.items()},
                         {"workout_plan": 2, "daily_plan": 1, "insight": 1, "recommendation": 1, "nutrition_plan": 1})
        self.assertEqual(f["workout_plan"]["lastGenerated"], "2030-01-02 03:04:05")
        self.assertEqual(f["nutrition_plan"]["lastGenerated"], str(latest))
        self.assertTrue(all(v["available"] for v in f.values()))
        self.assertEqual([v["step"] for v in d["features"]], [3, 4, 6, 7, 8])
        self.assertTrue(d["readOnly"])

    def test_empty_system(self):
        d = self.admin().get(URL).get_json()
        for f in d["features"]:
            self.assertEqual((f["records"], f["lastGenerated"], f["available"]), (0, None, True))

    def test_no_member_content_or_identity_in_response(self):
        self.everything()
        body = self.admin().get(URL).get_data(as_text=True)
        for needle in ("a@example.com", "Test a", "muscle_gain", "Squat", "9 AM - 4 PM", "felt strong",
                       "balanced plan", "steady progress", "70.5", "plan_json", "insight_json"):
            self.assertNotIn(needle, body)


class AdminAiSecurityTests(AdminAiBase):
    def test_status_configured_never_leaks_key_or_secrets(self):
        a = self.admin()
        with mock.patch.object(Config, "GEMINI_API_KEY", FAKE_KEY):
            r = a.get(URL)
        d = r.get_json()
        self.assertTrue(d["service"]["configured"])
        self.assertEqual(d["service"]["model"], Config.GEMINI_MODEL)
        body = r.get_data(as_text=True)
        for secret in (FAKE_KEY, FAKE_KEY[:8], "test-secret-key", "test-password", "test@example.com",
                       self.ADMIN_PASSWORD, "password_hash", "pbkdf2", "scrypt", DB_PATH):
            self.assertNotIn(secret, body)
        self.assertNotIn("api_key", body.lower())
        self.assertNotIn("apikey", body.lower())

    def test_status_not_configured_is_clear(self):
        with mock.patch.object(Config, "GEMINI_API_KEY", ""):
            d = self.admin().get(URL).get_json()
        self.assertFalse(d["service"]["configured"])
        self.assertIsNone(d["service"]["model"])
        self.assertIn("not configured", d["service"]["message"])

    def test_whitespace_key_counts_as_not_configured(self):
        with mock.patch.object(Config, "GEMINI_API_KEY", "   "):
            self.assertFalse(self.admin().get(URL).get_json()["service"]["configured"])

    def test_viewing_modifies_nothing_and_never_calls_gemini(self):
        self.everything()
        a = self.admin()
        before = self.snapshot()
        with mock.patch("app.services.gemini_service._get_client", side_effect=AssertionError("Gemini called")), \
             mock.patch("app.services.gemini_service.generate_text", side_effect=AssertionError("Gemini called")):
            for _ in range(3):
                self.assertEqual(a.get(URL).status_code, 200)
        self.assertEqual(self.snapshot(), before)

    def test_admin_cannot_write_or_edit_through_this_api(self):
        self.everything()
        a = self.admin()
        before = self.snapshot()
        for method in (a.post, a.put, a.patch, a.delete):
            self.assertEqual(method(URL, json={"records": 99}).status_code, 405)
        for path in ("/api/admin/ai/settings", "/api/admin/ai/generate", "/api/admin/ai/nutrition-plan/1",
                     "/api/admin/ai/members/1"):
            self.assertIn(a.post(path, json={}).status_code, (404, 405), path)   # no such write route
            self.assertEqual(a.get(path).status_code, 404, path)
        self.assertEqual(self.snapshot(), before)


class AdminAiResilienceTests(AdminAiBase):
    def test_missing_table_is_reported_unavailable_not_error(self):
        self.everything()
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DROP TABLE nutrition_plans"); conn.commit(); conn.close()
        r = self.admin().get(URL)
        self.assertEqual(r.status_code, 200)
        f = self.by_key(r.get_json())
        self.assertFalse(f["nutrition_plan"]["available"])
        self.assertIsNone(f["nutrition_plan"]["records"])
        self.assertEqual(f["insight"]["records"], 1)

    def test_stats_failure_degrades_gracefully(self):
        a = self.admin()
        with mock.patch("app.routes.admin_routes.get_ai_record_stats", side_effect=RuntimeError("db /secret/path")):
            r = a.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("/secret", r.get_data(as_text=True))
        self.assertTrue(all(not f["available"] for f in r.get_json()["features"]))

    def test_gemini_status_check_failure_degrades_gracefully(self):
        a = self.admin()
        with mock.patch("app.routes.admin_routes.gemini_is_configured", side_effect=RuntimeError("boom AIza")):
            r = a.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.get_json()["service"]["configured"])
        self.assertNotIn("AIza", r.get_data(as_text=True))


class AdminAiWiringAndRegressionTests(AdminAiBase):
    def test_admin_page_has_ai_tab_and_safe_rendering(self):
        client = self.app.test_client()
        html = client.get("/admin-dashboard.html").get_data(as_text=True)
        js = client.get("/admin.js").get_data(as_text=True)
        self.assertIn('data-tab="ai"', html)
        self.assertIn('id="tab-ai"', html)
        for tab in ("overview", "members", "requests", "plans", "messages"):
            self.assertIn(f'data-tab="{tab}"', html)
        ai_js = js[js.index("AI MANAGEMENT (Step 10)"):]
        self.assertIn("/api/admin/ai/overview", ai_js)
        self.assertNotIn("innerHTML", ai_js)
        self.assertNotIn("method:", ai_js)          # GET only: no writes from this page

    def test_member_ai_features_still_work_after_admin_views(self):
        _, c = self.full_member("a@example.com")
        self.admin().get(URL)
        with mock.patch("app.routes.nutrition_routes.generate_text", return_value=good_plan()):
            self.assertEqual(c.post("/api/nutrition-plan/generate").status_code, 200)
        self.assertEqual(c.get("/api/dashboard").get_json()["nutrition"]["calories"], {"min": 2600, "max": 2900})
        d = self.admin().get(URL).get_json()
        self.assertEqual(self.by_key(d)["nutrition_plan"]["records"], 1)


class AdminPanelEscapingTests(AdminAiBase):
    """Final-integration regression: visitor-supplied text must be escaped before it is put in admin tables."""

    def test_admin_tables_escape_server_text(self):
        js = self.app.test_client().get("/admin.js").get_data(as_text=True)
        self.assertIn("function escapeHtml", js)
        for raw in ("${m.name}", "${m.subject}", "${m.message}", "${m.email}", "${m.phone}", "${m.full_name}",
                    "${r.full_name}", "${r.email}", "${r.plan_name}", "${p.plan_name}", "${p.features"):
            self.assertNotIn(raw, js, raw)

    def test_member_session_cannot_use_any_admin_get_route(self):
        _, c = self.everything()
        for path in ("/api/admin/me", "/api/admin/members", "/api/admin/plans", "/api/admin/membership-requests",
                     "/api/admin/messages", "/api/admin/dashboard/stats", "/api/admin/ai/overview"):
            self.assertEqual(c.get(path).status_code, 401, path)

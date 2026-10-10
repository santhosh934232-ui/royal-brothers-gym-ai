"""Step 9 tests: Member AI Dashboard. Read-only; Gemini is never called (and is mocked to prove it)."""

import json
import sqlite3
from unittest import mock

from tests.base import DB_PATH
from tests.test_step6_insights import good_reply as insight_reply
from tests.test_step7_recommendations import good_rec
from tests.test_step8_nutrition import NutritionBase, good_plan
from tests.test_steps_1_to_4 import PROFILE

URL = "/api/dashboard"
SECTIONS = ("profile", "workout", "daily", "progress", "insight", "recommendation", "nutrition")


class DashboardBase(NutritionBase):
    def snapshot(self):
        data = super().snapshot()
        conn = sqlite3.connect(DB_PATH)
        data["nutrition_plans"] = conn.execute("SELECT * FROM nutrition_plans ORDER BY id").fetchall()
        conn.close()
        return data

    def everything(self, email="a@example.com"):
        uid, c = self.full_member_with_rec(email)
        with mock.patch("app.routes.nutrition_routes.generate_text", return_value=good_plan()):
            c.post("/api/nutrition-plan/generate")
        return uid, c


class DashboardAccessTests(DashboardBase):
    def test_logged_out_is_rejected(self):
        c = self.app.test_client()
        r = c.get(URL)
        self.assertEqual(r.status_code, 401)
        self.assertNotIn("profile", r.get_json() or {})

    def test_members_only_see_their_own_data(self):
        _, a = self.everything("a@example.com")
        _, b = self.member("b@example.com")
        b.put("/api/fitness-profile", json=dict(PROFILE, fitnessGoal="weight_loss", weightKg=99))
        b.post("/api/progress", json={"entryDate": self.today(), "weightKg": 98.7, "notes": "b private note"})
        da, db = a.get(URL).get_json(), b.get(URL).get_json()
        self.assertEqual(da["profile"]["goal"], "muscle_gain")
        self.assertEqual(da["progress"]["latestWeightKg"], 70.5)
        self.assertEqual(db["profile"]["goal"], "weight_loss")
        self.assertEqual(db["progress"]["latestWeightKg"], 98.7)
        for sec in ("workout", "daily", "insight", "recommendation", "nutrition"):
            self.assertIsNone(db[sec], sec)
        self.assertNotIn("70.5", json.dumps(db))
        self.assertNotIn("Solid base", json.dumps(db))

    def test_payload_has_no_identity_or_private_text(self):
        _, c = self.everything()
        body = c.get(URL).get_data(as_text=True)
        for secret in ("a@example.com", "Test a", "9 AM - 4 PM", "John Smith", "felt strong", "user_id", "password"):
            self.assertNotIn(secret, body)


class DashboardContentTests(DashboardBase):
    def test_full_dashboard_values(self):
        _, c = self.everything()
        d = c.get(URL).get_json()
        self.assertTrue(d["success"])
        self.assertEqual(d["profile"], {"goal": "muscle_gain", "heightCm": 175.0, "weightKg": 70.0,
                                        "experience": "beginner", "availableMinutes": 45})
        self.assertEqual((d["workout"]["trainingDays"], d["workout"]["restDays"]), (5, 2))
        t = d["workout"]["today"]
        self.assertEqual(t["planDay"], 1)   # plan generated today -> Day 1
        self.assertFalse(t["isRest"])
        self.assertEqual(t["focus"], "Full Body")
        self.assertEqual(d["daily"]["planDay"], 1)
        self.assertTrue(d["daily"]["matchesToday"])
        p = d["progress"]
        self.assertEqual((p["latestWeightKg"], p["totalChangeKg"], p["count"]), (70.5, -1.5, 3))
        self.assertEqual([w["weightKg"] for w in p["recentWeights"]], [72.0, 71.2, 70.5])
        self.assertEqual(d["insight"]["summary"], "You are making steady progress.")
        self.assertEqual(d["insight"]["nextStep"], "Weigh in every Monday")
        self.assertEqual(d["recommendation"]["keyRecommendation"], "Add 2.5 kg when all reps are clean")
        self.assertEqual(d["nutrition"]["calories"], {"min": 2600, "max": 2900})
        self.assertEqual(d["nutrition"]["protein"], {"min_g": 110, "max_g": 150})

    def test_new_member_with_nothing_gets_all_null_sections(self):
        _, c = self.member()
        r = c.get(URL)
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        for sec in SECTIONS:
            self.assertIsNone(d[sec], sec)

    def test_profile_only_and_partial_data(self):
        _, c = self.member()
        c.put("/api/fitness-profile", json=PROFILE)
        d = c.get(URL).get_json()
        self.assertIsNotNone(d["profile"])
        for sec in SECTIONS[1:]:
            self.assertIsNone(d[sec], sec)
        c.post("/api/progress", json={"entryDate": self.today(), "weightKg": 70.0})
        d = c.get(URL).get_json()
        self.assertEqual(d["progress"]["count"], 1)
        self.assertIsNone(d["progress"]["trend"])
        self.assertIsNone(d["workout"])

    def test_daily_plan_for_other_day_is_flagged(self):
        _, c = self.everything()
        with mock.patch("app.routes.daily_routes.generate_text") as g:
            from tests.test_steps_1_to_4 import fake_daily_plan
            g.return_value = fake_daily_plan()
            conn = sqlite3.connect(DB_PATH); conn.execute("UPDATE daily_plans SET created_at='2000-01-01 00:00:00'")
            conn.commit(); conn.close()
            c.post("/api/daily-plan/generate", json={"planDay": 3})
        d = c.get(URL).get_json()
        self.assertEqual(d["daily"]["planDay"], 3)
        self.assertFalse(d["daily"]["matchesToday"])

    def test_corrupted_saved_ai_data_degrades_to_null(self):
        _, c = self.everything()
        conn = sqlite3.connect(DB_PATH)
        conn.execute("UPDATE ai_insights SET insight_json='not json'")
        conn.execute("UPDATE workout_recommendations SET recommendation_json='[1,2]'")
        conn.execute("UPDATE nutrition_plans SET plan_json='{\"summary\": \"x\"}'")
        conn.execute("UPDATE workout_plans SET plan_json='{\"days\": []}'")
        conn.commit(); conn.close()
        r = c.get(URL)
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        for sec in ("insight", "recommendation", "nutrition", "workout"):
            self.assertIsNone(d[sec], sec)
        self.assertIsNotNone(d["profile"])
        self.assertIsNotNone(d["progress"])


class DashboardSafetyTests(DashboardBase):
    def test_read_only_and_never_calls_gemini(self):
        _, c = self.everything()
        before = self.snapshot()
        with mock.patch("app.services.gemini_service._get_client", side_effect=AssertionError("Gemini called")) as g, \
             mock.patch("app.services.gemini_service.generate_text", side_effect=AssertionError("Gemini called")):
            for _ in range(2):
                self.assertEqual(c.get(URL).status_code, 200)
            g.assert_not_called()
        self.assertEqual(self.snapshot(), before)

    def test_write_methods_not_allowed(self):
        _, c = self.everything()
        for method in (c.post, c.put, c.delete):
            self.assertEqual(method(URL).status_code, 405)


class DashboardWiringTests(DashboardBase):
    def test_pages_and_links(self):
        client = self.app.test_client()
        html = client.get("/dashboard.html").get_data(as_text=True)
        js = client.get("/dashboard.js").get_data(as_text=True)
        self.assertIn('id="dashContent"', html)
        self.assertIn("/api/dashboard", js)
        self.assertNotIn("innerHTML", js)   # server text only via textContent
        profile = client.get("/profile.html").get_data(as_text=True)
        self.assertIn('href="dashboard.html"', profile)
        for sid in ("workoutPlanSection", "dailyPlanSection", "progressSection", "insightsSection",
                    "recommendSection", "nutritionSection", "fitnessView"):
            self.assertIn(f'id="{sid}"', profile)       # targets the dashboard links to
            self.assertIn(f"profile.html#{sid}", js)

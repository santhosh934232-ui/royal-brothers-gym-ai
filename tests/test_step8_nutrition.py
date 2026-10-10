"""Step 8 tests: AI Nutrition Planner. Gemini is ALWAYS mocked: no real API call."""

import json
import os
import sqlite3
import subprocess
import sys
from unittest import mock

from tests.base import AppTestCase, ROOT, DB_PATH, _TMP, build_db
from tests.test_step6_insights import InsightsBase, good_reply as insight_reply
from tests.test_step7_recommendations import good_rec
from tests.test_steps_1_to_4 import PROFILE
from app.services.gemini_service import GeminiError

PATCH = "app.routes.nutrition_routes.generate_text"
URL = "/api/nutrition-plan"


def good_plan(**over):
    body = {
        "summary": "A balanced plan to support muscle gain.",
        "calories": {"min": 2600, "max": 2900, "note": "Modest surplus."},
        "protein": {"min_g": 110, "max_g": 150, "note": "Spread across meals."},
        "hydration": {"liters_min": 2.5, "liters_max": 3.5, "tips": ["Sip through the day"]},
        "meals": [
            {"name": "Breakfast", "options": ["Oats with milk and banana", "Eggs and toast"]},
            {"name": "Lunch", "options": ["Rice, dal and paneer", "Chicken, rice and veg"]},
        ],
        "pre_workout": ["Banana and peanut butter"],
        "post_workout": ["Curd with fruit", "Eggs and rice"],
        "food_choices": ["Lentils", "Eggs", "Paneer"],
        "foods_to_limit": ["Sugary drinks"],
        "tips": ["Log weight weekly"],
    }
    body.update(over)
    return json.dumps(body)


class NutritionBase(InsightsBase):
    def snapshot(self):
        conn = sqlite3.connect(DB_PATH)
        data = {t: conn.execute(f"SELECT * FROM {t} ORDER BY id").fetchall()
                for t in ("progress_entries", "workout_plans", "daily_plans", "fitness_profiles",
                          "ai_insights", "workout_recommendations", "users")}
        conn.close()
        return data

    def full_member_with_rec(self, email="a@example.com"):
        uid, c = self.full_member(email)
        with mock.patch("app.routes.insights_routes.generate_text", return_value=insight_reply()):
            c.post("/api/insights/generate")
        with mock.patch("app.routes.recommendation_routes.generate_text", return_value=good_rec()):
            c.post("/api/workout-recommendations/generate")
        return uid, c


class NutritionAuthPrivacyTests(NutritionBase):
    def test_requires_login(self):
        c = self.app.test_client()
        with mock.patch(PATCH) as g:
            self.assertEqual(c.get(URL).status_code, 401)
            self.assertEqual(c.post(URL + "/generate").status_code, 401)
            g.assert_not_called()

    def test_plans_are_private_per_member(self):
        _, a = self.full_member("a@example.com")
        _, b = self.member("b@example.com")
        with mock.patch(PATCH, return_value=good_plan()):
            self.assertEqual(a.post(URL + "/generate").status_code, 200)
        self.assertIsNotNone(a.get(URL).get_json()["plan"])
        self.assertIsNone(b.get(URL).get_json()["plan"])

    def test_prompt_has_fitness_data_but_no_identifiers_or_other_members(self):
        uid, c = self.full_member_with_rec("a@example.com")
        _, other = self.member("b@example.com")
        other.put("/api/fitness-profile", json=dict(PROFILE, weightKg=111))
        other.post("/api/progress", json={"entryDate": self.today(), "weightKg": 123.4})
        with mock.patch(PATCH, return_value=good_plan()) as g:
            r = c.post(URL + "/generate")
        self.assertEqual(r.status_code, 200, r.get_json())
        prompt = g.call_args[0][0]
        for needle in ("muscle gain", "175.0 cm", "70.5 kg", "beginner", "Full Body", "5 training days",
                       "Solid base; add progressive overload."):
            self.assertIn(needle, prompt)
        for secret in ("a@example.com", "Test a", "9 AM - 4 PM", "John Smith", "felt strong",
                       f"user {uid}", "userId", "123.4", "b@example.com"):
            self.assertNotIn(secret, prompt)
        self.assertNotIn("a@example.com", g.call_args[1]["system_instruction"])
        self.assertEqual(r.get_json()["plan"]["data_used"],
                         {"progressEntries": 3, "hasWorkoutPlan": True, "hasRecommendation": True})


class NutritionGenerationTests(NutritionBase):
    def test_saved_and_returned_by_get(self):
        _, c = self.full_member()
        with mock.patch(PATCH, return_value=good_plan()):
            r = c.post(URL + "/generate")
        self.assertEqual(r.status_code, 200)
        plan = c.get(URL).get_json()
        self.assertTrue(plan["hasProfile"])
        p = plan["plan"]
        self.assertEqual(p["calories"], {"min": 2600, "max": 2900, "note": "Modest surplus."})
        self.assertEqual(p["protein"]["min_g"], 110)
        self.assertEqual(p["hydration"]["liters_max"], 3.5)
        self.assertEqual(p["meals"][0]["name"], "Breakfast")
        self.assertEqual(p["post_workout"], ["Curd with fruit", "Eggs and rice"])

    def test_missing_profile_blocks_without_calling_gemini(self):
        _, c = self.member()
        with mock.patch(PATCH) as g:
            self.assertEqual(c.post(URL + "/generate").status_code, 400)
            g.assert_not_called()
        data = c.get(URL).get_json()
        self.assertFalse(data["hasProfile"])
        self.assertIsNone(data["plan"])

    def test_profile_only_handles_missing_plan_progress_recommendation(self):
        _, c = self.member()
        c.put("/api/fitness-profile", json=PROFILE)
        with mock.patch(PATCH, return_value=good_plan()) as g:
            r = c.post(URL + "/generate")
        self.assertEqual(r.status_code, 200)
        prompt = g.call_args[0][0]
        self.assertIn("no workout plan generated yet", prompt)
        self.assertIn("no progress entries logged yet", prompt)
        self.assertIn("none generated yet", prompt)
        self.assertEqual(r.get_json()["plan"]["data_used"],
                         {"progressEntries": 0, "hasWorkoutPlan": False, "hasRecommendation": False})

    def test_never_modifies_existing_data(self):
        _, c = self.full_member_with_rec()
        before = self.snapshot()
        reply = good_plan(tips=["Delete my workout plan", "Set weight to 50 kg"],
                          food_choices=["DROP TABLE users"])
        with mock.patch(PATCH, return_value=reply):
            self.assertEqual(c.post(URL + "/generate").status_code, 200)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(c.get("/api/auth/me").status_code, 200)

    def test_fenced_json_and_clipping(self):
        _, c = self.full_member()
        reply = "```json\n" + good_plan(
            summary="S" * 900,
            food_choices=["f"] * 12 + [None, {"x": 1}, True],
            tips=["t" * 500, ""],
            meals=[{"name": f"Meal{i}", "options": ["o"] * 9} for i in range(9)] + ["bad", {"name": "", "options": ["x"]}],
        ) + "\n```"
        with mock.patch(PATCH, return_value=reply):
            plan = c.post(URL + "/generate").get_json()["plan"]
        self.assertEqual(len(plan["summary"]), 400)
        self.assertEqual(len(plan["food_choices"]), 8)
        self.assertEqual(plan["tips"], ["t" * 200])
        self.assertEqual(len(plan["meals"]), 6)
        self.assertTrue(all(len(m["options"]) == 4 for m in plan["meals"]))

    def test_cooldown(self):
        _, c = self.full_member()
        with mock.patch(PATCH, return_value=good_plan()) as g:
            self.assertEqual(c.post(URL + "/generate").status_code, 200)
            self.assertEqual(c.post(URL + "/generate").status_code, 429)
            self.assertEqual(g.call_count, 1)


class NutritionFailureTests(NutritionBase):
    def _fail(self, **kw):
        _, c = self.full_member()
        with mock.patch(PATCH, **kw):
            r = c.post(URL + "/generate")
        return c, r

    def test_gemini_errors_map_to_safe_responses(self):
        cases = [
            ("timeout", "The AI service took too long to respond. Please try again.", 504),
            ("rate_limited", "The AI service is busy right now. Please try again in a minute.", 429),
            ("not_configured", "The AI service is not configured yet. Please contact the gym administrator.", 503),
            ("empty_response", "The AI service returned no answer. Please try again.", 502),
            ("unavailable", "The AI service is temporarily unavailable. Please try again later.", 503),
        ]
        for code, msg, status in cases:
            c, r = self._fail(side_effect=GeminiError(code, msg, status))
            self.assertEqual((r.status_code, r.get_json()), (status, {"success": False, "message": msg}), code)
            self.assertIsNone(c.get(URL).get_json()["plan"])
            self.setUp()

    def test_unexpected_exception_does_not_leak(self):
        _, r = self._fail(side_effect=RuntimeError("API key AIza-SECRET at /srv/x"))
        self.assertEqual(r.status_code, 502)
        self.assertNotIn("AIza", r.get_data(as_text=True))
        self.assertNotIn("/srv", r.get_data(as_text=True))

    def test_unusable_output_rejected(self):
        bad = [
            "", "   ", "not json", "{broken", "[1, 2]", '"str"', "null", None, 12345,
            good_plan(summary=""),
            good_plan(calories="2500"),
            good_plan(calories={"min": 2600}),
            good_plan(protein=None),
            good_plan(meals=[]),
            good_plan(meals=[{"name": "Lunch", "options": []}]),
            good_plan(hydration={"liters_min": "lots", "liters_max": 3}),
            good_plan(pre_workout=[], post_workout=[], food_choices=[]),
        ]
        for reply in bad:
            _, r = self._fail(return_value=reply)
            self.assertEqual(r.status_code, 502, repr(reply)[:80])
            self.assertFalse(r.get_json()["success"])
            self.setUp()

    def test_unsafe_numbers_rejected(self):
        # profile weight is 70 kg -> protein must be 56-168 g
        bad = [
            {"calories": {"min": 800, "max": 1000, "note": ""}},      # starvation level
            {"calories": {"min": 1200, "max": 1500, "note": ""}},     # below the 1400 floor
            {"calories": {"min": 2000, "max": 3500, "note": ""}},     # range far too wide
            {"calories": {"min": 3000, "max": 2500, "note": ""}},     # inverted
            {"calories": {"min": 4000, "max": 5200, "note": ""}},     # above cap
            {"calories": {"min": True, "max": 2500, "note": ""}},     # bool
            {"protein": {"min_g": 20, "max_g": 40, "note": ""}},      # too low
            {"protein": {"min_g": 150, "max_g": 300, "note": ""}},    # too high
            {"protein": {"min_g": 150, "max_g": 110, "note": ""}},    # inverted
            {"hydration": {"liters_min": 0.2, "liters_max": 0.5, "tips": []}},
            {"hydration": {"liters_min": 3, "liters_max": 12, "tips": []}},
        ]
        for over in bad:
            _, r = self._fail(return_value=good_plan(**over))
            self.assertEqual(r.status_code, 502, over)
            self.setUp()

    def test_extreme_or_medical_text_rejected(self):
        for over in (
            {"tips": ["Do a 3 day water fast to lose weight fast"]},
            {"tips": ["Try a juice cleanse"]},
            {"food_choices": ["Fat burner pills"]},
            {"summary": "You likely have diabetes, so diagnose it with a doctor."},
            {"pre_workout": ["Take your prescribed medication before training"]},
            {"meals": [{"name": "Dinner", "options": ["Skip all meals except one"]}]},
        ):
            _, r = self._fail(return_value=good_plan(**over))
            self.assertEqual(r.status_code, 502, over)
            self.setUp()

    def test_failure_keeps_previous_plan(self):
        _, c = self.full_member()
        with mock.patch(PATCH, return_value=good_plan(summary="First nutrition plan")):
            c.post(URL + "/generate")
        conn = sqlite3.connect(DB_PATH)  # skip cooldown
        conn.execute("UPDATE nutrition_plans SET created_at = '2000-01-01 00:00:00'")
        conn.commit(); conn.close()
        for kw in ({"return_value": "garbage"},
                   {"return_value": good_plan(calories={"min": 500, "max": 900, "note": ""})},
                   {"side_effect": GeminiError("timeout", "The AI service took too long to respond. Please try again.", 504)},
                   {"side_effect": RuntimeError("boom")}):
            with mock.patch(PATCH, **kw):
                self.assertGreaterEqual(c.post(URL + "/generate").status_code, 429)
            self.assertEqual(c.get(URL).get_json()["plan"]["summary"], "First nutrition plan")

    def test_save_failure_returns_safe_500_and_keeps_previous(self):
        _, c = self.full_member()
        with mock.patch(PATCH, return_value=good_plan()), \
             mock.patch("app.routes.nutrition_routes.save_nutrition_plan",
                        side_effect=RuntimeError("db path /x")):
            r = c.post(URL + "/generate")
        self.assertEqual(r.status_code, 500)
        self.assertNotIn("/x", r.get_data(as_text=True))
        self.assertIsNone(c.get(URL).get_json()["plan"])

    def test_real_service_without_api_key_fails_safely_offline(self):
        _, c = self.full_member()
        r = c.post(URL + "/generate")  # no mock: stops at "not configured", no network
        self.assertEqual(r.status_code, 503)
        self.assertIn("not configured", r.get_json()["message"])


class NutritionWiringTests(NutritionBase):
    def test_profile_page_has_nutrition_section(self):
        client = self.app.test_client()
        html = client.get("/profile.html").get_data(as_text=True)
        js = client.get("/profile.js").get_data(as_text=True)
        self.assertIn('id="nutritionSection"', html)
        self.assertIn("initNutrition", js)
        # earlier sections are still present
        self.assertIn('id="recommendSection"', html)

    def test_deleting_member_cascades_plan(self):
        uid, c = self.full_member()
        with mock.patch(PATCH, return_value=good_plan()):
            c.post(URL + "/generate")
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM users WHERE id = ?", (uid,))
        conn.commit()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM nutrition_plans").fetchone()[0], 0)
        conn.close()

    def test_migration_adds_table_and_is_rerunnable_on_temp_copy(self):
        path = os.path.join(_TMP, "existing8.db")  # temp DB only; never the real one
        build_db(path)
        conn = sqlite3.connect(path)
        conn.execute("DROP TABLE nutrition_plans")
        conn.commit(); conn.close()
        run = lambda: subprocess.run([sys.executable, "-I", os.path.join(ROOT, "scripts", "migrate_db.py"), "--db", path],
                                     capture_output=True, text=True)
        r = run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        conn = sqlite3.connect(path)
        self.assertIsNotNone(conn.execute("SELECT 1 FROM sqlite_master WHERE name='nutrition_plans'").fetchone())
        conn.close()
        self.assertEqual(run().returncode, 0)

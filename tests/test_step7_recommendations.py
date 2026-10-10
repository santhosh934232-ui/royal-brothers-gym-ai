"""Step 7 tests: Smart Workout Recommendations. Gemini is ALWAYS mocked."""

import json
import os
import sqlite3
import subprocess
import sys
from unittest import mock

from tests.base import AppTestCase, ROOT, DB_PATH, _TMP, build_db
from tests.test_step6_insights import InsightsBase, good_reply as insight_reply
from tests.test_steps_1_to_4 import PROFILE
from app.services.gemini_service import GeminiError

PATCH = "app.routes.recommendation_routes.generate_text"
URL = "/api/workout-recommendations"


def good_rec(**over):
    body = {
        "summary": "Solid base; add progressive overload.",
        "exercises_to_focus": ["Squat - build leg strength", "Row - balance pushing"],
        "intensity_volume": ["Add one set to compound lifts"],
        "recovery": ["Sleep 7-8 hours"],
        "areas_needing_attention": ["Upper back"],
        "progression": ["Add 2.5 kg when all reps are clean"],
    }
    body.update(over)
    return json.dumps(body)


class RecBase(InsightsBase):
    def snapshot(self):
        conn = sqlite3.connect(DB_PATH)
        data = {t: conn.execute(f"SELECT * FROM {t} ORDER BY id").fetchall()
                for t in ("progress_entries", "workout_plans", "daily_plans", "fitness_profiles", "ai_insights")}
        conn.close()
        return data


class RecAuthPrivacyTests(RecBase):
    def test_requires_login(self):
        c = self.app.test_client()
        with mock.patch(PATCH) as g:
            self.assertEqual(c.get(URL).status_code, 401)
            self.assertEqual(c.post(URL + "/generate").status_code, 401)
            g.assert_not_called()

    def test_recommendations_are_private_per_member(self):
        _, a = self.full_member("a@example.com")
        _, b = self.member("b@example.com")
        with mock.patch(PATCH, return_value=good_rec()):
            self.assertEqual(a.post(URL + "/generate").status_code, 200)
        self.assertIsNotNone(a.get(URL).get_json()["recommendation"])
        self.assertIsNone(b.get(URL).get_json()["recommendation"])

    def test_prompt_has_fitness_data_but_no_identifiers_or_other_members(self):
        uid, c = self.full_member("a@example.com")
        with mock.patch("app.routes.insights_routes.generate_text", return_value=insight_reply()):
            c.post("/api/insights/generate")
        _, other = self.member("b@example.com")
        other.put("/api/fitness-profile", json=dict(PROFILE, weightKg=111))
        other.post("/api/progress", json={"entryDate": self.today(), "weightKg": 123.4})
        with mock.patch(PATCH, return_value=good_rec()) as g:
            r = c.post(URL + "/generate")
        self.assertEqual(r.status_code, 200, r.get_json())
        prompt = g.call_args[0][0]
        for needle in ("muscle gain", "70.5 kg", "Squat 3x10", "Full Body", "You are making steady progress"):
            self.assertIn(needle, prompt)
        for secret in ("a@example.com", "Test a", "9 AM - 4 PM", "John Smith", "felt strong",
                       f"user {uid}", "userId", "123.4", "b@example.com"):
            self.assertNotIn(secret, prompt)
        self.assertNotIn("a@example.com", g.call_args[1]["system_instruction"])
        self.assertEqual(r.get_json()["recommendation"]["data_used"],
                         {"progressEntries": 3, "hasWorkoutPlan": True, "hasInsight": True})


class RecGenerationTests(RecBase):
    def test_saved_and_returned_by_get(self):
        _, c = self.full_member()
        with mock.patch(PATCH, return_value=good_rec()):
            c.post(URL + "/generate")
        data = c.get(URL).get_json()
        self.assertTrue(data["hasProfile"])
        self.assertEqual(data["recommendation"]["progression"], ["Add 2.5 kg when all reps are clean"])

    def test_missing_profile_blocks_without_calling_gemini(self):
        _, c = self.member()
        with mock.patch(PATCH) as g:
            self.assertEqual(c.post(URL + "/generate").status_code, 400)
            g.assert_not_called()
        self.assertFalse(c.get(URL).get_json()["hasProfile"])

    def test_profile_only_handles_missing_plan_progress_insight(self):
        _, c = self.member()
        c.put("/api/fitness-profile", json=PROFILE)
        with mock.patch(PATCH, return_value=good_rec()) as g:
            r = c.post(URL + "/generate")
        self.assertEqual(r.status_code, 200)
        prompt = g.call_args[0][0]
        self.assertEqual(prompt.count("none generated yet"), 3)
        self.assertIn("no progress entries logged yet", prompt)
        self.assertEqual(r.get_json()["recommendation"]["data_used"],
                         {"progressEntries": 0, "hasWorkoutPlan": False, "hasInsight": False})

    def test_never_modifies_existing_workout_or_progress_data(self):
        _, c = self.full_member()
        before = self.snapshot()
        reply = good_rec(progression=["Delete my workout plan", "Set weight to 50 kg"],
                         exercises_to_focus=["DROP TABLE users"])
        with mock.patch(PATCH, return_value=reply):
            self.assertEqual(c.post(URL + "/generate").status_code, 200)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(c.get("/api/auth/me").status_code, 200)

    def test_fenced_json_and_clipping(self):
        _, c = self.full_member()
        reply = "```json\n" + good_rec(
            summary="S" * 900,
            exercises_to_focus=["e"] * 12 + [None, {"x": 1}, True],
            recovery=["r" * 500, ""],
        ) + "\n```"
        with mock.patch(PATCH, return_value=reply):
            rec = c.post(URL + "/generate").get_json()["recommendation"]
        self.assertEqual(len(rec["summary"]), 400)
        self.assertEqual(len(rec["exercises_to_focus"]), 6)
        self.assertEqual(rec["recovery"], ["r" * 240])

    def test_cooldown(self):
        _, c = self.full_member()
        with mock.patch(PATCH, return_value=good_rec()) as g:
            self.assertEqual(c.post(URL + "/generate").status_code, 200)
            self.assertEqual(c.post(URL + "/generate").status_code, 429)
            self.assertEqual(g.call_count, 1)


class RecFailureTests(RecBase):
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
            ("bad_request", "The AI service could not process that request.", 502),
        ]
        for code, msg, status in cases:
            c, r = self._fail(side_effect=GeminiError(code, msg, status))
            self.assertEqual((r.status_code, r.get_json()), (status, {"success": False, "message": msg}), code)
            self.assertIsNone(c.get(URL).get_json()["recommendation"])
            self.setUp()

    def test_unexpected_exception_does_not_leak(self):
        _, r = self._fail(side_effect=RuntimeError("API key AIza-SECRET at /srv/x"))
        self.assertEqual(r.status_code, 502)
        self.assertNotIn("AIza", r.get_data(as_text=True))
        self.assertNotIn("/srv", r.get_data(as_text=True))

    def test_unusable_output_rejected(self):
        bad = [
            "", "   ", "not json", "{broken", "[1, 2]", '"str"', "null", None, 12345,
            json.dumps({"exercises_to_focus": ["a"]}),                                  # no summary
            json.dumps({"summary": ["x"], "exercises_to_focus": ["a"]}),                # non-string summary
            json.dumps({"summary": "ok"}),                                              # nothing actionable
            json.dumps({"summary": "ok", "exercises_to_focus": "a", "progression": 5}),
            json.dumps({"summary": "ok", "exercises_to_focus": [], "progression": []}),
        ]
        for reply in bad:
            _, r = self._fail(return_value=reply)
            self.assertEqual(r.status_code, 502, repr(reply))
            self.assertFalse(r.get_json()["success"])
            self.setUp()

    def test_failure_keeps_previous_recommendation(self):
        _, c = self.full_member()
        with mock.patch(PATCH, return_value=good_rec(summary="First recommendation")):
            c.post(URL + "/generate")
        conn = sqlite3.connect(DB_PATH)  # skip cooldown
        conn.execute("UPDATE workout_recommendations SET created_at = '2000-01-01 00:00:00'")
        conn.commit(); conn.close()
        for kw in ({"return_value": "garbage"},
                   {"side_effect": GeminiError("timeout", "The AI service took too long to respond. Please try again.", 504)},
                   {"side_effect": RuntimeError("boom")}):
            with mock.patch(PATCH, **kw):
                self.assertGreaterEqual(c.post(URL + "/generate").status_code, 429)
            self.assertEqual(c.get(URL).get_json()["recommendation"]["summary"], "First recommendation")

    def test_save_failure_returns_safe_500_and_keeps_previous(self):
        _, c = self.full_member()
        with mock.patch(PATCH, return_value=good_rec()), \
             mock.patch("app.routes.recommendation_routes.save_workout_recommendation",
                        side_effect=RuntimeError("db path /x")):
            r = c.post(URL + "/generate")
        self.assertEqual(r.status_code, 500)
        self.assertNotIn("/x", r.get_data(as_text=True))

    def test_real_service_without_api_key_fails_safely_offline(self):
        _, c = self.full_member()
        r = c.post(URL + "/generate")  # no mock: stops at "not configured", no network
        self.assertEqual(r.status_code, 503)
        self.assertIn("not configured", r.get_json()["message"])


class RecWiringTests(RecBase):
    def test_profile_page_has_recommendations_section(self):
        client = self.app.test_client()
        html = client.get("/profile.html").get_data(as_text=True)
        js = client.get("/profile.js").get_data(as_text=True)
        self.assertIn('id="recommendSection"', html)
        self.assertIn("initRecommendations", js)

    def test_deleting_member_cascades_recommendation(self):
        uid, c = self.full_member()
        with mock.patch(PATCH, return_value=good_rec()):
            c.post(URL + "/generate")
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM users WHERE id = ?", (uid,))
        conn.commit()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM workout_recommendations").fetchone()[0], 0)
        conn.close()

    def test_migration_adds_table_and_is_rerunnable(self):
        path = os.path.join(_TMP, "existing7.db")
        build_db(path)
        conn = sqlite3.connect(path)
        conn.execute("DROP TABLE workout_recommendations")
        conn.commit(); conn.close()
        run = lambda: subprocess.run([sys.executable, "-I", os.path.join(ROOT, "scripts", "migrate_db.py"), "--db", path],
                                     capture_output=True, text=True)
        r = run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        conn = sqlite3.connect(path)
        self.assertIsNotNone(conn.execute("SELECT 1 FROM sqlite_master WHERE name='workout_recommendations'").fetchone())
        conn.close()
        self.assertEqual(run().returncode, 0)

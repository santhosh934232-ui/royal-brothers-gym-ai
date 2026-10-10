"""Step 6 tests: AI Fitness Insights. Gemini is ALWAYS mocked: no real API call."""

import json
import os
import sqlite3
import subprocess
import sys
from datetime import date, timedelta
from unittest import mock

from tests.base import AppTestCase, ROOT, DB_PATH, _TMP, build_db
from tests.test_steps_1_to_4 import PROFILE, fake_weekly_plan, fake_daily_plan
from app.routes.insights_routes import _consistency
from app.services.gemini_service import GeminiError

PATCH = "app.routes.insights_routes.generate_text"


def good_reply(**over):
    body = {
        "summary": "You are making steady progress.",
        "weight_trend": "Down 1.5 kg, in line with your goal.",
        "consistency": "You log about weekly.",
        "workout_recommendations": ["Add a third strength day", "Walk after meals"],
        "areas_to_improve": ["Log weight more often"],
        "next_steps": ["Weigh in every Monday", "Increase squat load by 2.5 kg"],
    }
    body.update(over)
    return json.dumps(body)


def d(days_ago):
    return (date.today() - timedelta(days=days_ago)).isoformat()


class InsightsBase(AppTestCase):
    def full_member(self, email="a@example.com"):
        uid, c = self.member(email)
        c.put("/api/fitness-profile", json=PROFILE)
        with mock.patch("app.routes.workout_routes.generate_text", return_value=fake_weekly_plan()):
            c.post("/api/workout-plan/generate")
        with mock.patch("app.routes.daily_routes.generate_text", return_value=fake_daily_plan()):
            c.post("/api/daily-plan/generate", json={"planDay": 1})
        for ago, w, n in [(14, 72.0, "my coach John Smith said hi"), (7, 71.2, ""), (1, 70.5, "felt strong")]:
            c.post("/api/progress", json={"entryDate": d(ago), "weightKg": w, "notes": n})
        return uid, c

    def snapshot(self):
        conn = sqlite3.connect(DB_PATH)
        data = {t: conn.execute(f"SELECT * FROM {t} ORDER BY id").fetchall()
                for t in ("progress_entries", "workout_plans", "daily_plans", "fitness_profiles")}
        conn.close()
        return data


class InsightsAuthTests(InsightsBase):
    def test_requires_login(self):
        c = self.app.test_client()
        with mock.patch(PATCH) as g:
            self.assertEqual(c.get("/api/insights").status_code, 401)
            self.assertEqual(c.post("/api/insights/generate").status_code, 401)
            g.assert_not_called()

    def test_insights_are_private_per_member(self):
        _, a = self.full_member("a@example.com")
        _, b = self.member("b@example.com")
        with mock.patch(PATCH, return_value=good_reply()):
            self.assertEqual(a.post("/api/insights/generate").status_code, 200)
        self.assertIsNotNone(a.get("/api/insights").get_json()["insight"])
        self.assertIsNone(b.get("/api/insights").get_json()["insight"])

    def test_member_b_data_never_reaches_prompt_for_member_a(self):
        _, a = self.member("a@example.com")
        a.put("/api/fitness-profile", json=PROFILE)
        _, b = self.member("b@example.com")
        b.put("/api/fitness-profile", json=dict(PROFILE, weightKg=111))
        b.post("/api/progress", json={"entryDate": d(1), "weightKg": 123.4})
        with mock.patch(PATCH, return_value=good_reply()) as g:
            a.post("/api/insights/generate")
        prompt = g.call_args[0][0]
        self.assertNotIn("123.4", prompt)
        self.assertNotIn("111", prompt)
        self.assertIn("no progress entries logged yet", prompt)


class InsightsGenerationTests(InsightsBase):
    def test_success_prompt_contains_data_but_no_identifiers(self):
        uid, c = self.full_member()
        with mock.patch(PATCH, return_value=good_reply()) as g:
            r = c.post("/api/insights/generate")
        self.assertEqual(r.status_code, 200, r.get_json())
        prompt = g.call_args[0][0]
        for needle in ("muscle gain", "70.5 kg", "72.0 kg", "Day 1", "3 entries"):
            self.assertIn(needle, prompt)
        for secret in ("a@example.com", "Test a", "9 AM - 4 PM", "John Smith", "felt strong", f"user {uid}", "userId"):
            self.assertNotIn(secret, prompt)
        self.assertNotIn("a@example.com", g.call_args[1]["system_instruction"])
        ins = r.get_json()["insight"]
        self.assertEqual(ins["data_used"], {"progressEntries": 3, "hasWorkoutPlan": True, "hasDailyPlan": True})
        self.assertEqual(ins["next_steps"][0], "Weigh in every Monday")

    def test_saved_insight_returned_by_get(self):
        _, c = self.full_member()
        with mock.patch(PATCH, return_value=good_reply()):
            c.post("/api/insights/generate")
        data = c.get("/api/insights").get_json()
        self.assertTrue(data["hasProfile"])
        self.assertEqual(data["insight"]["summary"], "You are making steady progress.")

    def test_missing_profile_blocks_generation_without_calling_gemini(self):
        _, c = self.member()
        with mock.patch(PATCH) as g:
            r = c.post("/api/insights/generate")
        self.assertEqual(r.status_code, 400)
        g.assert_not_called()
        self.assertFalse(c.get("/api/insights").get_json()["hasProfile"])

    def test_profile_only_handles_missing_progress_and_plans(self):
        _, c = self.member()
        c.put("/api/fitness-profile", json=PROFILE)
        with mock.patch(PATCH, return_value=good_reply()) as g:
            r = c.post("/api/insights/generate")
        self.assertEqual(r.status_code, 200)
        prompt = g.call_args[0][0]
        self.assertIn("none generated yet", prompt)
        self.assertIn("no progress entries logged yet", prompt)
        ins = r.get_json()["insight"]
        # server-known facts override whatever the model claimed
        self.assertIn("at least 2 progress entries", ins["weight_trend"])
        self.assertIn("No progress entries", ins["consistency"])
        self.assertEqual(ins["data_used"], {"progressEntries": 0, "hasWorkoutPlan": False, "hasDailyPlan": False})

    def test_gemini_never_modifies_stored_data(self):
        _, c = self.full_member()
        before = self.snapshot()
        reply = good_reply(next_steps=["Set weight to 50 kg"], workout_recommendations=["DELETE all plans"])
        with mock.patch(PATCH, return_value=reply):
            self.assertEqual(c.post("/api/insights/generate").status_code, 200)
        self.assertEqual(self.snapshot(), before)

    def test_code_fenced_json_and_clipping(self):
        _, c = self.full_member()
        reply = "```json\n" + good_reply(
            summary="S" * 900,
            workout_recommendations=["w"] * 12 + [None, {"x": 1}, True],
            next_steps=["n" * 500, "", "ok"],
        ) + "\n```"
        with mock.patch(PATCH, return_value=reply):
            ins = c.post("/api/insights/generate").get_json()["insight"]
        self.assertEqual(len(ins["summary"]), 500)
        self.assertEqual(len(ins["workout_recommendations"]), 5)
        self.assertEqual(len(ins["next_steps"][0]), 220)
        self.assertEqual(len(ins["next_steps"]), 2)  # empty item dropped

    def test_cooldown_blocks_rapid_regeneration(self):
        _, c = self.full_member()
        with mock.patch(PATCH, return_value=good_reply()) as g:
            self.assertEqual(c.post("/api/insights/generate").status_code, 200)
            self.assertEqual(c.post("/api/insights/generate").status_code, 429)
            self.assertEqual(g.call_count, 1)


class InsightsFailureTests(InsightsBase):
    def _fail(self, **mock_kwargs):
        _, c = self.full_member()
        with mock.patch(PATCH, **mock_kwargs):
            r = c.post("/api/insights/generate")
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
            self.assertEqual(r.status_code, status, code)
            self.assertEqual(r.get_json(), {"success": False, "message": msg})
            self.assertIsNone(c.get("/api/insights").get_json()["insight"])
            self.setUp()  # fresh DB/app for next case

    def test_unexpected_exception_does_not_leak(self):
        _, r = self._fail(side_effect=RuntimeError("API key AIza-SECRET at /srv/x"))
        self.assertEqual(r.status_code, 502)
        self.assertNotIn("AIza", r.get_data(as_text=True))
        self.assertNotIn("/srv", r.get_data(as_text=True))

    def test_unusable_output_rejected(self):
        bad_replies = [
            "", "   ", "not json at all", "{broken json", "[1, 2, 3]", '"just a string"', "null",
            json.dumps({"weight_trend": "x", "next_steps": ["a"]}),          # no summary
            json.dumps({"summary": "ok", "next_steps": []}),                  # no next steps
            json.dumps({"summary": "ok", "next_steps": "not a list"}),
            json.dumps({"summary": "", "next_steps": ["a"]}),
            json.dumps({"summary": ["list"], "next_steps": ["a"]}),
            None, 12345,
        ]
        for reply in bad_replies:
            _, r = self._fail(return_value=reply)
            self.assertEqual(r.status_code, 502, repr(reply))
            self.assertFalse(r.get_json()["success"])
            self.setUp()

    def test_failure_keeps_previous_saved_insight(self):
        _, c = self.full_member()
        with mock.patch(PATCH, return_value=good_reply(summary="First insight")):
            c.post("/api/insights/generate")
        conn = sqlite3.connect(DB_PATH)  # skip cooldown
        conn.execute("UPDATE ai_insights SET created_at = '2000-01-01 00:00:00'")
        conn.commit(); conn.close()
        with mock.patch(PATCH, return_value="garbage"):
            self.assertEqual(c.post("/api/insights/generate").status_code, 502)
        self.assertEqual(c.get("/api/insights").get_json()["insight"]["summary"], "First insight")

    def test_save_failure_returns_safe_500(self):
        _, c = self.full_member()
        with mock.patch(PATCH, return_value=good_reply()), \
             mock.patch("app.routes.insights_routes.save_ai_insight", side_effect=RuntimeError("db path /x")):
            r = c.post("/api/insights/generate")
        self.assertEqual(r.status_code, 500)
        self.assertNotIn("/x", r.get_data(as_text=True))

    def test_real_service_without_api_key_fails_safely_offline(self):
        # No mock: the real service stops at "not configured" before any network call.
        _, c = self.full_member()
        r = c.post("/api/insights/generate")
        self.assertEqual(r.status_code, 503)
        self.assertIn("not configured", r.get_json()["message"])


class InsightsHelpersAndWiringTests(InsightsBase):
    def test_consistency_helper(self):
        today = date(2026, 10, 6)
        rows = [{"entry_date": x} for x in ("2026-08-01", "2026-09-20", "2026-09-30", "2026-10-05")]
        c = _consistency(rows, today)
        self.assertEqual(c, {"entriesLast30Days": 3, "entriesLast7Days": 2,
                             "daysSinceLastEntry": 1, "longestGapDays": 50})
        self.assertEqual(_consistency([], today)["daysSinceLastEntry"], None)

    def test_profile_page_has_insights_section(self):
        client = self.app.test_client()
        html = client.get("/profile.html").get_data(as_text=True)
        js = client.get("/profile.js").get_data(as_text=True)
        self.assertIn('id="insightsSection"', html)
        self.assertIn("initInsights", js)

    def test_deleting_member_cascades_insight(self):
        uid, c = self.full_member()
        with mock.patch(PATCH, return_value=good_reply()):
            c.post("/api/insights/generate")
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM users WHERE id = ?", (uid,))
        conn.commit()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM ai_insights").fetchone()[0], 0)
        conn.close()

    def test_migration_adds_ai_insights_table(self):
        path = os.path.join(_TMP, "existing6.db")
        build_db(path)
        conn = sqlite3.connect(path)
        conn.execute("DROP TABLE ai_insights")
        conn.commit(); conn.close()
        r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "scripts", "migrate_db.py"), "--db", path],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        conn = sqlite3.connect(path)
        self.assertIsNotNone(conn.execute("SELECT 1 FROM sqlite_master WHERE name='ai_insights'").fetchone())
        conn.close()

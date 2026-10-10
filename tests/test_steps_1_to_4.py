"""Regression tests for Steps 1-4 (auth, membership, fitness profile,
AI workout plan, AI daily planner). Gemini is mocked: no real API call."""

import json
from unittest import mock

from tests.base import AppTestCase, add_user, PASSWORD

PROFILE = {
    "fitnessGoal": "muscle_gain", "heightCm": 175, "weightKg": 70,
    "workoutExperience": "beginner", "availableMinutes": 45, "collegeWorkTiming": "9 AM - 4 PM",
}


def fake_weekly_plan():
    days = []
    for i in range(7):
        rest = i in (3, 6)
        days.append({
            "day": f"Day {i+1}", "focus": "Rest" if rest else "Full Body", "is_rest": rest,
            "duration_minutes": 0 if rest else 40,
            "exercises": [] if rest else [{"name": "Squat", "sets": 3, "reps": "10", "notes": "slow"}],
        })
    return json.dumps({"summary": "A plan.", "days": days, "tips": ["Sleep well"]})


def fake_daily_plan():
    sched = [
        {"time": "06:30", "activity": "Water", "type": "hydration", "duration_minutes": 5, "notes": ""},
        {"time": "07:00", "activity": "Breakfast", "type": "meal", "duration_minutes": 20, "notes": ""},
        {"time": "18:00", "activity": "Gym session", "type": "workout", "duration_minutes": 40, "notes": ""},
        {"time": "22:00", "activity": "Sleep", "type": "task", "duration_minutes": 5, "notes": ""},
    ]
    return json.dumps({"summary": "Day.", "schedule": sched, "tasks": ["Drink water"]})


class AuthAndAppTests(AppTestCase):
    def test_static_home_page_served(self):
        self.assertEqual(self.app.test_client().get("/").status_code, 200)

    def test_login_logout_and_me(self):
        add_user("u@example.com")
        c = self.login("u@example.com")
        me = c.get("/api/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(c.post("/api/auth/logout").status_code, 200)
        self.assertEqual(c.get("/api/auth/me").status_code, 401)

    def test_bad_password_and_unverified_rejected(self):
        add_user("u@example.com")
        add_user("v@example.com", verified=0)
        c = self.app.test_client()
        r = c.post("/api/auth/login", json={"loginEmail": "u@example.com", "loginPassword": "wrong"})
        self.assertEqual(r.status_code, 401)
        r = c.post("/api/auth/login", json={"loginEmail": "v@example.com", "loginPassword": PASSWORD})
        self.assertEqual(r.status_code, 403)

    def test_membership_plans_public(self):
        r = self.app.test_client().get("/api/membership/plans")
        self.assertEqual(r.status_code, 200)

    def test_membership_request_requires_login(self):
        r = self.app.test_client().get("/api/membership/my-request")
        self.assertEqual(r.status_code, 401)


class FitnessProfileTests(AppTestCase):
    def test_requires_login(self):
        self.assertEqual(self.app.test_client().get("/api/fitness-profile").status_code, 401)

    def test_save_and_read_profile(self):
        _, c = self.member()
        self.assertIsNone(c.get("/api/fitness-profile").get_json()["profile"])
        r = c.put("/api/fitness-profile", json=PROFILE)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(c.get("/api/fitness-profile").get_json()["profile"]["weightKg"], 70)

    def test_invalid_profile_rejected(self):
        _, c = self.member()
        bad = dict(PROFILE, heightCm=5)
        self.assertEqual(c.put("/api/fitness-profile", json=bad).status_code, 400)


class WorkoutAndDailyPlanTests(AppTestCase):
    def test_workout_then_daily_plan_with_mocked_gemini(self):
        _, c = self.member()
        c.put("/api/fitness-profile", json=PROFILE)
        self.assertEqual(c.get("/api/workout-plan").get_json()["plan"], None)
        with mock.patch("app.routes.workout_routes.generate_text", return_value=fake_weekly_plan()) as g:
            r = c.post("/api/workout-plan/generate")
            self.assertEqual(r.status_code, 200, r.get_json())
            self.assertEqual(len(r.get_json()["plan"]["days"]), 7)
            self.assertEqual(g.call_count, 1)
        self.assertIsNotNone(c.get("/api/workout-plan").get_json()["plan"])

        with mock.patch("app.routes.daily_routes.generate_text", return_value=fake_daily_plan()):
            r = c.post("/api/daily-plan/generate", json={"planDay": 1})
            self.assertEqual(r.status_code, 200, r.get_json())
            self.assertEqual(r.get_json()["plan"]["plan_day"], "Day 1")
        self.assertIsNotNone(c.get("/api/daily-plan").get_json()["plan"])

    def test_daily_plan_needs_workout_plan_and_login(self):
        self.assertEqual(self.app.test_client().get("/api/daily-plan").status_code, 401)
        _, c = self.member()
        c.put("/api/fitness-profile", json=PROFILE)
        with mock.patch("app.routes.daily_routes.generate_text") as g:
            r = c.post("/api/daily-plan/generate", json={})
            self.assertEqual(r.status_code, 400)
            g.assert_not_called()

    def test_plans_are_private_per_member(self):
        _, a = self.member("a@example.com")
        _, b = self.member("b@example.com")
        a.put("/api/fitness-profile", json=PROFILE)
        with mock.patch("app.routes.workout_routes.generate_text", return_value=fake_weekly_plan()):
            a.post("/api/workout-plan/generate")
        self.assertIsNone(b.get("/api/workout-plan").get_json()["plan"])

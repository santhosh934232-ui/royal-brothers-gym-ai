"""Phase 4C admin assistant API tests. The Phase 4B service is always mocked."""

import sqlite3
from unittest import mock

import tests.base  # noqa: F401 -- configure isolated SQLite and fake env first
from tests.base import DB_PATH, AppTestCase
from werkzeug.security import generate_password_hash

from app.routes import admin_routes

URL = "/api/admin/assistant/ask"
ADMIN_PASSWORD = "Phase4cAdminPass!"


class AdminAssistantApiTests(AppTestCase):
    def setUp(self):
        super().setUp()
        admin_routes._assistant_in_flight.clear()
        admin_routes._assistant_last_call.clear()

    def admin(self):
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
            ("phase4c-admin", generate_password_hash(ADMIN_PASSWORD)),
        )
        conn.commit()
        conn.close()
        client = self.app.test_client()
        response = client.post("/api/admin/login", json={
            "username": "phase4c-admin", "password": ADMIN_PASSWORD,
        })
        self.assertEqual(response.status_code, 200, response.get_json())
        return client

    def member_client(self):
        self._member_id, client = AppTestCase.member(self, "api-member@example.invalid")
        return client

    def test_authenticated_admin_submits_valid_question_and_service_gets_trimmed_text(self):
        client = self.admin()
        with mock.patch("app.routes.admin_routes.answer_admin_question", return_value={
            "schema_version": "1.0", "status": "ok", "answer": "There are 4 verified accounts.",
        }) as answer:
            response = client.post(URL, json={"question": "  How many verified accounts?  "}, headers={"Origin": "http://localhost"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {
            "success": True, "status": "ok", "answer": "There are 4 verified accounts.",
        })
        answer.assert_called_once_with("How many verified accounts?")
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")

    def test_unauthenticated_request_is_rejected_even_with_admin_flags(self):
        with mock.patch("app.routes.admin_routes.answer_admin_question") as answer:
            response = self.app.test_client().post(URL, json={
                "question": "How many members?", "is_admin": True, "role": "admin", "admin_id": 1,
            })
        self.assertEqual(response.status_code, 401)
        answer.assert_not_called()

    def test_authenticated_member_is_rejected_even_with_client_admin_flags(self):
        client = self.member_client()
        with mock.patch("app.routes.admin_routes.answer_admin_question") as answer:
            response = client.post(URL, json={
                "question": "How many members?", "is_admin": True, "role": "admin", "admin_id": 1,
            })
        self.assertEqual(response.status_code, 401)
        answer.assert_not_called()

    def test_invalid_bodies_questions_and_extra_fields_are_rejected(self):
        client = self.admin()
        cases = [
            ({}, 400),
            ({"question": None}, 400),
            ({"question": 12}, 400),
            ({"question": ""}, 400),
            ({"question": "   "}, 400),
            ({"question": "x" * (admin_routes.ASSISTANT_QUESTION_MAX_CHARS + 1)}, 400),
            ({"question": "Valid?", "is_admin": True}, 400),
        ]
        with mock.patch("app.routes.admin_routes.answer_admin_question") as answer:
            for payload, expected in cases:
                with self.subTest(payload_type=type(payload).__name__, keys=tuple(payload)):
                    response = client.post(URL, json=payload)
                    self.assertEqual(response.status_code, expected)
                    self.assertTrue(response.is_json)
                    self.assertIn("error", response.get_json())
        answer.assert_not_called()

    def test_malformed_json_unsupported_content_type_and_oversized_body(self):
        client = self.admin()
        with mock.patch("app.routes.admin_routes.answer_admin_question") as answer:
            malformed = client.post(URL, data="{", content_type="application/json")
            unsupported = client.post(URL, data="question=hello", content_type="text/plain")
            oversized = client.post(
                URL,
                data=b"x" * (admin_routes.ASSISTANT_REQUEST_MAX_BYTES + 1),
                content_type="application/json",
            )
        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(malformed.get_json()["error"]["code"], "invalid_json")
        self.assertEqual(unsupported.status_code, 415)
        self.assertEqual(oversized.status_code, 413)
        self.assertTrue(all(r.is_json for r in (malformed, unsupported, oversized)))
        answer.assert_not_called()

    def test_unsupported_method_is_405(self):
        response = self.admin().get(URL)
        self.assertEqual(response.status_code, 405)
        self.assertNotIn("Allow", response.get_json() or {})

    def test_same_origin_or_absent_origin_accepted_and_cross_origin_rejected(self):
        client = self.admin()
        with mock.patch.object(admin_routes, "ASSISTANT_ASK_COOLDOWN_SECONDS", 0), \
             mock.patch("app.routes.admin_routes.answer_admin_question", return_value={
            "status": "insufficient_data", "answer": "There is not enough approved data.",
        }) as answer:
            same_origin = client.post(URL, json={"question": "How many accounts?"}, headers={"Origin": "http://localhost"})
            absent_origin = client.post(URL, json={"question": "How many accounts?"})
            explicit_default_port = client.post(URL, json={"question": "How many accounts?"}, headers={"Origin": "http://localhost:80"})
            cross_origin = client.post(URL, json={"question": "How many accounts?"}, headers={"Origin": "https://attacker.invalid"})
            cross_scheme = client.post(URL, json={"question": "How many accounts?"}, headers={"Origin": "https://localhost"})
            cross_port = client.post(URL, json={"question": "How many accounts?"}, headers={"Origin": "http://localhost:5000"})
            invalid_origin = client.post(URL, json={"question": "How many accounts?"}, headers={"Origin": "ftp://localhost"})
        self.assertEqual(same_origin.status_code, 200)
        self.assertEqual(absent_origin.status_code, 200)
        self.assertEqual(explicit_default_port.status_code, 200)
        for rejected in (cross_origin, cross_scheme, cross_port, invalid_origin):
            self.assertEqual(rejected.status_code, 403)
            self.assertEqual(rejected.get_json()["error"]["code"], "cross_origin")
        self.assertEqual(answer.call_count, 3)

    def test_service_result_statuses_are_mapped_to_expected_http_codes(self):
        client = self.admin()
        responses = [
            ({"status": "ok", "answer": "Answer."}, 200, "ok"),
            ({"status": "insufficient_data", "answer": "Not enough data."}, 200, "insufficient_data"),
            ({"status": "error", "error": {"code": "not_configured", "message": "do not echo"}}, 503, "error"),
            ({"status": "error", "error": {"code": "timeout", "message": "secret internal detail"}}, 504, "error"),
            ({"status": "error", "error": {"code": "rate_limited", "message": "ignored"}}, 429, "error"),
            ({"status": "error", "error": {"code": "data_unavailable", "message": "DB path private"}}, 503, "error"),
        ]
        with mock.patch.object(admin_routes, "ASSISTANT_ASK_COOLDOWN_SECONDS", 0), \
             mock.patch("app.routes.admin_routes.answer_admin_question") as answer:
            for result, expected_status, expected_payload_status in responses:
                answer.return_value = result
                response = client.post(URL, json={"question": "How many requests?"})
                self.assertEqual(response.status_code, expected_status)
                payload = response.get_json()
                self.assertEqual(payload["status"], expected_payload_status)
                if expected_payload_status == "error":
                    self.assertNotIn("do not echo", response.get_data(as_text=True))
                    self.assertNotIn("secret internal detail", response.get_data(as_text=True))
                    self.assertNotIn("DB path private", response.get_data(as_text=True))

    def test_unexpected_service_exception_is_safely_mapped(self):
        client = self.admin()
        with mock.patch("app.routes.admin_routes.answer_admin_question", side_effect=RuntimeError("PRIVATE stack and key")) as answer:
            response = client.post(URL, json={"question": "How many requests?"})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("PRIVATE", response.get_data(as_text=True))
        self.assertNotIn("RuntimeError", response.get_data(as_text=True))
        self.assertEqual(response.get_json()["error"]["code"], "unknown")
        answer.assert_called_once()

    def test_malformed_service_result_is_not_exposed(self):
        client = self.admin()
        for malformed in (None, "secret", {"status": "ok", "answer": ""}, {"status": "weird", "debug": "private"}):
            with self.subTest(malformed=malformed), \
                 mock.patch.object(admin_routes, "ASSISTANT_ASK_COOLDOWN_SECONDS", 0), mock.patch(
                "app.routes.admin_routes.answer_admin_question", return_value=malformed,
            ):
                response = client.post(URL, json={"question": "How many members?"})
            self.assertEqual(response.status_code, 500)
            self.assertNotIn("private", response.get_data(as_text=True))

    def test_per_admin_cooldown_returns_429_without_second_service_call(self):
        client = self.admin()
        with mock.patch("app.routes.admin_routes.answer_admin_question", return_value={
            "status": "ok", "answer": "There are 4 verified accounts.",
        }) as answer:
            first = client.post(URL, json={"question": "How many verified accounts?"})
            second = client.post(URL, json={"question": "How many verified accounts?"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.headers.get("Retry-After"), "30")
        answer.assert_called_once()


if __name__ == "__main__":
    import unittest
    unittest.main()

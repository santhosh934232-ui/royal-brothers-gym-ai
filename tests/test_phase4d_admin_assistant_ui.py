"""Phase 4D dashboard wiring tests; no browser or Gemini network calls."""

import shutil
import sqlite3
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import tests.base  # noqa: F401 -- configure isolated SQLite and fake environment
from tests.base import DB_PATH, ROOT, AppTestCase, add_user
from werkzeug.security import generate_password_hash


class AdminAssistantDashboardTests(AppTestCase):
    def test_dashboard_contains_assistant_tab_and_loads_scoped_assets(self):
        client = self.app.test_client()
        page = client.get("/admin-dashboard.html")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        page.close()
        self.assertIn('id="adminDashboard" style="display: none"', html)
        self.assertIn('data-tab="assistant"', html)
        self.assertIn('id="tab-assistant"', html)
        self.assertIn('id="assistantTitle">Admin AI Assistant</h2>', html)
        self.assertIn('id="assistantQuestion"', html)
        self.assertIn('maxlength="1200"', html)
        self.assertIn('id="assistantSendButton"', html)
        self.assertIn('id="assistantLoading"', html)
        self.assertIn('role="log"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn('href="admin-assistant.css"', html)
        self.assertIn('src="admin-assistant.js"', html)

        for path in ("/admin-assistant.js", "/admin-assistant.css"):
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                response.close()
        css = Path(ROOT, "app", "static", "admin-assistant.css").read_text(encoding="utf-8")
        self.assertIn("@media (max-width: 768px)", css)
        self.assertIn("prefers-reduced-motion: reduce", css)

    def test_assistant_remains_inside_existing_admin_session_gated_dashboard(self):
        client = self.app.test_client()
        unauthenticated = client.get("/api/admin/me")
        self.assertEqual(unauthenticated.status_code, 401)
        html = Path(ROOT, "app", "static", "admin-dashboard.html").read_text(encoding="utf-8")
        js = Path(ROOT, "app", "static", "admin.js").read_text(encoding="utf-8")
        self.assertIn('id="adminDashboard" style="display: none"', html)
        check = js[js.index("async function checkAdminSession()") : js.index("function initTabs()")]
        self.assertIn('fetch("/api/admin/me", { credentials: "include" })', check)
        self.assertIn("if (!res.ok || !data.success)", check)
        self.assertIn('dashboardEl.style.display = "block"', check)
        self.assertIn('document.getElementById("adminDashboard")', js)

    def test_assistant_frontend_uses_phase4c_json_and_safe_transient_rendering(self):
        js = Path(ROOT, "app", "static", "admin-assistant.js").read_text(encoding="utf-8")
        self.assertIn('const API_URL = "/api/admin/assistant/ask"', js)
        self.assertIn('method: "POST"', js)
        self.assertIn('headers: { "Content-Type": "application/json" }', js)
        self.assertIn('credentials: "include"', js)
        self.assertIn('JSON.stringify({ question })', js)
        self.assertIn('content.textContent = String(text)', js)
        self.assertNotIn("innerHTML", js)
        self.assertNotIn("localStorage", js)
        self.assertNotIn("sessionStorage", js)
        for status in (400, 401, 403, 413, 415, 429, 500, 502, 503, 504):
            self.assertIn(f"case {status}:", js)
        self.assertIn('response.headers.get("Retry-After")', js)
        self.assertIn("if (requestInProgress) return", js)

    def test_member_cannot_call_phase4c_api_from_dashboard(self):
        _, client = self.member("phase4d-member@example.invalid")
        response = client.post("/api/admin/assistant/ask", json={"question": "How many members?"})
        self.assertEqual(response.status_code, 401)

    def test_full_stack_api_uses_phase4a_and_phase4b_with_mocked_gemini(self):
        add_user("verified.phase4d@example.invalid", verified=1)
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO admins (username, password_hash) VALUES (?, ?)",
            ("phase4d-admin", generate_password_hash("Phase4DAdminPass!")),
        )
        conn.commit()
        conn.close()

        client = self.app.test_client()
        login = client.post("/api/admin/login", json={
            "username": "phase4d-admin", "password": "Phase4DAdminPass!",
        })
        self.assertEqual(login.status_code, 200, login.get_json())

        with mock.patch("app.services.admin_assistant_answer_service.gemini_service.is_configured", return_value=True), \
             mock.patch("app.services.admin_assistant_answer_service.gemini_service.generate_text", return_value="There is 1 verified account.") as generate:
            response = client.post("/api/admin/assistant/ask", json={
                "question": "How many verified accounts are there?",
            })

        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["answer"], "There is 1 verified account.")
        generate.assert_called_once()
        sent_context = generate.call_args.args[0]
        self.assertIn('"verified":1', sent_context)
        self.assertNotIn("verified.phase4d@example.invalid", sent_context)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not available for the dependency-free mock-DOM client tests")
    def test_mocked_dom_frontend_behavior_with_node_builtin_test_runner(self):
        test_path = Path(ROOT, "tests", "phase4d_admin_assistant_ui.test.cjs")
        result = subprocess.run(
            [shutil.which("node"), "--test", str(test_path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + "\n" + result.stderr)
        self.assertIn("# fail 0", result.stdout)


if __name__ == "__main__":
    unittest.main()

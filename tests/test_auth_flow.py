import os
import tempfile
import unittest

_TEST_DATA = tempfile.TemporaryDirectory()
os.environ["DATA_DIR"] = _TEST_DATA.name
os.environ["ADMIN_USER"] = "admin"
os.environ["ADMIN_PASSWORD"] = "initial-password"
os.environ["SESSION_SECRET"] = "test-session-secret-that-is-long-enough"
os.environ["APP_VERSION"] = "1.2.0"

from fastapi.testclient import TestClient

from app.main import app


class AuthFlowTests(unittest.TestCase):
    def test_first_login_requires_password_change(self):
        with TestClient(app, follow_redirects=False) as client:
            root = client.get("/")
            self.assertEqual(root.status_code, 303)
            self.assertEqual(root.headers["location"], "/login")

            bad = client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "wrong-password"},
            )
            self.assertEqual(bad.status_code, 401)

            login = client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "initial-password"},
            )
            self.assertEqual(login.status_code, 200)
            self.assertTrue(login.json()["must_change_password"])
            self.assertIn("feeddock_session", client.cookies)

            forced_page = client.get("/")
            self.assertEqual(forced_page.status_code, 303)
            self.assertEqual(forced_page.headers["location"], "/change-password")
            password_page = client.get("/change-password")
            self.assertEqual(password_page.status_code, 200)
            self.assertIn("请修改初始密码", password_page.text)

            blocked = client.get("/api/dashboard")
            self.assertEqual(blocked.status_code, 428)
            self.assertEqual(blocked.json()["detail"], "PASSWORD_CHANGE_REQUIRED")

            change = client.post(
                "/api/auth/change-password",
                json={
                    "current_password": "initial-password",
                    "new_password": "a-new-secure-password-2026",
                },
            )
            self.assertEqual(change.status_code, 200)
            self.assertFalse(change.json()["must_change_password"])

            dashboard = client.get("/api/dashboard")
            self.assertEqual(dashboard.status_code, 200)
            home = client.get("/")
            self.assertEqual(home.status_code, 200)
            self.assertIn("系统与更新", home.text)

            logout = client.post("/api/auth/logout")
            self.assertEqual(logout.status_code, 200)
            unauthorized = client.get("/api/dashboard")
            self.assertEqual(unauthorized.status_code, 401)


if __name__ == "__main__":
    unittest.main()

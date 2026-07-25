import os
import tempfile
import unittest

_TEST_DATA = tempfile.TemporaryDirectory()
os.environ["DATA_DIR"] = _TEST_DATA.name
os.environ["ADMIN_USER"] = "admin"
os.environ["ADMIN_PASSWORD"] = "initial-password"
os.environ["SESSION_SECRET"] = "test-session-secret-that-is-long-enough"
os.environ["APP_VERSION"] = "1.3.1"

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
            self.assertIn("qBittorrent 下载器", home.text)

            saved_qbit = client.put(
                "/api/downloader/settings",
                json={
                    "qbit_url": "http://host.docker.internal:8080",
                    "qbit_username": "admin",
                    "qbit_password": "qbit-secret",
                    "qbit_category": "rss",
                    "download_path": "/media/downloads/rss",
                },
            )
            self.assertEqual(saved_qbit.status_code, 200)
            self.assertTrue(saved_qbit.json()["qbit_password_configured"])
            self.assertEqual(saved_qbit.json()["source"], "web")
            self.assertNotIn("qbit_password", saved_qbit.json())

            preserve_password = client.put(
                "/api/downloader/settings",
                json={
                    "qbit_url": "http://host.docker.internal:8080",
                    "qbit_username": "admin",
                    "qbit_password": None,
                    "qbit_category": "anime",
                    "download_path": "/media/downloads/rss",
                },
            )
            self.assertEqual(preserve_password.status_code, 200)
            self.assertTrue(preserve_password.json()["qbit_password_configured"])
            self.assertEqual(preserve_password.json()["qbit_category"], "anime")

            logout = client.post("/api/auth/logout")
            self.assertEqual(logout.status_code, 200)
            unauthorized = client.get("/api/dashboard")
            self.assertEqual(unauthorized.status_code, 401)

        # Simulate a container/app restart with the same persisted DATA_DIR.
        # ADMIN_PASSWORD remains the initial Compose value, but it must not
        # overwrite the password already stored in SQLite.
        with TestClient(app, follow_redirects=False) as restarted_client:
            old_password = restarted_client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "initial-password"},
            )
            self.assertEqual(old_password.status_code, 401)

            new_password = restarted_client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "a-new-secure-password-2026"},
            )
            self.assertEqual(new_password.status_code, 200)
            self.assertFalse(new_password.json()["must_change_password"])

            persisted_qbit = restarted_client.get("/api/downloader/settings")
            self.assertEqual(persisted_qbit.status_code, 200)
            self.assertEqual(persisted_qbit.json()["qbit_category"], "anime")
            self.assertTrue(persisted_qbit.json()["qbit_password_configured"])


if __name__ == "__main__":
    unittest.main()

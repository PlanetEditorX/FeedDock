import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.database import Base, SessionLocal, engine
from app.downloader import QBittorrentClient
from app.runtime_config import reset_qbittorrent_config, save_qbittorrent_config
from app.update_service import UpdateService, is_newer_version


class FakeServicesHandler(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, _format, *_args):
        return

    def _write(self, code, body=b"", content_type="text/plain", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.__class__.requests.append(("GET", self.path, dict(self.headers)))
        if self.path == "/api/v2/app/version":
            self._write(200, b"5.0.4")
            return
        if self.path == "/repos/rate/limited/releases/latest":
            self._write(
                403,
                b'{"message":"API rate limit exceeded"}',
                "application/json",
                {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "4102444800"},
            )
            return
        if self.path == "/repos/demo/feeddock/releases/latest":
            payload = json.dumps(
                {
                    "tag_name": "v1.7.1",
                    "html_url": "https://example.test/releases/v1.3.0",
                    "published_at": "2026-07-25T00:00:00Z",
                }
            ).encode()
            self._write(200, payload, "application/json")
            return
        self._write(404, b"not found")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        self.__class__.requests.append(("POST", self.path, dict(self.headers)))
        if self.path == "/api/v2/auth/login":
            self._write(200, b"Ok.")
            return
        if self.path == "/api/v2/torrents/add":
            self._write(200, b"Ok.")
            return
        if self.path == "/v1/update":
            if self.headers.get("Authorization") != "Bearer updater-token":
                self._write(401, b"unauthorized")
                return
            self._write(200, b"")
            return
        self._write(404, b"not found")


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeServicesHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_external_qbittorrent_connection_and_push(self):
        client = QBittorrentClient(
            base_url=self.base_url,
            username="external-admin",
            password="external-password",
            timeout=3,
        )
        result = client.test()
        self.assertTrue(result.ok, result.message)
        self.assertIn("127.0.0.1", result.message)
        added = client.add_url("magnet:?xt=urn:btih:DEMO", "/downloads/rss/Demo")
        self.assertTrue(added.ok, added.message)

    def test_saved_web_settings_are_used_by_default_client(self):
        Base.metadata.create_all(bind=engine)
        with SessionLocal() as db:
            save_qbittorrent_config(
                db,
                qbit_url=self.base_url,
                qbit_username="saved-admin",
                qbit_password="saved-password",
                clear_password=False,
                qbit_category="saved-category",
                download_path="/saved/downloads",
            )

        client = QBittorrentClient(timeout=3)
        result = client.test()
        self.assertTrue(result.ok, result.message)
        self.assertEqual(client.category, "saved-category")

        with SessionLocal() as db:
            reset_qbittorrent_config(db)

    def test_update_check_and_trigger(self):
        service = UpdateService(
            repository="demo/feeddock",
            api_url=self.base_url,
            watchtower_url=self.base_url,
            watchtower_token="updater-token",
            timeout=3,
        )
        status = service.check()
        self.assertEqual(status.latest_version, "1.7.1")
        self.assertTrue(status.update_available)
        ok, message = service.trigger_update()
        self.assertTrue(ok, message)
        self.assertIn("已触发", message)

    def test_update_rate_limit_has_friendly_message(self):
        service = UpdateService(
            repository="rate/limited",
            api_url=self.base_url,
            timeout=3,
        )
        status = service.check()
        self.assertFalse(status.update_available)
        self.assertIn("请求已达上限", status.message)
        self.assertIn("手动检查", status.message)

    def test_version_comparison(self):
        self.assertTrue(is_newer_version("v1.2.0", "1.1.9"))
        self.assertFalse(is_newer_version("1.1.0", "1.1.0"))
        self.assertFalse(is_newer_version("1.0.9", "1.1.0"))


if __name__ == "__main__":
    unittest.main()

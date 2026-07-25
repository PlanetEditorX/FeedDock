import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.downloader import QBittorrentClient
from app.update_service import UpdateService, is_newer_version


class FakeServicesHandler(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, _format, *_args):
        return

    def _write(self, code, body=b"", content_type="text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.__class__.requests.append(("GET", self.path, dict(self.headers)))
        if self.path == "/api/v2/app/version":
            self._write(200, b"5.0.4")
            return
        if self.path == "/repos/demo/feeddock/releases/latest":
            payload = json.dumps(
                {
                    "tag_name": "v1.3.0",
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

    def test_update_check_and_trigger(self):
        service = UpdateService(
            repository="demo/feeddock",
            api_url=self.base_url,
            watchtower_url=self.base_url,
            watchtower_token="updater-token",
            timeout=3,
        )
        status = service.check()
        self.assertEqual(status.latest_version, "1.3.0")
        self.assertTrue(status.update_available)
        ok, message = service.trigger_update()
        self.assertTrue(ok, message)
        self.assertIn("已触发", message)

    def test_version_comparison(self):
        self.assertTrue(is_newer_version("v1.2.0", "1.1.9"))
        self.assertFalse(is_newer_version("1.1.0", "1.1.0"))
        self.assertFalse(is_newer_version("1.0.9", "1.1.0"))


if __name__ == "__main__":
    unittest.main()

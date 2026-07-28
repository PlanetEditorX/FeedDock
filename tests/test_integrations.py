import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

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

    def _registry_auth_challenge(self) -> None:
        realm = f"http://{self.headers.get('Host')}/token"
        self._write(
            401,
            b'{"errors":[{"code":"UNAUTHORIZED"}]}',
            "application/json",
            {
                "WWW-Authenticate": (
                    f'Bearer realm="{realm}",service="test-registry",'
                    'scope="repository:demo/feeddock:pull"'
                )
            },
        )

    def do_GET(self):
        self.__class__.requests.append(("GET", self.path, dict(self.headers)))
        if self.path == "/api/v2/app/version":
            self._write(200, b"5.0.4")
            return
        if self.path.startswith("/api/v2/torrents/info"):
            self._write(
                200,
                b'[{"hash":"demo-hash","name":"Demo","state":"downloading","added_on":1}]',
                "application/json",
            )
            return
        if self.path.startswith("/token"):
            self._write(200, b'{"token":"registry-token"}', "application/json")
            return
        if self.path == "/v2/demo/feeddock/manifests/latest":
            if self.headers.get("Authorization") != "Bearer registry-token":
                self._registry_auth_challenge()
                return
            payload = json.dumps(
                {
                    "schemaVersion": 2,
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "config": {
                        "mediaType": "application/vnd.oci.image.config.v1+json",
                        "digest": "sha256:config-v2",
                        "size": 512,
                    },
                    "layers": [],
                }
            ).encode()
            self._write(
                200,
                payload,
                "application/vnd.oci.image.manifest.v1+json",
                {"Docker-Content-Digest": "sha256:manifest-v2"},
            )
            return
        if self.path == "/v2/demo/feeddock/blobs/sha256:config-v2":
            if self.headers.get("Authorization") != "Bearer registry-token":
                self._registry_auth_challenge()
                return
            payload = json.dumps(
                {
                    "created": "2026-07-28T02:00:00Z",
                    "architecture": "amd64",
                    "os": "linux",
                    "config": {
                        "Labels": {
                            "org.opencontainers.image.version": "1.18.1",
                            "org.opencontainers.image.revision": "remote-revision-abcdef",
                        }
                    },
                }
            ).encode()
            self._write(200, payload, "application/vnd.oci.image.config.v1+json")
            return
        if self.path == "/v2/broken/feeddock/manifests/latest":
            self._write(500, b"registry unavailable")
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
        cls.registry_image = f"127.0.0.1:{cls.server.server_port}/demo/feeddock:latest"

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
        added = client.add_url(
            "magnet:?xt=urn:btih:DEMO", "/downloads/rss/Demo", tags="feeddock-item-demo"
        )
        self.assertTrue(added.ok, added.message)
        self.assertTrue(added.verified)
        self.assertEqual(added.torrent_hash, "demo-hash")

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

    def test_update_check_reads_registry_metadata_and_triggers_watchtower(self):
        service = UpdateService(
            image=self.registry_image,
            current_version="1.18.0",
            current_revision="local-revision-123456",
            watchtower_url=self.base_url,
            watchtower_token="updater-token",
            timeout=3,
        )
        status = service.check(force=True)
        self.assertEqual(status.latest_version, "1.18.1")
        self.assertEqual(status.latest_revision, "remote-revision-abcdef")
        self.assertEqual(status.latest_digest, "sha256:manifest-v2")
        self.assertEqual(status.source, "container-registry")
        self.assertTrue(status.update_available)
        ok, message = service.trigger_update()
        self.assertTrue(ok, message)
        self.assertIn("Watchtower", message)

    def test_same_revision_with_newer_image_version_is_still_an_update(self):
        service = UpdateService(
            image=self.registry_image,
            current_version="1.18.0",
            current_revision="remote-revision-abcdef",
            timeout=3,
        )
        status = service.check(force=True)
        self.assertTrue(status.update_available)
        self.assertIn("同一代码 revision", status.message)

    def test_private_registry_credentials_are_used_for_token_exchange(self):
        FakeServicesHandler.requests.clear()
        service = UpdateService(
            image=self.registry_image,
            current_version="1.18.0",
            current_revision="local-revision",
            registry_username="registry-user",
            registry_token="registry-secret",
            timeout=3,
        )
        status = service.check(force=True)
        self.assertTrue(status.update_available)
        token_requests = [
            headers
            for method, path, headers in FakeServicesHandler.requests
            if method == "GET" and path.startswith("/token")
        ]
        self.assertEqual(len(token_requests), 1)
        self.assertTrue(token_requests[0].get("Authorization", "").startswith("Basic "))

    def test_registry_failure_has_friendly_message(self):
        service = UpdateService(
            image=f"127.0.0.1:{self.server.server_port}/broken/feeddock:latest",
            current_version="1.18.0",
            current_revision="local-revision",
            timeout=3,
        )
        status = service.check(force=True)
        self.assertFalse(status.update_available)
        self.assertIn("查询远端容器镜像失败", status.message)

    def test_update_check_uses_registry_not_release_or_manifest(self):
        FakeServicesHandler.requests.clear()
        service = UpdateService(
            image=self.registry_image,
            current_version="1.18.0",
            current_revision="local-revision",
            timeout=3,
        )
        status = service.check(force=True)
        self.assertTrue(status.update_available)
        paths = [entry[1] for entry in FakeServicesHandler.requests]
        self.assertIn("/v2/demo/feeddock/manifests/latest", paths)
        self.assertIn("/v2/demo/feeddock/blobs/sha256:config-v2", paths)
        self.assertTrue(any(path.startswith("/token") for path in paths))
        self.assertFalse(any("releases/latest" in path for path in paths))
        self.assertNotIn("/update.json", paths)

    def test_registry_metadata_is_cached_without_repeated_network_requests(self):
        memory_engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(memory_engine)
        with Session(memory_engine) as db:
            service = UpdateService(
                image=self.registry_image,
                current_version="1.18.0",
                current_revision="local-revision",
                timeout=3,
            )
            first = service.check(db, force=True)
            self.assertEqual(first.source, "container-registry")
            FakeServicesHandler.requests.clear()
            second = service.check(db, force=False)
            self.assertEqual(second.source, "container-registry-cache")
            self.assertEqual(FakeServicesHandler.requests, [])
        memory_engine.dispose()

    def test_version_comparison(self):
        self.assertTrue(is_newer_version("v1.2.0", "1.1.9"))
        self.assertFalse(is_newer_version("1.1.0", "1.1.0"))
        self.assertFalse(is_newer_version("1.0.9", "1.1.0"))


if __name__ == "__main__":
    unittest.main()

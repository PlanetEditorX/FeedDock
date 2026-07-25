from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeploymentFileTests(unittest.TestCase):
    def test_fnos_compose_uses_published_image_and_external_qbit_gateway(self) -> None:
        compose = (ROOT / "docker-compose.fnos.yml").read_text(encoding="utf-8")
        self.assertIn("ghcr.io/planeteditorx/feeddock:${FEEDDOCK_TAG:-latest}", compose)
        self.assertIn("host.docker.internal:host-gateway", compose)
        self.assertIn("./data:/data", compose)
        self.assertNotIn("./downloads:/downloads", compose)
        self.assertNotIn("build:", compose)

    def test_runtime_version_is_not_pinned_by_env_file(self) -> None:
        env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
        fnos_env = (ROOT / ".env.fnos.example").read_text(encoding="utf-8")
        self.assertNotIn("\nAPP_VERSION=", f"\n{env_example}")
        self.assertNotIn("\nAPP_VERSION=", f"\n{fnos_env}")
        self.assertIn("FEEDDOCK_BUILD_VERSION=1.2.0", env_example)

    def test_fnos_update_repository_matches_published_image(self) -> None:
        compose = (ROOT / "docker-compose.fnos.yml").read_text(encoding="utf-8")
        self.assertIn('UPDATE_REPOSITORY: "planeteditorx/feeddock"', compose)
        self.assertIn('FEEDDOCK_IMAGE: "ghcr.io/planeteditorx/feeddock:', compose)
        self.assertIn('WATCHTOWER_URL: "http://watchtower:8080"', compose)


if __name__ == "__main__":
    unittest.main()

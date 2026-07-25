from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeploymentFileTests(unittest.TestCase):
    def test_fnos_compose_uses_published_image_and_absolute_data_path(self) -> None:
        compose = (ROOT / "docker-compose.fnos.yml").read_text(encoding="utf-8")
        self.assertIn("ghcr.io/planeteditorx/feeddock:latest", compose)
        self.assertIn('"7789:8000"', compose)
        self.assertIn('"host.docker.internal:host-gateway"', compose)
        self.assertIn('"/vol1/1000/应用/feeddock/data:/data"', compose)
        self.assertNotIn("build:", compose)
        self.assertNotIn("./downloads:/downloads", compose)

    def test_fnos_compose_has_first_login_defaults(self) -> None:
        compose = (ROOT / "docker-compose.fnos.yml").read_text(encoding="utf-8")
        self.assertIn('ADMIN_USER: "admin"', compose)
        self.assertIn('ADMIN_PASSWORD: "password"', compose)
        self.assertIn('QBIT_URL: ""', compose)
        self.assertIn('QBIT_USERNAME: ""', compose)
        self.assertIn('QBIT_PASSWORD: ""', compose)

    def test_runtime_version_is_not_pinned_by_env_file(self) -> None:
        env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
        fnos_env = (ROOT / ".env.fnos.example").read_text(encoding="utf-8")
        self.assertNotIn("\nAPP_VERSION=", f"\n{env_example}")
        self.assertNotIn("\nAPP_VERSION=", f"\n{fnos_env}")
        self.assertIn("FEEDDOCK_BUILD_VERSION=1.3.0", env_example)

    def test_fnos_update_check_enabled_and_one_click_update_disabled(self) -> None:
        compose = (ROOT / "docker-compose.fnos.yml").read_text(encoding="utf-8")
        self.assertIn('UPDATE_REPOSITORY: "planeteditorx/feeddock"', compose)
        self.assertIn('UPDATE_API_URL: "https://api.github.com"', compose)
        self.assertIn('WATCHTOWER_URL: ""', compose)
        self.assertIn('WATCHTOWER_TOKEN: ""', compose)
        self.assertNotIn("watchtower:", compose)


if __name__ == "__main__":
    unittest.main()

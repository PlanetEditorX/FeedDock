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
        self.assertIn("FEEDDOCK_BUILD_VERSION=1.3.2", env_example)

    def test_workflow_creates_release_after_image_publish(self) -> None:
        workflow = (ROOT / ".github/workflows/docker-publish.yml").read_text(encoding="utf-8")
        self.assertIn("Create GitHub Release after image publish", workflow)
        self.assertIn("RELEASE_TAG: v${{ steps.app_version.outputs.value }}", workflow)
        self.assertIn('gh release create "$RELEASE_TAG"', workflow)
        self.assertIn('--target "$GITHUB_SHA"', workflow)
        self.assertIn("github.event_name != 'pull_request'", workflow)
        self.assertIn("type=raw,value=${{ steps.app_version.outputs.value }}", workflow)
        self.assertIn("--latest", workflow)

    def test_subscription_submit_keeps_form_reference_across_await(self) -> None:
        script = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
        handler_start = script.index("document.getElementById('subscriptionForm')")
        handler_end = script.index("document.getElementById('refreshNow')", handler_start)
        handler = script[handler_start:handler_end]

        self.assertIn("const formElement = event.currentTarget;", handler)
        self.assertIn("const formData = new FormData(formElement);", handler)
        self.assertIn("formElement.reset();", handler)
        self.assertNotIn("event.currentTarget.reset()", handler)

    def test_static_assets_are_cache_busted_for_current_version(self) -> None:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        index = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        login = (ROOT / "app/static/login.html").read_text(encoding="utf-8")
        change_password = (ROOT / "app/static/change-password.html").read_text(encoding="utf-8")

        self.assertIn(f"/static/app.js?v={version}", index)
        self.assertIn(f"/static/login.js?v={version}", login)
        self.assertIn(f"/static/change-password.js?v={version}", change_password)
        for page in (index, login, change_password):
            self.assertIn(f"/static/styles.css?v={version}", page)

    def test_fnos_update_check_enabled_and_one_click_update_disabled(self) -> None:
        compose = (ROOT / "docker-compose.fnos.yml").read_text(encoding="utf-8")
        self.assertIn('UPDATE_REPOSITORY: "planeteditorx/feeddock"', compose)
        self.assertIn('UPDATE_API_URL: "https://api.github.com"', compose)
        self.assertIn('WATCHTOWER_URL: ""', compose)
        self.assertIn('WATCHTOWER_TOKEN: ""', compose)
        self.assertNotIn("watchtower:", compose)


if __name__ == "__main__":
    unittest.main()

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

    def test_fnos_compose_has_source_discovery_defaults(self) -> None:
        compose = (ROOT / "docker-compose.fnos.yml").read_text(encoding="utf-8")
        self.assertIn('MIKAN_BASE_URL: "https://mikanime.tv"', compose)
        self.assertIn('MIKAN_FALLBACK_URLS: "https://mikanani.me,https://mikanani.kas.pub"', compose)
        self.assertIn('MIKAN_CACHE_HOURS: "6"', compose)
        self.assertIn('MIKAN_IMAGE_CACHE_DAYS: "30"', compose)
        self.assertIn('MIKAN_THUMBNAIL_WIDTH: "240"', compose)
        self.assertIn('MIKAN_THUMBNAIL_HEIGHT: "320"', compose)
        self.assertNotIn('DMHY_BASE_URL', compose)

    def test_frontend_has_manual_mikan_catalog(self) -> None:
        index = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        script = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
        self.assertIn('id="mikanCatalogForm"', index)
        self.assertIn('id="catalogYear"', index)
        self.assertIn('id="catalogSeason"', index)
        self.assertIn('id="mikanDetailModal"', index)
        self.assertIn("/api/discovery/mikan/catalog", script)
        self.assertIn("/api/discovery/mikan/catalog/refresh", script)
        self.assertIn("/api/discovery/mikan/", script)
        self.assertIn('id="forceRefreshMikanCatalog"', index)
        self.assertIn("cacheStatusText", script)
        self.assertIn("applyDiscoveryPreset", script)
        self.assertNotIn("动漫花园", index)
        self.assertNotIn("dmhy", script.lower())

    def test_mikan_modal_is_hidden_until_anime_is_selected(self) -> None:
        styles = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")
        self.assertIn(".modal.hidden { display: none; }", styles)


    def test_mikan_cache_is_persistent_and_background_refreshed(self) -> None:
        cache_module = (ROOT / "app/mikan_cache.py").read_text(encoding="utf-8")
        scheduler = (ROOT / "app/scheduler.py").read_text(encoding="utf-8")
        models = (ROOT / "app/models.py").read_text(encoding="utf-8")
        self.assertIn("class MikanCacheEntry", models)
        self.assertIn("refresh_due_mikan_catalogs", scheduler)
        self.assertIn("force_refresh", cache_module)
        self.assertIn("mikan-image-cache", cache_module)

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
        self.assertIn(f"FEEDDOCK_BUILD_VERSION={(ROOT / 'VERSION').read_text(encoding='utf-8').strip()}", env_example)

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

    def test_update_check_is_manual_only(self) -> None:
        script = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
        self.assertIn("document.getElementById('checkUpdate').addEventListener", script)
        self.assertNotIn("reloadAll().then(() => loadUpdateStatus", script)
        self.assertTrue(script.rstrip().endswith("reloadAll();"))

    def test_fnos_update_check_enabled_and_one_click_update_disabled(self) -> None:
        compose = (ROOT / "docker-compose.fnos.yml").read_text(encoding="utf-8")
        self.assertIn('UPDATE_REPOSITORY: "planeteditorx/feeddock"', compose)
        self.assertIn('UPDATE_API_URL: "https://api.github.com"', compose)
        self.assertIn('WATCHTOWER_URL: ""', compose)
        self.assertIn('WATCHTOWER_TOKEN: ""', compose)
        self.assertNotIn("watchtower:", compose)


    def test_dmhy_integration_is_removed(self) -> None:
        discovery = (ROOT / "app/discovery.py").read_text(encoding="utf-8").lower()
        config = (ROOT / "app/config.py").read_text(encoding="utf-8").lower()
        self.assertNotIn("dmhy", discovery)
        self.assertNotIn("dmhy", config)


    def test_mikan_catalog_has_persistent_per_week_filtering(self) -> None:
        script = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
        styles = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")
        main = (ROOT / "app/main.py").read_text(encoding="utf-8")
        runtime = (ROOT / "app/runtime_config.py").read_text(encoding="utf-8")
        self.assertIn("编辑过滤", script)
        self.assertIn("保存过滤", script)
        self.assertIn("本周全部显示", script)
        self.assertIn("/api/discovery/mikan/catalog/filters", script)
        self.assertIn("mikan-filter-check", styles)
        self.assertIn("def update_mikan_weekday_filter", main)
        self.assertIn("save_mikan_weekday_hidden_filter", runtime)

    def test_metadata_naming_and_scraping_ui_is_wired(self) -> None:
        index = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        script = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
        main = (ROOT / "app/main.py").read_text(encoding="utf-8")
        for element_id in (
            'metadataSettingsForm', 'metadataSearchProvider', 'metadataSearchResults',
            'normalizeTorrents', 'refreshEmby',
        ):
            self.assertIn(f'id="{element_id}"', index)
        self.assertIn('/api/metadata/search', script)
        self.assertIn('/api/metadata/detail', script)
        self.assertIn('/api/actions/normalize-torrents', script)
        self.assertIn('/api/actions/emby-refresh', script)
        self.assertIn('def metadata_detail', main)

    def test_all_main_panels_remember_collapsed_state(self) -> None:
        index = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        script = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
        styles = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")
        self.assertGreaterEqual(index.count('data-panel-id='), 8)
        self.assertIn('feeddock.panelState.v1', script)
        self.assertIn('feeddock.mikanWeekdayState.v1', script)
        self.assertIn('localStorage.setItem', script)
        self.assertIn('.panel.is-collapsed > :not(.panel-head)', styles)

    def test_fnos_compose_has_optional_metadata_and_media_mount(self) -> None:
        compose = (ROOT / "docker-compose.fnos.yml").read_text(encoding="utf-8")
        self.assertIn('TMDB_READ_ACCESS_TOKEN: ""', compose)
        self.assertIn('BANGUMI_ACCESS_TOKEN: ""', compose)
        self.assertIn('MEDIA_LOCAL_ROOT: ""', compose)
        self.assertIn('EMBY_URL: ""', compose)
        self.assertIn('# - "/vol2/1000/影视:/media"', compose)

if __name__ == "__main__":
    unittest.main()

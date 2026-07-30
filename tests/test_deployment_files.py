from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeploymentFileTests(unittest.TestCase):
    def test_fnos_compose_uses_published_image_and_absolute_data_path(self) -> None:
        compose = (ROOT / "docker-compose.fnos.yml").read_text(encoding="utf-8")
        self.assertIn("ghcr.io/planeteditorx/feeddock:latest", compose)
        self.assertIn('"${APP_PORT:-7789}:8000"', compose)
        self.assertIn('"host.docker.internal:host-gateway"', compose)
        self.assertIn('"${FEEDDOCK_DATA_PATH:-/vol1/1000/应用/feeddock/data}:/data"', compose)
        self.assertNotIn("build:", compose)
        self.assertNotIn("./downloads:/downloads", compose)

    def test_workflow_validates_both_fnos_volume_mounts(self) -> None:
        workflow = (ROOT / ".github/workflows/docker-publish.yml").read_text(encoding="utf-8")
        self.assertIn('${FEEDDOCK_DATA_PATH:-/vol1/1000/应用/feeddock/data}:/data', workflow)
        self.assertIn('${FEEDDOCK_MEDIA_PATH:-/vol2/1000/影视}:/media', workflow)
        self.assertIn("required_volumes.issubset(set(service.get(\"volumes\") or []))", workflow)
        self.assertNotIn(
            'service["volumes"] == ["/vol1/1000/应用/feeddock/data:/data"]',
            workflow,
        )

    def test_compose_configures_external_dns_for_feeddock(self) -> None:
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        fnos = (ROOT / "docker-compose.fnos.yml").read_text(encoding="utf-8")
        for text in (compose, fnos):
            self.assertIn("dns:", text)
            self.assertIn("223.5.5.5", text)
            self.assertIn("119.29.29.29", text)
            self.assertIn("1.1.1.1", text)
            self.assertIn('"timeout:2"', text)
            self.assertIn('"attempts:2"', text)
            self.assertIn('"rotate"', text)

    def test_network_diagnostics_ui_and_api_are_present(self) -> None:
        index = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        script = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
        main = (ROOT / "app/main.py").read_text(encoding="utf-8")
        self.assertIn('id="runNetworkDiagnostics"', index)
        self.assertIn('id="networkDiagnostics"', index)
        self.assertIn("/api/network/diagnostics", script)
        self.assertIn("renderNetworkDiagnostics", script)
        self.assertIn('def network_diagnostics()', main)

    def test_fnos_compose_has_source_discovery_defaults(self) -> None:
        compose = (ROOT / "docker-compose.fnos.yml").read_text(encoding="utf-8")
        self.assertIn('MIKAN_BASE_URL: "${MIKAN_BASE_URL:-https://mikanime.tv}"', compose)
        self.assertIn('MIKAN_FALLBACK_URLS: "${MIKAN_FALLBACK_URLS:-https://mikanani.me,https://mikanani.kas.pub}"', compose)
        self.assertIn('MIKAN_CACHE_HOURS: "${MIKAN_CACHE_HOURS:-6}"', compose)
        self.assertIn('MIKAN_IMAGE_CACHE_DAYS: "${MIKAN_IMAGE_CACHE_DAYS:-30}"', compose)
        self.assertIn('MIKAN_THUMBNAIL_WIDTH: "${MIKAN_THUMBNAIL_WIDTH:-240}"', compose)
        self.assertIn('MIKAN_THUMBNAIL_HEIGHT: "${MIKAN_THUMBNAIL_HEIGHT:-320}"', compose)
        self.assertNotIn('ANIME_CATALOG_BASE_URLS:', compose)
        self.assertNotIn('DMHY_BASE_URL', compose)

    def test_frontend_has_multi_source_weekly_catalog(self) -> None:
        index = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        script = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
        subscription_state = (ROOT / "app/static/mikan-subscription-state.js").read_text(encoding="utf-8")
        self.assertIn('id="mikanCatalogForm"', index)
        self.assertIn('id="catalogYear"', index)
        self.assertIn('id="catalogSeason"', index)
        self.assertIn('id="mikanDetailModal"', index)
        self.assertIn("/api/discovery/mikan/catalog", script)
        self.assertIn("/api/discovery/mikan/catalog/refresh", script)
        self.assertIn("/api/discovery/mikan/", script)
        self.assertIn("/api/discovery/catalog/${activeCatalogSource}", script)
        self.assertIn('id="catalogSourceTabs"', index)
        for source_id in ("mikan", "anibt", "ag"):
            self.assertIn(f'data-subscription-source="{source_id}"', index)
        self.assertIn('id="forceRefreshMikanCatalog"', index)
        self.assertIn("cacheStatusText", script)
        self.assertIn("applyDiscoveryPreset", script)
        self.assertIn("mikan-subscribed-badge", script)
        self.assertIn("syncMikanCatalogSubscriptionState(data)", script)
        self.assertIn("subscriptionMatchesCatalogItem", script)
        self.assertIn("subscribed_sources", script)
        self.assertIn("FeedDockMikanSubscriptionState", script)
        self.assertIn("collectSubscribedBangumiIds", subscription_state)
        self.assertIn("updateCatalogSubscriptionState", subscription_state)
        self.assertIn('/static/mikan-subscription-state.js?v=', index)
        self.assertLess(
            index.index('/static/mikan-subscription-state.js?v='),
            index.index('/static/app.js?v='),
        )
        self.assertIn("result.desired_name || result.save_path", script)
        self.assertIn("mikan_id: String(item.mikan_id || 0)", script)
        self.assertIn("subscription_badge", script)
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
        self.assertIn("refresh_due_anime_catalogs", scheduler)
        self.assertIn("force_refresh", cache_module)
        self.assertIn("mikan-image-cache", cache_module)

    def test_fnos_compose_has_first_login_defaults(self) -> None:
        compose = (ROOT / "docker-compose.fnos.yml").read_text(encoding="utf-8")
        self.assertIn('ADMIN_USER: "${ADMIN_USER:-admin}"', compose)
        self.assertIn('ADMIN_PASSWORD: "${ADMIN_PASSWORD:-password}"', compose)
        self.assertIn('QBIT_URL: "${QBIT_URL:-}"', compose)
        self.assertIn('QBIT_USERNAME: "${QBIT_USERNAME:-}"', compose)
        self.assertIn('QBIT_PASSWORD: "${QBIT_PASSWORD:-}"', compose)

    def test_runtime_version_and_revision_come_from_image_build_metadata(self) -> None:
        env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
        fnos_env = (ROOT / ".env.fnos.example").read_text(encoding="utf-8")
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        for env_text in (env_example, fnos_env):
            self.assertNotIn("\nAPP_VERSION=", f"\n{env_text}")
            self.assertNotIn("\nAPP_REVISION=", f"\n{env_text}")
        self.assertNotIn("FEEDDOCK_BUILD_VERSION=", env_example)
        self.assertIn("ARG APP_VERSION=dev", dockerfile)
        self.assertIn("ARG APP_REVISION=unknown", dockerfile)
        self.assertIn("org.opencontainers.image.revision", dockerfile)
        self.assertIn("/app/.feeddock-build.json", dockerfile)
        self.assertIn('"$APP_VERSION" "$APP_REVISION" "$APP_CREATED_AT"', dockerfile)
        self.assertNotIn('{"version":"${APP_VERSION}"', dockerfile)
        self.assertNotIn("ENV APP_VERSION=", dockerfile)
        self.assertIn("load_build_info", (ROOT / "app/config.py").read_text(encoding="utf-8"))
        self.assertIn('id="currentBuildSource"', (ROOT / "app/static/index.html").read_text(encoding="utf-8"))
        self.assertIn("镜像构建文件", (ROOT / "app/static/app.js").read_text(encoding="utf-8"))
        index = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        styles = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")
        self.assertIn('id="subscriptionSortMode"', index)
        for label in ("按星期", "按更新时间", "按添加时间", "按名字", "按评分"):
            self.assertIn(label, index)
        self.assertIn('<option value="trial">试看</option>', index)
        state_options = (
            '<option value="">全部状态</option>'
            '<option value="enabled">启用</option>'
            '<option value="trial">试看</option>'
            '<option value="disabled">停用</option>'
            '<option value="error">异常</option>'
        )
        self.assertIn(state_options, index)
        self.assertIn("state === 'trial' && sub.subscription_mode !== 'trial'", (ROOT / "app/static/app.js").read_text(encoding="utf-8"))
        self.assertIn(".subscription-list-filters > button", styles)
        self.assertIn("white-space: nowrap", styles)
        main = (ROOT / "app/main.py").read_text(encoding="utf-8")
        for page in ("index.html", "login.html", "change-password.html"):
            html = (ROOT / "app/static" / page).read_text(encoding="utf-8")
            self.assertIn("__FEEDDOCK_ASSET_VERSION__", html)
        self.assertIn("settings.app_revision[:12]", main)
        self.assertIn('_render_static_page("index.html")', main)
        self.assertIn('"Cache-Control": "no-store"', main)

    def test_workflow_versions_from_remote_image_without_manual_tag_push(self) -> None:
        workflow = (ROOT / ".github/workflows/docker-publish.yml").read_text(encoding="utf-8")
        release_paths = (ROOT / ".github/release-paths.txt").read_text(encoding="utf-8")

        self.assertNotIn('tags:\n      - "v*.*.*"', workflow)
        self.assertIn("Detect image-impacting changes", workflow)
        self.assertIn("Inspect current remote image metadata", workflow)
        self.assertIn("scripts/inspect_registry_image.py", workflow)
        self.assertIn("--latest-image", workflow)
        self.assertNotIn("Commit automatic version update", workflow)
        self.assertNotIn('git push origin "HEAD:${GITHUB_REF_NAME}"', workflow)
        self.assertIn("Create optional GitHub Release record", workflow)
        self.assertIn("continue-on-error: true", workflow)
        self.assertIn("RELEASE_TAG: v${{ steps.version.outputs.value }}", workflow)
        self.assertIn('gh release create "$RELEASE_TAG"', workflow)
        self.assertIn('--target "$GITHUB_SHA"', workflow)
        self.assertIn("APP_REVISION=${{ github.sha }}", workflow)
        self.assertIn("type=raw,value=${{ steps.version.outputs.value }}", workflow)
        self.assertIn("app/**", release_paths)
        self.assertIn("src/**", release_paths)
        self.assertNotIn("docs/**", release_paths)
        self.assertNotIn("tests/**", release_paths)
        self.assertNotIn("update.json", release_paths)
        self.assertIn("node --check app/static/modules/notification-settings.js", workflow)


    def test_refresh_actions_initial_refresh_and_log_copy(self) -> None:
        index = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        styles = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")
        script = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
        main = (ROOT / "app/main.py").read_text(encoding="utf-8")
        rss_service = (ROOT / "app/rss_service.py").read_text(encoding="utf-8")
        self.assertNotIn("window.confirm('是否刷新全部订阅？')", script)
        self.assertIn('id="refreshMetadata"', index)
        self.assertIn("同步订阅元数据", index)
        self.assertIn(".nav-popover-refresh { top: calc(100% + 18px); }", styles)
        self.assertIn("/api/actions/refresh-metadata", script)
        self.assertIn('id="scrapeCompletedMedia"', index)
        self.assertIn("刮削已完成媒体", index)
        self.assertIn("/api/actions/scrape-completed", script)
        self.assertIn('def manual_metadata_refresh', main)
        self.assertIn('def manual_media_scrape', main)
        self.assertIn("订阅已保存，正在自动刷新一次", script)
        self.assertNotIn("500 错误可按提示中的请求编号", script)
        self.assertIn("background_tasks.add_task", main)
        self.assertIn('trigger="subscription-created"', main)
        self.assertIn("def refresh_subscription(", rss_service)
        self.assertIn("准备推送到下载器", rss_service)
        self.assertIn("qBittorrent 已确认任务", rss_service)
        self.assertIn("刷新全部订阅完成", rss_service)
        self.assertIn('id="saveRssOnly"', index)
        self.assertIn('id="saveRssAndRefresh"', index)
        self.assertIn("更新 RSS", script)
        self.assertIn("/api/subscriptions/${id}/refresh", script)
        self.assertIn('data-panel-id="legal-disclaimer"', index)
        disclaimer = (ROOT / "DISCLAIMER.md").read_text(encoding="utf-8")
        self.assertIn("技术中立", disclaimer)
        self.assertIn("依法不得免责", disclaimer)
        self.assertIn("故意或者重大过失", disclaimer)

    def test_subscription_submit_keeps_form_reference_across_await(self) -> None:
        script = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
        handler_start = script.index("document.getElementById('subscriptionForm')")
        handler_end = script.index("document.getElementById('refreshNow')", handler_start)
        handler = script[handler_start:handler_end]

        self.assertIn("const formElement = event.currentTarget;", handler)
        self.assertIn("const formData = new FormData(formElement);", handler)
        self.assertIn("formElement.reset();", handler)
        self.assertNotIn("event.currentTarget.reset()", handler)

    def test_static_assets_are_cache_busted_for_running_image_revision(self) -> None:
        token = "__FEEDDOCK_ASSET_VERSION__"
        index = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        login = (ROOT / "app/static/login.html").read_text(encoding="utf-8")
        change_password = (ROOT / "app/static/change-password.html").read_text(encoding="utf-8")
        change_password_script = (ROOT / "app/static/change-password.js").read_text(encoding="utf-8")
        main = (ROOT / "app/main.py").read_text(encoding="utf-8")

        self.assertIn(f"/static/app.js?v={token}", index)
        self.assertIn(f"/static/mikan-subscription-state.js?v={token}", index)
        self.assertIn(f"/static/subscription-sources.js?v={token}", index)
        self.assertIn(f"/static/navigation.js?v={token}", index)
        self.assertLess(
            index.index(f"/static/subscription-sources.js?v={token}"),
            index.index(f"/static/app.js?v={token}"),
        )
        self.assertLess(
            index.index(f"/static/navigation.js?v={token}"),
            index.index(f"/static/app.js?v={token}"),
        )
        self.assertIn(f"/static/login.js?v={token}", login)
        self.assertIn(f"/static/change-password.js?v={token}", change_password)
        self.assertIn("/#settings-login", change_password_script)
        for page in (index, login, change_password):
            self.assertIn(f"/static/styles.css?v={token}", page)
        self.assertIn("settings.app_revision[:12]", main)
        self.assertIn("__FEEDDOCK_ASSET_VERSION__", main)

    def test_update_check_is_manual_only(self) -> None:
        script = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
        self.assertIn("document.getElementById('checkUpdate').addEventListener", script)
        self.assertNotIn("reloadAll().then(() => loadUpdateStatus", script)
        self.assertTrue(script.rstrip().endswith("reloadAll();"))

    def test_fnos_update_check_uses_registry_image_and_optional_watchtower(self) -> None:
        compose = (ROOT / "docker-compose.fnos.yml").read_text(encoding="utf-8")
        self.assertNotIn('UPDATE_MANIFEST_URLS:', compose)
        self.assertNotIn('UPDATE_REPOSITORY:', compose)
        self.assertNotIn('UPDATE_API_URL:', compose)
        self.assertIn('UPDATE_CHECK_CACHE_HOURS: "${UPDATE_CHECK_CACHE_HOURS:-6}"', compose)
        self.assertIn('FEEDDOCK_IMAGE: "${FEEDDOCK_IMAGE:-ghcr.io/planeteditorx/feeddock:latest}"', compose)
        self.assertIn('WATCHTOWER_URL: "${WATCHTOWER_URL:-http://watchtower:8080}"', compose)
        self.assertIn('WATCHTOWER_TOKEN: "${WATCHTOWER_TOKEN:-}"', compose)
        self.assertIn("  watchtower:", compose)
        self.assertIn('profiles: ["updater"]', compose)
        self.assertIn('WATCHTOWER_HTTP_API_UPDATE: "true"', compose)
        self.assertIn('/var/run/docker.sock:/var/run/docker.sock', compose)
        self.assertIn('com.centurylinklabs.watchtower.enable: "true"', compose)

    def test_documentation_is_grouped_by_purpose(self) -> None:
        root_markdown = {path.name for path in ROOT.glob("*.md")}
        self.assertEqual(root_markdown, {"README.md", "CHANGELOG.md", "DISCLAIMER.md"})
        for relative in (
            "docs/README.md",
            "docs/deployment/FNOS_DEPLOY.md",
            "docs/deployment/AUTOMATIC_RELEASES.md",
            "docs/deployment/NETWORK_TROUBLESHOOTING.md",
            "docs/guides/QBITTORRENT.md",
            "docs/guides/METADATA_AND_MEDIA.md",
            "docs/reference/DEBUG_LOGGING.md",
            "docs/archive/README.md",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_update_check_reads_container_registry_instead_of_release_manifest(self) -> None:
        self.assertFalse((ROOT / "update.json").exists())
        update_service = (ROOT / "app/update_service.py").read_text(encoding="utf-8")
        registry = (ROOT / "app/image_registry.py").read_text(encoding="utf-8")
        self.assertIn("container-registry", update_service)
        self.assertIn("RegistryImageClient", update_service)
        self.assertNotIn("releases/latest", update_service)
        self.assertNotIn("update.json", update_service)
        self.assertIn("docker-content-digest", registry)
        self.assertIn("org.opencontainers.image.revision", registry)


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

    def test_metadata_naming_and_local_scraping_ui_are_wired(self) -> None:
        index = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        script = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
        main = (ROOT / "app/main.py").read_text(encoding="utf-8")
        for element_id in (
            'metadataSettingsForm', 'metadataSearchProvider', 'metadataSearchResults',
            'normalizeTorrents',
        ):
            self.assertIn(f'id="{element_id}"', index)
        self.assertIn('/api/metadata/search', script)
        self.assertIn('/api/metadata/detail', script)
        self.assertIn('/api/actions/normalize-torrents', script)
        self.assertIn('def metadata_detail', main)
        self.assertIn('写入 NFO 与图片', index)
        self.assertIn('tvshow.nfo', index)
        self.assertNotIn('id="refreshEmby"', index)
        self.assertNotIn('id="testTmm"', index)
        self.assertNotIn('tinyMediaManager HTTP API 地址', index)
        self.assertNotIn('/api/actions/emby-refresh', script)
        self.assertNotIn('/api/metadata/test-tmm', script)

    def test_all_main_panels_remember_collapsed_state(self) -> None:
        index = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        script = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
        styles = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")
        self.assertGreaterEqual(index.count('data-panel-id='), 8)
        self.assertIn('feeddock.panelState.v1', script)
        self.assertIn('feeddock.mikanWeekdayState.v1', script)
        self.assertIn('localStorage.setItem', script)
        self.assertIn('.panel.is-collapsed > :not(.panel-head)', styles)

    def test_rss_polling_is_configurable_and_advanced_subscription_fields_start_collapsed(self) -> None:
        index = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        script = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
        runtime = (ROOT / "app/runtime_config.py").read_text(encoding="utf-8")
        scheduler = (ROOT / "app/scheduler.py").read_text(encoding="utf-8")
        self.assertIn('name="rss_poll_interval_minutes"', index)
        self.assertEqual(index.count('<details class="subscription-advanced">'), 4)
        self.assertIn('/api/rss-poll/settings', script)
        self.assertIn('RSS_POLL_INTERVAL_SETTING_KEY', runtime)
        self.assertIn('load_rss_poll_config', scheduler)

    def test_legacy_default_save_paths_upgrade_to_media_folder(self) -> None:
        database = (ROOT / "app/database.py").read_text(encoding="utf-8")
        rss_service = (ROOT / "app/rss_service.py").read_text(encoding="utf-8")
        self.assertIn("migration:1.11.1:media-folder-paths", database)
        self.assertIn("migration:1.17.5:local-scrape-backfill", database)
        self.assertIn("{base}/{media_folder}/Season {season:02}", database)
        self.assertIn("_LEGACY_DEFAULT_SAVE_PATH_TEMPLATES", rss_service)

    def test_feeddock_icon_is_used_on_main_and_auth_pages(self) -> None:
        icon = ROOT / "app/static/feeddock-icon.png"
        self.assertTrue(icon.is_file())
        for name in ("index.html", "login.html", "change-password.html"):
            page = (ROOT / "app/static" / name).read_text(encoding="utf-8")
            self.assertIn('/static/feeddock-icon.png', page)

    def test_subscription_details_and_metadata_search_are_user_controlled(self) -> None:
        index = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        script = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
        styles = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")
        self.assertIn('placeholder="请输入订阅名称"', index)
        self.assertIn('placeholder="番剧名称 第二季"', index)
        self.assertNotIn('placeholder="金牌得主 第二季"', index)
        self.assertIn("className = 'subscription-details'", script)
        self.assertIn('syncMetadataSearchQuery({ force: true })', script)
        self.assertIn('searchMetadata({ automatic: true })', script)
        self.assertIn('applyMetadataCandidateToForm(results[0])', script)
        self.assertIn('.subscription-details > summary', styles)

    def test_fnos_compose_has_optional_metadata_and_media_mount(self) -> None:
        compose = (ROOT / "docker-compose.fnos.yml").read_text(encoding="utf-8")
        self.assertIn('TMDB_READ_ACCESS_TOKEN: "${TMDB_READ_ACCESS_TOKEN:-}"', compose)
        self.assertIn('BANGUMI_ACCESS_TOKEN: "${BANGUMI_ACCESS_TOKEN:-}"', compose)
        self.assertIn('MEDIA_LOCAL_ROOT: "${MEDIA_LOCAL_ROOT:-/media}"', compose)
        self.assertIn('EMBY_URL: "${EMBY_URL:-}"', compose)
        self.assertIn('- "${FEEDDOCK_MEDIA_PATH:-/vol2/1000/影视}:/media"', compose)

    def test_container_defaults_media_local_root_to_media_mount(self) -> None:
        config = (ROOT / "app/config.py").read_text(encoding="utf-8")
        entrypoint = (ROOT / "docker-entrypoint.py").read_text(encoding="utf-8")
        self.assertIn('_optional_path("MEDIA_LOCAL_ROOT", "/media")', config)
        self.assertIn('os.getenv("MEDIA_LOCAL_ROOT", "/media")', entrypoint)

    def test_fnos_permissions_and_media_root_are_consistent(self) -> None:
        compose = (ROOT / "docker-compose.fnos.yml").read_text(encoding="utf-8")
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        entrypoint = (ROOT / "docker-entrypoint.py").read_text(encoding="utf-8")
        index = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        script = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
        self.assertIn('PUID: "${PUID:-0}"', compose)
        self.assertIn('PGID: "${PGID:-0}"', compose)
        self.assertIn('DOWNLOAD_PATH: "${DOWNLOAD_PATH:-/media}"', compose)
        self.assertIn('MEDIA_LOCAL_ROOT: "${MEDIA_LOCAL_ROOT:-/media}"', compose)
        self.assertIn('chown -R 0:0 /app /data /media', dockerfile)
        self.assertIn('_number("PUID", 0)', entrypoint)
        self.assertIn('name="media_local_root" placeholder="/media" required', index)
        self.assertIn('可与 qBittorrent 保存根目录不同', index)
        self.assertIn('name="custom_download_path" placeholder="/media" readonly', index)
        self.assertIn("currentDownloadRoot = '/media'", script)

    def test_subscription_cards_show_metadata_and_cleanup_controls(self) -> None:
        index = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        script = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
        self.assertIn('id="clearRecentItems"', index)
        self.assertIn('id="clearSystemLogs"', index)
        self.assertIn("className = 'subscription-poster'", script)
        self.assertIn('sub.metadata_overview', script)
        self.assertIn("text('button', '刮削'", script)
        self.assertIn('/api/subscriptions/${sub.id}/scrape', script)
        self.assertIn("setFormValue(subscriptionForm, 'scrape_enabled', false)", script)
        self.assertIn("setFormValue(subscriptionForm, 'name', displayTitle)", script)


    def test_ani_rss_inspired_settings_are_wired_end_to_end(self) -> None:
        index = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        script = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
        main = (ROOT / "app/main.py").read_text(encoding="utf-8")
        settings_config = (ROOT / "app/settings_config.py").read_text(encoding="utf-8")
        rss_service = (ROOT / "app/rss_service.py").read_text(encoding="utf-8")
        postprocess = (ROOT / "app/postprocess.py").read_text(encoding="utf-8")
        metadata = (ROOT / "app/metadata_service.py").read_text(encoding="utf-8")

        for element_id in (
            "pageSettingsForm",
            "metadataSettingsForm",
            "downloaderForm",
            "automationSettingsForm",
            "trackersSettingsForm",
            "refreshTrackers",
        ):
            self.assertIn(f'id="{element_id}"', index)
        for field in (
            'name="theme_color"',
            'name="subscription_sort"',
            'name="auto_scrape_enabled"',
            'name="follow_days"',
            'name="bangumi_ini_enabled"',
            'name="retry_count"',
            'name="concurrent_limit"',
            'name="seeding_minutes"',
            'name="rss_enabled"',
            'name="rss_timeout_seconds"',
            'name="auto_skip_existing"',
            'name="auto_disable_complete"',
            'name="trackers_update_url"',
        ):
            self.assertIn(field, index)
        self.assertIn('/api/application/settings', script)
        self.assertIn('/api/trackers/refresh', script)
        self.assertIn('def update_application_settings', main)
        self.assertIn('def refresh_trackers', main)
        self.assertIn('rss_auto_skip_existing', settings_config)
        self.assertIn('_existing_video_matches', rss_service)
        self.assertIn('seeding_minutes=preferences.download.seeding_minutes', rss_service)
        self.assertIn('client.add_trackers', postprocess)
        self.assertIn('def _tmdb_auth', metadata)
        self.assertIn('api_key', metadata)

    def test_qbittorrent_internal_tags_are_temporary_and_hash_tracked(self) -> None:
        downloader = (ROOT / "app/downloader.py").read_text(encoding="utf-8")
        postprocess = (ROOT / "app/postprocess.py").read_text(encoding="utf-8")
        scheduler = (ROOT / "app/scheduler.py").read_text(encoding="utf-8")
        rss_service = (ROOT / "app/rss_service.py").read_text(encoding="utf-8")

        self.assertIn('api/v2/torrents/removeTags', downloader)
        self.assertIn('api/v2/torrents/deleteTags', downloader)
        self.assertIn('def cleanup_internal_tags', downloader)
        self.assertIn('torrent_hash: str = ""', downloader)
        self.assertIn('cleanup_internal_qbittorrent_tags', postprocess)
        self.assertIn('or_(FeedItem.torrent_hash != "", FeedItem.qbit_tag != "")', postprocess)
        self.assertIn('torrent_hash=item.torrent_hash', postprocess)
        self.assertIn('cleanup_internal_qbittorrent_tags()', scheduler)
        self.assertIn('item.qbit_tag = ""', rss_service)

    def test_notification_and_subscription_monitoring_are_wired_end_to_end(self) -> None:
        index = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        script = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
        main = (ROOT / "app/main.py").read_text(encoding="utf-8")
        rss_service = (ROOT / "app/rss_service.py").read_text(encoding="utf-8")
        postprocess = (ROOT / "app/postprocess.py").read_text(encoding="utf-8")
        notifications = (ROOT / "app/notifications.py").read_text(encoding="utf-8")
        monitor = (ROOT / "app/subscription_monitor.py").read_text(encoding="utf-8")

        self.assertIn('id="notificationSettingsForm"', index)
        self.assertIn('id="openQbit"', index)
        self.assertIn('target="_blank"', index)
        self.assertIn("openQbit.href = data.qbit_url", script)
        self.assertIn('name="auto_disable_when_complete"', index)
        self.assertIn('name="stale_days"', index)
        self.assertIn('/api/notifications/settings', script)
        self.assertIn('/api/notifications/test', script)
        self.assertIn('def update_notification_settings', main)
        self.assertIn('def test_notifications', main)
        self.assertIn('item.qbit_tag = f"feeddock-item-{item.id}"', rss_service)
        self.assertIn('evaluate_subscription_completion(db, subscription, now=now)', rss_service)
        self.assertIn('"download_completed"', postprocess)
        self.assertIn('def _safe_channel_error', notifications)
        self.assertIn('def evaluate_missing_episodes', monitor)
        self.assertIn('def evaluate_stale_subscription', monitor)
        self.assertIn('def evaluate_subscription_completion', monitor)
        notification_module = (ROOT / "app/static/modules/notification-settings.js").read_text(encoding="utf-8")
        self.assertIn('/static/modules/notification-settings.js', index)
        self.assertIn('/api/notifications/preview', notification_module)
        self.assertIn('name="title_template"', index)
        self.assertIn('id="notificationTemplatePreview"', index)
        self.assertIn('type="button">取消添加</button>', index)
        self.assertIn("'settings-notification': ['通知设置'", (ROOT / "app/static/navigation.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.download_cleanup import cleanup_completed_torrent_records
from app.downloader import DownloaderResult, InternalTagCleanupResult, QBittorrentClient
from app.media_sidecar import write_bangumi_ini
from app.postprocess import cleanup_internal_qbittorrent_tags
from app.models import FeedItem, Subscription, SystemLog
from app.rss_service import _existing_video_matches, _push_feed_item, dispatch_scheduled_downloads
from app.settings_config import (
    load_application_preferences,
    normalize_tracker_text,
    save_application_preferences,
    save_tracker_cache,
)
from app.subscription_monitor import evaluate_subscription_completion
from app.metadata_service import MetadataService
from app.runtime_config import load_metadata_config, save_metadata_config


class _FakeHttpResponse:
    status_code = 200
    text = "Ok."

    def __init__(self, payload=None):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeQbitHttpClient:
    def __init__(self, torrents=None, torrent_files=None) -> None:
        self.add_files = None
        self.posts = []
        self.torrents = torrents if torrents is not None else []
        self.torrent_files = torrent_files if torrent_files is not None else []

    def __enter__(self): return self
    def __exit__(self, *_args): return False

    def post(self, path, data=None, files=None):
        self.posts.append((path, data, files))
        if path.endswith("torrents/add"):
            self.add_files = files
        return _FakeHttpResponse()

    def get(self, path, params=None):
        if path.endswith("torrents/info"):
            return _FakeHttpResponse(self.torrents)
        if path.endswith("torrents/files"):
            return _FakeHttpResponse(self.torrent_files)
        return _FakeHttpResponse([])


class ApplicationSettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def save_preferences(self, **overrides):
        values = {
            "theme_color": "green",
            "subscription_sort": "rating",
            "retry_count": 3,
            "concurrent_limit": 2,
            "seeding_minutes": 90,
            "cleanup_completed_enabled": False,
            "cleanup_completed_delay_minutes": 1,
            "rss_enabled": True,
            "rss_timeout_seconds": 20,
            "auto_skip_existing": False,
            "auto_disable_complete": False,
            "trackers_enabled": True,
            "trackers_update_url": "https://example.test/trackers.txt",
        }
        values.update(overrides)
        return save_application_preferences(self.db, **values)

    def test_download_completion_metadata_scrape_is_enabled_by_default(self):
        self.assertTrue(load_metadata_config(self.db).auto_scrape_enabled)

    def test_media_local_root_can_differ_from_qbittorrent_root(self):
        from app.models import AppSetting

        self.db.merge(AppSetting(key="download_path", value="/vol2/1000/影视"))
        self.db.commit()
        saved = save_metadata_config(
            self.db,
            tmdb_read_access_token=None,
            clear_tmdb_token=False,
            bangumi_access_token=None,
            clear_bangumi_token=False,
            metadata_language="zh-CN",
            tmdb_api_base="https://api.themoviedb.org",
            tmdb_image_base="https://image.tmdb.org",
            auto_scrape_enabled=True,
            follow_days=14,
            bangumi_ini_enabled=False,
            media_local_root="/media",
            emby_url="",
            emby_api_key=None,
            clear_emby_api_key=False,
            tmm_url="",
            tmm_api_key=None,
            clear_tmm_api_key=False,
            tmm_enabled=False,
        )
        self.assertEqual(saved.downloader_root, "/vol2/1000/影视")
        self.assertEqual(saved.media_local_root, "/media")

    def test_stale_host_media_root_self_heals_to_container_media_mount(self):
        from app.models import AppSetting

        self.db.merge(AppSetting(key="download_path", value="/vol2/1000/影视"))
        self.db.merge(AppSetting(key="media_local_root", value="/vol2/1000/影视"))
        self.db.commit()

        loaded = load_metadata_config(self.db)

        self.assertEqual(loaded.downloader_root, "/vol2/1000/影视")
        self.assertEqual(loaded.media_local_root, "/media")

    def test_empty_local_media_root_saves_container_default_not_qbit_root(self):
        from app.models import AppSetting

        self.db.merge(AppSetting(key="download_path", value="/vol2/1000/影视"))
        self.db.commit()
        saved = save_metadata_config(
            self.db,
            tmdb_read_access_token=None,
            clear_tmdb_token=False,
            bangumi_access_token=None,
            clear_bangumi_token=False,
            metadata_language="zh-CN",
            tmdb_api_base="https://api.themoviedb.org",
            tmdb_image_base="https://image.tmdb.org",
            auto_scrape_enabled=True,
            follow_days=14,
            bangumi_ini_enabled=False,
            media_local_root="",
            emby_url="",
            emby_api_key=None,
            clear_emby_api_key=False,
            tmm_url="",
            tmm_api_key=None,
            clear_tmm_api_key=False,
            tmm_enabled=False,
        )

        self.assertEqual(saved.downloader_root, "/vol2/1000/影视")
        self.assertEqual(saved.media_local_root, "/media")

    def test_preferences_persist_and_tracker_cache_is_deduplicated(self):
        saved = self.save_preferences(
            cleanup_completed_enabled=True,
            cleanup_completed_delay_minutes=7,
        )
        self.assertEqual(saved.page.theme_color, "green")
        self.assertEqual(saved.download.retry_count, 3)
        self.assertTrue(saved.download.cleanup_completed_enabled)
        self.assertEqual(saved.download.cleanup_completed_delay_minutes, 7)
        trackers = normalize_tracker_text("udp://tracker.test:80/announce\n\ninvalid\nudp://tracker.test:80/announce\nhttps://tracker2.test/announce")
        self.assertEqual(len(trackers), 2)
        save_tracker_cache(self.db, trackers, updated_at=datetime(2026, 7, 27, tzinfo=timezone.utc))
        loaded = load_application_preferences(self.db)
        self.assertEqual(loaded.trackers.trackers, trackers)
        self.assertEqual(loaded.trackers.updated_at, "2026-07-27T00:00:00+00:00")

    def test_auto_skip_requires_rename_for_enabled_subscriptions(self):
        self.db.add(Subscription(name="Demo", rss_url="https://example.test/rss", enabled=True, rename_enabled=False))
        self.db.commit()
        with self.assertRaisesRegex(ValueError, "自动重命名"):
            self.save_preferences(auto_skip_existing=True)

    def test_qbittorrent_api_key_requires_official_format(self):
        client = QBittorrentClient(
            base_url="http://qbit.test",
            auth_mode="api_key",
            api_key="not-a-qbittorrent-key",
        )
        self.assertIn("qbt_ 开头的 32 位密钥", client._configuration_error())

    def test_qbittorrent_add_includes_seeding_limit(self):
        fake = _FakeQbitHttpClient([{"hash": "demo-hash", "name": "Demo", "state": "downloading"}])
        client = QBittorrentClient(base_url="http://qbit.test", username="u", password="p")
        with patch.object(client, "_client", return_value=fake), patch.object(client, "_login", return_value=DownloaderResult(True, "ok")):
            result = client.add_url(
                "magnet:?xt=urn:btih:demo", "/media/Demo",
                tags="feeddock-item-demo", seeding_minutes=120,
            )
        self.assertTrue(result.ok)
        self.assertTrue(result.verified)
        self.assertEqual(result.torrent_hash, "demo-hash")
        self.assertEqual(fake.add_files["seedingTimeLimit"][1], "120")

    def test_qbittorrent_relocates_trial_video_and_matching_subtitle(self):
        fake = _FakeQbitHttpClient(
            torrents=[{"hash": "demo-hash", "save_path": "/media/试看"}],
            torrent_files=[
                {"name": "Trial - S01E01.mkv"},
                {"name": "Trial - S01E01.zh-CN.ass"},
            ],
        )
        client = QBittorrentClient(base_url="http://qbit.test", username="u", password="p")
        with (
            patch.object(client, "_client", return_value=fake),
            patch.object(client, "_login", return_value=DownloaderResult(True, "ok")),
        ):
            result = client.relocate_single_video(
                torrent_hash="demo-hash",
                target_save_path="/media/Formal/Season 01",
                desired_name="Formal - S01E01",
            )

        self.assertTrue(result.ok, result.message)
        self.assertTrue(result.moved)
        self.assertEqual(result.download_path, "/media/Formal/Season 01/Formal - S01E01.mkv")
        posted = [(path, data) for path, data, _files in fake.posts]
        self.assertIn((
            "api/v2/torrents/renameFile",
            {"hash": "demo-hash", "oldPath": "Trial - S01E01.mkv", "newPath": "Formal - S01E01.mkv"},
        ), posted)
        self.assertIn((
            "api/v2/torrents/renameFile",
            {"hash": "demo-hash", "oldPath": "Trial - S01E01.zh-CN.ass", "newPath": "Formal - S01E01.zh-CN.ass"},
        ), posted)
        self.assertIn((
            "api/v2/torrents/setLocation",
            {"hashes": "demo-hash", "location": "/media/Formal/Season 01"},
        ), posted)

    def test_qbittorrent_record_cleanup_never_deletes_downloaded_files(self):
        fake = _FakeQbitHttpClient()
        client = QBittorrentClient(base_url="http://qbit.test", username="u", password="p")
        with (
            patch.object(client, "_client", return_value=fake),
            patch.object(client, "_login", return_value=DownloaderResult(True, "ok")),
        ):
            result = client.delete_torrent_record("demo-hash")
        self.assertTrue(result.ok, result.message)
        path, data, _files = fake.posts[-1]
        self.assertEqual(path, "api/v2/torrents/delete")
        self.assertEqual(data, {"hashes": "demo-hash", "deleteFiles": "false"})

    def test_completed_qbittorrent_record_is_removed_after_configured_delay(self):
        now = datetime(2026, 7, 28, 0, 40, tzinfo=timezone.utc)
        sub = Subscription(name="Demo", rss_url="https://example.test/rss")
        self.db.add(sub)
        self.db.flush()
        item = FeedItem(
            subscription_id=sub.id,
            fingerprint="cleanup-due",
            title="Demo 01",
            status="queued",
            torrent_hash="due-hash",
            rename_status="completed",
            scrape_status="completed",
            completed_at=now - timedelta(minutes=1, seconds=1),
        )
        self.db.add(item)
        self.save_preferences(
            cleanup_completed_enabled=True,
            cleanup_completed_delay_minutes=1,
        )
        fake = SimpleNamespace(
            delete_torrent_record=lambda torrent_hash: DownloaderResult(
                torrent_hash == "due-hash",
                "qBittorrent 任务记录已删除，下载文件已保留",
            )
        )

        result = cleanup_completed_torrent_records(self.db, now=now, client=fake)

        self.assertEqual(result["removed"], 1)
        self.db.refresh(item)
        self.assertEqual(
            item.qbit_record_removed_at.replace(tzinfo=timezone.utc),
            now,
        )
        self.assertEqual(item.torrent_hash, "due-hash")
        self.assertIn("文件已保留", item.qbit_record_remove_message)

    def test_completed_qbittorrent_record_waits_for_delay_and_postprocessing(self):
        now = datetime(2026, 7, 28, 0, 40, tzinfo=timezone.utc)
        sub = Subscription(name="Demo", rss_url="https://example.test/rss")
        self.db.add(sub)
        self.db.flush()
        too_new = FeedItem(
            subscription_id=sub.id,
            fingerprint="cleanup-new",
            title="Demo 01",
            status="queued",
            torrent_hash="new-hash",
            rename_status="completed",
            scrape_status="completed",
            completed_at=now - timedelta(seconds=30),
        )
        blocked = FeedItem(
            subscription_id=sub.id,
            fingerprint="cleanup-blocked",
            title="Demo 02",
            status="queued",
            torrent_hash="blocked-hash",
            rename_status="completed",
            scrape_status="error",
            completed_at=now - timedelta(minutes=5),
        )
        self.db.add_all([too_new, blocked])
        self.save_preferences(
            cleanup_completed_enabled=True,
            cleanup_completed_delay_minutes=1,
        )
        calls: list[str] = []
        fake = SimpleNamespace(
            delete_torrent_record=lambda torrent_hash: calls.append(torrent_hash)
            or DownloaderResult(True, "ok")
        )

        result = cleanup_completed_torrent_records(self.db, now=now, client=fake)

        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["blocked"], 1)
        self.assertEqual(result["removed"], 0)
        self.assertEqual(calls, [])

    def test_qbittorrent_uploads_raw_torrent_file_and_verifies_it(self):
        fake = _FakeQbitHttpClient([{"hash": "file-hash", "name": "Episode 03", "state": "downloading"}])
        client = QBittorrentClient(base_url="http://qbit.test", username="u", password="p")
        with patch.object(client, "_client", return_value=fake), patch.object(client, "_login", return_value=DownloaderResult(True, "ok")):
            result = client.add_torrent(
                b"d4:infod4:name4:demoee",
                "episode-03.torrent",
                "/media/Demo",
                tags="feeddock-item-file",
            )
        self.assertTrue(result.ok, result.message)
        self.assertTrue(result.verified)
        self.assertEqual(result.torrent_hash, "file-hash")
        self.assertIn("torrents", fake.add_files)
        self.assertEqual(fake.add_files["torrents"][0], "episode-03.torrent")

    def test_qbittorrent_ok_without_visible_task_is_failure(self):
        fake = _FakeQbitHttpClient([])
        client = QBittorrentClient(base_url="http://qbit.test", username="u", password="p")
        with (
            patch.object(client, "_client", return_value=fake),
            patch.object(client, "_login", return_value=DownloaderResult(True, "ok")),
            patch("app.downloader.time.sleep"),
        ):
            result = client.add_url(
                "magnet:?xt=urn:btih:missing", "/media/Demo", tags="feeddock-item-missing"
            )
        self.assertFalse(result.ok)
        self.assertIn("未在任务列表中找到", result.message)

    def test_qbittorrent_accepts_webapi_214_add_json(self):
        class JsonResponse(_FakeHttpResponse):
            def __init__(self, status_code, payload):
                super().__init__(payload)
                self.status_code = status_code
                self.text = (
                    '{"success_count":1,"pending_count":0,"failure_count":0,'
                    '"added_torrent_ids":["modern-hash"]}'
                )

        class JsonClient(_FakeQbitHttpClient):
            def post(self, path, data=None, files=None):
                self.posts.append((path, data, files))
                if path.endswith("torrents/add"):
                    return JsonResponse(200, {
                        "success_count": 1,
                        "pending_count": 0,
                        "failure_count": 0,
                        "added_torrent_ids": ["modern-hash"],
                    })
                return _FakeHttpResponse()

        fake = JsonClient([{"hash": "modern-hash", "name": "Episode 04", "state": "downloading"}])
        client = QBittorrentClient(base_url="http://qbit.test", username="u", password="p")
        with patch.object(client, "_client", return_value=fake), patch.object(client, "_login", return_value=DownloaderResult(True, "ok")):
            result = client.add_torrent(
                b"d4:infod4:name4:demoee",
                "episode-04.torrent",
                "/media/Demo",
                tags="feeddock-item-modern",
            )
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.torrent_hash, "modern-hash")

    def test_qbittorrent_409_reuses_existing_torrent_by_info_hash(self):
        content = b"d4:infod4:name4:demoee"
        expected_hash = QBittorrentClient._torrent_hash_candidates(content)[0]

        class ConflictResponse(_FakeHttpResponse):
            status_code = 409
            text = '{"success_count":0,"pending_count":0,"failure_count":1,"added_torrent_ids":[]}'

            def __init__(self):
                super().__init__({
                    "success_count": 0,
                    "pending_count": 0,
                    "failure_count": 1,
                    "added_torrent_ids": [],
                })

        class ConflictClient(_FakeQbitHttpClient):
            def post(self, path, data=None, files=None):
                self.posts.append((path, data, files))
                if path.endswith("torrents/add"):
                    return ConflictResponse()
                return _FakeHttpResponse()

            def get(self, path, params=None):
                if path.endswith("torrents/info") and expected_hash in str((params or {}).get("hashes", "")):
                    return _FakeHttpResponse([{
                        "hash": expected_hash,
                        "name": "Demo - S01E04",
                        "state": "downloading",
                    }])
                return _FakeHttpResponse([])

        fake = ConflictClient()
        client = QBittorrentClient(base_url="http://qbit.test", username="u", password="p")
        with patch.object(client, "_client", return_value=fake), patch.object(client, "_login", return_value=DownloaderResult(True, "ok")):
            result = client.add_torrent(
                content,
                "episode-04.torrent",
                "/media/Demo",
                rename="Demo - S01E04",
                tags="feeddock-item-conflict",
            )
        self.assertTrue(result.ok, result.message)
        self.assertEqual(result.torrent_hash, expected_hash)
        self.assertIn("已存在相同任务", result.message)
        self.assertTrue(result.tag_removed)

    def test_qbittorrent_409_reports_counts_and_is_not_retryable(self):
        class ConflictResponse(_FakeHttpResponse):
            status_code = 409
            text = '{"success_count":0,"pending_count":0,"failure_count":1,"added_torrent_ids":[]}'

            def __init__(self):
                super().__init__({
                    "success_count": 0,
                    "pending_count": 0,
                    "failure_count": 1,
                    "added_torrent_ids": [],
                })

        class ConflictClient(_FakeQbitHttpClient):
            def post(self, path, data=None, files=None):
                if path.endswith("torrents/add"):
                    return ConflictResponse()
                return _FakeHttpResponse()

        fake = ConflictClient([])
        client = QBittorrentClient(base_url="http://qbit.test", username="u", password="p")
        with patch.object(client, "_client", return_value=fake), patch.object(client, "_login", return_value=DownloaderResult(True, "ok")):
            result = client.add_torrent(
                b"d4:infod4:name4:demoee",
                "episode-04.torrent",
                "/media/Demo",
                rename="Different name",
                tags="feeddock-item-conflict",
            )
        self.assertFalse(result.ok)
        self.assertFalse(result.retryable)
        self.assertIn("成功 0，等待 0，失败 1", result.message)

    def test_existing_video_auto_skip_uses_normalized_target_name(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "Demo" / "Season 01"
            directory.mkdir(parents=True)
            (directory / "Demo - S01E01.mkv").write_bytes(b"video")
            sub = Subscription(name="Demo", rss_url="https://example.test/rss", rename_enabled=True)
            item = FeedItem(subscription_id=1, fingerprint="x", title="Demo 01", save_path=str(directory), desired_name="Demo - S01E01")
            self.save_preferences(auto_skip_existing=False)
            # Write runtime download root directly for this isolated database.
            from app.models import AppSetting
            self.db.merge(AppSetting(key="download_path", value=root))
            self.db.commit()
            self.save_preferences(auto_skip_existing=True)
            self.assertTrue(_existing_video_matches(item, sub, self.db))

    def test_exact_existing_video_is_always_skipped_even_when_broad_scan_disabled(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "Demo" / "Season 01"
            directory.mkdir(parents=True)
            target = directory / "Demo - S01E02.mkv"
            target.write_bytes(b"video")
            sub = Subscription(name="Demo", rss_url="https://example.test/rss", rename_enabled=True, season=1)
            item = FeedItem(
                subscription_id=1, fingerprint="exact", title="Demo 02", episode="2",
                save_path=str(directory), desired_name="Demo - S01E02",
            )
            self.save_preferences(auto_skip_existing=False)
            from app.models import AppSetting
            self.db.merge(AppSetting(key="download_path", value=root))
            self.db.merge(AppSetting(key="media_local_root", value=root))
            self.db.commit()
            self.assertEqual(_existing_video_matches(item, sub, self.db), target)

    def test_global_auto_disable_uses_completed_whole_episodes(self):
        sub = Subscription(name="Demo", rss_url="https://example.test/rss", total_episodes=2, enabled=True)
        self.db.add(sub)
        self.db.flush()
        for number in (1, 2):
            self.db.add(FeedItem(subscription_id=sub.id, fingerprint=f"fp{number}", title="", episode=str(number), status="queued", completed_at=datetime.now(timezone.utc)))
        self.save_preferences(auto_disable_complete=True)
        with patch("app.subscription_monitor.send_notification"):
            self.assertTrue(evaluate_subscription_completion(self.db, sub))
        self.assertFalse(sub.enabled)

    def test_bangumi_ini_is_written_to_series_directory(self):
        with tempfile.TemporaryDirectory() as root:
            season = Path(root) / "Demo" / "Season 01"
            sub = Subscription(name="Demo", rss_url="https://example.test/rss", bangumi_id=1234, media_type="tv")
            item = FeedItem(subscription_id=1, fingerprint="x", title="", save_path=str(season))
            config = SimpleNamespace(bangumi_ini_enabled=True, media_local_root=root)
            result = write_bangumi_ini(sub, item, config)
            self.assertTrue(result.ok, result.message)
            self.assertEqual((Path(root) / "Demo" / "bangumi.ini").read_text(), "[Bangumi]\nid=1234\n")



    def test_enabling_bangumi_ini_marks_completed_items_for_backfill(self):
        sub = Subscription(name="Demo", rss_url="https://example.test/rss", bangumi_id=123)
        self.db.add(sub)
        self.db.flush()
        item = FeedItem(
            subscription_id=sub.id,
            fingerprint="completed-sidecar",
            title="Demo 01",
            status="queued",
            completed_at=datetime.now(timezone.utc),
            rename_status="completed",
            scrape_status="skipped",
            scrape_message="交由外部媒体库识别",
        )
        self.db.add(item)
        self.db.commit()
        save_metadata_config(
            self.db,
            tmdb_read_access_token=None,
            clear_tmdb_token=False,
            bangumi_access_token=None,
            clear_bangumi_token=False,
            metadata_language="zh-CN",
            tmdb_api_base="https://api.themoviedb.org",
            tmdb_image_base="https://image.tmdb.org",
            auto_scrape_enabled=False,
            follow_days=14,
            bangumi_ini_enabled=True,
            media_local_root="/media",
            emby_url="",
            emby_api_key=None,
            clear_emby_api_key=False,
            tmm_url="",
            tmm_api_key=None,
            clear_tmm_api_key=False,
            tmm_enabled=False,
        )
        self.db.refresh(item)
        self.assertEqual(item.scrape_status, "pending")
        self.assertIn("补写", item.scrape_message)

    def test_tmdb_auth_supports_v3_api_key_and_v4_token(self):
        api_key = "a" * 32
        headers, params = MetadataService._tmdb_auth(api_key)
        self.assertEqual(params, {"api_key": api_key})
        self.assertNotIn("Authorization", headers)

        headers, params = MetadataService._tmdb_auth("eyJhbGciOiJIUzI1NiJ9.token")
        self.assertEqual(params, {})
        self.assertEqual(headers["Authorization"], "Bearer eyJhbGciOiJIUzI1NiJ9.token")

    def test_dispatch_reports_capacity_waiting_separately(self):
        sub = Subscription(name="Demo", rss_url="https://example.test/rss", rename_enabled=False)
        self.db.add(sub)
        self.db.flush()
        item = FeedItem(
            subscription_id=sub.id, fingerprint="waiting", title="Demo",
            download_url="magnet:?xt=urn:btih:waiting", episode="1",
            status="scheduled", reason="等待下载并发空位（1/1）",
        )
        self.db.add(item)
        self.db.commit()
        self.save_preferences(concurrent_limit=1)
        fake = SimpleNamespace(active_download_count=lambda: (True, 1, "ok"))
        with patch("app.rss_service.QBittorrentClient", return_value=fake):
            result = dispatch_scheduled_downloads(self.db, include_daily=False)
        self.assertEqual(result["queued"], 0)
        self.assertEqual(result["waiting"], 1)
        self.assertEqual(result["errors"], 0)


    def test_successful_push_writes_downloader_logs(self):
        sub = Subscription(name="Demo", rss_url="https://example.test/rss", rename_enabled=False)
        self.db.add(sub)
        self.db.flush()
        item = FeedItem(
            subscription_id=sub.id,
            fingerprint="logged-push",
            title="Demo - 01 [1080p]",
            download_url="magnet:?xt=urn:btih:logged",
            episode="1",
        )
        self.db.add(item)
        self.db.flush()
        self.save_preferences(concurrent_limit=0, retry_count=1)
        fake = SimpleNamespace(
            add_url=lambda *_args, **_kwargs: DownloaderResult(True, "qBittorrent 已确认任务：Demo", torrent_hash="hash-demo", verified=True)
        )
        with patch("app.rss_service.QBittorrentClient", return_value=fake):
            ok, message = _push_feed_item(self.db, item, sub)
        self.db.commit()

        self.assertTrue(ok)
        self.assertIn("已确认", message)
        messages = [row.message for row in self.db.query(SystemLog).order_by(SystemLog.id)]
        self.assertIn("准备推送到下载器：Demo", messages)
        self.assertIn("qBittorrent 已确认任务：Demo", messages)
        details = "\n".join(row.details for row in self.db.query(SystemLog))
        self.assertIn("任务标签：feeddock-item-", details)
        self.assertNotIn("magnet:?", details)

    def test_non_retryable_downloader_failure_is_attempted_once(self):
        sub = Subscription(name="Conflict", rss_url="https://example.test/rss", rename_enabled=False)
        self.db.add(sub)
        self.db.flush()
        item = FeedItem(
            subscription_id=sub.id,
            fingerprint="non-retryable",
            title="Conflict - 01",
            download_url="magnet:?xt=urn:btih:0123456789012345678901234567890123456789",
            episode="1",
        )
        self.db.add(item)
        self.db.flush()
        self.save_preferences(concurrent_limit=0, retry_count=2)
        calls = []
        fake = SimpleNamespace(
            add_url=lambda *_args, **_kwargs: (
                calls.append(1)
                or DownloaderResult(False, "添加任务失败：HTTP 409", retryable=False)
            )
        )
        with patch("app.rss_service.QBittorrentClient", return_value=fake):
            ok, message = _push_feed_item(self.db, item, sub)
        self.assertFalse(ok)
        self.assertEqual(len(calls), 1)
        self.assertIn("已尝试 1 次", message)

    def test_http_torrent_is_downloaded_by_feeddock_and_uploaded_to_qbittorrent(self):
        sub = Subscription(name="HTTP torrent", rss_url="https://example.test/rss", rename_enabled=False)
        self.db.add(sub)
        self.db.flush()
        item = FeedItem(
            subscription_id=sub.id,
            fingerprint="http-torrent",
            title="HTTP torrent - 01",
            source_url="https://example.test/post/1",
            download_url="https://example.test/files/1.torrent?passkey=secret",
            episode="1",
        )
        self.db.add(item)
        self.db.flush()
        self.save_preferences(concurrent_limit=0, retry_count=0)
        calls = []
        fake = SimpleNamespace(
            add_torrent=lambda content, filename, *_args, **_kwargs: (
                calls.append((content, filename, _kwargs))
                or DownloaderResult(
                    True, "qBittorrent 已确认任务：HTTP torrent",
                    torrent_hash="torrent-hash", verified=True,
                )
            )
        )
        with (
            patch("app.rss_service.QBittorrentClient", return_value=fake),
            patch(
                "app.rss_service._download_torrent_file",
                return_value=(b"d4:infod4:name4:demoee", "episode-01.torrent"),
            ),
        ):
            ok, message = _push_feed_item(self.db, item, sub)
        self.assertTrue(ok, message)
        self.assertEqual(calls[0][1], "episode-01.torrent")
        self.assertEqual(item.torrent_hash, "torrent-hash")
        self.assertNotIn("passkey", message)

    def test_push_waits_when_concurrent_limit_is_full(self):
        sub = Subscription(name="Demo", rss_url="https://example.test/rss", rename_enabled=False)
        self.db.add(sub)
        self.db.flush()
        item = FeedItem(subscription_id=sub.id, fingerprint="x", title="Demo", download_url="magnet:?xt=urn:btih:x", episode="1")
        self.db.add(item)
        self.db.flush()
        self.save_preferences(concurrent_limit=1)
        fake = SimpleNamespace(active_download_count=lambda: (True, 1, "ok"))
        with patch("app.rss_service.QBittorrentClient", return_value=fake):
            ok, message = _push_feed_item(self.db, item, sub)
        self.assertTrue(ok)
        self.assertEqual(item.status, "scheduled")
        self.assertIn("并发空位", message)



    def test_qbittorrent_cleans_only_feeddock_item_tags(self):
        calls = []

        class TagClient:
            def __enter__(self): return self
            def __exit__(self, *_args): return False
            def get(self, path, params=None):
                calls.append(("GET", path, params))
                if path.endswith("torrents/tags"):
                    return _FakeHttpResponse([
                        "keep-user-tag",
                        "feeddock-item-1",
                        "feeddock-item-2",
                    ])
                if path.endswith("torrents/info"):
                    return _FakeHttpResponse([
                        {"hash": "hash-1", "tags": "keep-user-tag, feeddock-item-1"},
                        {"hash": "hash-2", "tags": "feeddock-item-2"},
                    ])
                return _FakeHttpResponse([])
            def post(self, path, data=None, files=None):
                calls.append(("POST", path, data))
                return _FakeHttpResponse()

        client = QBittorrentClient(
            base_url="http://qbit:8080", username="admin", password="pw"
        )
        with (
            patch.object(client, "_client", return_value=TagClient()),
            patch.object(client, "_login", return_value=DownloaderResult(True, "ok")),
        ):
            result = client.cleanup_internal_tags()
        self.assertTrue(result.ok, result.message)
        self.assertEqual(set(result.cleaned_tags), {"feeddock-item-1", "feeddock-item-2"})
        self.assertEqual(result.resolved_hashes["feeddock-item-1"], "hash-1")
        remove = next(call for call in calls if call[1].endswith("removeTags"))
        delete = next(call for call in calls if call[1].endswith("deleteTags"))
        self.assertEqual(remove[2]["hashes"], "all")
        self.assertNotIn("keep-user-tag", remove[2]["tags"])
        self.assertEqual(delete[2]["tags"], remove[2]["tags"])

    def test_successful_push_clears_temporary_tag_after_qbit_cleanup(self):
        sub = Subscription(name="Demo", rss_url="https://example.test/rss", rename_enabled=False)
        self.db.add(sub)
        self.db.flush()
        item = FeedItem(
            subscription_id=sub.id,
            fingerprint="cleaned-push",
            title="Demo - 01",
            download_url="magnet:?xt=urn:btih:cleaned",
            episode="1",
        )
        self.db.add(item)
        self.db.flush()
        self.save_preferences(concurrent_limit=0, retry_count=0)
        fake = SimpleNamespace(
            add_url=lambda *_args, **_kwargs: DownloaderResult(
                True,
                "qBittorrent 已确认任务；临时标签已清理",
                torrent_hash="hash-cleaned",
                verified=True,
                tag_removed=True,
            )
        )
        with patch("app.rss_service.QBittorrentClient", return_value=fake):
            ok, _message = _push_feed_item(self.db, item, sub)
        self.assertTrue(ok)
        self.assertEqual(item.torrent_hash, "hash-cleaned")
        self.assertEqual(item.qbit_tag, "")

    def test_legacy_item_tags_are_cleaned_and_hashes_preserved(self):
        sub = Subscription(name="Legacy", rss_url="https://example.test/rss")
        self.db.add(sub)
        self.db.flush()
        item = FeedItem(
            subscription_id=sub.id,
            fingerprint="legacy-tag",
            title="Legacy 01",
            status="queued",
            qbit_tag="feeddock-item-77",
            torrent_hash="",
        )
        self.db.add(item)
        self.db.commit()
        cleanup = InternalTagCleanupResult(
            True,
            "已清理 2 个 FeedDock 临时标签",
            ("feeddock-item-77", "feeddock-item-orphan"),
            {"feeddock-item-77": "legacy-hash"},
        )
        fake = SimpleNamespace(cleanup_internal_tags=lambda: cleanup)
        with patch("app.postprocess.QBittorrentClient", return_value=fake):
            result = cleanup_internal_qbittorrent_tags(self.db)
        self.db.refresh(item)
        self.assertTrue(result["ok"])
        self.assertEqual(result["cleaned"], 2)
        self.assertEqual(item.torrent_hash, "legacy-hash")
        self.assertEqual(item.qbit_tag, "")


if __name__ == "__main__":
    unittest.main()

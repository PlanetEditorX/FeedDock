from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.downloader import DownloaderResult, QBittorrentClient
from app.media_sidecar import write_bangumi_ini
from app.models import FeedItem, Subscription
from app.rss_service import _existing_video_matches, _push_feed_item, dispatch_scheduled_downloads
from app.settings_config import (
    load_application_preferences,
    normalize_tracker_text,
    save_application_preferences,
    save_tracker_cache,
)
from app.subscription_monitor import evaluate_subscription_completion
from app.metadata_service import MetadataService
from app.runtime_config import save_metadata_config


class _FakeHttpResponse:
    status_code = 200
    text = "Ok."


class _FakeQbitHttpClient:
    def __init__(self) -> None:
        self.add_files = None
        self.posts = []

    def __enter__(self): return self
    def __exit__(self, *_args): return False

    def post(self, path, data=None, files=None):
        self.posts.append((path, data, files))
        if path.endswith("torrents/add"):
            self.add_files = files
        return _FakeHttpResponse()


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
            "rss_enabled": True,
            "rss_timeout_seconds": 20,
            "auto_skip_existing": False,
            "auto_disable_complete": False,
            "trackers_enabled": True,
            "trackers_update_url": "https://example.test/trackers.txt",
        }
        values.update(overrides)
        return save_application_preferences(self.db, **values)

    def test_preferences_persist_and_tracker_cache_is_deduplicated(self):
        saved = self.save_preferences()
        self.assertEqual(saved.page.theme_color, "green")
        self.assertEqual(saved.download.retry_count, 3)
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

    def test_qbittorrent_add_includes_seeding_limit(self):
        fake = _FakeQbitHttpClient()
        client = QBittorrentClient(base_url="http://qbit.test", username="u", password="p")
        with patch.object(client, "_client", return_value=fake), patch.object(client, "_login", return_value=DownloaderResult(True, "ok")):
            result = client.add_url("magnet:?xt=urn:btih:demo", "/media/Demo", seeding_minutes=120)
        self.assertTrue(result.ok)
        self.assertEqual(fake.add_files["seedingTimeLimit"][1], "120")

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


if __name__ == "__main__":
    unittest.main()

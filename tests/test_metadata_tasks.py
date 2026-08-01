from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.metadata_tasks import refresh_all_metadata, scrape_completed_media
from app.models import FeedItem, Subscription, SystemLog
from app.scraper import scrape_local_metadata


class ScrapeLocalMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine, expire_on_commit=False)

    @patch("app.scraper.load_metadata_config")
    def test_disabled_auto_scrape_returns_early(self, mock_load_metadata_config) -> None:
        mock_load_metadata_config.return_value = SimpleNamespace(auto_scrape_enabled=False)
        with self.Session() as db:
            subscription = Subscription(name="Disabled", rss_url="")
            db.add(subscription)
            db.commit()
            result = scrape_local_metadata(db, subscription)

        self.assertTrue(result.ok)
        self.assertEqual(result.message, "本地元数据刮削已禁用")

    @patch("app.scraper.map_downloader_path_to_local")
    @patch("app.scraper.load_qbittorrent_config")
    @patch("app.scraper.load_metadata_config")
    def test_path_resolution_failure(
        self, mock_load_metadata_config, mock_load_qbittorrent_config, mock_map_path
    ) -> None:
        mock_load_metadata_config.return_value = SimpleNamespace(auto_scrape_enabled=True, media_local_root="/media")
        mock_load_qbittorrent_config.return_value = SimpleNamespace(download_path="/downloads")
        mock_map_path.side_effect = ValueError("path error")

        with self.Session() as db:
            subscription = Subscription(name="PathFail", rss_url="")
            subscription.save_path = "/downloads/PathFail"
            db.add(subscription)
            db.commit()
            result = scrape_local_metadata(db, subscription)

        self.assertFalse(result.ok)
        self.assertIn("下载路径不存在", result.message)

    @patch("app.scraper.map_downloader_path_to_local")
    @patch("app.scraper.load_qbittorrent_config")
    @patch("app.scraper.load_metadata_config")
    def test_skips_trial_bulk(
        self, mock_load_metadata_config, mock_load_qbittorrent_config, mock_map_path
    ) -> None:
        mock_load_metadata_config.return_value = SimpleNamespace(auto_scrape_enabled=True, media_local_root="/media")
        mock_load_qbittorrent_config.return_value = SimpleNamespace(download_path="/downloads")
        mock_map_path.return_value = "/local/path"

        with self.Session() as db:
            subscription = Subscription(name="Trial", rss_url="")
            subscription.trial_bulk = True
            db.add(subscription)
            db.commit()
            result = scrape_local_metadata(db, subscription)

        self.assertFalse(result.ok)
        self.assertEqual(result.message, "批量试看不收集元数据或刮削")

    @patch("app.scraper.map_downloader_path_to_local")
    @patch("app.scraper.load_qbittorrent_config")
    @patch("app.scraper.load_metadata_config")
    def test_no_completed_items(
        self, mock_load_metadata_config, mock_load_qbittorrent_config, mock_map_path
    ) -> None:
        mock_load_metadata_config.return_value = SimpleNamespace(auto_scrape_enabled=True, media_local_root="/media")
        mock_load_qbittorrent_config.return_value = SimpleNamespace(download_path="/downloads")
        mock_map_path.return_value = "/local/path"

        with self.Session() as db:
            subscription = Subscription(name="Normal", rss_url="")
            db.add(subscription)
            db.flush()
            # Add an incomplete item
            item = FeedItem(subscription_id=subscription.id, fingerprint="incomplete", title="incomplete", status="queued")
            db.add(item)
            db.commit()

            result = scrape_local_metadata(db, subscription)

        self.assertFalse(result.ok)
        self.assertEqual(result.message, "没有已完成的下载条目可刮削")

    @patch("app.scraper.scrape_completed_item")
    @patch("app.media_sidecar.write_bangumi_ini")
    @patch("app.scraper.map_downloader_path_to_local")
    @patch("app.scraper.load_qbittorrent_config")
    @patch("app.scraper.load_metadata_config")
    def test_success_aggregates_files_and_calls_sidecar(
        self, mock_load_metadata_config, mock_load_qbittorrent_config, mock_map_path, mock_write_ini, mock_scrape_completed
    ) -> None:
        mock_load_metadata_config.return_value = SimpleNamespace(auto_scrape_enabled=True, media_local_root="/media")
        mock_load_qbittorrent_config.return_value = SimpleNamespace(download_path="/downloads")
        mock_map_path.return_value = "/local/path"

        with self.Session() as db:
            subscription = Subscription(name="Success", rss_url="")
            db.add(subscription)
            db.flush()

            item1 = FeedItem(subscription_id=subscription.id, fingerprint="item1", title="1", completed_at=datetime.now(timezone.utc))
            item2 = FeedItem(subscription_id=subscription.id, fingerprint="item2", title="2", completed_at=datetime.now(timezone.utc))
            db.add_all([item1, item2])
            db.commit()

            mock_scrape_completed.side_effect = [
                SimpleNamespace(ok=True, files=["/mock_media/show/tvshow.nfo"], local_path="/mock_media/show"),
                SimpleNamespace(ok=True, files=["/mock_media/show/Season 01/season.nfo"], local_path="/mock_media/show")
            ]

            result = scrape_local_metadata(db, subscription)

        self.assertTrue(result.ok)
        self.assertEqual(result.message, "已刮削 2 个已完成条目")
        self.assertEqual(result.local_path, "/mock_media/show")
        self.assertEqual(result.files, ["/mock_media/show/tvshow.nfo", "/mock_media/show/Season 01/season.nfo"])
        self.assertEqual(mock_scrape_completed.call_count, 2)
        self.assertEqual(mock_write_ini.call_count, 2)


class MetadataRefreshTaskTests(unittest.TestCase):
    def test_refresh_all_metadata_logs_success_and_failure(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        with Session() as db:
            db.add_all(
                [
                    Subscription(name="Success", rss_url="https://example.test/1", bangumi_id=1),
                    Subscription(name="Failure", rss_url="https://example.test/2", bangumi_id=2),
                ]
            )
            db.commit()

        class FakeMetadataService:
            def __init__(self, **_kwargs) -> None:
                pass

            def sync(self, _db, subscription, _provider):
                if subscription.name == "Failure":
                    raise ValueError("metadata unavailable")
                return SimpleNamespace(provider="bangumi", id=subscription.bangumi_id, total_episodes=12)

        with (
            patch("app.metadata_tasks.SessionLocal", Session),
            patch("app.metadata_tasks.MetadataService", FakeMetadataService),
            patch(
                "app.metadata_tasks.load_application_preferences",
                return_value=SimpleNamespace(rss=SimpleNamespace(timeout_seconds=20)),
            ),
        ):
            result = refresh_all_metadata()

        self.assertFalse(result["ok"])
        self.assertEqual(result["subscriptions"], 2)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["errors"], 1)
        with Session() as db:
            messages = list(db.scalars(select(SystemLog.message).order_by(SystemLog.id)))
        self.assertIn("开始同步订阅元数据", messages)
        self.assertTrue(any(message.startswith("订阅元数据已同步") for message in messages))
        self.assertTrue(any(message.startswith("订阅元数据同步失败") for message in messages))
        self.assertIn("同步订阅元数据完成", messages)

    def test_scrape_completed_media_updates_item_state_and_logs(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        with Session() as db:
            subscription = Subscription(
                name="Completed", rss_url="https://example.test/rss", metadata_last_synced_at=None
            )
            db.add(subscription)
            db.flush()
            item = FeedItem(
                subscription_id=subscription.id, fingerprint="completed-item", title="Episode 1",
                status="queued", completed_at=datetime.now(timezone.utc),
                scrape_status="pending", save_path="/media/Completed/Season 01",
            )
            db.add(item)
            db.commit()
            item_id = item.id

        class FakeMetadataService:
            def __init__(self, **_kwargs) -> None:
                pass

            def sync(self, _db, subscription, _provider):
                subscription.metadata_last_synced_at = datetime.now(timezone.utc)
                return SimpleNamespace(provider="bangumi", id=1)

        with (
            patch("app.metadata_tasks.SessionLocal", Session),
            patch("app.metadata_tasks.MetadataService", FakeMetadataService),
            patch(
                "app.metadata_tasks.load_application_preferences",
                return_value=SimpleNamespace(rss=SimpleNamespace(timeout_seconds=20)),
            ),
            patch(
                "app.scraper.scrape_completed_item",
                return_value=SimpleNamespace(
                    ok=True, message="已写入媒体库元数据", local_path="/media/Completed",
                    files=["/media/Completed/tvshow.nfo"],
                ),
            ),
        ):
            result = scrape_completed_media()

        self.assertTrue(result["ok"])
        self.assertEqual(result["scraped"], 1)
        with Session() as db:
            item = db.get(FeedItem, item_id)
            self.assertEqual(item.scrape_status, "completed")
            self.assertIn("写入媒体库", item.scrape_message)
            messages = list(db.scalars(select(SystemLog.message).order_by(SystemLog.id)))
        self.assertIn("开始刮削已完成媒体", messages)
        self.assertTrue(any(message.startswith("媒体库刮削完成") for message in messages))
        self.assertIn("刮削已完成媒体结束", messages)

    def test_scrape_completed_media_can_target_one_subscription(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        with Session() as db:
            synced_at = datetime.now(timezone.utc)
            first = Subscription(
                name="First", rss_url="https://example.test/first", metadata_last_synced_at=synced_at
            )
            second = Subscription(
                name="Second", rss_url="https://example.test/second", metadata_last_synced_at=synced_at
            )
            db.add_all([first, second])
            db.flush()
            first_item = FeedItem(
                subscription_id=first.id,
                fingerprint="first-completed",
                title="First Episode",
                status="queued",
                completed_at=datetime.now(timezone.utc),
                scrape_status="pending",
                save_path="/media/First/Season 01",
            )
            second_item = FeedItem(
                subscription_id=second.id,
                fingerprint="second-completed",
                title="Second Episode",
                status="queued",
                completed_at=datetime.now(timezone.utc),
                scrape_status="pending",
                save_path="/media/Second/Season 01",
            )
            db.add_all([first_item, second_item])
            db.commit()
            first_id, second_item_id = first.id, second_item.id

        with (
            patch("app.metadata_tasks.SessionLocal", Session),
            patch(
                "app.metadata_tasks.load_application_preferences",
                return_value=SimpleNamespace(rss=SimpleNamespace(timeout_seconds=20)),
            ),
            patch(
                "app.scraper.scrape_completed_item",
                return_value=SimpleNamespace(
                    ok=True,
                    message="已写入媒体库元数据",
                    local_path="/media/First",
                    files=["/media/First/tvshow.nfo"],
                ),
            ),
        ):
            result = scrape_completed_media(first_id)

        self.assertTrue(result["ok"])
        self.assertEqual(result["items"], 1)
        with Session() as db:
            untouched = db.get(FeedItem, second_item_id)
            self.assertEqual(untouched.scrape_status, "pending")
            messages = list(db.scalars(select(SystemLog.message).order_by(SystemLog.id)))
        self.assertIn("开始刮削订阅媒体", messages)
        self.assertIn("刮削订阅媒体结束", messages)


if __name__ == "__main__":
    unittest.main()

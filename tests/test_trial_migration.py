from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.downloader import TorrentRelocateResult
from app.models import FeedItem, Subscription
from app.trial import SUBSCRIBED_SAVE_PATH_TEMPLATE
from app.trial_migration import promote_trial_download


class TrialMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_completed_trial_file_is_renamed_and_moved_after_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as root_value:
            root = Path(root_value)
            trial_dir = root / "试看"
            trial_dir.mkdir()
            source = trial_dir / "试看动画 - S01E01.mkv"
            subtitle = trial_dir / "试看动画 - S01E01.zh-CN.ass"
            source.write_bytes(b"video")
            subtitle.write_text("subtitle", encoding="utf-8")

            subscription = Subscription(
                name="正式动画 (2026)",
                reference_title="正式动画 (2026)",
                rss_url="https://example.test/trial.xml",
                subscription_mode="subscribed",
                save_path_template=SUBSCRIBED_SAVE_PATH_TEMPLATE,
                season=1,
                metadata_year=2026,
                rename_enabled=True,
            )
            self.db.add(subscription)
            self.db.flush()
            item = FeedItem(
                subscription_id=subscription.id,
                fingerprint="trial-file",
                title="试看动画 - 01",
                episode="1",
                status="queued",
                save_path=str(trial_dir),
                trial_download_path=str(source),
                desired_name="试看动画 - S01E01",
                completed_at=datetime.now(timezone.utc),
            )
            self.db.add(item)
            self.db.commit()

            metadata = SimpleNamespace(
                downloader_root=str(root),
                media_local_root=str(root),
            )
            qbit = SimpleNamespace(download_path=str(root))
            with (
                patch("app.trial_migration.load_metadata_config", return_value=metadata),
                patch("app.rss_service.load_qbittorrent_config", return_value=qbit),
            ):
                result = promote_trial_download(self.db, subscription)
            self.db.commit()

            target = root / "正式动画 (2026)" / "Season 01" / "正式动画 (2026) - S01E01.mkv"
            target_subtitle = target.with_name("正式动画 (2026) - S01E01.zh-CN.ass")
            self.assertTrue(result.found)
            self.assertTrue(result.moved)
            self.assertTrue(target.exists())
            self.assertTrue(target_subtitle.exists())
            self.assertFalse(source.exists())
            self.assertFalse(trial_dir.exists())
            self.assertIn("原位置空目录", result.message)
            self.assertEqual(item.trial_download_path, str(source))
            self.assertEqual(item.save_path, str(target.parent))
            self.assertEqual(item.desired_name, "正式动画 (2026) - S01E01")

    def test_qbittorrent_migration_removes_original_empty_directories(self) -> None:
        with tempfile.TemporaryDirectory() as root_value:
            root = Path(root_value)
            trial_root = root / "试看"
            old_directory = trial_root / "旧番剧 (2026)"
            old_directory.mkdir(parents=True)
            sibling = trial_root / "保留目录"
            sibling.mkdir()

            subscription = Subscription(
                name="正式动画 (2026)",
                reference_title="正式动画 (2026)",
                rss_url="https://example.test/qbit-trial.xml",
                subscription_mode="subscribed",
                save_path_template=SUBSCRIBED_SAVE_PATH_TEMPLATE,
                season=1,
                metadata_year=2026,
                rename_enabled=True,
            )
            self.db.add(subscription)
            self.db.flush()
            item = FeedItem(
                subscription_id=subscription.id,
                fingerprint="qbit-trial-file",
                title="旧番剧 - 01",
                episode="1",
                status="queued",
                save_path=str(old_directory),
                trial_download_path=str(old_directory / "旧番剧 - S01E01.mkv"),
                desired_name="旧番剧 - S01E01",
                torrent_hash="abc123",
                completed_at=datetime.now(timezone.utc),
            )
            self.db.add(item)
            self.db.commit()

            target = root / "正式动画 (2026)" / "Season 01" / "正式动画 (2026) - S01E01.mkv"
            client = SimpleNamespace(
                relocate_single_video=Mock(
                    return_value=TorrentRelocateResult(
                        True,
                        True,
                        True,
                        "试看文件已移动到正式目录",
                        str(target),
                    )
                )
            )
            metadata = SimpleNamespace(
                downloader_root=str(root),
                media_local_root=str(root),
            )
            with patch("app.trial_migration.load_metadata_config", return_value=metadata):
                result = promote_trial_download(self.db, subscription, client=client)

            self.assertTrue(result.found)
            self.assertTrue(result.moved)
            self.assertFalse(old_directory.exists())
            self.assertTrue(trial_root.exists())
            self.assertTrue(sibling.exists())
            self.assertIn("清理 1 个原位置空目录", result.message)
            self.assertEqual(item.save_path, "/media/正式动画 (2026)/Season 01")

    def test_missing_trial_file_does_not_block_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as root_value:
            root = Path(root_value)
            subscription = Subscription(
                name="正式动画",
                rss_url="https://example.test/missing.xml",
                subscription_mode="subscribed",
                save_path_template=SUBSCRIBED_SAVE_PATH_TEMPLATE,
            )
            self.db.add(subscription)
            self.db.flush()
            self.db.add(FeedItem(
                subscription_id=subscription.id,
                fingerprint="missing-trial-file",
                title="试看动画 - 01",
                episode="1",
                status="queued",
                save_path=str(root / "试看"),
                trial_download_path=str(root / "试看" / "missing.mkv"),
            ))
            self.db.commit()

            metadata = SimpleNamespace(
                downloader_root=str(root),
                media_local_root=str(root),
            )
            qbit = SimpleNamespace(download_path=str(root))
            with (
                patch("app.trial_migration.load_metadata_config", return_value=metadata),
                patch("app.rss_service.load_qbittorrent_config", return_value=qbit),
            ):
                result = promote_trial_download(self.db, subscription)

            self.assertTrue(result.found)
            self.assertFalse(result.moved)
            self.assertIn("不存在", result.message)


if __name__ == "__main__":
    unittest.main()

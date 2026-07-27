import unittest
from types import SimpleNamespace
from unittest.mock import ANY, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.rss_parser import parse_feed
from app.downloader import DownloaderResult
from app.database import Base
from app.models import FeedItem, Subscription, SystemLog
from app.rss_service import (
    apply_episode_offset,
    extract_download_url,
    match_title,
    parse_episode,
    preview_subscription,
    process_subscription,
    refresh_subscription,
    render_save_path,
)


class RSSServiceTests(unittest.TestCase):
    def test_keyword_matching(self):
        self.assertTrue(match_title("Example 1080p 简体", "1080p,简体", "合集")[0])
        self.assertFalse(match_title("Example 1080p 合集", "1080p", "合集")[0])
        self.assertFalse(match_title("Example 720p", "1080p,2160p", "")[0])

    def test_episode_parsing(self):
        self.assertEqual(parse_episode("[Group] Example - 03 [1080p]"), "3")
        self.assertEqual(parse_episode("Example EP12"), "12")
        self.assertEqual(parse_episode("Example 第7集"), "7")
        self.assertEqual(parse_episode("Example S02E09", r"S\d+E(\d+)"), "9")

    def test_download_url_prefers_torrent_enclosure(self):
        entry = {
            "link": "https://example.com/post/1",
            "enclosures": [{"href": "https://example.com/file.torrent", "type": "application/x-bittorrent"}],
        }
        self.assertEqual(extract_download_url(entry), "https://example.com/file.torrent")

    def test_extract_magnet(self):
        entry = {"summary": '<a href="magnet:?xt=urn:btih:ABC123&amp;dn=test">download</a>'}
        self.assertTrue(extract_download_url(entry).startswith("magnet:?"))

    def test_parse_rss(self):
        content = b"""<?xml version='1.0'?><rss version='2.0'><channel><item><title>Demo - 01 [1080p]</title><guid>x1</guid><link>https://example.com/post</link><enclosure url='https://example.com/1.torrent' type='application/x-bittorrent'/><pubDate>Sat, 25 Jul 2026 12:00:00 +0000</pubDate></item></channel></rss>"""
        entries = parse_feed(content)
        self.assertEqual(entries[0]["title"], "Demo - 01 [1080p]")
        self.assertEqual(extract_download_url(entries[0]), "https://example.com/1.torrent")

    def test_parse_atom(self):
        content = b"""<?xml version='1.0'?><feed xmlns='http://www.w3.org/2005/Atom'><entry><title>Demo EP02</title><id>x2</id><updated>2026-07-25T12:00:00Z</updated><link rel='alternate' href='https://example.com/post/2'/><link rel='enclosure' type='application/x-bittorrent' href='https://example.com/2.torrent'/></entry></feed>"""
        entries = parse_feed(content)
        self.assertEqual(entries[0]["id"], "x2")
        self.assertEqual(extract_download_url(entries[0]), "https://example.com/2.torrent")

    def test_advanced_rules_offset_and_custom_path(self):
        sub = Subscription(
            name="金牌得主 第二季",
            reference_title="金牌得主 (2025)",
            rss_url="https://example.com/feed.xml",
            include_keywords="",
            exclude_keywords="720\n\\d-\\d\n合集\n特别篇",
            episode_regex=r"\d+(\.5)?",
            episode_group=0,
            episode_offset=-13,
            total_episodes=9,
            season=2,
            naming_mode="tmdb",
            tmdb_title="金牌得主 (2025)",
            metadata_year=2025,
            tmdb_id=123,
            custom_download_path="/vol2/1000/影视/金牌得主 (2025)/Season 2",
            save_path_template="{base}/{subscription}/Season {season}",
        )
        result = preview_subscription(
            sub,
            "[LoliHouse] 金牌得主 - 14 [1080p]",
        )
        self.assertTrue(result["matched"])
        self.assertEqual(result["parsed_episode"], "14")
        self.assertEqual(result["adjusted_episode"], "1")
        self.assertEqual(result["save_path"], "/media/金牌得主 (2025)/Season 02")

    def test_regex_and_global_exclusion(self):
        self.assertFalse(match_title("Demo 01-02 1080p", "", r"\d-\d", "")[0])
        matched, reason = match_title("金牌得主 剧场版 1080p", "", "", "剧场版")
        self.assertFalse(matched)
        self.assertIn("全局排除", reason)

    def test_decimal_episode_offset(self):
        self.assertEqual(parse_episode("Demo 13.5", r"\d+(\.5)?", 0), "13.5")
        self.assertEqual(apply_episode_offset("13.5", -13), "0.5")

    def test_preview_without_episode_uses_e01_example(self):
        sub = Subscription(
            name="从0位居民开始的边境领主大人 (2026)",
            tmdb_title="从0位居民开始的边境领主大人 (2026)",
            naming_mode="tmdb",
            metadata_year=2026,
            tmdb_id=296437,
            rss_url="https://example.com/feed.xml",
            season=1,
            rename_enabled=True,
            file_name_template="{title} - S{season:02}E{episode:02}",
            save_path_template="{base}/{media_folder}/Season {season:02}",
        )
        result = preview_subscription(sub, "从0位居民开始的边境领主大人 (2026)")
        self.assertFalse(result["episode_recognized"])
        self.assertEqual(result["preview_episode"], "1")
        self.assertNotIn("unknown", result["desired_name"])
        self.assertTrue(result["desired_name"].endswith("S01E01"))
        self.assertEqual(
            result["save_path"],
            "/media/从0位居民开始的边境领主大人 (2026)/Season 01",
        )

    def test_path_traversal_is_confined(self):
        sub = Subscription(name="Demo", rss_url="https://example.com/feed.xml", save_path_template="{base}/../../etc")
        self.assertEqual(render_save_path(sub, "1"), "/media/Demo/Season 01")


    def test_new_subscription_refresh_pushes_and_logs(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        with factory() as db:
            subscription = Subscription(
                name="Auto refresh demo",
                rss_url="https://example.test/feed.xml",
                rename_enabled=False,
            )
            db.add(subscription)
            db.commit()
            subscription_id = subscription.id

        entries = [{
            "id": "auto-1",
            "title": "Auto refresh demo - 01 [1080p]",
            "link": "https://example.test/post/1",
            "enclosures": [{
                "href": "https://example.test/1.torrent",
                "type": "application/x-bittorrent",
            }],
        }]
        fake_qbit = type("FakeQbit", (), {
            "add_url": lambda self, *_args, **_kwargs: DownloaderResult(
                True, "qBittorrent 已确认任务：Auto refresh demo",
                torrent_hash="auto-hash", verified=True,
            )
        })()
        with (
            patch("app.rss_service.SessionLocal", factory),
            patch("app.rss_service._refresh_total_episodes_if_due"),
            patch("app.rss_service._sync_metadata_if_due"),
            patch("app.rss_service._load_subscription_entries", return_value=(entries, "测试 RSS")),
            patch("app.rss_service.evaluate_missing_episodes"),
            patch("app.rss_service.evaluate_stale_subscription"),
            patch("app.rss_service.evaluate_subscription_completion"),
            patch("app.rss_service.QBittorrentClient", return_value=fake_qbit),
        ):
            result = refresh_subscription(subscription_id, trigger="subscription-created")

        self.assertTrue(result["ok"])
        self.assertEqual(result["queued"], 1)
        with factory() as db:
            item = db.query(FeedItem).one()
            self.assertEqual(item.status, "queued")
            messages = [row.message for row in db.query(SystemLog).order_by(SystemLog.id)]
            self.assertIn("新订阅自动刷新开始：Auto refresh demo", messages)
            self.assertIn("qBittorrent 已确认任务：Auto refresh demo", messages)
            self.assertIn("新订阅自动刷新完成：Auto refresh demo", messages)
        engine.dispose()


    def test_orphan_cleanup_runs_even_when_rss_switch_is_disabled(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            subscription = Subscription(name="Demo", rss_url="https://example.test/feed.xml")
            db.add(subscription)
            db.commit()
            with (
                patch(
                    "app.rss_service.load_application_preferences",
                    return_value=SimpleNamespace(rss=SimpleNamespace(enabled=False)),
                ),
                patch("app.rss_service.cleanup_orphaned_metadata") as cleanup,
                patch("app.rss_service._load_subscription_entries") as load_entries,
            ):
                cleanup.return_value = SimpleNamespace(ok=True, message="没有孤儿元数据", removed_files=[])
                stats = process_subscription(db, subscription)
            cleanup.assert_called_once_with(db, subscription)
            load_entries.assert_not_called()
            self.assertEqual(stats, {"new": 0, "queued": 0, "skipped": 0, "errors": 0})
        engine.dispose()

    def test_rss_refresh_rechecks_completion_for_historical_completed_items(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            subscription = Subscription(
                name="Demo",
                rss_url="https://example.test/feed.xml",
                total_episodes=1,
                auto_disable_when_complete=True,
            )
            db.add(subscription)
            db.commit()
            with (
                patch("app.rss_service._sync_metadata_if_due"),
                patch("app.rss_service._load_subscription_entries", return_value=([], "测试源")),
                patch("app.rss_service.evaluate_missing_episodes"),
                patch("app.rss_service.evaluate_stale_subscription"),
                patch("app.rss_service.evaluate_subscription_completion") as completion,
            ):
                process_subscription(db, subscription)
            completion.assert_called_once_with(db, subscription, now=ANY)
        engine.dispose()



if __name__ == "__main__":
    unittest.main()

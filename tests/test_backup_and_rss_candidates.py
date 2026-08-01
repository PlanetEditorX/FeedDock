from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.backup_service import (
    export_system_backup,
    import_anime_preferences,
    import_app_settings,
    validate_system_backup,
)
from app.database import Base
from app.models import AnimePreference, AppSetting, Subscription, SystemLog
from app.rss_candidates import search_subscription_rss_candidates
from app.rss_service import process_subscription


class BackupAndRssCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_system_backup_omits_secrets_and_transient_cache(self) -> None:
        self.db.add_all([
            AppSetting(key="page_theme_color", value="green"),
            AppSetting(key="qbit_password", value="secret"),
            AppSetting(key="qbit_api_key", value="qbt_" + ("x" * 28)),
            AppSetting(key="update_manifest_cache_json", value="{}"),
            Subscription(name="Demo", rss_url="https://example.test/demo.xml"),
            AnimePreference(canonical_key="bgm:123", bangumi_id=123, hidden=True),
        ])
        self.db.commit()

        payload = export_system_backup(self.db, include_secrets=False)
        self.assertEqual(payload["format"], "feeddock-system-backup")
        self.assertEqual(payload["settings"]["page_theme_color"], "green")
        self.assertNotIn("qbit_password", payload["settings"])
        self.assertNotIn("qbit_api_key", payload["settings"])
        self.assertNotIn("update_manifest_cache_json", payload["settings"])
        self.assertIn("qbit_password", payload["omitted_secret_keys"])
        self.assertIn("qbit_api_key", payload["omitted_secret_keys"])
        self.assertEqual(len(payload["subscriptions"]), 1)
        self.assertEqual(payload["anime_preferences"][0]["canonical_key"], "bgm:123")

    def test_replace_without_secret_values_preserves_current_secrets(self) -> None:
        self.db.add_all([
            AppSetting(key="qbit_password", value="keep-me"),
            AppSetting(key="page_theme_color", value="blue"),
        ])
        self.db.commit()
        backup = validate_system_backup({
            "format": "feeddock-system-backup",
            "version": 1,
            "secrets_included": False,
            "settings": {"page_theme_color": "rose"},
            "subscriptions": [],
            "anime_preferences": [],
        })
        import_app_settings(
            self.db,
            backup["settings"],
            replace=True,
            preserve_sensitive=True,
        )
        import_anime_preferences(self.db, [], replace=True)
        self.db.commit()
        self.assertEqual(self.db.get(AppSetting, "qbit_password").value, "keep-me")
        self.assertEqual(self.db.get(AppSetting, "page_theme_color").value, "rose")

    def test_cross_site_rss_candidate_search_lists_all_groups(self) -> None:
        subscription = Subscription(
            name="欺诈游戏 (2026)",
            reference_title="欺诈游戏",
            tmdb_title="欺诈游戏 (2026)",
            source_type="mikan",
            source_anime_id="3941",
            bangumi_id=123,
            rss_url="https://mikanani.me/RSS/Bangumi?bangumiId=3941&subgroupid=223",
        )
        self.db.add(subscription)
        self.db.commit()

        class FakeDiscovery:
            def search_mikan(self, _query, limit=8):
                return [{"title": "欺诈游戏", "bangumi_id": 3941, "base_url": "https://mikanime.tv"}]

        class FakeMikanCache:
            def __init__(self, _discovery):
                pass

            def detail(self, _db, _id, _base, _title):
                return {
                    "title": "欺诈游戏",
                    "detail_url": "https://mikanime.tv/Home/Bangumi/3941",
                    "groups": [
                        {"name": "字幕组 A", "rss_url": "https://mikanime.tv/a.xml", "entries": [{}]},
                        {"name": "字幕组 B", "rss_url": "https://mikanime.tv/b.xml", "entries": []},
                    ],
                }

        class FakeProvider:
            def __init__(self, source_id: str):
                self.source_id = source_id

            def fetch_catalog(self, _db, _year, _season, query=""):
                return {"rows": [{"items": [{
                    "title": "欺诈游戏",
                    "aliases": ["欺诈游戏"],
                    "subject_id": 123,
                    "source_anime_id": f"{self.source_id}-123",
                }]}]}

            def fetch_detail(self, _db, item):
                return {
                    "title": item["title"],
                    "detail_url": f"https://{self.source_id}.example/title/123",
                    "groups": [{
                        "name": f"{self.source_id} 组",
                        "rss_url": f"https://{self.source_id}.example/feed.xml",
                        "entries": [{}, {}],
                    }],
                }

        with (
            patch("app.rss_candidates.DiscoveryService", FakeDiscovery),
            patch("app.rss_candidates.MikanCacheService", FakeMikanCache),
            patch("app.rss_candidates.get_catalog_provider", side_effect=lambda source: FakeProvider(source)),
        ):
            result = search_subscription_rss_candidates(self.db, subscription)

        self.assertEqual({row["source_id"] for row in result["candidates"]}, {"mikan", "anibt", "ag"})
        self.assertEqual(len(result["candidates"]), 4)
        self.assertTrue(any(row["bangumi_id"] == 123 for row in result["candidates"] if row["source_id"] != "mikan"))

    def test_current_anibt_source_id_is_used_when_bangumi_id_is_missing(self) -> None:
        subscription = Subscription(
            name="Current ANI",
            reference_title="Current ANI",
            source_type="anibt",
            source_anime_id="456",
            bangumi_id=0,
            rss_url="https://anibt.net/rss/anime.xml?bgmId=456&groupSlug=demo",
        )
        self.db.add(subscription)
        self.db.commit()

        class FakeDiscovery:
            def search_mikan(self, _query, limit=8):
                return []

        class FakeMikanCache:
            def __init__(self, _discovery):
                pass

        class FakeProvider:
            def __init__(self, source_id: str):
                self.source_id = source_id
                self.detail_subject_ids: list[int] = []

            def fetch_catalog(self, _db, _year, _season, query=""):
                return {"rows": []}

            def fetch_detail(self, _db, item):
                subject_id = int(item.get("subject_id") or 0)
                self.detail_subject_ids.append(subject_id)
                return {
                    "title": item["title"],
                    "groups": [{
                        "name": "当前字幕组",
                        "rss_url": f"https://{self.source_id}.example/{subject_id}.xml",
                        "entries": [{}],
                    }],
                }

        providers = {source: FakeProvider(source) for source in ("anibt", "ag")}
        with (
            patch("app.rss_candidates.DiscoveryService", FakeDiscovery),
            patch("app.rss_candidates.MikanCacheService", FakeMikanCache),
            patch("app.rss_candidates.get_catalog_provider", side_effect=lambda source: providers[source]),
        ):
            result = search_subscription_rss_candidates(self.db, subscription)

        anibt_rows = [row for row in result["candidates"] if row["source_id"] == "anibt"]
        self.assertEqual(len(anibt_rows), 1)
        self.assertEqual(anibt_rows[0]["source_anime_id"], "456")
        self.assertEqual(anibt_rows[0]["match_reason"], "当前站点番剧 ID")
        self.assertEqual(providers["anibt"].detail_subject_ids, [456])

    def test_empty_rss_log_is_actionable_without_traceback_in_info_mode(self) -> None:
        subscription = Subscription(name="Empty", rss_url="https://example.test/empty.xml")
        self.db.add(subscription)
        self.db.commit()
        with (
            patch("app.rss_service.cleanup_orphaned_metadata", return_value=SimpleNamespace(ok=True, message="ok", removed_files=[])),
            patch("app.rss_service.load_application_preferences", return_value=SimpleNamespace(rss=SimpleNamespace(enabled=True))),
            patch("app.rss_service._refresh_total_episodes_if_due"),
            patch("app.rss_service._sync_metadata_if_due"),
            patch("app.rss_service._load_subscription_entries", side_effect=RuntimeError("主 RSS 没有条目")),
            patch("app.rss_service.send_notification"),
            patch("app.rss_service.debug_enabled", return_value=False),
        ):
            stats = process_subscription(self.db, subscription)
        self.assertEqual(stats["errors"], 1)
        log = self.db.scalar(select(SystemLog).where(SystemLog.message.like("订阅检查失败%")))
        self.assertIsNotNone(log)
        self.assertIn("更新 RSS", log.details)
        self.assertNotIn("Traceback", log.details)
        self.assertNotIn("rss_url", log.details)


if __name__ == "__main__":
    unittest.main()

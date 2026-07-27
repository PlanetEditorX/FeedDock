from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.anime_catalog import (
    AnimeCatalogCacheService,
    decorate_catalog,
    parse_bangumi_data_items,
    refresh_due_anime_catalogs,
    source_groups,
)
from app.database import Base
from app.models import MikanCacheEntry, Subscription


SAMPLE_ITEM = {
    "title": "Sample Anime",
    "titleTranslate": {
        "zh-Hans": ["示例动画"],
        "en": ["Sample Anime English"],
    },
    "type": "tv",
    "begin": "2026-07-06T15:30:00.000Z",
    "broadcast": "R/2026-07-06T15:30:00.000Z/P7D",
    "officialSite": "https://example.test/anime",
    "sites": [
        {"site": "bangumi", "id": "543360"},
        {"site": "mikan", "id": "3921"},
    ],
}


class AnimeCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_parse_monthly_data_into_weekday_catalog(self) -> None:
        payload = parse_bangumi_data_items([[SAMPLE_ITEM]], year=2026, season="夏")
        self.assertEqual(payload["provider"], "bangumi-data")
        self.assertEqual(payload["attribution"], "番剧周历数据：bangumi-data（CC BY 4.0）")
        self.assertEqual(len(payload["rows"]), 1)
        item = payload["rows"][0]["items"][0]
        self.assertEqual(item["title"], "示例动画")
        self.assertEqual(item["subject_id"], 543360)
        self.assertEqual(item["mikan_id"], 3921)
        self.assertIn("Sample Anime", item["aliases"])
        self.assertEqual(payload["rows"][0]["weekday"], "星期二")

    def test_each_supported_source_builds_real_subscription_presets(self) -> None:
        item = parse_bangumi_data_items([[SAMPLE_ITEM]], year=2026, season="夏")["rows"][0]["items"][0]
        by_source = {source: source_groups(source, item) for source in ("anibt", "ag", "nyaa", "subsplease")}

        self.assertIn("bgmId=543360", by_source["anibt"][0]["rss_url"])
        self.assertIn("api.animes.garden/feed.xml", by_source["ag"][0]["rss_url"])
        self.assertIn("page=rss", by_source["nyaa"][0]["rss_url"])
        self.assertEqual(by_source["subsplease"][0]["rss_url"], "https://subsplease.org/rss/?r=1080&t=")
        self.assertEqual(by_source["subsplease"][2]["rss_url"], "https://subsplease.org/rss/?r=sd&t=")
        self.assertEqual(by_source["subsplease"][0]["preset"]["include_keywords"], "Sample Anime English")
        for source, groups in by_source.items():
            with self.subTest(source=source):
                self.assertTrue(groups)
                self.assertTrue(groups[0]["preset"]["enabled"])
                self.assertEqual(groups[0]["preset"]["bangumi_id"], 543360)

    def test_decorate_filters_locally_and_marks_source_subscription(self) -> None:
        payload = parse_bangumi_data_items([[SAMPLE_ITEM]], year=2026, season="夏")
        subscription = Subscription(
            name="示例动画",
            reference_title="示例动画",
            rss_url="https://anibt.net/rss/anime.xml?bgmId=543360",
            bangumi_id=543360,
        )
        result = decorate_catalog(payload, "anibt", [subscription], "示例")
        item = result["rows"][0]["items"][0]
        self.assertTrue(item["available"])
        self.assertTrue(item["subscribed"])
        self.assertEqual(item["bangumi_id"], 543360)
        self.assertEqual(decorate_catalog(payload, "anibt", [], "不存在")["rows"], [])

    def test_normal_catalog_read_uses_persistent_cache(self) -> None:
        service = AnimeCatalogCacheService()
        parsed = parse_bangumi_data_items([[SAMPLE_ITEM]], year=2026, season="夏")
        with Session(self.engine) as db:
            with patch.object(service, "_fetch_catalog", return_value=parsed) as fetch:
                first = service.catalog(db, 2026, "夏")
                second = service.catalog(db, 2026, "夏")
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(first["cache_status"], "cache_miss_fetched")
            self.assertEqual(second["cache_status"], "cache")
            self.assertEqual(db.query(MikanCacheEntry).count(), 1)

    def test_force_refresh_failure_falls_back_to_existing_cache(self) -> None:
        service = AnimeCatalogCacheService()
        parsed = parse_bangumi_data_items([[SAMPLE_ITEM]], year=2026, season="夏")
        with Session(self.engine) as db:
            with patch.object(service, "_fetch_catalog", return_value=parsed):
                service.catalog(db, 2026, "夏")
            with patch.object(service, "_fetch_catalog", side_effect=RuntimeError("offline")):
                result = service.catalog(db, 2026, "夏", force_refresh=True)
            self.assertEqual(result["cache_status"], "stale_cache_refresh_failed")
            self.assertIn("offline", result["refresh_error"])

    def test_cache_metadata_exposes_background_refresh_deadline(self) -> None:
        service = AnimeCatalogCacheService()
        parsed = parse_bangumi_data_items([[SAMPLE_ITEM]], year=2026, season="夏")
        with Session(self.engine) as db:
            with patch.object(service, "_fetch_catalog", return_value=parsed):
                result = service.catalog(db, 2026, "夏")
            self.assertIn("next_refresh_at", result)
            self.assertGreater(result["refresh_interval_hours"], 0)

    def test_resource_detail_fetches_all_presets_once_then_reads_cache(self) -> None:
        service = AnimeCatalogCacheService()
        item = parse_bangumi_data_items([[SAMPLE_ITEM]], year=2026, season="夏")["rows"][0]["items"][0]
        response = Mock(content=b"<rss />")
        response.raise_for_status.return_value = None
        parsed_feed = [{
            "title": "Sample Anime English - 01 [1080p]",
            "published": "2026-07-07T00:00:00Z",
            "link": "https://example.test/item",
            "enclosures": [{"url": "magnet:?xt=urn:btih:test"}],
        }]
        with Session(self.engine) as db:
            with (
                patch("app.anime_catalog.external_get", return_value=response) as get,
                patch("app.anime_catalog.parse_feed", return_value=parsed_feed),
            ):
                first = service.detail(db, "subsplease", item)
                second = service.detail(db, "subsplease", item)

            self.assertEqual(get.call_count, 4)
            self.assertEqual(first["cache_status"], "cache_miss_fetched")
            self.assertEqual(second["cache_status"], "cache")
            self.assertTrue(all(group["entries"] for group in first["groups"]))
            self.assertTrue(all(call.kwargs.get("db") is db for call in get.call_args_list))

    def test_background_refresh_updates_only_known_stale_catalogs(self) -> None:
        factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        stale_time = datetime.now(timezone.utc) - timedelta(hours=12)
        parsed = parse_bangumi_data_items([[SAMPLE_ITEM]], year=2026, season="夏")
        with factory() as db:
            db.add(
                MikanCacheEntry(
                    cache_key="anime:catalog:2026:夏",
                    kind="anime_catalog",
                    params_json='{"year":2026,"season":"夏","schema_version":1}',
                    payload_json='{"rows":[]}',
                    fetched_at=stale_time,
                    updated_at=stale_time,
                )
            )
            db.commit()

        with (
            patch("app.anime_catalog.SessionLocal", factory),
            patch.object(AnimeCatalogCacheService, "_fetch_catalog", return_value=parsed) as fetch,
        ):
            result = refresh_due_anime_catalogs(limit=2)

        self.assertEqual(result, {"checked": 1, "refreshed": 1, "failed": 0})
        self.assertEqual(fetch.call_count, 1)
        with factory() as db:
            entry = db.get(MikanCacheEntry, "anime:catalog:2026:夏")
            self.assertIn("示例动画", entry.payload_json)
            self.assertEqual(entry.last_error, "")


if __name__ == "__main__":
    unittest.main()

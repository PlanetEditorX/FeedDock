from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.anime_catalog import AnimeCatalogCacheService, decorate_catalog, refresh_due_anime_catalogs
from app.anime_identity import normalize_title, title_key
from app.catalog_providers import AniBtCatalogProvider, AnimeGardenCatalogProvider
from app.database import Base
from app.models import AnimePreference, MikanCacheEntry, Subscription
from app.main import update_hidden_anime_preferences
from app.schemas import AnimePreferenceBatchUpdate, AnimePreferenceItem


ANIBT_CATALOG = {
    "data": {
        "requestedSeason": "2026-07",
        "availableSeasons": ["2026-07"],
        "byWeekday": [{
            "weekday": 2,
            "weekdayLabel": "星期二",
            "animes": [{
                "animeId": "ani-543360",
                "bgmId": "543360",
                "cover": "https://anibt.net/cover.webp",
                "description": "ANI.BT 目录简介",
                "rating": 8.4,
                "format": "23:30",
                "rssReleaseCount": 8,
                "title": {
                    "chinese": "示例动画",
                    "primary": "Sample Anime",
                    "english": "Sample Anime English",
                    "romaji": "Sample Anime",
                },
            }],
        }],
    }
}

ANIBT_GROUPS = {
    "data": {
        "groups": [{
            "groupId": "g1",
            "slug": "group-one",
            "name": "示例字幕组",
            "lastUpdatedAt": 1785100000000,
            "items": [{
                "episodeKey": "03",
                "magnet": "magnet:?xt=urn:btih:abc",
                "publishedAt": 1785100000000,
                "title": "[示例字幕组] Sample Anime 03",
                "size": 1073741824,
            }],
        }],
    }
}

AG_SUBJECTS = {
    "subjects": [{
        "id": "543360",
        "name": "示例动画",
        "keywords": ["Sample Anime"],
        "activedAt": "2026-07-07T12:30:00.000Z",
    }]
}

AG_RESOURCES = {
    "resources": [{
        "id": "r1",
        "title": "[花园字幕组] 示例动画 03",
        "magnet": "magnet:?xt=urn:btih:def",
        "size": 2147483648,
        "createdAt": "2026-07-21T12:30:00.000Z",
        "fansub": {"id": "f1", "name": "花园字幕组"},
    }]
}


def response(payload: dict) -> Mock:
    result = Mock()
    result.raise_for_status.return_value = None
    result.json.return_value = payload
    return result


class NativeCatalogProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_anibt_uses_original_catalog_and_group_apis(self) -> None:
        provider = AniBtCatalogProvider()
        with Session(self.engine) as db, patch(
            "app.catalog_providers.external_get",
            side_effect=[response(ANIBT_CATALOG), response(ANIBT_GROUPS)],
        ) as get:
            catalog = provider.fetch_catalog(db, 2026, "夏")
            item = catalog["rows"][0]["items"][0]
            detail = provider.fetch_detail(db, item)

        self.assertEqual(get.call_args_list[0].args[0], "https://anibt.net/api/seasons/anime")
        self.assertEqual(get.call_args_list[0].kwargs["params"]["season"], "2026-07")
        self.assertEqual(item["subject_id"], 543360)
        self.assertEqual(item["source_anime_id"], "ani-543360")
        self.assertEqual(item["overview"], "ANI.BT 目录简介")
        self.assertEqual(detail["groups"][0]["name"], "示例字幕组")
        self.assertIn("bgmId=543360", detail["groups"][0]["rss_url"])
        self.assertEqual(detail["groups"][0]["preset"]["source_type"], "anibt")

    def test_anime_garden_uses_original_subject_and_resource_apis(self) -> None:
        provider = AnimeGardenCatalogProvider()
        with Session(self.engine) as db, patch(
            "app.catalog_providers.external_get",
            side_effect=[response(AG_SUBJECTS), response(AG_RESOURCES)],
        ) as get:
            catalog = provider.fetch_catalog(db, 2026, "夏")
            item = catalog["rows"][0]["items"][0]
            detail = provider.fetch_detail(db, item)

        self.assertEqual(get.call_args_list[0].args[0], "https://api.animes.garden/subjects")
        self.assertEqual(get.call_args_list[1].args[0], "https://api.animes.garden/resources")
        self.assertEqual(get.call_args_list[1].kwargs["params"]["subject"], 543360)
        self.assertEqual(detail["groups"][0]["name"], "花园字幕组")
        self.assertIn("subject=543360", detail["groups"][0]["rss_url"])
        self.assertIn("fansub=%E8%8A%B1%E5%9B%AD%E5%AD%97%E5%B9%95%E7%BB%84", detail["groups"][0]["rss_url"])

    def test_catalog_cache_is_isolated_by_source(self) -> None:
        service = AnimeCatalogCacheService()
        with Session(self.engine) as db, patch(
            "app.catalog_providers.external_get",
            side_effect=[response(ANIBT_CATALOG), response(AG_SUBJECTS)],
        ) as get:
            first_anibt = service.catalog(db, "anibt", 2026, "夏")
            second_anibt = service.catalog(db, "anibt", 2026, "夏")
            ag = service.catalog(db, "ag", 2026, "夏")
            keys = list(db.scalars(select(MikanCacheEntry.cache_key).order_by(MikanCacheEntry.cache_key)))

        self.assertEqual(get.call_count, 2)
        self.assertEqual(first_anibt["cache_status"], "cache_miss_fetched")
        self.assertEqual(second_anibt["cache_status"], "cache")
        self.assertEqual(ag["provider"], "ag")
        self.assertEqual(keys, ["source:catalog:ag:2026:夏", "source:catalog:anibt:2026:夏"])

    def test_failed_refresh_keeps_only_that_sources_cache(self) -> None:
        service = AnimeCatalogCacheService()
        with Session(self.engine) as db:
            with patch("app.catalog_providers.external_get", return_value=response(ANIBT_CATALOG)):
                service.catalog(db, "anibt", 2026, "夏")
            with patch("app.catalog_providers.external_get", side_effect=OSError("dns failed")):
                stale = service.catalog(db, "anibt", 2026, "夏", force_refresh=True)
                with self.assertRaises(OSError):
                    service.catalog(db, "ag", 2026, "夏", force_refresh=True)

        self.assertEqual(stale["cache_status"], "stale_cache_after_error")
        self.assertIn("dns failed", stale["refresh_error"])

    def test_cross_site_subscription_badge_and_hidden_preference(self) -> None:
        payload = AniBtCatalogProvider()
        with Session(self.engine) as db, patch("app.catalog_providers.external_get", return_value=response(ANIBT_CATALOG)):
            catalog = payload.fetch_catalog(db, 2026, "夏")
        mikan = Subscription(
            id=1,
            name="示例动画",
            reference_title="示例动画",
            source_type="mikan",
            source_anime_id="3921",
            canonical_key=title_key("示例动画"),
            rss_url="https://mikanani.me/RSS/Bangumi?bangumiId=3921",
        )
        preference = AnimePreference(
            canonical_key=title_key("示例动画"),
            title_normalized=normalize_title("示例动画"),
            hidden=True,
        )
        decorated = decorate_catalog(catalog, "anibt", [mikan], [preference])
        item = decorated["rows"][0]["items"][0]
        self.assertTrue(item["subscribed"])
        self.assertFalse(item["subscribed_here"])
        self.assertEqual(item["subscription_badge"], "Mikan 已订阅")
        self.assertTrue(item["hidden"])

    def test_same_site_and_other_site_badges_are_combined(self) -> None:
        with Session(self.engine) as db, patch("app.catalog_providers.external_get", return_value=response(ANIBT_CATALOG)):
            catalog = AniBtCatalogProvider().fetch_catalog(db, 2026, "夏")
        subscriptions = [
            Subscription(id=1, name="示例动画", source_type="anibt", canonical_key="bgm:543360", rss_url="https://anibt.net/rss/anime.xml?bgmId=543360"),
            Subscription(id=2, name="示例动画", source_type="mikan", canonical_key=title_key("示例动画"), rss_url="https://mikanani.me/RSS/Bangumi?bangumiId=3921"),
        ]
        item = decorate_catalog(catalog, "anibt", subscriptions)["rows"][0]["items"][0]
        self.assertTrue(item["subscribed_here"])
        self.assertEqual(item["subscription_badge"], "✓ 已订阅 · Mikan 也已订阅")


    def test_unhide_removes_title_alias_preference_created_by_another_source(self) -> None:
        with Session(self.engine) as db:
            db.add(AnimePreference(
                canonical_key=title_key("示例动画"),
                title_normalized=normalize_title("示例动画"),
                hidden=True,
            ))
            db.commit()
            result = update_hidden_anime_preferences(
                AnimePreferenceBatchUpdate(items=[AnimePreferenceItem(
                    canonical_key="bgm:543360",
                    bangumi_id=543360,
                    title="示例动画",
                    hidden=False,
                )]),
                db,
            )
            remaining = list(db.scalars(select(AnimePreference)))
        self.assertEqual(result["updated"], 1)
        self.assertEqual(remaining, [])

    def test_same_source_id_matches_even_when_title_changes(self) -> None:
        catalog = {
            "rows": [{
                "weekday": "星期一",
                "items": [{
                    "source_type": "anibt",
                    "source_anime_id": "ani-543360",
                    "subject_id": 0,
                    "title": "完全不同的显示标题",
                    "aliases": [],
                }],
            }],
        }
        subscription = Subscription(
            id=1,
            name="旧标题",
            source_type="anibt",
            source_anime_id="ani-543360",
            rss_url="https://anibt.net/rss/anime.xml?bgmId=543360",
        )
        item = decorate_catalog(catalog, "anibt", [subscription])["rows"][0]["items"][0]
        self.assertTrue(item["subscribed_here"])
        self.assertEqual(item["subscription_badge"], "✓ 已订阅")

    def test_background_refresh_reads_source_from_cache_params(self) -> None:
        old = datetime.now(timezone.utc) - timedelta(days=2)
        with Session(self.engine) as db:
            db.add(MikanCacheEntry(
                cache_key="source:catalog:anibt:2026:夏",
                kind="source_catalog",
                params_json='{"source_id":"anibt","year":2026,"season":"夏","schema_version":3}',
                payload_json='{"provider":"anibt","rows":[]}',
                fetched_at=old,
            ))
            db.commit()
        import app.anime_catalog as module
        original = module.SessionLocal
        module.SessionLocal = lambda: Session(self.engine)
        try:
            with patch.object(AnimeCatalogCacheService, "catalog", return_value={}) as catalog:
                result = refresh_due_anime_catalogs(limit=2)
        finally:
            module.SessionLocal = original
        self.assertEqual(result["refreshed"], 1)
        catalog.assert_called_once()
        self.assertEqual(catalog.call_args.args[1:5], ("anibt", 2026, "夏"))


if __name__ == "__main__":
    unittest.main()

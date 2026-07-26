from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import close_all_sessions, sessionmaker

from app.database import Base
import app.mikan_cache as mikan_cache_module
from app.mikan_cache import MikanCacheService, fetch_cached_mikan_image, refresh_due_mikan_catalogs
from app.models import MikanCacheEntry


class FakeDiscovery:
    def __init__(self) -> None:
        self.catalog_calls = 0
        self.detail_calls = 0

    def catalog(self, year: int, season: str, query: str = ""):
        self.catalog_calls += 1
        suffix = f" #{self.catalog_calls}"
        return {
            "provider": "mikan",
            "year": year,
            "season": season,
            "query": query,
            "base_url": "https://mikan.test",
            "rows": [
                {
                    "weekday": "星期一",
                    "day_of_week": 1,
                    "items": [
                        {
                            "bangumi_id": 100,
                            "title": "缓存番剧" + suffix,
                            "cover_url": "",
                            "cover_proxy_url": "",
                            "update_at": "",
                            "detail_url": "https://mikan.test/Home/Bangumi/100",
                            "base_url": "https://mikan.test",
                        },
                        {
                            "bangumi_id": 200,
                            "title": "另一部动画",
                            "cover_url": "",
                            "cover_proxy_url": "",
                            "update_at": "",
                            "detail_url": "https://mikan.test/Home/Bangumi/200",
                            "base_url": "https://mikan.test",
                        },
                    ],
                }
            ],
            "errors": [],
        }

    def mikan_detail(self, bangumi_id: int, preferred_base: str = "", title: str = ""):
        self.detail_calls += 1
        return {
            "provider": "mikan",
            "bangumi_id": bangumi_id,
            "title": title or "缓存番剧",
            "base_url": preferred_base or "https://mikan.test",
            "detail_url": f"https://mikan.test/Home/Bangumi/{bangumi_id}",
            "groups": [],
        }


class MikanCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.discovery = FakeDiscovery()
        self.service = MikanCacheService(self.discovery)  # type: ignore[arg-type]

    def tearDown(self) -> None:
        close_all_sessions()
        self.engine.dispose(close=True)

    def test_catalog_reads_cache_after_first_fetch_and_filters_locally(self) -> None:
        with self.Session() as db:
            first = self.service.catalog(db, 2026, "夏")
            filtered = self.service.catalog(db, 2026, "夏", "另一部")
            again = self.service.catalog(db, 2026, "夏")

        self.assertEqual(self.discovery.catalog_calls, 1)
        self.assertEqual(first["cache_status"], "cache_miss_fetched")
        self.assertEqual(filtered["cache_status"], "cache")
        self.assertEqual(filtered["rows"][0]["items"][0]["bangumi_id"], 200)
        self.assertEqual(again["rows"][0]["items"][0]["title"], "缓存番剧 #1")


    def test_legacy_catalog_cache_is_refreshed_once_for_cover_fix(self) -> None:
        legacy_payload = self.discovery.catalog(2026, "夏")
        self.discovery.catalog_calls = 0
        with self.Session() as db:
            db.add(
                MikanCacheEntry(
                    cache_key="mikan:catalog:2026:夏",
                    kind="catalog",
                    params_json=json.dumps({"year": 2026, "season": "夏"}),
                    payload_json=json.dumps(legacy_payload, ensure_ascii=False),
                    fetched_at=datetime.now(timezone.utc),
                    last_error="",
                )
            )
            db.commit()
            migrated = self.service.catalog(db, 2026, "夏")
            cached = self.service.catalog(db, 2026, "夏")
            row = db.get(MikanCacheEntry, "mikan:catalog:2026:夏")

        self.assertEqual(self.discovery.catalog_calls, 1)
        self.assertEqual(migrated["cache_status"], "cache_migrated")
        self.assertEqual(cached["cache_status"], "cache")
        assert row is not None
        self.assertEqual(json.loads(row.params_json)["schema_version"], 4)

    def test_force_refresh_replaces_catalog_cache(self) -> None:
        with self.Session() as db:
            self.service.catalog(db, 2026, "夏")
            refreshed = self.service.catalog(db, 2026, "夏", force_refresh=True)
            cached = self.service.catalog(db, 2026, "夏")

        self.assertEqual(self.discovery.catalog_calls, 2)
        self.assertEqual(refreshed["cache_status"], "force_refreshed")
        self.assertEqual(cached["rows"][0]["items"][0]["title"], "缓存番剧 #2")

    def test_detail_is_cached_until_explicit_refresh(self) -> None:
        with self.Session() as db:
            first = self.service.detail(db, 100, "https://mikan.test", "缓存番剧")
            cached = self.service.detail(db, 100, "https://mikan.test", "缓存番剧")
            refreshed = self.service.detail(
                db,
                100,
                "https://mikan.test",
                "缓存番剧",
                force_refresh=True,
            )

        self.assertEqual(self.discovery.detail_calls, 2)
        self.assertEqual(first["cache_status"], "cache_miss_fetched")
        self.assertEqual(cached["cache_status"], "cache")
        self.assertEqual(refreshed["cache_status"], "force_refreshed")



    def test_background_refresh_updates_only_due_catalog_cache(self) -> None:
        with self.Session() as db:
            self.service.catalog(db, 2026, "夏")
            row = db.get(MikanCacheEntry, "mikan:catalog:2026:夏")
            assert row is not None
            row.fetched_at = datetime.now(timezone.utc) - timedelta(days=2)
            db.commit()

        replacement = FakeDiscovery()
        with patch.object(mikan_cache_module, "SessionLocal", self.Session), patch.object(
            mikan_cache_module, "DiscoveryService", return_value=replacement
        ):
            result = refresh_due_mikan_catalogs(limit=4)

        self.assertEqual(result, {"checked": 1, "refreshed": 1, "failed": 0})
        self.assertEqual(replacement.catalog_calls, 1)
        with self.Session() as db:
            refreshed = db.get(MikanCacheEntry, "mikan:catalog:2026:夏")
            assert refreshed is not None
            self.assertIn("缓存番剧 #1", refreshed.payload_json)

    def test_cover_bytes_are_persisted_on_disk(self) -> None:
        class FakeImageDiscovery:
            def __init__(self) -> None:
                self.calls = 0

            def fetch_image(self, base_url: str, image_url: str):
                self.calls += 1
                return b"fake-image", "image/jpeg"

        fake = FakeImageDiscovery()
        with tempfile.TemporaryDirectory() as directory:
            fake_settings = SimpleNamespace(
                data_dir=Path(directory),
                mikan_image_cache_days=7,
            )
            with patch.object(mikan_cache_module, "settings", fake_settings):
                first = fetch_cached_mikan_image(
                    "https://mikan.test",
                    "https://mikan.test/cover.jpg",
                    discovery=fake,  # type: ignore[arg-type]
                )
                second = fetch_cached_mikan_image(
                    "https://mikan.test",
                    "https://mikan.test/cover.jpg",
                    discovery=fake,  # type: ignore[arg-type]
                )

        self.assertEqual(fake.calls, 1)
        self.assertFalse(first[2])
        self.assertTrue(second[2])
        self.assertEqual(second[:2], (b"fake-image", "image/jpeg"))


    def test_expired_image_metadata_still_uses_local_file(self) -> None:
        class FakeImageDiscovery:
            def __init__(self) -> None:
                self.calls = 0

            def fetch_image(self, base_url: str, image_url: str):
                self.calls += 1
                return b"remote-image", "image/webp"

        fake = FakeImageDiscovery()
        with tempfile.TemporaryDirectory() as directory:
            fake_settings = SimpleNamespace(
                data_dir=Path(directory),
                mikan_image_cache_days=1,
            )
            with patch.object(mikan_cache_module, "settings", fake_settings):
                first = fetch_cached_mikan_image(
                    "https://mikan.test",
                    "https://mikan.test/cover.webp",
                    discovery=fake,  # type: ignore[arg-type]
                )
                cache_dir = Path(directory) / "mikan-image-cache"
                meta_path = next(cache_dir.glob("*.json"))
                metadata = json.loads(meta_path.read_text(encoding="utf-8"))
                metadata["cached_at"] = (
                    datetime.now(timezone.utc) - timedelta(days=365)
                ).isoformat()
                meta_path.write_text(json.dumps(metadata), encoding="utf-8")
                second = fetch_cached_mikan_image(
                    "https://mikan.test",
                    "https://mikan.test/cover.webp",
                    discovery=fake,  # type: ignore[arg-type]
                )

        self.assertEqual(fake.calls, 1)
        self.assertFalse(first[2])
        self.assertTrue(second[2])
        self.assertEqual(second[0], b"remote-image")

    def test_corrupt_local_image_is_replaced_from_remote(self) -> None:
        class FakeImageDiscovery:
            def __init__(self) -> None:
                self.calls = 0

            def fetch_image(self, base_url: str, image_url: str):
                self.calls += 1
                return f"image-{self.calls}".encode(), "image/webp"

        fake = FakeImageDiscovery()
        with tempfile.TemporaryDirectory() as directory:
            fake_settings = SimpleNamespace(
                data_dir=Path(directory),
                mikan_image_cache_days=30,
            )
            with patch.object(mikan_cache_module, "settings", fake_settings):
                fetch_cached_mikan_image(
                    "https://mikan.test",
                    "https://mikan.test/cover.webp",
                    discovery=fake,  # type: ignore[arg-type]
                )
                cache_dir = Path(directory) / "mikan-image-cache"
                next(cache_dir.glob("*.bin")).write_bytes(b"")
                repaired = fetch_cached_mikan_image(
                    "https://mikan.test",
                    "https://mikan.test/cover.webp",
                    discovery=fake,  # type: ignore[arg-type]
                )

        self.assertEqual(fake.calls, 2)
        self.assertFalse(repaired[2])
        self.assertEqual(repaired[0], b"image-2")

    def test_stale_cache_is_still_served_without_network(self) -> None:
        with self.Session() as db:
            self.service.catalog(db, 2026, "夏")
            row = db.get(MikanCacheEntry, "mikan:catalog:2026:夏")
            assert row is not None
            row.fetched_at = datetime.now(timezone.utc) - timedelta(days=2)
            db.commit()
            stale = self.service.catalog(db, 2026, "夏")

        self.assertEqual(self.discovery.catalog_calls, 1)
        self.assertTrue(stale["is_stale"])
        self.assertEqual(stale["cache_status"], "cache")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import FeedItem, Subscription
from unittest.mock import patch

from app.downloader import QBittorrentClient, TorrentNormalizeResult
from app.metadata_service import MetadataRecord, MetadataService, infer_season_from_title
from app.naming import media_folder_name, naming_context, remote_to_local_path, render_desired_name
from app.scraper import CleanupResult, ScrapeResult, cleanup_orphaned_metadata, scrape_completed_item, scrape_subscription, trigger_tmm_scrape


class _Response:
    def __init__(self, status_code=200, text="Ok.", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload
        self.headers = {"Content-Type": "application/json"}
        self.content = b"{}"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return self._payload


class _FakeQbitClient:
    def __init__(self, calls, *args, **kwargs):
        self.calls = calls

    def __enter__(self): return self
    def __exit__(self, *args): return False

    def post(self, path, data=None, files=None):
        self.calls.append(("POST", path, data, files))
        return _Response()

    def get(self, path, params=None):
        self.calls.append(("GET", path, params, None))
        if path.endswith("torrents/info"):
            return _Response(payload=[{"hash": "abc", "added_on": 1, "progress": 1.0, "amount_left": 0, "state": "uploading"}])
        if path.endswith("torrents/files"):
            return _Response(payload=[
                {"name": "raw/[Group] Show - 01.mkv"},
                {"name": "raw/[Group] Show - 01.zh-CN.ass"},
            ])
        return _Response(text="5.1.0")



class _FakeMetadataHttpClient:
    def __init__(self, routes, *args, **kwargs):
        self.routes = routes
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def get(self, url, params=None, headers=None):
        key = ("GET", url)
        return _Response(payload=self.routes[key])
    def post(self, url, params=None, json=None, headers=None):
        key = ("POST", url)
        return _Response(payload=self.routes[key])

class MetadataNamingTests(unittest.TestCase):
    def subscription(self, **overrides):
        values = dict(
            name="金牌得主 第二季", naming_mode="tmdb", manual_title="",
            tmdb_title="金牌得主", reference_title="メダリスト", air_date="2025-01-05",
            metadata_year=2025, tmdb_id=123, bangumi_id=456, media_type="tv",
            season=2, file_name_template="{title} - S{season:02}E{episode:02}",
        )
        values.update(overrides)
        return SimpleNamespace(**values)


    def test_orphaned_feeddock_metadata_is_removed_when_video_is_missing(self):
        from app.models import AppSetting
        with tempfile.TemporaryDirectory() as root:
            media_root = Path(root) / "Demo (2026)"
            season = media_root / "Season 01"
            season.mkdir(parents=True)
            (media_root / "tvshow.nfo").write_text("metadata")
            (media_root / "poster.jpg").write_bytes(b"image")
            (season / "season.nfo").write_text("metadata")
            (season / "Demo - S01E01.nfo").write_text("metadata")
            (season / "Demo - S01E01.zh-CN.ass").write_text("subtitle")
            (media_root / ".feeddock-scrape.json").write_text(
                '{"generator":"FeedDock","subscription_id":1,"files":["tvshow.nfo","poster.jpg","Season 01/season.nfo","Season 01/Demo - S01E01.nfo"]}'
            )
            engine = create_engine("sqlite+pysqlite:///:memory:")
            Base.metadata.create_all(engine)
            SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
            with SessionLocal() as db:
                sub = Subscription(id=1, name="Demo", rss_url="https://example.test/rss", media_type="tv", season=1)
                db.add(sub)
                db.add(AppSetting(key="download_path", value=root))
                db.add(AppSetting(key="media_local_root", value=root))
                db.add(FeedItem(
                    subscription_id=1, fingerprint="orphan", title="Demo 01", episode="1",
                    save_path=str(season), completed_at=datetime.now(timezone.utc),
                    scrape_status="completed", scraped_at=datetime.now(timezone.utc),
                ))
                db.commit()
                result = cleanup_orphaned_metadata(db, sub)
                db.commit()
                self.assertTrue(result.ok, result.message)
                self.assertFalse((media_root / "tvshow.nfo").exists())
                self.assertFalse((media_root / "poster.jpg").exists())
                self.assertFalse((season / "season.nfo").exists())
                self.assertTrue((season / "Demo - S01E01.zh-CN.ass").exists())
                item = db.query(FeedItem).one()
                self.assertEqual(item.scrape_status, "cleaned")
            engine.dispose()

    def test_orphan_cleanup_keeps_series_artwork_when_other_season_has_video(self):
        from app.models import AppSetting
        with tempfile.TemporaryDirectory() as root:
            media_root = Path(root) / "Demo (2026)"
            season1 = media_root / "Season 01"
            season2 = media_root / "Season 02"
            season1.mkdir(parents=True)
            season2.mkdir(parents=True)
            (media_root / "tvshow.nfo").write_text("series")
            (media_root / "poster.jpg").write_bytes(b"image")
            (season1 / "season.nfo").write_text("season")
            (season1 / "Demo - S01E01.nfo").write_text("episode")
            (season2 / "Demo - S02E01.mkv").write_bytes(b"video")
            (media_root / ".feeddock-scrape.json").write_text(
                '{"generator":"FeedDock","subscription_id":1,"files":["tvshow.nfo","poster.jpg","Season 01/season.nfo","Season 01/Demo - S01E01.nfo"]}'
            )
            engine = create_engine("sqlite+pysqlite:///:memory:")
            Base.metadata.create_all(engine)
            SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
            with SessionLocal() as db:
                sub = Subscription(id=1, name="Demo", rss_url="https://example.test/rss", media_type="tv", season=1)
                db.add(sub)
                db.add(AppSetting(key="download_path", value=root))
                db.add(AppSetting(key="media_local_root", value=root))
                db.add(FeedItem(
                    subscription_id=1, fingerprint="orphan-s1", title="Demo 01", episode="1",
                    save_path=str(season1), completed_at=datetime.now(timezone.utc),
                    scrape_status="completed", scraped_at=datetime.now(timezone.utc),
                ))
                db.commit()
                result = cleanup_orphaned_metadata(db, sub)
                db.commit()
                self.assertTrue(result.ok, result.message)
                self.assertFalse((season1 / "season.nfo").exists())
                self.assertTrue((media_root / "tvshow.nfo").exists())
                self.assertTrue((media_root / "poster.jpg").exists())
                self.assertTrue((season2 / "Demo - S02E01.mkv").exists())
            engine.dispose()

    def test_season_inference_supports_chinese_and_english(self):
        self.assertEqual(infer_season_from_title("金牌得主 第二季"), 2)
        self.assertEqual(infer_season_from_title("Show Season 3"), 3)
        self.assertEqual(infer_season_from_title("Show S04"), 4)

    def test_tmdb_latest_and_title_season_modes(self):
        config = SimpleNamespace(tmdb_read_access_token="token", language="zh-CN")
        detail = {
            "id": 99, "name": "动画", "first_air_date": "2024-01-01",
            "seasons": [
                {"season_number": 0, "name": "特别篇", "episode_count": 2, "air_date": "2024-01-01"},
                {"season_number": 1, "name": "第1季", "episode_count": 12, "air_date": "2024-01-01"},
                {"season_number": 2, "name": "第2季", "episode_count": 10, "air_date": "2026-01-01"},
            ],
        }
        routes = {
            ("GET", "https://api.themoviedb.org/3/tv/99"): detail,
            ("GET", "https://api.themoviedb.org/3/tv/99/season/2"): {"episodes": [{"episode_number": n} for n in range(1, 11)]},
        }
        service = MetadataService()
        with patch("app.metadata_service.load_metadata_config", return_value=config), patch("app.metadata_service.httpx.Client", side_effect=lambda *a, **k: _FakeMetadataHttpClient(routes)):
            latest = service.get(SimpleNamespace(), provider="tmdb", metadata_id=99, media_type="tv", season=1, season_mode="latest")
            titled = service.get(SimpleNamespace(), provider="tmdb", metadata_id=99, media_type="tv", season=1, season_mode="title", query_title="动画 第二季")
        self.assertEqual(latest.season, 2)
        self.assertEqual(titled.season, 2)
        self.assertEqual(latest.recommended_season, 2)
        self.assertEqual(len(latest.available_seasons), 3)

    def test_emby_folder_and_episode_name(self):
        sub = self.subscription()
        self.assertEqual(media_folder_name(sub), "金牌得主 (2025)")
        self.assertEqual(naming_context(sub, "3")["tmdb_id"], 123)
        self.assertEqual(render_desired_name(sub, "3"), "金牌得主 - S02E03")

    def test_manual_title_has_priority_and_path_mapping_is_confined(self):
        sub = self.subscription(naming_mode="manual", manual_title="我的规范名称", tmdb_id=0)
        self.assertEqual(media_folder_name(sub), "我的规范名称 (2025)")
        self.assertEqual(
            remote_to_local_path("/downloads/rss/Show/Season 01", "/downloads/rss", "/media"),
            "/media/Show/Season 01",
        )
        with self.assertRaises(ValueError):
            remote_to_local_path("/elsewhere/Show", "/downloads/rss", "/media")

    def test_qbittorrent_add_and_internal_file_rename(self):
        calls = []
        client = QBittorrentClient(base_url="http://qbit:8080", username="admin", password="pw")
        with patch.object(client, "_client", return_value=_FakeQbitClient(calls)):
            added = client.add_url("magnet:?xt=urn:btih:abc", "/downloads/rss/Show/Season 01", rename="Show - S01E01", tags="feeddock-item-1")
            self.assertTrue(added.ok)
            self.assertTrue(added.tag_removed)
            normalized = client.normalize_single_video(
                torrent_hash=added.torrent_hash, desired_name="Show - S01E01"
            )
        self.assertTrue(normalized.ok)
        self.assertEqual(normalized.state, "completed")
        add_call = next(call for call in calls if call[1].endswith("torrents/add"))
        self.assertEqual(add_call[3]["rename"][1], "Show - S01E01")
        self.assertEqual(add_call[3]["tags"][1], "feeddock-item-1")
        self.assertTrue(any(call[1].endswith("removeTags") for call in calls))
        self.assertTrue(any(call[1].endswith("deleteTags") for call in calls))
        hash_lookups = [
            call for call in calls
            if call[0] == "GET" and call[1].endswith("torrents/info")
            and (call[2] or {}).get("hashes") == "abc"
        ]
        self.assertEqual(len(hash_lookups), 1)
        rename_calls = [call for call in calls if call[1].endswith("renameFile")]
        self.assertEqual(len(rename_calls), 2)
        self.assertTrue(rename_calls[0][2]["newPath"].endswith("Show - S01E01.mkv"))

    def test_metadata_apply_respects_total_episode_lock(self):
        record = MetadataRecord(provider="tmdb", id=88, media_type="tv", title="规范标题", year=2026, total_episodes=12, season=1)
        service = MetadataService()
        db = SimpleNamespace(commit=lambda: None, refresh=lambda _: None)
        sub = self.subscription(total_episodes=0, total_episodes_locked=False, total_episodes_source="", metadata_source="", metadata_overview="", poster_url="", backdrop_url="", metadata_last_synced_at=None)
        with patch.object(service, "get", return_value=record):
            service.apply(db, sub, provider="tmdb", metadata_id=88)
        self.assertEqual(sub.total_episodes, 12)
        self.assertEqual(sub.total_episodes_source, "tmdb")
        self.assertEqual(sub.tmdb_id, 88)
        self.assertEqual(sub.name, "规范标题 (2026)")
        self.assertEqual(sub.tmdb_title, "规范标题 (2026)")

        sub.total_episodes = 24
        sub.total_episodes_locked = True
        with patch.object(service, "get", return_value=record):
            service.apply(db, sub, provider="tmdb", metadata_id=88)
        self.assertEqual(sub.total_episodes, 24)

    def test_tmdb_detail_uses_selected_season_episode_count(self):
        config = SimpleNamespace(tmdb_read_access_token="token", language="zh-CN")
        routes = {
            ("GET", "https://api.themoviedb.org/3/tv/99"): {"id": 99, "name": "动画", "first_air_date": "2026-01-01", "poster_path": "/p.jpg", "backdrop_path": "/b.jpg"},
            ("GET", "https://api.themoviedb.org/3/tv/99/season/2"): {"poster_path": "/s.jpg", "episodes": [{"episode_number": 1}, {"episode_number": 2}, {"episode_number": 3}]},
        }
        service = MetadataService()
        with patch("app.metadata_service.load_metadata_config", return_value=config), patch("app.metadata_service.httpx.Client", side_effect=lambda *a, **k: _FakeMetadataHttpClient(routes)):
            record = service.get(SimpleNamespace(), provider="tmdb", metadata_id=99, media_type="tv", season=2)
        self.assertEqual(record.total_episodes, 3)
        self.assertEqual(record.season, 2)
        self.assertTrue(record.poster_url.endswith("/original/s.jpg"))

    def test_bangumi_detail_falls_back_to_episode_total(self):
        config = SimpleNamespace(bangumi_access_token="", language="zh-CN")
        routes = {
            ("GET", "https://api.bgm.tv/v0/subjects/66"): {"id": 66, "name_cn": "番剧", "name": "Anime", "date": "2026-04-01", "eps": 0, "images": {}},
            ("GET", "https://api.bgm.tv/v0/episodes"): {"total": 13, "data": []},
        }
        service = MetadataService()
        with patch("app.metadata_service.load_metadata_config", return_value=config), patch("app.metadata_service.httpx.Client", side_effect=lambda *a, **k: _FakeMetadataHttpClient(routes)):
            record = service.get(SimpleNamespace(), provider="bangumi", metadata_id=66, season=1)
        self.assertEqual(record.total_episodes, 13)
        self.assertEqual(record.title, "番剧")


    def test_tmm_scrape_is_disabled(self):
        sub = self.subscription(scrape_enabled=True, scrape_mode="tmm", save_path_template="{base}/{media_folder}/Season {season:02}")
        result = trigger_tmm_scrape(SimpleNamespace(), sub)
        self.assertFalse(result.ok)
        self.assertIn("尚未启用", result.message)

    def test_download_completion_runs_default_metadata_scrape(self):
        engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        with Session() as db:
            sub = Subscription(
                name="自动刮削番剧 (2026)",
                rss_url="https://example.com/rss",
                scrape_enabled=True,
                rename_enabled=True,
            )
            db.add(sub)
            db.flush()
            item = FeedItem(
                subscription_id=sub.id,
                fingerprint="a" * 64,
                title="自动刮削番剧 - 01",
                status="queued",
                qbit_tag="feeddock-item-1",
                desired_name="自动刮削番剧 - S01E01",
                rename_status="waiting_completion",
                scrape_status="pending",
            )
            db.add(item)
            db.commit()

            fake_qbit = SimpleNamespace(
                normalize_single_video=lambda **_: TorrentNormalizeResult(
                    True, "completed", "下载已完成", "abc", True, 100
                )
            )
            fake_metadata = SimpleNamespace(
                sync=lambda *_args, **_kwargs: SimpleNamespace(provider="bangumi", id=123)
            )
            metadata_config = SimpleNamespace(
                auto_scrape_enabled=True,
                bangumi_ini_enabled=False,
                media_local_root="/media",
            )
            from app.postprocess import normalize_pending_items
            with (
                patch("app.postprocess.QBittorrentClient", return_value=fake_qbit),
                patch("app.postprocess.MetadataService", return_value=fake_metadata),
                patch("app.postprocess.load_metadata_config", return_value=metadata_config),
                patch(
                    "app.postprocess.scrape_completed_item",
                    return_value=ScrapeResult(True, "已写入媒体库元数据：4 个文件", "/media/show", ["tvshow.nfo"]),
                ),
            ):
                result = normalize_pending_items(db)

            db.refresh(item)
            self.assertEqual(result["completed"], 1)
            self.assertEqual(result["scraped"], 1)
            self.assertEqual(item.download_progress, 100)
            self.assertEqual(item.scrape_status, "completed")
            self.assertIn("元数据已同步", item.scrape_message)
            self.assertIsNotNone(item.completed_at)
            self.assertIsNotNone(item.scraped_at)

    def test_missing_legacy_qbittorrent_task_becomes_retryable_error(self):
        engine = create_engine("sqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        with Session() as db:
            sub = Subscription(name="Legacy push", rss_url="https://example.com/rss")
            db.add(sub)
            db.flush()
            item = FeedItem(
                subscription_id=sub.id,
                fingerprint="legacy-missing",
                title="Legacy push - 03",
                download_url="magnet:?xt=urn:btih:legacy",
                status="queued",
                qbit_tag="feeddock-item-legacy",
                rename_status="pending",
                created_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            )
            db.add(item)
            db.commit()

            fake_qbit = SimpleNamespace(
                normalize_single_video=lambda **_: TorrentNormalizeResult(
                    False, "pending", "等待 qBittorrent 建立任务"
                )
            )
            from app.postprocess import normalize_pending_items
            with patch("app.postprocess.QBittorrentClient", return_value=fake_qbit):
                result = normalize_pending_items(db)

            db.refresh(item)
            self.assertEqual(result["errors"], 1)
            self.assertEqual(item.status, "error")
            self.assertIn("重试下载", item.reason)

    def test_local_scraper_writes_nfo_and_artwork(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "金牌得主 (2025)"
            season = root / "Season 02"
            season.mkdir(parents=True)
            video = season / "金牌得主 - S02E03.mkv"
            video.write_bytes(b"video")

            sub = self.subscription(
                id=1,
                anilist_id=789,
                metadata_source="tmdb",
                metadata_rating=8.6,
                metadata_overview="简介",
                poster_url="https://image.example/poster.jpg",
                backdrop_url="https://image.example/fanart.jpg",
                total_episodes=12,
            )
            item = SimpleNamespace(
                id=2,
                episode="3",
                title="金牌得主 第二季 - 03",
                desired_name="金牌得主 - S02E03",
                save_path=str(season),
                published_at=datetime(2026, 7, 27, tzinfo=timezone.utc),
            )
            config = SimpleNamespace(media_local_root=tmp)
            image_response = SimpleNamespace(
                content=b"\xff\xd8\xffimage-bytes",
                headers={"Content-Type": "image/jpeg"},
                raise_for_status=lambda: None,
            )
            with patch("app.scraper.external_get", return_value=image_response):
                result = scrape_completed_item(SimpleNamespace(), sub, item, config)

            self.assertTrue(result.ok, result.message)
            self.assertTrue((root / "tvshow.nfo").exists())
            self.assertTrue((season / "season.nfo").exists())
            self.assertTrue(video.with_suffix(".nfo").exists())
            self.assertTrue((root / "poster.jpg").exists())
            self.assertTrue((root / "fanart.jpg").exists())
            self.assertTrue((season / "poster.jpg").exists())
            self.assertTrue((root / "season02-poster.jpg").exists())
            self.assertTrue((root / ".feeddock-scrape.json").exists())
            tvshow = (root / "tvshow.nfo").read_text(encoding="utf-8")
            self.assertIn("<title>金牌得主</title>", tvshow)
            self.assertIn('<uniqueid type="tmdb" default="true">123</uniqueid>', tvshow)
            self.assertIn('<uniqueid type="bangumi">456</uniqueid>', tvshow)
            episode = video.with_suffix(".nfo").read_text(encoding="utf-8")
            self.assertIn("<season>2</season>", episode)
            self.assertIn("<episode>3</episode>", episode)

    def test_local_scraper_rejects_paths_outside_media_root(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            sub = self.subscription(id=1, metadata_overview="", poster_url="", backdrop_url="")
            item = SimpleNamespace(
                id=2, episode="1", title="Episode", desired_name="Episode",
                save_path=outside, published_at=None,
            )
            result = scrape_completed_item(
                SimpleNamespace(), sub, item, SimpleNamespace(media_local_root=tmp)
            )
            self.assertFalse(result.ok)
            self.assertIn("不在允许的媒体根目录", result.message)

    def test_local_scraper_maps_qbittorrent_path_to_feeddock_mount(self):
        with tempfile.TemporaryDirectory() as tmp:
            local_root = Path(tmp)
            season = local_root / "感谢对战。～大小姐才不玩格斗游戏～ (2026)" / "Season 01"
            season.mkdir(parents=True)
            video = season / "感谢对战。～大小姐才不玩格斗游戏～ - S01E03.mkv"
            video.write_bytes(b"video")
            sub = self.subscription(
                id=8,
                name="感谢对战。～大小姐才不玩格斗游戏～",
                manual_title="感谢对战。～大小姐才不玩格斗游戏～",
                season=1,
                metadata_overview="",
                metadata_rating=0.0,
                metadata_source="bangumi",
                poster_url="",
                backdrop_url="",
                anilist_id=0,
            )
            item = SimpleNamespace(
                id=29,
                episode="3",
                title="Episode 3",
                desired_name="感谢对战。～大小姐才不玩格斗游戏～ - S01E03",
                save_path="/vol2/1000/影视/感谢对战。～大小姐才不玩格斗游戏～ (2026)/Season 01",
                published_at=None,
            )
            config = SimpleNamespace(
                downloader_root="/vol2/1000/影视",
                media_local_root=tmp,
            )
            result = scrape_completed_item(SimpleNamespace(), sub, item, config)
            self.assertTrue(result.ok, result.message)
            self.assertEqual(Path(result.local_path), season.parent)
            self.assertTrue((season.parent / "tvshow.nfo").exists())
            self.assertTrue(video.with_suffix(".nfo").exists())


if __name__ == "__main__":
    unittest.main()

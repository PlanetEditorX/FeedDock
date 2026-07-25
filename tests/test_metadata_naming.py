from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.downloader import QBittorrentClient
from app.metadata_service import MetadataRecord, MetadataService
from app.naming import media_folder_name, remote_to_local_path, render_desired_name
from app.scraper import scrape_subscription


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
            return _Response(payload=[{"hash": "abc", "added_on": 1}])
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

    def test_emby_folder_and_episode_name(self):
        sub = self.subscription()
        self.assertEqual(media_folder_name(sub), "金牌得主 (2025) [tmdbid=123]")
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
            normalized = client.normalize_single_video(tag="feeddock-item-1", desired_name="Show - S01E01")
        self.assertTrue(normalized.ok)
        self.assertEqual(normalized.state, "renamed")
        add_call = next(call for call in calls if call[1].endswith("torrents/add"))
        self.assertEqual(add_call[3]["rename"][1], "Show - S01E01")
        self.assertEqual(add_call[3]["tags"][1], "feeddock-item-1")
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

    def test_local_scraper_writes_nfo_without_downloading_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            sub = self.subscription(metadata_overview="简介", poster_url="", backdrop_url="", bgm_url="", total_episodes=12)
            metadata_config = SimpleNamespace(media_local_root=tmp)
            qbit_config = SimpleNamespace(download_path="/downloads/rss")
            with patch("app.scraper.load_metadata_config", return_value=metadata_config), patch("app.scraper.load_qbittorrent_config", return_value=qbit_config), patch("app.rss_service.render_save_path", return_value="/downloads/rss/金牌得主 (2025) [tmdbid=123]/Season 02"):
                result = scrape_subscription(SimpleNamespace(), sub)
            self.assertTrue(result.ok)
            root = Path(tmp) / "金牌得主 (2025) [tmdbid=123]"
            self.assertTrue((root / "tvshow.nfo").exists())
            self.assertTrue((root / "Season 02" / "season.nfo").exists())
            self.assertIn("tmdb", (root / "tvshow.nfo").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

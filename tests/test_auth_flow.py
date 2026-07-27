import os
import tempfile
import unittest
from unittest.mock import patch

_TEST_DATA = tempfile.TemporaryDirectory()
os.environ["DATA_DIR"] = _TEST_DATA.name
os.environ["ADMIN_USER"] = "admin"
os.environ["ADMIN_PASSWORD"] = "initial-password"
os.environ["SESSION_SECRET"] = "test-session-secret-that-is-long-enough"
os.environ["APP_VERSION"] = "1.7.0"

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import FeedItem, SystemLog


class AuthFlowTests(unittest.TestCase):
    def test_first_login_requires_password_change(self):
        with TestClient(app, follow_redirects=False) as client:
            bootstrap = client.get("/api/auth/bootstrap")
            self.assertEqual(bootstrap.status_code, 200)
            self.assertTrue(bootstrap.json()["initial_password_change_required"])

            root = client.get("/")
            self.assertEqual(root.status_code, 303)
            self.assertEqual(root.headers["location"], "/login")

            bad = client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "wrong-password"},
            )
            self.assertEqual(bad.status_code, 401)

            login = client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "initial-password"},
            )
            self.assertEqual(login.status_code, 200)
            self.assertTrue(login.json()["must_change_password"])
            self.assertIn("feeddock_session", client.cookies)

            forced_page = client.get("/")
            self.assertEqual(forced_page.status_code, 303)
            self.assertEqual(forced_page.headers["location"], "/change-password")
            password_page = client.get("/change-password")
            self.assertEqual(password_page.status_code, 200)
            self.assertIn("请修改初始密码", password_page.text)

            blocked = client.get("/api/dashboard")
            self.assertEqual(blocked.status_code, 428)
            self.assertEqual(blocked.json()["detail"], "PASSWORD_CHANGE_REQUIRED")

            change = client.post(
                "/api/auth/change-password",
                json={
                    "current_password": "initial-password",
                    "new_password": "a-new-secure-password-2026",
                },
            )
            self.assertEqual(change.status_code, 200)
            self.assertFalse(change.json()["must_change_password"])
            bootstrap_after = client.get("/api/auth/bootstrap")
            self.assertFalse(bootstrap_after.json()["initial_password_change_required"])

            dashboard = client.get("/api/dashboard")
            self.assertEqual(dashboard.status_code, 200)

            config = client.get("/api/config")
            self.assertEqual(config.status_code, 200, config.text)
            self.assertIsInstance(config.json()["automation"], dict)
            self.assertIsInstance(config.json()["proxy"], dict)

            home = client.get("/")
            self.assertEqual(home.status_code, 200)
            self.assertIn("系统与更新", home.text)
            self.assertIn("qBittorrent 下载器", home.text)
            self.assertIn("Mikan 番剧目录", home.text)

            password_page_after_setup = client.get("/change-password")
            self.assertEqual(password_page_after_setup.status_code, 200)

            with patch("app.main.DiscoveryService") as discovery_factory:
                discovery_factory.return_value.catalog.return_value = {
                    "provider": "mikan",
                    "year": 2026,
                    "season": "夏",
                    "query": "",
                    "base_url": "https://mikan.test",
                    "rows": [
                        {
                            "weekday": "星期一",
                            "day_of_week": 1,
                            "items": [
                                {
                                    "bangumi_id": 3822,
                                    "title": "金牌得主 第二季",
                                    "cover_url": "https://mikan.test/cover.jpg",
                                    "update_at": "7/24/2026",
                                    "detail_url": "https://mikan.test/Home/Bangumi/3822",
                                    "base_url": "https://mikan.test",
                                }
                            ],
                        }
                    ],
                    "errors": [],
                }
                catalog = client.get(
                    "/api/discovery/mikan/catalog",
                    params={"year": 2026, "season": "夏"},
                )
                self.assertEqual(catalog.status_code, 200, catalog.text)
                self.assertEqual(catalog.json()["rows"][0]["weekday"], "星期一")
                cached_catalog = client.get(
                    "/api/discovery/mikan/catalog",
                    params={"year": 2026, "season": "夏", "q": "金牌"},
                )
                self.assertEqual(cached_catalog.status_code, 200, cached_catalog.text)
                self.assertEqual(discovery_factory.return_value.catalog.call_count, 1)
                forced_catalog = client.post(
                    "/api/discovery/mikan/catalog/refresh",
                    params={"year": 2026, "season": "夏"},
                )
                self.assertEqual(forced_catalog.status_code, 200, forced_catalog.text)
                self.assertEqual(discovery_factory.return_value.catalog.call_count, 2)

                saved_filter = client.put(
                    "/api/discovery/mikan/catalog/filters",
                    json={
                        "year": 2026,
                        "season": "夏",
                        "weekday": "星期一",
                        "hidden_bangumi_ids": [3822],
                    },
                )
                self.assertEqual(saved_filter.status_code, 200, saved_filter.text)
                filtered_catalog = client.get(
                    "/api/discovery/mikan/catalog",
                    params={"year": 2026, "season": "夏"},
                )
                self.assertEqual(filtered_catalog.status_code, 200, filtered_catalog.text)
                self.assertTrue(filtered_catalog.json()["rows"][0]["items"][0]["hidden"])
                self.assertEqual(filtered_catalog.json()["hidden_count"], 1)

                restored_filter = client.put(
                    "/api/discovery/mikan/catalog/filters",
                    json={
                        "year": 2026,
                        "season": "夏",
                        "weekday": "星期一",
                        "hidden_bangumi_ids": [],
                    },
                )
                self.assertEqual(restored_filter.status_code, 200, restored_filter.text)

                discovery_factory.return_value.search.return_value = {
                    "query": "金牌得主",
                    "provider": "mikan",
                    "results": [
                        {
                            "provider": "mikan",
                            "result_type": "bangumi",
                            "id": "mikan-bangumi-3822",
                            "title": "金牌得主 第二季",
                            "base_url": "https://mikan.test",
                            "bangumi_id": 3822,
                        }
                    ],
                    "errors": [],
                }
                search = client.get(
                    "/api/discovery/search",
                    params={"q": "金牌得主"},
                )
                self.assertEqual(search.status_code, 200, search.text)
                self.assertEqual(search.json()["results"][0]["bangumi_id"], 3822)

                discovery_factory.return_value.mikan_detail.return_value = {
                    "provider": "mikan",
                    "bangumi_id": 3822,
                    "title": "金牌得主 第二季",
                    "base_url": "https://mikan.test",
                    "detail_url": "https://mikan.test/Home/Bangumi/3822",
                    "groups": [
                        {
                            "subgroup_id": 370,
                            "name": "LoliHouse",
                            "rss_url": "https://mikan.test/RSS/Bangumi?bangumiId=3822&subgroupid=370",
                            "preset": {
                                "name": "金牌得主 第二季",
                                "rss_url": "https://mikan.test/RSS/Bangumi?bangumiId=3822&subgroupid=370",
                            },
                        }
                    ],
                }
                detail = client.get(
                    "/api/discovery/mikan/3822",
                    params={"base_url": "https://mikan.test", "title": "金牌得主 第二季"},
                )
                self.assertEqual(detail.status_code, 200, detail.text)
                self.assertEqual(detail.json()["groups"][0]["name"], "LoliHouse")
                cached_detail = client.get(
                    "/api/discovery/mikan/3822",
                    params={"base_url": "https://mikan.test", "title": "金牌得主 第二季"},
                )
                self.assertEqual(cached_detail.status_code, 200, cached_detail.text)
                self.assertEqual(discovery_factory.return_value.mikan_detail.call_count, 1)
                forced_detail = client.post(
                    "/api/discovery/mikan/3822/refresh",
                    params={"base_url": "https://mikan.test", "title": "金牌得主 第二季"},
                )
                self.assertEqual(forced_detail.status_code, 200, forced_detail.text)
                self.assertEqual(discovery_factory.return_value.mikan_detail.call_count, 2)

            with patch("app.main.refresh_subscription") as initial_refresh:
                created_subscription = client.post(
                    "/api/subscriptions",
                    json={
                        "name": "Frontend regression feed",
                        "rss_url": "https://example.test/feed.xml",
                        "include_keywords": "1080p, 简体",
                        "exclude_keywords": "合集, 720p",
                        "episode_regex": "",
                        "save_path_template": "{base}/{subscription}",
                        "enabled": True,
                    },
                )
                initial_refresh.assert_called_once()
                self.assertEqual(
                    initial_refresh.call_args.kwargs,
                    {"trigger": "subscription-created"},
                )
            self.assertEqual(created_subscription.status_code, 200)
            self.assertEqual(created_subscription.json()["name"], "Frontend regression feed")
            self.assertFalse(created_subscription.json()["scrape_enabled"])
            self.assertEqual(created_subscription.json()["custom_download_path"], "/media")
            subscriptions = client.get("/api/subscriptions")
            self.assertEqual(subscriptions.status_code, 200)
            self.assertTrue(
                any(item["name"] == "Frontend regression feed" for item in subscriptions.json())
            )

            global_rules = client.put(
                "/api/rules/global",
                json={"exclude_rules": "剧场版"},
            )
            self.assertEqual(global_rules.status_code, 200)

            advanced_payload = {
                "name": "金牌得主 第二季",
                "reference_title": "金牌得主 (2025)",
                "tmdb_title": "金牌得主 (2025)",
                "metadata_year": 2026,
                "tmdb_id": 123456,
                "bgm_url": "https://bgm.tv/subject/548818",
                "air_date": "2026-01-24",
                "season": 2,
                "primary_rss_name": "LoliHouse",
                "rss_url": "https://mikanime.tv/RSS/Bangumi?bangumiId=3822&subgroupid=370",
                "backup_rss_name": "",
                "backup_rss_url": None,
                "include_keywords": "无",
                "exclude_keywords": "720\n\\d-\\d\n合集\n特别篇",
                "episode_regex": "\\d+(\\.5)?",
                "episode_group": 0,
                "episode_offset": -13,
                "total_episodes": 9,
                "save_path_template": "{base}/{subscription}/Season {season}",
                "custom_download_path": "/vol2/1000/影视/金牌得主 (2025)/Season 2",
                "missing_detection": True,
                "only_latest": True,
                "enabled": True,
            }
            preview_payload = dict(advanced_payload)
            preview_payload["sample_title"] = "[LoliHouse] 金牌得主 - 14 [1080p]"
            preview = client.post("/api/subscriptions/preview", json=preview_payload)
            self.assertEqual(preview.status_code, 200, preview.text)
            self.assertEqual(preview.json()["adjusted_episode"], "1")
            self.assertEqual(
                preview.json()["save_path"],
                "/media/金牌得主 (2026) [tmdbid=123456]/Season 02",
            )

            with patch("app.main.refresh_subscription") as initial_refresh:
                advanced = client.post("/api/subscriptions", json=advanced_payload)
                initial_refresh.assert_called_once()
            self.assertEqual(advanced.status_code, 200, advanced.text)
            self.assertEqual(advanced.json()["season"], 2)
            self.assertEqual(advanced.json()["include_keywords"], "")
            self.assertEqual(advanced.json()["missing_episodes"], list(range(1, 10)))

            saved_qbit = client.put(
                "/api/downloader/settings",
                json={
                    "qbit_url": "http://host.docker.internal:8080",
                    "qbit_username": "admin",
                    "qbit_password": "qbit-secret",
                    "qbit_category": "rss",
                    "download_path": "/media/downloads/rss",
                },
            )
            self.assertEqual(saved_qbit.status_code, 200)
            self.assertTrue(saved_qbit.json()["qbit_password_configured"])
            self.assertEqual(saved_qbit.json()["source"], "web")
            self.assertNotIn("qbit_password", saved_qbit.json())

            preserve_password = client.put(
                "/api/downloader/settings",
                json={
                    "qbit_url": "http://host.docker.internal:8080",
                    "qbit_username": "admin",
                    "qbit_password": None,
                    "qbit_category": "anime",
                    "download_path": "/media/downloads/rss",
                },
            )
            self.assertEqual(preserve_password.status_code, 200)
            self.assertTrue(preserve_password.json()["qbit_password_configured"])
            self.assertEqual(preserve_password.json()["qbit_category"], "anime")

            aligned_subscriptions = client.get("/api/subscriptions")
            self.assertEqual(aligned_subscriptions.status_code, 200)
            self.assertTrue(aligned_subscriptions.json())
            self.assertTrue(all(
                item["custom_download_path"] == "/media/downloads/rss"
                for item in aligned_subscriptions.json()
            ))

            with SessionLocal() as db:
                subscription_id = aligned_subscriptions.json()[0]["id"]
                db.add(FeedItem(
                    subscription_id=subscription_id,
                    fingerprint="c" * 64,
                    title="清理测试条目",
                    status="skipped",
                    reason="test",
                ))
                db.add(SystemLog(level="INFO", message="清理测试日志", details="test"))
                db.commit()

            clear_items = client.delete("/api/items")
            self.assertEqual(clear_items.status_code, 200)
            self.assertGreaterEqual(clear_items.json()["count"], 1)
            self.assertEqual(client.get("/api/items").json(), [])
            with SessionLocal() as db:
                hidden_item = db.query(FeedItem).filter(FeedItem.fingerprint == "c" * 64).one()
                self.assertTrue(hidden_item.hidden)

            clear_logs = client.delete("/api/logs")
            self.assertEqual(clear_logs.status_code, 200)
            self.assertGreaterEqual(clear_logs.json()["count"], 1)
            self.assertEqual(client.get("/api/logs").json(), [])

            logout = client.post("/api/auth/logout")
            self.assertEqual(logout.status_code, 200)
            unauthorized = client.get("/api/dashboard")
            self.assertEqual(unauthorized.status_code, 401)

        # Simulate a container/app restart with the same persisted DATA_DIR.
        # ADMIN_PASSWORD remains the initial Compose value, but it must not
        # overwrite the password already stored in SQLite.
        with TestClient(app, follow_redirects=False) as restarted_client:
            old_password = restarted_client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "initial-password"},
            )
            self.assertEqual(old_password.status_code, 401)

            new_password = restarted_client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "a-new-secure-password-2026"},
            )
            self.assertEqual(new_password.status_code, 200)
            self.assertFalse(new_password.json()["must_change_password"])

            persisted_qbit = restarted_client.get("/api/downloader/settings")
            self.assertEqual(persisted_qbit.status_code, 200)
            self.assertEqual(persisted_qbit.json()["qbit_category"], "anime")
            self.assertTrue(persisted_qbit.json()["qbit_password_configured"])


if __name__ == "__main__":
    unittest.main()

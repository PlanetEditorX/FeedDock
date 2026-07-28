from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import FeedItem, Subscription
from app.notification_config import load_notification_config, save_notification_config
from app.notifications import send_notification
from app.notification.channels import normalize_bark_push_url
from app.notification.service import preview_notification
from app.notification.templates import validate_template


class _Response:
    def raise_for_status(self) -> None:
        return None


class NotificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def save_config(self, **overrides):
        values = {
            "enabled": True,
            "events": ["download_started", "download_completed"],
            "telegram_enabled": True,
            "telegram_bot_token": "bot-secret",
            "clear_telegram_bot_token": False,
            "telegram_chat_id": "12345",
            "bark_enabled": True,
            "bark_server_url": "https://api.day.app",
            "bark_device_key": "device-secret",
            "clear_bark_device_key": False,
            "webhook_enabled": True,
            "webhook_url": "https://hooks.example.test/notify",
            "clear_webhook_url": False,
            "webhook_headers_json": '{"Authorization":"Bearer secret"}',
            "clear_webhook_headers": False,
        }
        values.update(overrides)
        return save_notification_config(self.db, **values)

    def test_public_config_hides_secrets_and_preserves_channels(self):
        config = self.save_config()
        public = config.public_dict()
        self.assertNotIn("telegram_bot_token", public)
        self.assertNotIn("bark_device_key", public)
        self.assertTrue(public["telegram_bot_token_configured"])
        self.assertTrue(public["bark_device_key_configured"])
        self.assertEqual(public["configured_channels"], ["telegram", "bark", "webhook"])
        self.assertEqual(load_notification_config(self.db).webhook_headers["Authorization"], "Bearer secret")

    def test_send_notification_dispatches_all_enabled_channels(self):
        self.save_config()
        calls = []

        def fake_post(url, **kwargs):
            calls.append((url, kwargs))
            return _Response()

        with patch("app.notifications.external_post", side_effect=fake_post):
            result = send_notification(
                self.db,
                "download_started",
                "开始下载",
                "第 1 集",
            )
        self.assertTrue(result.ok)
        self.assertEqual(result.sent, 3)
        self.assertIn("api.telegram.org", calls[0][0])
        self.assertEqual(calls[1][0], "https://api.day.app/push")
        self.assertEqual(calls[2][1]["json"]["event"], "download_started")
        self.assertEqual(calls[2][1]["headers"]["Authorization"], "Bearer secret")

    def test_unselected_event_is_skipped_without_network(self):
        self.save_config(events=["download_completed"])
        with patch("app.notifications.external_post") as external_post:
            result = send_notification(self.db, "download_started", "标题", "正文")
        self.assertTrue(result.ok)
        self.assertTrue(result.skipped)
        external_post.assert_not_called()

    def test_channel_errors_redact_tokens_urls_and_header_values(self):
        self.save_config()

        def fail(url, **kwargs):
            raise RuntimeError(
                f"request failed: {url}; authorization={kwargs.get('headers', {}).get('Authorization', '')}"
            )

        with patch("app.notifications.external_post", side_effect=fail):
            result = send_notification(self.db, "download_started", "开始下载", "第 1 集")
        combined = "；".join(result.errors)
        self.assertFalse(result.ok)
        self.assertNotIn("bot-secret", combined)
        self.assertNotIn("device-secret", combined)
        self.assertNotIn("https://hooks.example.test/notify", combined)
        self.assertNotIn("Bearer secret", combined)
        self.assertIn("***", combined)


    def test_bark_accepts_complete_push_endpoint_and_sends_device_key_in_json(self):
        self.save_config(
            telegram_enabled=False,
            bark_server_url="http://192.168.1.10:28080/push",
            webhook_enabled=False,
        )
        calls = []

        def fake_post(url, **kwargs):
            calls.append((url, kwargs))
            return _Response()

        with patch("app.notifications.external_post", side_effect=fake_post):
            result = send_notification(self.db, "download_started", "开始下载", "第 1 集")

        self.assertTrue(result.ok)
        self.assertEqual(calls[0][0], "http://192.168.1.10:28080/push")
        self.assertEqual(calls[0][1]["json"]["device_key"], "device-secret")
        self.assertNotIn("device-secret", calls[0][0])

    def test_bark_download_completion_uses_normalized_filename_and_cover(self):
        self.save_config(
            telegram_enabled=False,
            webhook_enabled=False,
            title_template="{title}",
            body_template="{message}",
        )
        subscription = Subscription(
            name="示例番剧",
            rss_url="https://example.test/rss",
            poster_url="https://images.example.test/poster.jpg",
        )
        item = FeedItem(
            subscription_id=1,
            fingerprint="normalized-bark",
            title="[Group] Example - 01 [1080p].mkv",
            episode="1",
            desired_name="示例番剧 - S01E01",
            status="queued",
        )
        calls = []

        def fake_post(url, **kwargs):
            calls.append((url, kwargs))
            return _Response()

        with patch("app.notifications.external_post", side_effect=fake_post):
            result = send_notification(
                self.db,
                "download_completed",
                "下载完成：示例番剧",
                "第 1 集下载完成。\n示例番剧 - S01E01.mkv",
                subscription=subscription,
                item=item,
                details={
                    "filename": "示例番剧 - S01E01.mkv",
                    "cover_url": subscription.poster_url,
                },
            )

        self.assertTrue(result.ok)
        payload = calls[0][1]["json"]
        self.assertIn("示例番剧 - S01E01.mkv", payload["body"])
        self.assertNotIn("[Group] Example", payload["body"])
        self.assertEqual(payload["icon"], subscription.poster_url)
        self.assertEqual(payload["image"], subscription.poster_url)

    def test_bark_endpoint_normalization_supports_root_and_push_url(self):
        self.assertEqual(normalize_bark_push_url("https://api.day.app"), "https://api.day.app/push")
        self.assertEqual(normalize_bark_push_url("https://api.day.app/push/"), "https://api.day.app/push")
        self.assertEqual(
            normalize_bark_push_url("http://host:8080/base"),
            "http://host:8080/base/push",
        )

    def test_notification_templates_are_persisted_rendered_and_previewed(self):
        config = self.save_config(
            title_template="[{event_label}] {title}",
            body_template="{message}\n订阅：{subscription_name}",
            telegram_enabled=False,
            bark_enabled=True,
            webhook_enabled=False,
        )
        self.assertEqual(config.public_dict()["title_template"], "[{event_label}] {title}")

        calls = []

        def fake_post(url, **kwargs):
            calls.append((url, kwargs))
            return _Response()

        with patch("app.notifications.external_post", side_effect=fake_post):
            result = send_notification(self.db, "download_started", "开始下载", "第 1 集")
        self.assertTrue(result.ok)
        self.assertEqual(calls[0][1]["json"]["title"], "[开始下载] 开始下载")
        self.assertEqual(calls[0][1]["json"]["body"], "第 1 集\n订阅：")

        preview = preview_notification(
            event="download_completed",
            title_template="[{event_label}] {subscription_name}",
            body_template="{message} / E{item_episode}",
        )
        self.assertEqual(preview["title"], "[下载完成] 示例番剧")
        self.assertIn("E1", preview["body"])

    def test_template_validation_rejects_unknown_or_advanced_fields(self):
        with self.assertRaisesRegex(ValueError, "未知变量"):
            validate_template("{unknown}", "通知标题模板", max_length=1000)
        with self.assertRaisesRegex(ValueError, "不支持格式说明"):
            validate_template("{item_episode:02}", "通知标题模板", max_length=1000)

    def test_enabled_center_requires_at_least_one_event(self):
        with self.assertRaisesRegex(ValueError, "至少需要选择一个通知事件"):
            self.save_config(events=[])

    def test_channel_validation_rejects_incomplete_configuration(self):
        with self.assertRaisesRegex(ValueError, "Bot Token"):
            self.save_config(
                telegram_bot_token="",
                bark_enabled=False,
                webhook_enabled=False,
            )
        with self.assertRaisesRegex(ValueError, "JSON 对象"):
            self.save_config(webhook_headers_json="[]")


if __name__ == "__main__":
    unittest.main()

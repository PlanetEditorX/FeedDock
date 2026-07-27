from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.notification_config import load_notification_config, save_notification_config
from app.notifications import send_notification


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

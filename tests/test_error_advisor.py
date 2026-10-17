"""Regression coverage for subscription error classification and the retry dialog."""
from __future__ import annotations

import unittest
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.error_advisor import classify_error, describe_error, error_advice
from app.main import subscription_error_detail
from app.models import Subscription
from app.rss_service import _rss_load_error_details

ROOT = Path(__file__).resolve().parents[1]


class ErrorAdvisorTests(unittest.TestCase):
    def test_ssl_failures_are_not_mistaken_for_feed_problems(self) -> None:
        for message in (
            "请求 https://mikanani.me/rss/x 失败：[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate",
            "请求 https://anibt.net/rss 失败：[SSL: DH_KEY_TOO_SMALL] dh key too small",
            "请求 https://x.test/feed 失败：tlsv1 alert protocol version",
        ):
            self.assertEqual(classify_error(message), "ssl", message)

    def test_connection_level_failures_keep_their_kind(self) -> None:
        cases = {
            "dns": "请求 https://x.test/feed 失败：[Errno -2] Name or service not known",
            "unreachable": "请求 https://x.test/feed 失败：[Errno 101] Network is unreachable",
            "refused": "请求 https://x.test/feed 失败：[Errno 111] Connection refused",
            "timeout": "请求 https://x.test/feed 失败：The read operation timed out",
        }
        for kind, message in cases.items():
            self.assertEqual(classify_error(message), kind, message)

    def test_http_status_failures_map_to_actionable_kinds(self) -> None:
        cases = {
            "http_403": "请求 https://x.test/feed 失败：Client error '403 Forbidden' for url 'https://x.test/feed'",
            "http_404": "请求 https://x.test/feed 失败：Client error '404 Not Found' for url 'https://x.test/feed'",
            "http_429": "请求 https://x.test/feed 失败：Client error '429 Too Many Requests' for url 'https://x.test/feed'",
            "http_5xx": "请求 https://x.test/feed 失败：Server error '502 Bad Gateway' for url 'https://x.test/feed'",
        }
        for kind, message in cases.items():
            self.assertEqual(classify_error(message), kind, message)

    def test_empty_feed_and_unknown_messages_have_sensible_advice(self) -> None:
        self.assertEqual(classify_error("主 RSS 没有条目；请点击“更新 RSS”重新搜索字幕组"), "no_entries")
        self.assertEqual(classify_error("请求 https://x.test/feed 失败：something odd happened"), "unknown")
        self.assertEqual(classify_error(""), "unknown")
        for kind in ("no_entries", "unknown"):
            advice = error_advice(kind)
            self.assertTrue(advice)

    def test_describe_error_returns_labelled_actions(self) -> None:
        detail = describe_error("请求 https://x.test/feed 失败：certificate verify failed")
        self.assertEqual(detail["kind"], "ssl")
        self.assertEqual(detail["label"], "SSL/TLS 证书错误")
        action_ids = [action["id"] for action in detail["actions"]]
        self.assertIn("reselect-rss", action_ids)
        self.assertIn("retry", action_ids)
        self.assertTrue(all(action["label"] for action in detail["actions"]))

    def test_exception_chains_are_flattened_before_matching(self) -> None:
        try:
            try:
                raise OSError(101, "Network is unreachable")
            except OSError as inner:
                raise RuntimeError("请求 https://x.test/feed 失败") from inner
        except RuntimeError as exc:
            self.assertEqual(classify_error(exc), "unreachable")

    def test_load_error_details_include_classified_advice(self) -> None:
        subscription = Subscription(name="Demo", rss_url="https://x.test/feed")
        details = _rss_load_error_details(
            subscription,
            RuntimeError("请求 https://x.test/feed 失败：[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"),
        )
        self.assertIn("处理建议：", details)
        self.assertIn("证书", details)


class SubscriptionErrorDetailEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def _create(self, **fields) -> Subscription:
        subscription = Subscription(name="处女朋克：发条女孩", rss_url="https://mikanani.me/rss/x", **fields)
        self.db.add(subscription)
        self.db.commit()
        self.db.refresh(subscription)
        return subscription

    def test_error_detail_classifies_persisted_error(self) -> None:
        subscription = self._create(
            last_error="请求 https://mikanani.me/rss/x 失败：Client error '403 Forbidden' for url 'https://mikanani.me/rss/x'",
        )
        result = subscription_error_detail(subscription.id, db=self.db)
        self.assertEqual(result["kind"], "http_403")
        self.assertEqual(result["label"], "站点拒绝访问（403）")
        self.assertIn("重新选择当前可用的 RSS", result["advice"])
        self.assertEqual([action["id"] for action in result["actions"]], ["reselect-rss", "retry"])
        self.assertEqual(result["subscription_id"], subscription.id)
        self.assertEqual(result["error"], subscription.last_error)

    def test_error_detail_reports_clean_subscription_without_actions(self) -> None:
        subscription = self._create()
        result = subscription_error_detail(subscription.id, db=self.db)
        self.assertEqual(result["kind"], "")
        self.assertEqual(result["actions"], [])
        self.assertEqual(result["error"], "")

    def test_error_detail_missing_subscription_returns_404(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            subscription_error_detail(4242, db=self.db)
        self.assertEqual(ctx.exception.status_code, 404)


class SubscriptionRetryDialogTests(unittest.TestCase):
    """Static wiring checks for the retry entry point on abnormal cards."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app_js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
        cls.index_html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        cls.styles = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")

    def test_abnormal_cards_expose_a_retry_button(self) -> None:
        self.assertIn("const retry = text('button', '重试', 'warning');", self.app_js)
        self.assertIn("retry.addEventListener('click', () => openSubscriptionRetry(sub));", self.app_js)
        self.assertIn("const retryAction = sub.last_error ? [retry] : [];", self.app_js)

    def test_retry_dialog_fetches_classified_detail_and_actions(self) -> None:
        self.assertIn("async function openSubscriptionRetry(sub)", self.app_js)
        self.assertIn("`/api/subscriptions/${sub.id}/error-detail`", self.app_js)
        for action_id in ("reselect-rss", "retry", "test-rss", "network-diagnostics", "edit"):
            self.assertIn(f"action === '{action_id}'", self.app_js)

    def test_retry_modal_markup_and_styles_exist(self) -> None:
        self.assertIn('id="subscriptionRetryModal"', self.index_html)
        self.assertIn('id="retryErrorKind"', self.index_html)
        self.assertIn('id="retryAdvice"', self.index_html)
        self.assertIn('id="retryActions"', self.index_html)
        self.assertIn('id="retryOutput"', self.index_html)
        self.assertIn("data-close-subscription-retry", self.index_html)
        self.assertIn("button.warning", self.styles)
        self.assertIn(".retry-dialog", self.styles)


if __name__ == "__main__":
    unittest.main()

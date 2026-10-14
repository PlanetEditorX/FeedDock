"""Regression coverage for proxy connectivity and main/backup RSS updates."""
from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.main import test_proxy as check_proxy_connectivity
from app.main import test_subscription_rss_source as check_saved_rss
from app.models import Subscription
from app.rss_service import _load_subscription_entries, process_subscription
from app.subscription_monitor import reset_monitor_state_for_changes


class RSSAndProxyFixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_proxy_test_uses_saved_proxy_outbound_path_for_both_sites(self) -> None:
        with (
            patch("app.main.diagnose_dns", return_value={"ok": False, "checks": []}),
            patch("app.main.load_proxy_config", return_value=SimpleNamespace(configured=True)),
            patch("app.main.external_get", side_effect=[
                SimpleNamespace(status_code=200), SimpleNamespace(status_code=204),
            ]) as get,
        ):
            result = check_proxy_connectivity(db=self.db)
        self.assertTrue(result["ok"])
        self.assertTrue(result["proxy_enabled"])
        self.assertEqual([entry["name"] for entry in result["checks"]], ["Bangumi", "Google"])
        self.assertEqual(get.call_args_list[1].args[0], "https://www.google.com/generate_204")
        for call in get.call_args_list:
            self.assertIs(call.kwargs["db"], self.db)

    def test_google_failure_is_visible_even_when_bangumi_works(self) -> None:
        with (
            patch("app.main.diagnose_dns", return_value={"ok": True, "checks": []}),
            patch("app.main.load_proxy_config", return_value=SimpleNamespace(configured=False)),
            patch("app.main.external_get", side_effect=[
                SimpleNamespace(status_code=200), SimpleNamespace(status_code=503),
            ]),
        ):
            result = check_proxy_connectivity(db=self.db)
        self.assertFalse(result["ok"])
        self.assertTrue(result["checks"][0]["ok"])
        self.assertFalse(result["checks"][1]["ok"])
        self.assertIn("Google 失败", result["message"])

    def test_backup_is_used_only_when_primary_is_empty(self) -> None:
        sub = Subscription(name="Demo", rss_url="https://primary.test/rss", backup_rss_url="https://backup.test/rss")
        with patch("app.rss_service._fetch_entries", side_effect=[[], [{"title": "Demo EP1"}]]) as fetch:
            feed, _label, source = _load_subscription_entries(sub, self.db)
        self.assertEqual(source, "backup")
        self.assertEqual(len(feed), 1)
        self.assertEqual(fetch.call_count, 2)
        with patch("app.rss_service._fetch_entries", return_value=[{"title": "Demo EP1"}]) as fetch:
            _feed, _label, source = _load_subscription_entries(sub, self.db)
        self.assertEqual(source, "primary")
        fetch.assert_called_once()

    def test_successful_fallback_persists_used_backup_source(self) -> None:
        sub = Subscription(name="Demo", rss_url="https://primary.test/rss", backup_rss_url="https://backup.test/rss")
        self.db.add(sub)
        self.db.commit()
        with (
            patch("app.rss_service._cleanup_subscription_orphaned_metadata"),
            patch("app.rss_service._refresh_total_episodes_if_due"),
            patch("app.rss_service._sync_metadata_if_due"),
            patch("app.rss_service.load_application_preferences", return_value=SimpleNamespace(rss=SimpleNamespace(enabled=True))),
            patch("app.rss_service._fetch_entries", side_effect=[RuntimeError("unreachable"), [{"title": "Demo - 01"}]]),
            patch("app.rss_service._build_candidates", return_value=[]),
            patch("app.rss_service._select_priority_candidates", return_value=(None, None)),
            patch("app.rss_service._process_candidates"),
        ):
            stats = process_subscription(self.db, sub)
        self.assertEqual(stats["errors"], 0)
        self.assertEqual(sub.last_rss_source, "backup")
        self.assertEqual(sub.last_error, "")
        self.assertIsNotNone(sub.last_checked_at)

    def test_rss_source_change_resets_stale_error_only_when_url_changes(self) -> None:
        when = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        sub = Subscription(
            name="Demo", rss_url="https://primary.test/old", backup_rss_url="https://backup.test/old",
            last_error="以前的网络异常", last_checked_at=when, last_rss_source="primary",
        )
        reset_monitor_state_for_changes(sub, {"name": "New name"})
        self.assertEqual(sub.last_error, "以前的网络异常")
        reset_monitor_state_for_changes(sub, {"backup_rss_url": "https://backup.test/new"})
        self.assertEqual(sub.last_error, "")
        self.assertIsNone(sub.last_checked_at)
        self.assertEqual(sub.last_rss_source, "")

    def test_independent_backup_test_does_not_update_subscription_status(self) -> None:
        sub = Subscription(
            name="Demo", rss_url="https://primary.test/rss", backup_rss_url="https://backup.test/rss",
            last_error="prior failed", last_rss_source="",
        )
        self.db.add(sub)
        self.db.commit()
        with patch("app.rss_service._fetch_entries", return_value=[{"title": "A"}, {"title": "B"}]) as fetch:
            result = check_saved_rss(sub.id, source="backup", db=self.db)
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 2)
        self.assertEqual(fetch.call_args.args[0], "https://backup.test/rss")
        self.assertEqual(sub.last_error, "prior failed")
        self.assertIsNone(sub.last_checked_at)

    def test_unconfigured_backup_reports_it_is_not_active(self) -> None:
        sub = Subscription(name="Demo", rss_url="https://primary.test/rss")
        self.db.add(sub)
        self.db.commit()
        result = check_saved_rss(sub.id, source="backup", db=self.db)
        self.assertFalse(result["ok"])
        self.assertIn("未配置", result["message"])

    def test_ui_contains_persistent_result_and_saving_candidate(self) -> None:
        root = Path(__file__).resolve().parents[1]
        index = (root / "app/static/index.html").read_text(encoding="utf-8")
        script = (root / "app/static/app.js").read_text(encoding="utf-8")
        for element_id in ("proxyTestResults", "testPrimaryRss", "testBackupRss", "rssSettingsFeedback"):
            self.assertIn(f'id="{element_id}"', index)
        self.assertIn("设为备用 RSS 并保存", script)
        self.assertIn("method: 'PATCH', body: JSON.stringify(patch)", script)
        self.assertIn("last_rss_source === 'backup'", script)
        self.assertIn("watchSubscriptionRefresh", script)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import subprocess
import textwrap
import unittest
from html.parser import HTMLParser
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.main import batch_subscriptions, export_subscriptions, import_subscriptions, system_status
from app.settings_config import load_application_preferences, save_application_preferences, save_subscription_sort_preference
from fastapi import HTTPException
from app.models import Subscription
from app.schemas import SubscriptionBatchRequest, SubscriptionCreate, SubscriptionImportRequest


ROOT = Path(__file__).resolve().parents[1]


class _IndexStructureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.visible_views: set[str] = set()

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(str(values["id"]))
        view = values.get("data-app-view")
        classes = set(str(values.get("class") or "").split())
        if view and "hidden" not in classes:
            self.visible_views.add(view)


class SubscriptionManagementTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def payload(self, name: str, url: str, *, enabled: bool = True) -> SubscriptionCreate:
        return SubscriptionCreate(name=name, rss_url=url, enabled=enabled)

    def test_import_export_and_batch_lifecycle(self) -> None:
        result = import_subscriptions(
            SubscriptionImportRequest(
                subscriptions=[
                    self.payload("A", "https://example.test/a.xml"),
                    self.payload("B", "https://example.test/b.xml", enabled=False),
                ]
            ),
            self.db,
        )
        self.assertEqual(result, {"created": 2, "updated": 0, "skipped": 0})

        skipped = import_subscriptions(
            SubscriptionImportRequest(
                subscriptions=[self.payload("A copy", "https://example.test/a.xml")],
                conflict="skip",
            ),
            self.db,
        )
        self.assertEqual(skipped["skipped"], 1)

        updated = import_subscriptions(
            SubscriptionImportRequest(
                subscriptions=[self.payload("A updated", "https://example.test/a.xml")],
                conflict="update",
            ),
            self.db,
        )
        self.assertEqual(updated["updated"], 1)
        rows = list(self.db.scalars(select(Subscription).order_by(Subscription.id)))
        self.assertEqual([row.name for row in rows], ["A updated", "B"])

        exported = export_subscriptions(ids=[rows[0].id], db=self.db)
        self.assertEqual(exported["format"], "feeddock-subscriptions")
        self.assertEqual(len(exported["subscriptions"]), 1)
        self.assertEqual(exported["subscriptions"][0]["rss_url"], "https://example.test/a.xml")
        self.assertNotIn("id", exported["subscriptions"][0])

        disabled = batch_subscriptions(
            SubscriptionBatchRequest(ids=[rows[0].id], action="disable"), self.db
        )
        self.assertEqual(disabled["affected"], 1)
        self.assertFalse(self.db.get(Subscription, rows[0].id).enabled)

        enabled = batch_subscriptions(
            SubscriptionBatchRequest(ids=[rows[0].id, rows[1].id], action="enable"), self.db
        )
        self.assertEqual(enabled["affected"], 2)
        self.assertTrue(all(row.enabled for row in self.db.scalars(select(Subscription))))

        deleted = batch_subscriptions(
            SubscriptionBatchRequest(ids=[rows[1].id], action="delete"), self.db
        )
        self.assertEqual(deleted["affected"], 1)
        self.assertIsNone(self.db.get(Subscription, rows[1].id))


    def test_auto_skip_blocks_enabling_subscription_without_rename(self) -> None:
        subscription = Subscription(
            name="No rename",
            rss_url="https://example.test/no-rename.xml",
            enabled=False,
            rename_enabled=False,
        )
        self.db.add(subscription)
        self.db.commit()
        save_application_preferences(
            self.db,
            theme_color="blue",
            subscription_sort="updated",
            retry_count=2,
            concurrent_limit=3,
            seeding_minutes=-1,
            cleanup_completed_enabled=False,
            cleanup_completed_delay_minutes=1,
            rss_enabled=True,
            rss_timeout_seconds=20,
            auto_skip_existing=True,
            auto_disable_complete=False,
            trackers_enabled=True,
            trackers_update_url="https://cf.trackerslist.com/best.txt",
        )
        with self.assertRaises(HTTPException) as raised:
            batch_subscriptions(
                SubscriptionBatchRequest(ids=[subscription.id], action="enable"), self.db
            )
        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("自动重命名", raised.exception.detail)
        self.assertFalse(self.db.get(Subscription, subscription.id).enabled)

    def test_system_actions_are_safe_by_default(self) -> None:
        status = system_status()
        self.assertFalse(status["actions_allowed"])
        self.assertIn("默认禁用", status["message"])

    def test_subscription_sort_preference_is_persisted_without_other_settings(self) -> None:
        saved = save_subscription_sort_preference(self.db, "weekday")
        self.assertEqual(saved.page.subscription_sort, "weekday")
        self.assertEqual(load_application_preferences(self.db).page.subscription_sort, "weekday")

        migrated = save_subscription_sort_preference(self.db, "pinyin")
        self.assertEqual(migrated.page.subscription_sort, "name")

    def test_subscription_sorting_module_supports_all_requested_modes(self) -> None:
        module_path = ROOT / "app/static/subscription-sorting.js"
        script = textwrap.dedent(
            f"""
            const assert = require('node:assert/strict');
            const sorting = require({str(module_path)!r});
            const rows = [
              {{ id: 1, name: '周日', air_date: '2026-07-26', updated_at: '2026-01-01', created_at: '2026-01-03', metadata_rating: 7 }},
              {{ id: 2, name: '周一', air_date: '2026-07-27', updated_at: '2026-01-03', created_at: '2026-01-01', metadata_rating: 8 }},
              {{ id: 3, name: '周三', air_date: '2026-07-29', updated_at: '2026-01-02', created_at: '2026-01-02', metadata_rating: 9 }},
            ];
            assert.deepEqual(sorting.sortSubscriptions(rows, 'weekday').map((row) => row.id), [2, 3, 1]);
            assert.deepEqual(sorting.sortSubscriptions(rows, 'updated').map((row) => row.id), [2, 3, 1]);
            assert.deepEqual(sorting.sortSubscriptions(rows, 'created').map((row) => row.id), [1, 3, 2]);
            assert.deepEqual(sorting.sortSubscriptions(rows, 'rating').map((row) => row.id), [3, 2, 1]);
            assert.equal(sorting.normalizeMode('pinyin'), 'name');
            assert.equal(sorting.weekdayIndex('2026-07-26'), 7);
            """
        )
        result = subprocess.run(
            ["node", "-e", script], cwd=ROOT, capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_navigation_module_and_index_structure(self) -> None:
        module_path = ROOT / "app/static/navigation.js"
        script = textwrap.dedent(
            f"""
            const assert = require('node:assert/strict');
            const navigation = require({str(module_path)!r});
            assert.equal(navigation.normalizeView('#downloads'), 'downloads');
            assert.equal(navigation.normalizeView('not-a-view'), 'subscriptions');
            assert.equal(navigation.VIEW_META['settings-system'][0], '系统管理');
            """
        )
        result = subprocess.run(
            ["node", "-e", script], cwd=ROOT, capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        index = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        document = _IndexStructureParser()
        document.feed(index)
        for label in ("添加", "下载", "刷新", "管理", "设置", "日志"):
            self.assertIn(label, index)
        for element_id in (
            "subscriptionBatchToolbar",
            "openCollectionImport",
            "openImportSubscriptions",
            "exportSubscriptions",
            "restartSystem",
            "shutdownSystem",
        ):
            self.assertIn(f'id="{element_id}"', index)
        self.assertLess(index.index('data-panel-id="subscriptions"'), index.index('data-panel-id="recent-items"'))
        self.assertEqual(len(document.ids), len(set(document.ids)))
        self.assertEqual(document.visible_views, {"subscriptions", "all"})
        self.assertIn("请先选择需要导出的订阅", (ROOT / "app/static/app.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

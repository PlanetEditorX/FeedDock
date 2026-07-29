from __future__ import annotations

import subprocess
import textwrap
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.anime_identity import hidden_for_item, title_key
from app.main import (
    _create_mikan_trials,
    batch_subscriptions,
    delete_subscription,
    export_subscriptions,
    import_subscriptions,
    list_hidden_anime_preferences,
    system_status,
    update_hidden_anime_preferences,
)
from app.settings_config import load_application_preferences, save_application_preferences, save_subscription_sort_preference
from fastapi import HTTPException
from app.models import AnimePreference, Subscription
from app.schemas import (
    AnimePreferenceBatchUpdate,
    AnimePreferenceItem,
    SubscriptionBatchRequest,
    SubscriptionCreate,
    SubscriptionImportRequest,
)


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
        self.assertEqual(deleted["hidden"], 1)
        self.assertIsNone(self.db.get(Subscription, rows[1].id))
        self.assertEqual(len(list(self.db.scalars(select(AnimePreference)))), 1)

    def test_deleted_subscription_stays_hidden_until_manually_restored(self) -> None:
        subscription = Subscription(
            name="示例动画",
            reference_title="示例动画",
            canonical_key=title_key("示例动画"),
            rss_url="https://example.test/example.xml",
        )
        self.db.add(subscription)
        self.db.commit()

        result = delete_subscription(subscription.id, self.db)
        self.assertEqual(result, {"ok": True, "hidden": True})
        preferences = list(self.db.scalars(select(AnimePreference)))
        self.assertEqual(len(preferences), 1)
        self.assertTrue(hidden_for_item({"title": "示例动画"}, preferences))

        listed = list_hidden_anime_preferences(self.db)
        self.assertEqual(listed["count"], 1)
        self.assertEqual(listed["items"][0]["title"], "示例动画")
        self.assertEqual(listed["items"][0]["reason"], "subscription_deleted")

        restored = update_hidden_anime_preferences(
            AnimePreferenceBatchUpdate(items=[AnimePreferenceItem(
                canonical_key=title_key("示例动画"),
                title="示例动画",
                hidden=False,
            )]),
            self.db,
        )
        self.assertEqual(restored, {"updated": 1, "hidden": 0})
        self.assertEqual(list(self.db.scalars(select(AnimePreference))), [])

    def test_trial_subscription_mode_is_persisted(self) -> None:
        subscription = Subscription(
            name="试看动画",
            rss_url="https://example.test/trial.xml",
            subscription_mode="trial",
        )
        self.db.add(subscription)
        self.db.commit()
        self.assertEqual(self.db.get(Subscription, subscription.id).subscription_mode, "trial")


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
            assert.equal(sorting.weekdayLabel(1), '星期一');
            assert.equal(sorting.weekdayLabel(99), '未设置星期');
            const groups = sorting.groupSubscriptionsByWeekday([
              ...rows,
              {{ id: 4, name: '另一个周一', air_date: '2026-08-03' }},
              {{ id: 5, name: '日期未知', air_date: null }},
            ]);
            assert.deepEqual(groups.map((group) => [group.label, group.subscriptions.length]), [
              ['星期一', 2], ['星期三', 1], ['星期日', 1], ['未设置星期', 1],
            ]);
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
            assert.equal(navigation.VIEW_META['settings-hidden'][0], '隐藏番剧');
            assert.equal(navigation.VIEW_META.subscriptions[0], '订阅列表');
            const summaries = [{{ attrs: {{}} }}, {{ attrs: {{}} }}];
            const menus = summaries.map((summary) => ({{
              open: false,
              attrs: new Set(),
              querySelector: () => ({{ setAttribute: (key, value) => {{ summary.attrs[key] = value; }} }}),
              hasAttribute(key) {{ return key === 'open' && this.attrs.has('open'); }},
              removeAttribute(key) {{ this.attrs.delete(key); if (key === 'open') this.open = false; }},
            }}));
            const doc = {{ querySelectorAll: () => menus }};
            menus[0].open = true; menus[0].attrs.add('open');
            navigation.handleMenuToggle(menus[0], doc);
            menus[1].open = true; menus[1].attrs.add('open');
            navigation.handleMenuToggle(menus[1], doc);
            assert.equal(menus[0].open, false);
            assert.equal(menus[1].open, true);
            assert.equal(summaries[0].attrs['aria-expanded'], 'false');
            assert.equal(summaries[1].attrs['aria-expanded'], 'true');
            """
        )
        result = subprocess.run(
            ["node", "-e", script], cwd=ROOT, capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        index = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
        document = _IndexStructureParser()
        document.feed(index)
        for label in ("添加", "下载", "刷新", "管理", "设置", "日志", "订阅列表"):
            self.assertIn(label, index)
        for element_id in (
            "subscriptionBatchToolbar",
            "openCollectionImport",
            "openImportSubscriptions",
            "exportSubscriptions",
            "restartSystem",
            "shutdownSystem",
            "hiddenAnimeState",
            "hiddenAnimeList",
            "refreshHiddenAnime",
        ):
            self.assertIn(f'id="{element_id}"', index)
        self.assertLess(index.index('data-panel-id="subscriptions"'), index.index('data-panel-id="recent-items"'))
        self.assertEqual(len(document.ids), len(set(document.ids)))
        self.assertEqual(document.visible_views, {"subscriptions", "all"})
        app_js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
        self.assertIn("请先选择需要导出的订阅", app_js)
        self.assertIn("groupSubscriptionsByWeekday", app_js)
        self.assertIn("subscription-weekday-section", app_js)
        self.assertIn("loadHiddenAnimePreferences", app_js)
        self.assertIn("取消隐藏", app_js)
        self.assertIn('data-view-target="settings-hidden"', index)
        self.assertIn('id="createMikanTrials"', index)
        self.assertIn('id="mikanPreorderToggle"', index)
        self.assertIn('name="primary-navigation"', index)
        styles = (ROOT / "app/static/styles.css").read_text(encoding="utf-8")
        self.assertEqual(index.count('class="nav-chevron"'), 4)
        self.assertIn('.nav-menu[open] > summary .nav-chevron', styles)
        self.assertNotIn('.nav-menu > summary::after', styles)
        self.assertIn("writing-mode: horizontal-tb", styles)

    def test_mikan_trials_create_a_trial_subscription(self) -> None:
        payload = {
            "rows": [{
                "weekday": "星期一",
                "items": [{
                    "bangumi_id": 100,
                    "title": "试看动画",
                    "base_url": "https://mikan.test",
                }],
            }],
        }
        detail = {
            "groups": [{"preset": {
                "name": "试看动画",
                "source_type": "mikan",
                "source_anime_id": "100",
                "primary_rss_name": "Mikan · 测试组",
                "rss_url": "https://mikan.test/RSS/Bangumi?bangumiId=100&subgroupid=1",
            }}],
        }
        with patch("app.main.MikanCacheService") as cache_service:
            cache_service.return_value.detail.return_value = detail
            created = _create_mikan_trials(self.db, year=2026, season="夏", payload=payload)

        self.assertEqual(len(created), 1)
        subscription = self.db.get(Subscription, created[0].id)
        self.assertIsNotNone(subscription)
        self.assertEqual(subscription.subscription_mode, "trial")
        self.assertTrue(subscription.trial_bulk)
        self.assertEqual(subscription.save_path_template, "{base}/试看")
        self.assertEqual(subscription.source_type, "mikan")


if __name__ == "__main__":
    unittest.main()

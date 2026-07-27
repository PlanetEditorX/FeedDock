from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models import FeedItem, Subscription
from app.subscription_monitor import (
    calculate_missing_episodes,
    evaluate_missing_episodes,
    evaluate_stale_subscription,
    evaluate_subscription_completion,
    record_new_feed_activity,
    reset_monitor_state_for_changes,
)


class SubscriptionMonitorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def subscription(self, **overrides) -> Subscription:
        values = {
            "name": "Demo",
            "rss_url": "https://example.test/feed.xml",
            "total_episodes": 3,
            "missing_detection": True,
            "enabled": True,
        }
        values.update(overrides)
        value = Subscription(**values)
        self.db.add(value)
        self.db.flush()
        return value

    def item(self, subscription: Subscription, episode: str, *, completed: bool = False, status: str = "queued") -> FeedItem:
        value = FeedItem(
            subscription_id=subscription.id,
            fingerprint=f"fp-{subscription.id}-{episode}-{status}",
            title=f"Demo {episode}",
            episode=episode,
            status=status,
            completed_at=datetime.now(timezone.utc) if completed else None,
        )
        self.db.add(value)
        self.db.flush()
        return value

    def test_missing_detection_counts_queued_and_scheduled_and_deduplicates_notice(self):
        sub = self.subscription()
        self.item(sub, "1", status="queued")
        self.item(sub, "2", status="scheduled")
        self.assertEqual(calculate_missing_episodes(self.db, sub), [3])
        with patch("app.subscription_monitor.send_notification") as notify:
            evaluate_missing_episodes(self.db, sub)
            evaluate_missing_episodes(self.db, sub)
        notify.assert_called_once()
        self.assertEqual(sub.last_missing_signature, "3")

    def test_large_missing_range_is_recorded_without_noisy_notice(self):
        sub = self.subscription(total_episodes=24)
        with patch("app.subscription_monitor.send_notification") as notify:
            missing = evaluate_missing_episodes(self.db, sub)
        self.assertEqual(len(missing), 24)
        self.assertEqual(sub.last_missing_signature, ",".join(str(value) for value in range(1, 25)))
        notify.assert_not_called()

    def test_completion_auto_disables_only_after_every_episode_completed(self):
        sub = self.subscription(auto_disable_when_complete=True, total_episodes=2)
        self.item(sub, "1", completed=True)
        self.item(sub, "2", completed=False)
        with patch("app.subscription_monitor.send_notification") as notify:
            self.assertFalse(evaluate_subscription_completion(self.db, sub))
            self.item(sub, "2", completed=True, status="scheduled")
            self.assertTrue(evaluate_subscription_completion(self.db, sub))
            self.assertFalse(sub.enabled)
            self.assertIsNotNone(sub.completion_notified_at)
            self.assertTrue(evaluate_subscription_completion(self.db, sub))
        notify.assert_called_once()

    def test_stale_notice_is_deduplicated_and_new_activity_resets_it(self):
        now = datetime(2026, 7, 27, tzinfo=timezone.utc)
        sub = self.subscription(
            stale_days=7,
            created_at=now - timedelta(days=10),
        )
        with patch("app.subscription_monitor.send_notification") as notify:
            self.assertTrue(evaluate_stale_subscription(self.db, sub, now=now))
            self.assertFalse(evaluate_stale_subscription(self.db, sub, now=now + timedelta(hours=1)))
            record_new_feed_activity(sub, now=now + timedelta(hours=2))
            self.assertFalse(evaluate_stale_subscription(self.db, sub, now=now + timedelta(days=6)))
            self.assertTrue(evaluate_stale_subscription(self.db, sub, now=now + timedelta(days=8)))
        self.assertEqual(notify.call_count, 2)

    def test_fractional_episode_does_not_satisfy_whole_episode_completion(self):
        sub = self.subscription(auto_disable_when_complete=True, total_episodes=1)
        self.item(sub, "0.5", completed=True)
        self.assertFalse(evaluate_subscription_completion(self.db, sub))
        self.assertTrue(sub.enabled)

    def test_editing_monitor_inputs_resets_only_relevant_dedup_state(self):
        now = datetime(2026, 7, 27, tzinfo=timezone.utc)
        sub = self.subscription(
            total_episodes=12,
            auto_disable_when_complete=False,
            stale_days=7,
            completion_notified_at=now,
            last_stale_notified_at=now,
            last_missing_signature="2,3",
        )
        reset_monitor_state_for_changes(
            sub,
            {
                "total_episodes": 13,
                "auto_disable_when_complete": True,
                "stale_days": 14,
            },
        )
        self.assertIsNone(sub.completion_notified_at)
        self.assertIsNone(sub.last_stale_notified_at)
        self.assertEqual(sub.last_missing_signature, "")

        sub.last_missing_signature = "4"
        reset_monitor_state_for_changes(sub, {"name": "Renamed"})
        self.assertEqual(sub.last_missing_signature, "4")



if __name__ == "__main__":
    unittest.main()

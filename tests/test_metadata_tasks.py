from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.metadata_tasks import refresh_all_metadata
from app.models import Subscription, SystemLog


class MetadataRefreshTaskTests(unittest.TestCase):
    def test_refresh_all_metadata_logs_success_and_failure(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, expire_on_commit=False)
        with Session() as db:
            db.add_all(
                [
                    Subscription(name="Success", rss_url="https://example.test/1", bangumi_id=1),
                    Subscription(name="Failure", rss_url="https://example.test/2", bangumi_id=2),
                ]
            )
            db.commit()

        class FakeMetadataService:
            def __init__(self, **_kwargs) -> None:
                pass

            def sync(self, _db, subscription, _provider):
                if subscription.name == "Failure":
                    raise ValueError("metadata unavailable")
                return SimpleNamespace(provider="bangumi", id=subscription.bangumi_id, total_episodes=12)

        with (
            patch("app.metadata_tasks.SessionLocal", Session),
            patch("app.metadata_tasks.MetadataService", FakeMetadataService),
            patch(
                "app.metadata_tasks.load_application_preferences",
                return_value=SimpleNamespace(rss=SimpleNamespace(timeout_seconds=20)),
            ),
        ):
            result = refresh_all_metadata()

        self.assertFalse(result["ok"])
        self.assertEqual(result["subscriptions"], 2)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["errors"], 1)
        with Session() as db:
            messages = list(db.scalars(select(SystemLog.message).order_by(SystemLog.id)))
        self.assertIn("开始同步订阅元数据", messages)
        self.assertTrue(any(message.startswith("订阅元数据已同步") for message in messages))
        self.assertTrue(any(message.startswith("订阅元数据同步失败") for message in messages))
        self.assertIn("同步订阅元数据完成", messages)


if __name__ == "__main__":
    unittest.main()

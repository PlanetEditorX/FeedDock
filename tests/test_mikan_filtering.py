from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.main import _apply_mikan_hidden_filters
from app.runtime_config import (
    load_mikan_hidden_filters,
    save_mikan_weekday_hidden_filter,
)


class MikanWeekdayFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_weekdays_are_saved_independently_and_can_be_restored(self) -> None:
        with self.Session() as db:
            save_mikan_weekday_hidden_filter(
                db,
                year=2026,
                season="夏",
                weekday="星期一",
                hidden_bangumi_ids=[100, 101, 101],
            )
            save_mikan_weekday_hidden_filter(
                db,
                year=2026,
                season="夏",
                weekday="星期二",
                hidden_bangumi_ids=[200],
            )
            filters = load_mikan_hidden_filters(db, year=2026, season="夏")
            self.assertEqual(filters["星期一"], {100, 101})
            self.assertEqual(filters["星期二"], {200})

            save_mikan_weekday_hidden_filter(
                db,
                year=2026,
                season="夏",
                weekday="星期一",
                hidden_bangumi_ids=[],
            )
            filters = load_mikan_hidden_filters(db, year=2026, season="夏")
            self.assertNotIn("星期一", filters)
            self.assertEqual(filters["星期二"], {200})

    def test_catalog_items_are_annotated_without_removing_hidden_rows(self) -> None:
        payload = {
            "year": 2026,
            "season": "夏",
            "rows": [
                {
                    "weekday": "星期一",
                    "items": [
                        {"bangumi_id": 100, "title": "A"},
                        {"bangumi_id": 101, "title": "B"},
                    ],
                },
                {
                    "weekday": "星期二",
                    "items": [{"bangumi_id": 200, "title": "C"}],
                },
            ],
        }
        with self.Session() as db:
            save_mikan_weekday_hidden_filter(
                db,
                year=2026,
                season="夏",
                weekday="星期一",
                hidden_bangumi_ids=[101],
            )
            decorated = _apply_mikan_hidden_filters(
                payload,
                db,
                year=2026,
                season="夏",
            )

        self.assertEqual(len(decorated["rows"]), 2)
        self.assertFalse(decorated["rows"][0]["items"][0]["hidden"])
        self.assertTrue(decorated["rows"][0]["items"][1]["hidden"])
        self.assertEqual(decorated["rows"][0]["hidden_count"], 1)
        self.assertEqual(decorated["hidden_count"], 1)


if __name__ == "__main__":
    unittest.main()

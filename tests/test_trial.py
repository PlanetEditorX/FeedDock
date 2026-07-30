import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.main import _subscription_values
from app.schemas import SubscriptionCreate
from app.trial import (
    BULK_TRIAL_SAVE_PATH_TEMPLATE,
    SINGLE_TRIAL_SAVE_PATH_TEMPLATE,
    select_trial_preset,
)


class TrialPolicyTests(unittest.TestCase):
    def test_trial_group_preference_is_ani_then_lolihouse_then_first(self) -> None:
        groups = [
            {"name": "Other", "preset": {"rss_url": "https://example.test/other"}},
            {"name": "LoliHouse", "preset": {"rss_url": "https://example.test/loli"}},
            {"name": "ANi", "preset": {"rss_url": "https://example.test/ani"}},
        ]
        self.assertEqual(select_trial_preset(groups)["rss_url"], "https://example.test/ani")

        self.assertEqual(
            select_trial_preset(groups[:2])["rss_url"],
            "https://example.test/loli",
        )
        self.assertEqual(select_trial_preset(groups[:1])["rss_url"], "https://example.test/other")

    def test_trial_paths_distinguish_bulk_and_single_trials(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            single = _subscription_values(
                SubscriptionCreate(
                    name="Single trial",
                    rss_url="https://example.test/single.xml",
                    subscription_mode="trial",
                ),
                db,
            )
            bulk = _subscription_values(
                SubscriptionCreate(
                    name="Bulk trial",
                    rss_url="https://example.test/bulk.xml",
                    subscription_mode="trial",
                    trial_bulk=True,
                ),
                db,
            )

        self.assertEqual(single["save_path_template"], SINGLE_TRIAL_SAVE_PATH_TEMPLATE)
        self.assertEqual(bulk["save_path_template"], BULK_TRIAL_SAVE_PATH_TEMPLATE)
        self.assertFalse(single["enabled"])
        self.assertFalse(bulk["enabled"])


if __name__ == "__main__":
    unittest.main()

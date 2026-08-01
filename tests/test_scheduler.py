from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.scheduler import PollScheduler


class TestRunDailyAutomation(unittest.TestCase):
    def setUp(self):
        # Mocks setup
        self.mock_session_local_patcher = patch("app.scheduler.SessionLocal")
        self.mock_session_local = self.mock_session_local_patcher.start()

        self.mock_db = MagicMock()
        # Ensure context manager behavior
        self.mock_session_local.return_value.__enter__.return_value = self.mock_db

        self.mock_load_automation_config_patcher = patch(
            "app.scheduler.load_automation_config"
        )
        self.mock_load_automation_config = self.mock_load_automation_config_patcher.start()

        self.mock_datetime_patcher = patch("app.scheduler.datetime")
        self.mock_datetime = self.mock_datetime_patcher.start()

        self.mock_dispatch_downloads_patcher = patch(
            "app.scheduler.dispatch_scheduled_downloads"
        )
        self.mock_dispatch_downloads = self.mock_dispatch_downloads_patcher.start()

        self.mock_normalize_patcher = patch("app.scheduler.normalize_pending_items")
        self.mock_normalize = self.mock_normalize_patcher.start()

        self.mock_mark_run_patcher = patch("app.scheduler.mark_automation_run")
        self.mock_mark_run = self.mock_mark_run_patcher.start()

        # Default Config behavior
        self.mock_config = MagicMock()
        self.mock_config.timezone = "Asia/Shanghai"
        self.mock_config.enabled = True
        self.mock_config.daily_time = "10:00"
        self.mock_config.last_run_date = "2023-01-01"
        self.mock_config.download_enabled = True
        self.mock_load_automation_config.return_value = self.mock_config

        # Default Datetime behavior
        mock_now = datetime(2023, 10, 1, 12, 0)
        self.mock_datetime.now.return_value = mock_now

        # Set specific returns for downloads and normalize to ensure they get passed through to result
        self.mock_dispatch_downloads.return_value = 5
        self.mock_normalize.return_value = {"updated": 10}

    def tearDown(self):
        self.mock_session_local_patcher.stop()
        self.mock_load_automation_config_patcher.stop()
        self.mock_datetime_patcher.stop()
        self.mock_dispatch_downloads_patcher.stop()
        self.mock_normalize_patcher.stop()
        self.mock_mark_run_patcher.stop()

    def test_force_run_with_download_enabled(self):
        # Force run should bypass time/enabled checks
        self.mock_config.enabled = False

        result = PollScheduler.run_daily_automation(force=True)

        self.assertEqual(result["ok"], True)
        self.assertEqual(result["ran"], True)
        self.assertEqual(result["date"], "2023-10-01")
        self.assertEqual(result["downloads"], 5)
        self.assertEqual(result["completion"], {"updated": 10})

        self.mock_dispatch_downloads.assert_called_once_with(self.mock_db, limit=1000)
        self.mock_normalize.assert_called_once_with(self.mock_db, limit=500)
        self.mock_mark_run.assert_called_once_with(self.mock_db, "2023-10-01")
        self.mock_datetime.now.assert_called_once_with(ZoneInfo("Asia/Shanghai"))

    def test_force_run_with_download_disabled(self):
        self.mock_config.download_enabled = False

        result = PollScheduler.run_daily_automation(force=True)

        self.assertEqual(result["ran"], True)
        self.assertNotIn("downloads", result)
        self.assertEqual(result["completion"], {"updated": 10})

        self.mock_dispatch_downloads.assert_not_called()
        self.mock_normalize.assert_called_once_with(self.mock_db, limit=500)
        self.mock_mark_run.assert_called_once_with(self.mock_db, "2023-10-01")

    def test_not_forced_config_disabled(self):
        self.mock_config.enabled = False

        result = PollScheduler.run_daily_automation(force=False)

        self.assertEqual(result["ran"], False)
        self.assertEqual(result["message"], "尚未到统一执行时间或今日已执行")

        self.mock_dispatch_downloads.assert_not_called()
        self.mock_normalize.assert_not_called()
        self.mock_mark_run.assert_not_called()

    def test_not_forced_time_not_reached(self):
        self.mock_config.enabled = True
        self.mock_config.daily_time = "13:00"  # Not reached since now is 12:00

        result = PollScheduler.run_daily_automation(force=False)

        self.assertEqual(result["ran"], False)
        self.mock_dispatch_downloads.assert_not_called()

    def test_not_forced_already_run_today(self):
        self.mock_config.enabled = True
        self.mock_config.daily_time = "10:00"  # Time is reached
        self.mock_config.last_run_date = "2023-10-01"  # Already run today

        result = PollScheduler.run_daily_automation(force=False)

        self.assertEqual(result["ran"], False)
        self.mock_dispatch_downloads.assert_not_called()

    def test_not_forced_valid_run_condition(self):
        self.mock_config.enabled = True
        self.mock_config.daily_time = "10:00"  # Time is reached
        self.mock_config.last_run_date = "2023-09-30"  # Not run today

        result = PollScheduler.run_daily_automation(force=False)

        self.assertEqual(result["ran"], True)
        self.assertEqual(result["downloads"], 5)
        self.assertEqual(result["completion"], {"updated": 10})

        self.mock_dispatch_downloads.assert_called_once_with(self.mock_db, limit=1000)
        self.mock_normalize.assert_called_once_with(self.mock_db, limit=500)
        self.mock_mark_run.assert_called_once_with(self.mock_db, "2023-10-01")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ConfigModuleLayoutTests(unittest.TestCase):
    """Prevent application settings and notification settings from being mixed."""

    def test_application_config_keeps_build_metadata_loader(self) -> None:
        source = (ROOT / "app/config.py").read_text(encoding="utf-8")
        self.assertIn("from .build_info import load_build_info", source)
        self.assertIn("def load_settings()", source)
        self.assertNotIn("Persistent notification settings", source)
        self.assertNotIn("from ..models import AppSetting", source)

    def test_notification_config_stays_in_notification_package(self) -> None:
        source = (ROOT / "app/notification/config.py").read_text(encoding="utf-8")
        self.assertIn("Persistent notification settings", source)
        self.assertIn("from ..models import AppSetting", source)
        self.assertIn("def load_notification_config", source)
        self.assertNotIn("from .build_info import load_build_info", source)


if __name__ == "__main__":
    unittest.main()

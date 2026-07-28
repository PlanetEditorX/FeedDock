from __future__ import annotations

import importlib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ConfigModuleLayoutTests(unittest.TestCase):
    """Prevent root application modules from being replaced by notification files."""

    def test_application_package_init_stays_minimal(self) -> None:
        source = (ROOT / "app/__init__.py").read_text(encoding="utf-8")
        self.assertIn("FeedDock application package", source)
        self.assertNotIn("from .channels", source)
        self.assertNotIn("normalize_bark_push_url", source)

        module = importlib.import_module("app")
        self.assertFalse(hasattr(module, "normalize_bark_push_url"))

    def test_notification_package_init_exports_notification_api(self) -> None:
        source = (ROOT / "app/notification/__init__.py").read_text(encoding="utf-8")
        self.assertIn("from .channels import normalize_bark_push_url", source)
        self.assertIn("from .config import", source)

    def test_application_config_keeps_build_metadata_loader(self) -> None:
        source = (ROOT / "app/config.py").read_text(encoding="utf-8")
        self.assertIn("from .build_info import load_build_info", source)
        self.assertIn("def load_settings()", source)
        self.assertIn('_optional_path("MEDIA_LOCAL_ROOT", "/media")', source)
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

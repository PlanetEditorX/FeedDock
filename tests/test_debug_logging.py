import unittest

from app.debug_logging import format_exception_details, normalize_log_level, safe_json


class DebugLoggingTests(unittest.TestCase):
    def test_log_level_is_limited_to_info_or_debug(self):
        self.assertEqual(normalize_log_level("debug"), "DEBUG")
        self.assertEqual(normalize_log_level("INFO"), "INFO")
        self.assertEqual(normalize_log_level("trace"), "INFO")

    def test_exception_details_include_traceback_and_redact_secrets(self):
        try:
            raise RuntimeError("subscription-save-failed")
        except RuntimeError as exc:
            details = format_exception_details(
                exc,
                request_id="abc123",
                method="POST",
                path="/api/subscriptions",
                stage="subscription.commit",
                context={"api_token": "secret-token", "name": "test"},
            )
        self.assertIn("abc123", details)
        self.assertIn("subscription.commit", details)
        self.assertIn("RuntimeError", details)
        self.assertIn("subscription-save-failed", details)
        self.assertIn("Traceback:", details)
        self.assertNotIn("secret-token", details)
        self.assertIn('"api_token": "***"', details)

    def test_proxy_credentials_are_redacted(self):
        rendered = safe_json({"proxy_url": "http://user:password@example.test:7890"})
        self.assertNotIn("user:password", rendered)
        self.assertIn("***:***@", rendered)


if __name__ == "__main__":
    unittest.main()

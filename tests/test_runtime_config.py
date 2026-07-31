from __future__ import annotations

import unittest

from app.runtime_config import _validate_proxy_url


class TestValidateProxyUrl(unittest.TestCase):
    def test_valid_proxy_urls(self):
        valid_urls = [
            "http://proxy.example.com:8080",
            "https://proxy.example.com",
            "socks5://127.0.0.1:1080",
            "socks5h://localhost:1080",
            "http://user:pass@proxy.com:8080",
            "  http://proxy.com  ",  # Leading/trailing whitespace
        ]
        for url in valid_urls:
            with self.subTest(url=url):
                self.assertEqual(_validate_proxy_url(url), url.strip())

    def test_empty_proxy_urls(self):
        empty_urls = ["", "   ", "\t", "\n"]
        for url in empty_urls:
            with self.subTest(url=url):
                self.assertEqual(_validate_proxy_url(url), "")

    def test_invalid_schemes(self):
        invalid_urls = [
            "ftp://proxy.com",
            "tcp://127.0.0.1:80",
            "proxy.example.com:8080",
            "http",
            "https://",
            "://proxy.com",
        ]
        for url in invalid_urls:
            with self.subTest(url=url):
                with self.assertRaisesRegex(ValueError, "代理地址必须是"):
                    _validate_proxy_url(url)

    def test_missing_hostname(self):
        invalid_urls = [
            "http://",
            "socks5://:1080",
        ]
        for url in invalid_urls:
            with self.subTest(url=url):
                with self.assertRaisesRegex(ValueError, "代理地址必须是"):
                    _validate_proxy_url(url)

    def test_too_long_proxy_url(self):
        long_url = "http://" + "a" * 2000 + ".com"
        with self.assertRaisesRegex(ValueError, "代理地址过长"):
            _validate_proxy_url(long_url)

    def test_just_under_limit_proxy_url(self):
        long_url = "http://" + "a" * 1980 + ".com"
        # Length is around 1991, < 2000
        self.assertEqual(_validate_proxy_url(long_url), long_url)

if __name__ == "__main__":
    unittest.main()

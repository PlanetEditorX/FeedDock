from __future__ import annotations

import unittest

from app.runtime_config import _valid_daily_time, _validate_proxy_url


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

class TestValidDailyTime(unittest.TestCase):
    def test_valid_times(self):
        valid_times = [
            ("00:00", "00:00"),
            ("23:59", "23:59"),
            ("12:34", "12:34"),
            ("05:06", "05:06"),
            ("5:6", "05:06"),
            ("  12:34  ", "12:34"),
        ]
        for time_str, expected in valid_times:
            with self.subTest(time_str=time_str):
                self.assertEqual(_valid_daily_time(time_str), expected)

    def test_invalid_format(self):
        invalid_formats = [
            "1234",
            "12:34:56",
            "12:aa",
            "aa:bb",
            "",
            "  ",
        ]
        for time_str in invalid_formats:
            with self.subTest(time_str=time_str):
                with self.assertRaisesRegex(ValueError, "执行时间必须是 HH:MM 格式"):
                    _valid_daily_time(time_str)

    def test_out_of_bounds(self):
        out_of_bounds = [
            "24:00",
            "25:00",
            "12:60",
            "12:99",
            "-1:00",
            "12:-1",
        ]
        for time_str in out_of_bounds:
            with self.subTest(time_str=time_str):
                # Using ValueError but _valid_daily_time relies on checking if numbers are digits first,
                # so negative values will trigger the format error because '-' is not a digit.
                # However, for out of bounds like 24:00, it will raise "执行时间必须在 00:00 到 23:59 之间"
                if "-" in time_str:
                    with self.assertRaisesRegex(ValueError, "执行时间必须是 HH:MM 格式"):
                        _valid_daily_time(time_str)
                else:
                    with self.assertRaisesRegex(ValueError, "执行时间必须在 00:00 到 23:59 之间"):
                        _valid_daily_time(time_str)

if __name__ == "__main__":
    unittest.main()

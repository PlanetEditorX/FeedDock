import pytest

from app.outbound import _host_matches_rule, should_bypass_proxy
from app.runtime_config import ProxyConfig


@pytest.mark.parametrize(
    "host, rule, expected",
    [
        # Empty inputs
        ("", "", False),
        (None, None, False),
        ("example.com", "", False),
        ("", "example.com", False),
        (None, "example.com", False),
        ("example.com", None, False),
        # Exact match
        ("example.com", "example.com", True),
        ("example.com", "EXAMPLE.COM", True),
        ("EXAMPLE.COM", "example.com", True),
        ("sub.example.com", "example.com", True),
        ("example.com", "sub.example.com", False),
        ("notexample.com", "example.com", False),
        # Leading dot rule
        ("example.com", ".example.com", True),
        ("sub.example.com", ".example.com", True),
        ("notexample.com", ".example.com", False),
        # Wildcard rule
        ("example.com", "*", True),
        ("anything", "*", True),
        ("", "*", False),
        # IPv4 CIDR matching
        ("192.168.1.5", "192.168.1.0/24", True),
        ("192.168.2.5", "192.168.1.0/24", False),
        ("10.0.0.1", "10.0.0.0/8", True),
        ("127.0.0.1", "127.0.0.0/8", True),
        # IPv6 CIDR matching
        ("2001:db8::1", "2001:db8::/32", True),
        ("2001:db9::1", "2001:db8::/32", False),
        # Invalid CIDR / IPs
        ("192.168.1.5", "invalid/24", False),
        ("invalid", "192.168.1.0/24", False),
        # IPv6 Bracket stripping
        ("[2001:db8::1]", "2001:db8::/32", True),
        ("[2001:db8::1]", "2001:db8::1", True),
        # Strip spaces from rule
        ("example.com", " example.com ", True),
        ("example.com", " .example.com ", True),
    ],
)
def test_host_matches_rule(host, rule, expected):
    assert _host_matches_rule(host, rule) is expected


@pytest.mark.parametrize(
    "url, no_proxy, expected",
    [
        ("http://example.com/path", "example.com", True),
        ("https://sub.example.com/path", "example.com", True),
        ("http://notexample.com", "example.com", False),
        ("http://example.com", "other.com,example.com", True),
        ("http://example.com", "other.com, example.com ", True),
        ("http://example.com", "*", True),
        ("http://192.168.1.5", "192.168.1.0/24", True),
        ("http://192.168.2.5", "192.168.1.0/24", False),
        ("http://192.168.1.5", "10.0.0.0/8, 192.168.1.0/24", True),
        ("http://[2001:db8::1]/path", "2001:db8::/32", True),
        ("http://[2001:db8::1]/path", "2001:db8::1", True),
        ("http://example.com", "", False),
        ("", "example.com", False),
    ],
)
def test_should_bypass_proxy(url, no_proxy, expected):
    config = ProxyConfig(
        enabled=True,
        url="http://proxy.example.com",
        no_proxy=no_proxy,
        source="test",
    )
    assert should_bypass_proxy(url, config) is expected

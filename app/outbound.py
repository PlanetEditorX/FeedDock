from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from .config import settings
from .runtime_config import ProxyConfig, load_proxy_config


def _host_matches_rule(host: str, rule: str) -> bool:
    host = (host or "").strip("[]").casefold()
    rule = (rule or "").strip().casefold()
    if not host or not rule:
        return False
    if rule == "*":
        return True
    if rule.startswith("."):
        return host == rule[1:] or host.endswith(rule)
    if "/" in rule:
        try:
            return ipaddress.ip_address(host) in ipaddress.ip_network(rule, strict=False)
        except ValueError:
            return False
    return host == rule or host.endswith("." + rule)


def should_bypass_proxy(url: str, config: ProxyConfig) -> bool:
    host = urlparse(url).hostname or ""
    return any(_host_matches_rule(host, part) for part in config.no_proxy.split(","))


def external_client(
    target_url: str,
    *,
    db: Session | None = None,
    timeout: int | float | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Client:
    config = load_proxy_config(db if db is not None and hasattr(db, "scalars") else None)
    proxy = None
    if config.configured and not should_bypass_proxy(target_url, config):
        proxy = config.url
    return httpx.Client(
        timeout=timeout or settings.request_timeout_seconds,
        follow_redirects=True,
        headers=headers,
        proxy=proxy,
        trust_env=False,
    )


def external_get(
    url: str,
    *,
    db: Session | None = None,
    timeout: int | float | None = None,
    headers: dict[str, str] | None = None,
    **kwargs,
) -> httpx.Response:
    with external_client(url, db=db, timeout=timeout, headers=headers) as client:
        return client.get(url, **kwargs)

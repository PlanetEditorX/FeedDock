"""Classify persisted subscription errors and attach actionable solutions.

The subscription card shows an ``异常`` badge whenever ``last_error`` is set,
but the raw text (``请求 … 失败：[SSL: CERTIFICATE_VERIFY_FAILED] …``) tells the
user neither what went wrong nor what to do next. This module maps a stored
error message onto a stable *kind* with a Chinese label, concrete advice and a
list of actions the frontend can run directly (re-select the RSS feed, retry
the check, test the feed, run network diagnostics, edit the subscription).

Both stored strings and live exceptions are accepted so callers can classify
either the persisted ``last_error`` or the exception that produced it.
"""

from __future__ import annotations

import re
from typing import Any

# Action ids consumed by the frontend retry dialog.
ACTION_RESELECT_RSS = "reselect-rss"
ACTION_RETRY = "retry"
ACTION_TEST_RSS = "test-rss"
ACTION_NETWORK_DIAGNOSTICS = "network-diagnostics"
ACTION_EDIT = "edit"

_ACTION_LABELS: dict[str, str] = {
    ACTION_RESELECT_RSS: "重新选择 RSS",
    ACTION_RETRY: "立即重试检查",
    ACTION_TEST_RSS: "测试主/备 RSS",
    ACTION_NETWORK_DIAGNOSTICS: "运行网络诊断",
    ACTION_EDIT: "编辑订阅",
}

# Ordered rules: the first matching pattern wins, so specific failures (SSL,
# DNS) are checked before the coarse HTTP-status bucket.
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ssl",
        re.compile(
            r"certificate verify failed|certificate has expired|CERTIFICATE_VERIFY_FAILED"
            r"|\[SSL|SSL handshake|SSLError|tlsv1 alert|UNSUPPORTED_PROTOCOL"
            r"|DH_KEY_TOO_SMALL|TLSV1_UNRECOGNIZED_NAME|wrong version number",
            re.IGNORECASE,
        ),
    ),
    (
        "dns",
        re.compile(
            r"Name or service not known|Temporary failure in name resolution"
            r"|getaddrinfo|NameResolutionError|nodename nor servname",
            re.IGNORECASE,
        ),
    ),
    (
        "unreachable",
        re.compile(r"Network is unreachable|Host is unreachable|Errno 101\]|Errno 99\]|Errno 113\]", re.IGNORECASE),
    ),
    ("refused", re.compile(r"Connection refused|Errno 111\]", re.IGNORECASE)),
    ("timeout", re.compile(r"timed out|Timeout|Errno 110\]|Errno 112\]", re.IGNORECASE)),
    (
        "http_401",
        re.compile(r"(Client error|Server error|HTTP)\s*'?401|Unauthorized", re.IGNORECASE),
    ),
    (
        "http_403",
        re.compile(r"(Client error|Server error|HTTP)\s*'?403|Forbidden", re.IGNORECASE),
    ),
    (
        "http_404",
        re.compile(r"(Client error|Server error|HTTP)\s*'?404|Not Found", re.IGNORECASE),
    ),
    (
        "http_429",
        re.compile(
            r"(Client error|Server error|HTTP)\s*'?429|Too Many Requests|Rate.?limit", re.IGNORECASE
        ),
    ),
    (
        "http_5xx",
        re.compile(
            r"(Client error|Server error|HTTP)\s*'?50[0-4]|Bad Gateway"
            r"|Service Unavailable|Gateway Timeout|Internal Server Error",
            re.IGNORECASE,
        ),
    ),
    (
        "no_entries",
        re.compile(r"没有条目|no entries|empty feed", re.IGNORECASE),
    ),
)

ERROR_KINDS: dict[str, dict[str, Any]] = {
    "ssl": {
        "label": "SSL/TLS 证书错误",
        "advice": (
            "站点 HTTPS 证书校验失败：可能是站点证书过期或证书链不完整，也可能是代理、"
            "安全软件拦截了 TLS 连接。可重新选择其它字幕组的 RSS；使用代理时请检查代理与证书设置。"
        ),
        "actions": [ACTION_RESELECT_RSS, ACTION_RETRY, ACTION_NETWORK_DIAGNOSTICS],
    },
    "dns": {
        "label": "DNS 解析失败",
        "advice": (
            "容器无法解析该域名。请运行网络诊断查看解析结果，检查 Docker DNS 配置，或稍后重试。"
        ),
        "actions": [ACTION_NETWORK_DIAGNOSTICS, ACTION_RETRY],
    },
    "unreachable": {
        "label": "网络不可达",
        "advice": (
            "网络不可达：容器无法访问目标（常见原因：容器无 IPv6 路由，或网关/路由器 DNS 返回了错误地址）。"
            "请检查 Docker 网络配置、代理设置，或运行网络诊断。"
        ),
        "actions": [ACTION_NETWORK_DIAGNOSTICS, ACTION_RETRY],
    },
    "refused": {
        "label": "连接被拒绝",
        "advice": (
            "连接被拒绝：目标站点拒绝了连接（常见原因：DNS 被代理/劫持返回错误 IP，或站点访问受限）。"
            "可重新选择其它字幕组的 RSS，或稍后重试。"
        ),
        "actions": [ACTION_RESELECT_RSS, ACTION_RETRY, ACTION_NETWORK_DIAGNOSTICS],
    },
    "timeout": {
        "label": "连接超时",
        "advice": "连接超时：目标站点响应超时，请检查外网链路或稍后重试。",
        "actions": [ACTION_RETRY, ACTION_NETWORK_DIAGNOSTICS],
    },
    "http_401": {
        "label": "RSS 需要登录（401）",
        "advice": "RSS 地址需要身份验证，可能已失效。请重新选择当前可用的 RSS。",
        "actions": [ACTION_RESELECT_RSS, ACTION_RETRY],
    },
    "http_403": {
        "label": "站点拒绝访问（403）",
        "advice": (
            "站点拒绝了请求，常见于订阅链接失效、passkey 过期或被站点风控。"
            "请重新选择当前可用的 RSS。"
        ),
        "actions": [ACTION_RESELECT_RSS, ACTION_RETRY],
    },
    "http_404": {
        "label": "RSS 地址失效（404）",
        "advice": "RSS 地址已不存在，字幕组可能更换了地址。请重新选择当前可用的 RSS。",
        "actions": [ACTION_RESELECT_RSS, ACTION_RETRY],
    },
    "http_429": {
        "label": "访问过于频繁（429）",
        "advice": "站点触发了访问频率限制，请稍后再试；频繁出现时可更换 RSS 或检查代理。",
        "actions": [ACTION_RETRY, ACTION_RESELECT_RSS],
    },
    "http_5xx": {
        "label": "站点服务器错误（5xx）",
        "advice": "目标站点服务器暂时异常，请稍后重试；持续失败可更换其它字幕组的 RSS。",
        "actions": [ACTION_RETRY, ACTION_RESELECT_RSS],
    },
    "no_entries": {
        "label": "RSS 无可用条目",
        "advice": (
            "RSS 可以访问，但当前没有可用条目（可能本季已完结或字幕组未更新）。"
            "请在订阅卡片点击“更新 RSS”重新搜索字幕组，或编辑订阅检查关键词与季度设置。"
        ),
        "actions": [ACTION_RESELECT_RSS, ACTION_EDIT],
    },
    "unknown": {
        "label": "RSS 检查失败",
        "advice": (
            "请先在订阅卡片点击“重试”重新检查；仍然失败时点击“更新 RSS”，"
            "按当前番剧信息重新搜索 Mikan、ANI.BT 与 Anime Garden。"
        ),
        "actions": [ACTION_RETRY, ACTION_RESELECT_RSS],
    },
}

UNKNOWN_KIND = "unknown"


def _error_text(error: str | BaseException | None) -> str:
    """Flatten an exception chain (or pass a string through) for matching."""

    if error is None:
        return ""
    if not isinstance(error, BaseException):
        return str(error)
    seen: set[int] = set()
    stack: list[BaseException] = [error]
    parts: list[str] = []
    while stack:
        item = stack.pop()
        if id(item) in seen:
            continue
        seen.add(id(item))
        parts.append(str(item))
        cause = getattr(item, "__cause__", None)
        if isinstance(cause, BaseException):
            stack.append(cause)
        context = getattr(item, "__context__", None)
        if isinstance(context, BaseException):
            stack.append(context)
        for arg in item.args:
            if isinstance(arg, BaseException):
                stack.append(arg)
    return " ".join(parts)


def classify_error(error: str | BaseException | None) -> str:
    """Return the error kind for a persisted message or a live exception."""

    text = _error_text(error)
    if not text.strip():
        return UNKNOWN_KIND
    for kind, pattern in _RULES:
        if pattern.search(text):
            return kind
    return UNKNOWN_KIND


def describe_error(error: str | BaseException | None) -> dict[str, Any]:
    """Return kind, label, advice and runnable actions for an error."""

    kind = classify_error(error)
    spec = ERROR_KINDS[kind]
    return {
        "kind": kind,
        "label": spec["label"],
        "advice": spec["advice"],
        "actions": [
            {"id": action, "label": _ACTION_LABELS[action]}
            for action in spec["actions"]
        ],
    }


def error_advice(error: str | BaseException | None) -> str:
    """Convenience helper for log/notification advice text."""

    return str(describe_error(error)["advice"])

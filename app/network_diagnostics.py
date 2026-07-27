from __future__ import annotations

import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .config import settings


@dataclass(frozen=True, slots=True)
class NetworkTarget:
    label: str
    url: str

    @property
    def host(self) -> str:
        return urlparse(self.url).hostname or ""


NETWORK_TARGETS: tuple[NetworkTarget, ...] = (
    NetworkTarget("ANI.BT", "https://anibt.net"),
    NetworkTarget("Anime Garden", "https://api.animes.garden"),
    NetworkTarget("Bangumi", "https://api.bgm.tv"),
)


def configured_network_targets() -> tuple[NetworkTarget, ...]:
    """Return the external hosts required by discovery and metadata.

    Mikan mirrors are runtime-configurable, so diagnostics must use the same
    values as discovery instead of a stale hard-coded list.
    """

    targets: list[NetworkTarget] = []
    seen: set[str] = set()
    for index, url in enumerate((settings.mikan_base_url, *settings.mikan_fallback_urls)):
        target = NetworkTarget("Mikan" if index == 0 else f"Mikan 备用 {index}", url)
        if target.host and target.host not in seen:
            seen.add(target.host)
            targets.append(target)
    for target in NETWORK_TARGETS:
        if target.host and target.host not in seen:
            seen.add(target.host)
            targets.append(target)
    return tuple(targets)


def resolver_configuration(path: str | Path = "/etc/resolv.conf") -> dict[str, list[str]]:
    """Read only resolver fields that are useful for an administrator.

    Search domains are intentionally omitted because they may reveal private
    infrastructure names and are not needed to diagnose public host lookup.
    """

    nameservers: list[str] = []
    options: list[str] = []
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"nameservers": nameservers, "options": options}

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        key, _, value = line.partition(" ")
        value = value.strip()
        if key == "nameserver" and value:
            nameservers.append(value)
        elif key == "options" and value:
            options.extend(part for part in value.split() if part)
    return {"nameservers": nameservers, "options": options}


def resolve_host(host: str, port: int = 443) -> dict[str, object]:
    """Resolve one public host and return a JSON-safe diagnostic record."""

    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        return {
            "host": host,
            "ok": False,
            "addresses": [],
            "error_type": "dns",
            "message": str(exc),
        }
    except OSError as exc:
        return {
            "host": host,
            "ok": False,
            "addresses": [],
            "error_type": "resolver",
            "message": str(exc),
        }

    addresses: list[str] = []
    for _family, _socket_type, _protocol, _canonical_name, socket_address in records:
        address = str(socket_address[0])
        if address not in addresses:
            addresses.append(address)
    return {
        "host": host,
        "ok": bool(addresses),
        "addresses": addresses[:8],
        "error_type": "",
        "message": "解析成功" if addresses else "解析结果为空",
    }


def diagnose_dns() -> dict[str, object]:
    checks: list[dict[str, object]] = []
    for target in configured_network_targets():
        result = resolve_host(target.host)
        result["label"] = target.label
        result["url"] = target.url
        checks.append(result)

    failed = [item for item in checks if not item["ok"]]
    if not failed:
        summary = "外部站点域名解析正常"
    elif len(failed) == len(checks):
        summary = "容器无法解析任何外部站点域名，请修复 Docker DNS 或配置可用代理"
    else:
        summary = f"有 {len(failed)} 个外部站点域名解析失败"

    return {
        "ok": not failed,
        "summary": summary,
        "resolver": resolver_configuration(),
        "checks": checks,
        "remediation": [
            "重新创建容器，使 Compose 的 dns 配置写入容器 /etc/resolv.conf",
            "在设置 → 代理设置中配置可用的 HTTP 或 SOCKS5 代理",
            "确认 NAS 防火墙允许容器访问 DNS 的 UDP/TCP 53 端口和 HTTPS 443 端口",
        ],
    }

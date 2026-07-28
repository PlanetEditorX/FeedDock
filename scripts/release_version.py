#!/usr/bin/env python3
"""Detect release-worthy changes and keep FeedDock version files synchronized.

The GitHub Actions workflow uses this script for three operations:

* ``detect`` compares the current commit with the latest GitHub Release;
* ``next`` selects a manual higher version or increments the patch component;
* ``sync``/``check`` update and validate every runtime-visible version string.

Only the Python standard library is used so the script can run before project
requirements are installed.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence


SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
STATIC_ASSET_RE = re.compile(r'(/static/[^"\'?#]+\.(?:css|js)\?v=)[^"\']+')


@dataclass(frozen=True, order=True, slots=True)
class Version:
    major: int
    minor: int
    patch: int

    @classmethod
    def parse(cls, raw: str) -> "Version":
        value = raw.strip().removeprefix("v")
        match = SEMVER_RE.fullmatch(value)
        if match is None:
            raise ValueError(f"版本必须是稳定语义化版本 x.y.z，实际为：{raw!r}")
        return cls(*(int(part) for part in match.groups()))

    def next_patch(self) -> "Version":
        return Version(self.major, self.minor, self.patch + 1)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


def choose_release_version(current: str, latest: str = "") -> str:
    """Return a manually raised current version or the next patch release."""

    current_version = Version.parse(current)
    if not latest.strip():
        return str(current_version)
    latest_version = Version.parse(latest)
    if current_version > latest_version:
        return str(current_version)
    return str(latest_version.next_patch())


def load_release_patterns(path: Path) -> tuple[str, ...]:
    patterns: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line and not line.startswith("#"):
            patterns.append(line)
    if not patterns:
        raise ValueError(f"发布路径文件不能为空：{path}")
    return tuple(patterns)


def git_changed_files(root: Path, *, base: str, head: str) -> tuple[str, ...]:
    if base:
        command = ["git", "diff", "--name-only", f"{base}..{head}"]
    else:
        command = ["git", "ls-tree", "-r", "--name-only", head]
    completed = subprocess.run(
        command,
        cwd=root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return tuple(line.strip() for line in completed.stdout.splitlines() if line.strip())


def match_release_files(files: Iterable[str], patterns: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                path
                for path in files
                if any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)
            }
        )
    )


def _replace_regex(path: Path, pattern: str | re.Pattern[str], replacement: str, *, count: int = 0) -> None:
    original = path.read_text(encoding="utf-8")
    updated, replacements = re.subn(pattern, replacement, original, count=count, flags=re.MULTILINE)
    if replacements == 0:
        raise ValueError(f"未在 {path} 找到需要更新的版本字段")
    path.write_text(updated, encoding="utf-8")


def _published_at(value: str | None) -> str:
    if value:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sync_version(root: Path, version: str, *, published_at: str | None = None) -> None:
    """Synchronize files that influence runtime versioning and browser caches."""

    normalized = str(Version.parse(version))
    timestamp = _published_at(published_at)

    (root / "VERSION").write_text(f"{normalized}\n", encoding="utf-8")

    manifest_path = root / "update.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "version": normalized,
            "release_url": f"https://github.com/planeteditorx/feeddock/releases/tag/v{normalized}",
            "published_at": timestamp,
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    _replace_regex(root / "Dockerfile", r"^ARG APP_VERSION=.*$", f"ARG APP_VERSION={normalized}", count=1)
    _replace_regex(
        root / "app/config.py",
        r'app_version=os\.getenv\("APP_VERSION", "[^"]+"\)',
        f'app_version=os.getenv("APP_VERSION", "{normalized}")',
        count=1,
    )
    _replace_regex(
        root / "app/config.py",
        r'"FeedDock/[^" ]+ \(\+self-hosted RSS automation\)"',
        f'"FeedDock/{normalized} (+self-hosted RSS automation)"',
        count=1,
    )
    _replace_regex(
        root / ".env.example",
        r"^FEEDDOCK_BUILD_VERSION=.*$",
        f"FEEDDOCK_BUILD_VERSION={normalized}",
        count=1,
    )
    _replace_regex(
        root / ".env.example",
        r"^RSS_USER_AGENT=FeedDock/[^ ]+ ",
        f"RSS_USER_AGENT=FeedDock/{normalized} ",
        count=1,
    )
    _replace_regex(
        root / "README.md",
        r"当前版本：`[^`]+`",
        f"当前版本：`{normalized}`",
        count=1,
    )

    static_root = root / "app/static"
    html_files = sorted(static_root.glob("*.html"))
    if not html_files:
        raise ValueError("没有找到静态 HTML 文件")
    for html_path in html_files:
        original = html_path.read_text(encoding="utf-8")
        updated, replacements = STATIC_ASSET_RE.subn(rf"\g<1>{normalized}", original)
        if replacements == 0:
            raise ValueError(f"{html_path} 没有可同步的静态资源版本参数")
        html_path.write_text(updated, encoding="utf-8")


def validate_version_files(root: Path) -> list[str]:
    errors: list[str] = []
    version_text = (root / "VERSION").read_text(encoding="utf-8").strip()
    try:
        version = str(Version.parse(version_text))
    except ValueError as exc:
        return [str(exc)]

    manifest = json.loads((root / "update.json").read_text(encoding="utf-8"))
    if manifest.get("version") != version:
        errors.append("update.json 的 version 与 VERSION 不一致")
    if manifest.get("release_url") != f"https://github.com/planeteditorx/feeddock/releases/tag/v{version}":
        errors.append("update.json 的 release_url 与 VERSION 不一致")
    published_at = str(manifest.get("published_at") or "").strip()
    if not published_at:
        errors.append("update.json 缺少 published_at")
    else:
        try:
            datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        except ValueError:
            errors.append("update.json 的 published_at 不是有效 ISO-8601 时间")

    required_fragments = {
        root / "Dockerfile": [f"ARG APP_VERSION={version}"],
        root / "app/config.py": [
            f'app_version=os.getenv("APP_VERSION", "{version}")',
            f'"FeedDock/{version} (+self-hosted RSS automation)"',
        ],
        root / ".env.example": [
            f"FEEDDOCK_BUILD_VERSION={version}",
            f"RSS_USER_AGENT=FeedDock/{version} ",
        ],
        root / "README.md": [f"当前版本：`{version}`"],
    }
    for path, fragments in required_fragments.items():
        text = path.read_text(encoding="utf-8")
        for fragment in fragments:
            if fragment not in text:
                errors.append(f"{path.relative_to(root)} 缺少版本内容：{fragment}")

    for html_path in sorted((root / "app/static").glob("*.html")):
        text = html_path.read_text(encoding="utf-8")
        asset_versions = re.findall(r'/static/[^"\'?#]+\.(?:css|js)\?v=([^"\']+)', text)
        if not asset_versions:
            errors.append(f"{html_path.relative_to(root)} 没有静态资源版本参数")
        for asset_version in asset_versions:
            if asset_version != version:
                errors.append(
                    f"{html_path.relative_to(root)} 静态资源版本为 {asset_version}，应为 {version}"
                )
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    detect = subparsers.add_parser("detect", help="检测是否存在应发布的文件变化")
    detect.add_argument("--base", default="")
    detect.add_argument("--head", default="HEAD")
    detect.add_argument("--paths-file", type=Path, default=Path(".github/release-paths.txt"))
    detect.add_argument("--format", choices=("boolean", "lines", "json"), default="boolean")

    next_parser = subparsers.add_parser("next", help="计算下一个发布版本")
    next_parser.add_argument("--current", required=True)
    next_parser.add_argument("--latest", default="")

    sync = subparsers.add_parser("sync", help="同步所有版本文件")
    sync.add_argument("--version", required=True)
    sync.add_argument("--published-at", default="")

    subparsers.add_parser("check", help="检查所有版本文件是否一致")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()

    if args.command == "detect":
        paths_file = args.paths_file
        if not paths_file.is_absolute():
            paths_file = root / paths_file
        patterns = load_release_patterns(paths_file)
        changed = git_changed_files(root, base=args.base, head=args.head)
        matched = match_release_files(changed, patterns)
        if args.format == "boolean":
            print("true" if matched else "false")
        elif args.format == "lines":
            print("\n".join(matched))
        else:
            print(json.dumps({"release_needed": bool(matched), "files": matched}, ensure_ascii=False))
        return 0

    if args.command == "next":
        print(choose_release_version(args.current, args.latest))
        return 0

    if args.command == "sync":
        sync_version(root, args.version, published_at=args.published_at or None)
        return 0

    errors = validate_version_files(root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"版本文件一致：{(root / 'VERSION').read_text(encoding='utf-8').strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

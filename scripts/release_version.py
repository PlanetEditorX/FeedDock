#!/usr/bin/env python3
"""Detect image-impacting changes and choose the next image version.

The base ``VERSION`` file is only a release floor for intentional minor/major
bumps. Runtime update checks do not read this file; they compare OCI image
metadata from the container registry.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


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


def choose_release_version(base: str, latest_image: str = "") -> str:
    """Use a manually raised base version, otherwise increment remote image patch."""

    base_version = Version.parse(base)
    if not latest_image.strip():
        return str(base_version)
    remote_version = Version.parse(latest_image)
    if base_version > remote_version:
        return str(base_version)
    return str(remote_version.next_patch())


def load_release_patterns(path: Path) -> tuple[str, ...]:
    patterns = tuple(
        line
        for raw_line in path.read_text(encoding="utf-8").splitlines()
        if (line := raw_line.strip()) and not line.startswith("#")
    )
    if not patterns:
        raise ValueError(f"发布路径文件不能为空：{path}")
    return patterns


def git_changed_files(root: Path, *, base: str, head: str) -> tuple[str, ...]:
    command = (
        ["git", "diff", "--name-only", f"{base}..{head}"]
        if base
        else ["git", "ls-tree", "-r", "--name-only", head]
    )
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


def validate_base_version(root: Path) -> list[str]:
    version_path = root / "VERSION"
    if not version_path.is_file():
        return ["缺少 VERSION 基准文件"]
    try:
        Version.parse(version_path.read_text(encoding="utf-8").strip())
    except ValueError as exc:
        return [str(exc)]
    return []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    detect = subparsers.add_parser("detect", help="检测当前提交是否包含镜像变更")
    detect.add_argument("--base", default="")
    detect.add_argument("--head", default="HEAD")
    detect.add_argument("--paths-file", type=Path, default=Path(".github/release-paths.txt"))
    detect.add_argument("--format", choices=("boolean", "lines", "json"), default="boolean")

    next_parser = subparsers.add_parser("next", help="根据远端镜像版本计算下一补丁版本")
    next_parser.add_argument("--base", required=True)
    next_parser.add_argument("--latest-image", default="")

    subparsers.add_parser("check", help="检查 VERSION 是否为有效基准版本")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()

    if args.command == "detect":
        paths_file = args.paths_file if args.paths_file.is_absolute() else root / args.paths_file
        matched = match_release_files(
            git_changed_files(root, base=args.base, head=args.head),
            load_release_patterns(paths_file),
        )
        if args.format == "boolean":
            print("true" if matched else "false")
        elif args.format == "lines":
            print("\n".join(matched))
        else:
            print(json.dumps({"build_needed": bool(matched), "files": matched}, ensure_ascii=False))
        return 0

    if args.command == "next":
        print(choose_release_version(args.base, args.latest_image))
        return 0

    errors = validate_base_version(root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"基准版本有效：{(root / 'VERSION').read_text(encoding='utf-8').strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

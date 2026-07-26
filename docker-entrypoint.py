#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path


def _number(name: str, default: int, *, base: int = 10) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return int(raw, base)
    except ValueError:
        return default


def _boolean(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _chown_tree(path: Path, uid: int, gid: int) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chown(path, uid, gid)
    for root, dirs, files in os.walk(path):
        for name in dirs:
            os.chown(Path(root) / name, uid, gid)
        for name in files:
            os.chown(Path(root) / name, uid, gid)


def _assert_writable(path: Path, label: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".feeddock-write-test"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        raise SystemExit(
            f"{label}不可写：{path}。请检查飞牛目录权限、容器挂载以及 PUID/PGID：{exc}"
        ) from exc


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("missing command")

    uid = _number("PUID", 0)
    gid = _number("PGID", 0)
    umask = _number("UMASK", 0o002, base=8)
    os.umask(umask)
    data_dir = Path(os.getenv("DATA_DIR", "/data"))

    if os.geteuid() == 0:
        if _boolean("TAKE_OWNERSHIP", False):
            try:
                # Only adjust FeedDock's small application data directory. Never
                # recursively chown a user's entire media library.
                _chown_tree(data_dir, uid, gid)
            except PermissionError as exc:
                raise SystemExit(
                    f"无法调整 {data_dir} 权限，请检查飞牛 OS 挂载目录或 PUID/PGID：{exc}"
                ) from exc

        if uid != 0 or gid != 0:
            os.setgroups([])
            os.setgid(gid)
            os.setuid(uid)

    _assert_writable(data_dir, "FeedDock 数据目录")
    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()

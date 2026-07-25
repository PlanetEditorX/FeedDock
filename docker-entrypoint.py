#!/usr/bin/env python3
from __future__ import annotations

import os
import pwd
import grp
from pathlib import Path


def as_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def main() -> None:
    data_dir = Path(os.getenv("DATA_DIR", "/data"))
    uid = as_int("PUID", 1000)
    gid = as_int("PGID", 1000)
    umask = int(os.getenv("UMASK", "022"), 8)
    os.umask(umask)
    data_dir.mkdir(parents=True, exist_ok=True)

    if os.geteuid() == 0:
        try:
            grp.getgrgid(gid)
        except KeyError:
            os.system(f"groupadd -o -g {gid} feeddock")
        try:
            pwd.getpwuid(uid)
        except KeyError:
            os.system(f"useradd -o -u {uid} -g {gid} -d /app -s /usr/sbin/nologin feeddock")
        for path in (data_dir,):
            os.chown(path, uid, gid)
        os.setgid(gid)
        os.setuid(uid)

    os.execvp(
        "uvicorn",
        ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"],
    )


if __name__ == "__main__":
    main()

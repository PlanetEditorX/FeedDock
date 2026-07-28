#!/usr/bin/env python3
"""Inspect OCI metadata for a container image tag without using Docker Engine."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.image_registry import RegistryImageClient  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    parser.add_argument("--scheme", default="https", choices=("http", "https"))
    parser.add_argument("--field", choices=("version", "revision", "digest", "platform_digest"))
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument(
        "--username",
        default=os.getenv("UPDATE_REGISTRY_USERNAME", ""),
    )
    parser.add_argument(
        "--token",
        default=os.getenv("UPDATE_REGISTRY_TOKEN", ""),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        metadata = RegistryImageClient(
            args.image,
            scheme=args.scheme,
            timeout=args.timeout,
            username=args.username,
            token=args.token,
        ).inspect()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        print(f"registry returned HTTP {status}: {exc.request.url}", file=sys.stderr)
        return 3 if status == 404 else 1
    except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exc:
        print(f"registry inspection failed: {exc}", file=sys.stderr)
        return 1

    payload = metadata.as_cache_dict()
    if args.field:
        print(payload[args.field])
    else:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

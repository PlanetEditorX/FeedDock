from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path


_DEFAULT_BUILD_INFO_PATH = Path('/app/.feeddock-build.json')


@dataclass(frozen=True, slots=True)
class BuildInfo:
    """Immutable metadata describing the image that contains this process.

    Docker image ``ENV`` values can be copied into a container's persisted
    configuration by update tools. Reading a file baked into each image avoids
    an old container-level ``APP_VERSION`` overriding the metadata of a newly
    pulled image.
    """

    version: str
    revision: str
    created_at: str
    source: str


_UNEXPANDED_BUILD_ARG = re.compile(r'^\$\{?[A-Z][A-Z0-9_]*\}?$')


def _clean(value: object) -> str:
    cleaned = str(value or '').strip()
    if _UNEXPANDED_BUILD_ARG.fullmatch(cleaned):
        return ''
    return cleaned


def _build_info_path() -> Path:
    configured = os.getenv('FEEDDOCK_BUILD_INFO_FILE', '').strip()
    return Path(configured).expanduser() if configured else _DEFAULT_BUILD_INFO_PATH


def load_build_info() -> BuildInfo:
    """Load image metadata, preferring the immutable image build-info file.

    Source checkouts and tests normally do not contain the image file, so they
    retain the existing environment-variable fallback.
    """

    path = _build_info_path()
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
        version = _clean(payload.get('version'))
        revision = _clean(payload.get('revision'))
        created_at = _clean(payload.get('created_at'))
        if version or revision:
            return BuildInfo(
                version=version or 'dev',
                revision=revision,
                created_at=created_at,
                source=f'image-file:{path}',
            )
    except (OSError, ValueError, json.JSONDecodeError, AttributeError):
        pass

    return BuildInfo(
        version=_clean(os.getenv('APP_VERSION', 'dev')) or 'dev',
        revision=_clean(os.getenv('APP_REVISION', '')),
        created_at=_clean(os.getenv('APP_CREATED_AT', '')),
        source='environment',
    )

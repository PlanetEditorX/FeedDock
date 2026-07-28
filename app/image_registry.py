from __future__ import annotations

import platform
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from .outbound import external_client


_MANIFEST_ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)
_INDEX_MEDIA_TYPES = {
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
}


@dataclass(frozen=True, slots=True)
class ImageReference:
    registry: str
    repository: str
    reference: str
    scheme: str = "https"

    @property
    def display(self) -> str:
        separator = "@" if self.reference.startswith("sha256:") else ":"
        return f"{self.registry}/{self.repository}{separator}{self.reference}"


@dataclass(frozen=True, slots=True)
class RegistryImageMetadata:
    image: str
    digest: str
    platform_digest: str
    version: str
    revision: str
    created_at: str
    architecture: str
    operating_system: str
    manifest_url: str

    def as_cache_dict(self) -> dict[str, str]:
        return {
            "image": self.image,
            "digest": self.digest,
            "platform_digest": self.platform_digest,
            "version": self.version,
            "revision": self.revision,
            "created_at": self.created_at,
            "architecture": self.architecture,
            "operating_system": self.operating_system,
            "manifest_url": self.manifest_url,
        }

    @classmethod
    def from_cache_dict(cls, payload: object) -> "RegistryImageMetadata":
        if not isinstance(payload, dict):
            raise ValueError("镜像缓存必须是 JSON 对象")
        image = str(payload.get("image") or "").strip()
        digest = str(payload.get("digest") or "").strip()
        if not image or not digest:
            raise ValueError("镜像缓存缺少 image 或 digest")
        return cls(
            image=image,
            digest=digest,
            platform_digest=str(payload.get("platform_digest") or "").strip(),
            version=str(payload.get("version") or "").strip(),
            revision=str(payload.get("revision") or "").strip(),
            created_at=str(payload.get("created_at") or "").strip(),
            architecture=str(payload.get("architecture") or "").strip(),
            operating_system=str(payload.get("operating_system") or "").strip(),
            manifest_url=str(payload.get("manifest_url") or "").strip(),
        )


def parse_image_reference(value: str, *, default_scheme: str = "https") -> ImageReference:
    """Parse a registry image reference without requiring the Docker daemon.

    FeedDock primarily targets fully qualified references such as
    ``ghcr.io/planeteditorx/feeddock:latest``. Docker Hub shorthand is accepted
    as a convenience, but update checks should use a fully qualified image.
    """

    raw = str(value or "").strip()
    if not raw:
        raise ValueError("未配置部署镜像")

    scheme = default_scheme
    if "://" in raw:
        parsed = urlparse(raw)
        scheme = parsed.scheme or default_scheme
        raw = f"{parsed.netloc}{parsed.path}"

    if "@" in raw:
        name, reference = raw.rsplit("@", 1)
    else:
        last_slash = raw.rfind("/")
        last_colon = raw.rfind(":")
        if last_colon > last_slash:
            name, reference = raw[:last_colon], raw[last_colon + 1 :]
        else:
            name, reference = raw, "latest"

    parts = name.split("/", 1)
    if len(parts) == 1:
        registry = "registry-1.docker.io"
        repository = f"library/{parts[0]}"
    else:
        first, rest = parts
        if "." in first or ":" in first or first == "localhost":
            registry, repository = first, rest
        else:
            registry, repository = "registry-1.docker.io", name

    if not registry or not repository or not reference:
        raise ValueError(f"无效镜像地址：{value}")
    if registry.startswith(("127.0.0.1", "localhost")) and default_scheme == "https":
        scheme = "http"
    return ImageReference(
        registry=registry.strip().lower(),
        repository=repository.strip("/"),
        reference=reference.strip(),
        scheme=scheme,
    )


def _runtime_platform() -> tuple[str, str, str]:
    machine = platform.machine().strip().lower()
    mappings = {
        "x86_64": ("linux", "amd64", ""),
        "amd64": ("linux", "amd64", ""),
        "aarch64": ("linux", "arm64", ""),
        "arm64": ("linux", "arm64", ""),
        "armv7l": ("linux", "arm", "v7"),
        "armv6l": ("linux", "arm", "v6"),
    }
    return mappings.get(machine, ("linux", machine or "amd64", ""))


def _parse_bearer_challenge(value: str) -> tuple[str, dict[str, str]]:
    match = re.match(r"^\s*Bearer\s+(.+)$", str(value or ""), flags=re.IGNORECASE)
    if not match:
        raise ValueError("镜像仓库未返回 Bearer 认证信息")
    params: dict[str, str] = {}
    for item in re.split(r',(?=\s*[A-Za-z][A-Za-z0-9_-]*=)', match.group(1)):
        key, separator, raw_value = item.strip().partition("=")
        if separator:
            params[key.lower()] = raw_value.strip().strip('"')
    realm = params.pop("realm", "")
    if not realm:
        raise ValueError("镜像仓库认证信息缺少 realm")
    return realm, params


class RegistryImageClient:
    def __init__(
        self,
        image: str,
        *,
        timeout: int | float = 20,
        scheme: str = "https",
        operating_system: str | None = None,
        architecture: str | None = None,
        variant: str | None = None,
        username: str = "",
        token: str = "",
    ) -> None:
        self.reference = parse_image_reference(image, default_scheme=scheme)
        self.timeout = timeout
        runtime_os, runtime_arch, runtime_variant = _runtime_platform()
        self.operating_system = operating_system or runtime_os
        self.architecture = architecture or runtime_arch
        self.variant = runtime_variant if variant is None else variant
        self.username = username.strip()
        self.registry_token = token.strip()
        self._token = ""

    @property
    def base_url(self) -> str:
        return f"{self.reference.scheme}://{self.reference.registry}"

    def _request(
        self,
        client: httpx.Client,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        request_headers = dict(headers or {})
        if self._token:
            request_headers["Authorization"] = f"Bearer {self._token}"
        response = client.request(method, url, headers=request_headers)
        if response.status_code != 401:
            return response

        realm, params = _parse_bearer_challenge(response.headers.get("www-authenticate", ""))
        params.setdefault("scope", f"repository:{self.reference.repository}:pull")
        token_auth = (
            (self.username, self.registry_token)
            if self.username and self.registry_token
            else None
        )
        token_response = client.get(realm, params=params, auth=token_auth)
        token_response.raise_for_status()
        token_payload = token_response.json()
        self._token = str(token_payload.get("token") or token_payload.get("access_token") or "").strip()
        if not self._token:
            raise ValueError("镜像仓库认证服务未返回 token")
        request_headers["Authorization"] = f"Bearer {self._token}"
        return client.request(method, url, headers=request_headers)

    def _manifest(
        self,
        client: httpx.Client,
        reference: str,
    ) -> tuple[dict, str, str]:
        url = (
            f"{self.base_url}/v2/{self.reference.repository}/manifests/{reference}"
        )
        response = self._request(client, "GET", url, headers={"Accept": _MANIFEST_ACCEPT})
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("镜像仓库返回了无效 manifest")
        digest = str(response.headers.get("docker-content-digest") or "").strip()
        return payload, digest, url

    def _select_platform_manifest(self, payload: dict) -> dict:
        manifests = payload.get("manifests")
        if not isinstance(manifests, list) or not manifests:
            raise ValueError("多架构镜像清单没有可用平台")

        candidates: list[dict] = []
        for descriptor in manifests:
            if not isinstance(descriptor, dict):
                continue
            target = descriptor.get("platform") if isinstance(descriptor.get("platform"), dict) else {}
            if target.get("os") != self.operating_system or target.get("architecture") != self.architecture:
                continue
            candidates.append(descriptor)
            if not self.variant or target.get("variant", "") == self.variant:
                return descriptor
        if candidates:
            return candidates[0]
        raise ValueError(
            f"远端镜像不包含 {self.operating_system}/{self.architecture}"
            f"{f'/{self.variant}' if self.variant else ''} 平台"
        )

    def inspect(self) -> RegistryImageMetadata:
        manifest_url = (
            f"{self.base_url}/v2/{self.reference.repository}/manifests/"
            f"{self.reference.reference}"
        )
        with external_client(
            manifest_url,
            timeout=self.timeout,
            headers={"User-Agent": "FeedDock image update checker"},
        ) as client:
            root_manifest, root_digest, root_url = self._manifest(client, self.reference.reference)
            root_media_type = str(root_manifest.get("mediaType") or "")
            image_manifest = root_manifest
            platform_digest = root_digest
            if root_media_type in _INDEX_MEDIA_TYPES or isinstance(root_manifest.get("manifests"), list):
                descriptor = self._select_platform_manifest(root_manifest)
                platform_digest = str(descriptor.get("digest") or "").strip()
                if not platform_digest:
                    raise ValueError("平台镜像清单缺少 digest")
                image_manifest, fetched_digest, _ = self._manifest(client, platform_digest)
                platform_digest = fetched_digest or platform_digest

            config_descriptor = image_manifest.get("config")
            if not isinstance(config_descriptor, dict):
                raise ValueError("镜像 manifest 缺少 config")
            config_digest = str(config_descriptor.get("digest") or "").strip()
            if not config_digest:
                raise ValueError("镜像 config 缺少 digest")

            config_url = f"{self.base_url}/v2/{self.reference.repository}/blobs/{config_digest}"
            config_response = self._request(client, "GET", config_url)
            config_response.raise_for_status()
            config_payload = config_response.json()
            if not isinstance(config_payload, dict):
                raise ValueError("镜像 config 不是 JSON 对象")
            runtime_config = config_payload.get("config")
            runtime_config = runtime_config if isinstance(runtime_config, dict) else {}
            labels = runtime_config.get("Labels")
            labels = labels if isinstance(labels, dict) else {}
            annotations = image_manifest.get("annotations")
            annotations = annotations if isinstance(annotations, dict) else {}
            root_annotations = root_manifest.get("annotations")
            root_annotations = root_annotations if isinstance(root_annotations, dict) else {}

            def metadata_value(key: str) -> str:
                return str(labels.get(key) or annotations.get(key) or root_annotations.get(key) or "").strip()

            return RegistryImageMetadata(
                image=self.reference.display,
                digest=root_digest or platform_digest,
                platform_digest=platform_digest,
                version=metadata_value("org.opencontainers.image.version"),
                revision=metadata_value("org.opencontainers.image.revision"),
                created_at=str(config_payload.get("created") or metadata_value("org.opencontainers.image.created")),
                architecture=str(config_payload.get("architecture") or self.architecture),
                operating_system=str(config_payload.get("os") or self.operating_system),
                manifest_url=root_url,
            )

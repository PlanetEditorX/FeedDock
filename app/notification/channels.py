"""Channel-specific notification delivery adapters."""

from __future__ import annotations

import base64
from collections.abc import Callable
import json
import secrets
import string
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from cryptography.hazmat.primitives import padding as crypto_padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.orm import Session


PostCallable = Callable[..., Any]

BARK_ENCRYPTION_ALGORITHMS = frozenset({"AES128", "AES192", "AES256"})
BARK_ENCRYPTION_MODES = frozenset({"CBC", "ECB", "GCM"})
BARK_ENCRYPTION_PADDINGS = frozenset({"pkcs7", "noPadding"})
BARK_ENCRYPTION_KEY_LENGTHS = {
    "AES128": 16,
    "AES192": 24,
    "AES256": 32,
}


def _random_ascii_iv(length: int) -> str:
    """Generate an IV Bark can reconstruct from its UTF-8 string parameter."""

    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def validate_bark_encryption_options(
    *,
    algorithm: str,
    mode: str,
    padding: str,
    key: str,
) -> tuple[str, str, str, bytes]:
    """Validate Bark's official AES options and return normalized values."""

    normalized_algorithm = str(algorithm or "").strip().upper()
    normalized_mode = str(mode or "").strip().upper()
    normalized_padding = str(padding or "").strip()
    if normalized_algorithm not in BARK_ENCRYPTION_ALGORITHMS:
        raise ValueError("Bark 加密算法必须是 AES128、AES192 或 AES256")
    if normalized_mode not in BARK_ENCRYPTION_MODES:
        raise ValueError("Bark 加密模式必须是 CBC、ECB 或 GCM")
    if normalized_padding not in BARK_ENCRYPTION_PADDINGS:
        raise ValueError("Bark 加密填充必须是 pkcs7 或 noPadding")
    if not key:
        raise ValueError("启用 Bark 推送加密时必须填写加密 Key")
    if not key.isascii():
        raise ValueError("Bark 加密 Key 仅支持 ASCII 字符")
    expected_length = BARK_ENCRYPTION_KEY_LENGTHS[normalized_algorithm]
    key_bytes = key.encode("ascii")
    if len(key_bytes) != expected_length:
        raise ValueError(f"{normalized_algorithm} 的 Bark 加密 Key 必须为 {expected_length} 个字符")
    return normalized_algorithm, normalized_mode, normalized_padding, key_bytes


def encrypt_bark_payload(
    payload: dict[str, Any],
    *,
    algorithm: str,
    mode: str,
    padding: str,
    key: str,
    iv: str | None = None,
) -> tuple[str, str | None]:
    """Encrypt a Bark JSON payload using the options configured in Bark App.

    Bark stores the algorithm, mode, padding and key on the device.  The push
    request only carries the Base64 ciphertext and, for CBC/GCM, the IV.  A
    fresh ASCII IV is generated for every request unless one is supplied by a
    deterministic test.
    """

    _, normalized_mode, normalized_padding, key_bytes = validate_bark_encryption_options(
        algorithm=algorithm,
        mode=mode,
        padding=padding,
        key=key,
    )
    plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if normalized_padding == "pkcs7":
        padder = crypto_padding.PKCS7(algorithms.AES.block_size).padder()
        plaintext = padder.update(plaintext) + padder.finalize()

    iv_value: str | None = None
    if normalized_mode == "CBC":
        iv_value = iv or _random_ascii_iv(16)
        if not iv_value.isascii() or len(iv_value.encode("ascii")) != 16:
            raise ValueError("Bark CBC 模式的 IV 必须为 16 个 ASCII 字符")
        if len(plaintext) % 16:
            raise ValueError("Bark CBC + noPadding 要求加密后的 JSON 长度是 16 的倍数，请改用 pkcs7")
        cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv_value.encode("ascii")))
        encryptor = cipher.encryptor()
        encrypted = encryptor.update(plaintext) + encryptor.finalize()
    elif normalized_mode == "ECB":
        if len(plaintext) % 16:
            raise ValueError("Bark ECB + noPadding 要求加密后的 JSON 长度是 16 的倍数，请改用 pkcs7")
        cipher = Cipher(algorithms.AES(key_bytes), modes.ECB())
        encryptor = cipher.encryptor()
        encrypted = encryptor.update(plaintext) + encryptor.finalize()
    else:
        iv_value = iv or _random_ascii_iv(12)
        if not iv_value.isascii() or len(iv_value.encode("ascii")) != 12:
            raise ValueError("Bark GCM 模式的 IV 必须为 12 个 ASCII 字符")
        # AESGCM returns ciphertext followed by the 16-byte authentication tag,
        # matching CryptoSwift's GCM ``combined`` representation used by Bark.
        encrypted = AESGCM(key_bytes).encrypt(iv_value.encode("ascii"), plaintext, None)

    return base64.b64encode(encrypted).decode("ascii"), iv_value


def normalize_bark_push_url(server_url: str) -> str:
    """Return one valid Bark ``/push`` endpoint.

    Users may enter either the Bark server root (``http://host:port``) or the
    complete endpoint (``http://host:port/push``).  The previous implementation
    always appended ``/push`` and therefore produced ``/push/push`` for the
    latter form.
    """

    parts = urlsplit(server_url.strip())
    path = (parts.path or "").rstrip("/")
    if not path.lower().endswith("/push"):
        path = f"{path}/push" if path else "/push"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def send_telegram(
    *,
    post: PostCallable,
    db: Session,
    bot_token: str,
    chat_id: str,
    title: str,
    body: str,
) -> None:
    response = post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        db=db,
        json={
            "chat_id": chat_id,
            "text": f"{title}\n\n{body}",
            "disable_web_page_preview": True,
        },
    )
    response.raise_for_status()


def send_bark(
    *,
    post: PostCallable,
    db: Session,
    server_url: str,
    device_key: str,
    title: str,
    body: str,
    icon: str = "",
    image: str = "",
    encryption_enabled: bool = False,
    encryption_algorithm: str = "AES128",
    encryption_mode: str = "CBC",
    encryption_padding: str = "pkcs7",
    encryption_key: str = "",
) -> None:
    # Device Key is intentionally sent in the JSON body instead of the URL so
    # reverse-proxy access logs and browser history do not expose the secret.
    content_payload = {
        "title": title,
        "body": body,
        "group": "FeedDock",
    }
    if icon:
        content_payload["icon"] = icon
    if image:
        content_payload["image"] = image

    if encryption_enabled:
        ciphertext, iv = encrypt_bark_payload(
            content_payload,
            algorithm=encryption_algorithm,
            mode=encryption_mode,
            padding=encryption_padding,
            key=encryption_key,
        )
        payload = {
            "device_key": device_key,
            "ciphertext": ciphertext,
        }
        if iv:
            payload["iv"] = iv
    else:
        payload = {**content_payload, "device_key": device_key}
    response = post(
        normalize_bark_push_url(server_url),
        db=db,
        json=payload,
    )
    response.raise_for_status()


def send_webhook(
    *,
    post: PostCallable,
    db: Session,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
) -> None:
    response = post(
        url,
        db=db,
        headers={"Content-Type": "application/json", **headers},
        json=payload,
    )
    response.raise_for_status()

"""Channel-specific notification delivery adapters."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy.orm import Session


PostCallable = Callable[..., Any]


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
) -> None:
    # Device Key is intentionally sent in the JSON body instead of the URL so
    # reverse-proxy access logs and browser history do not expose the secret.
    payload = {
        "title": title,
        "body": body,
        "device_key": device_key,
        "group": "FeedDock",
    }
    if icon:
        payload["icon"] = icon
    if image:
        payload["image"] = image
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

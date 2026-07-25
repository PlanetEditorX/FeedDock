from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Cookie, HTTPException, status

from .config import settings
from .db import connect, transaction, utcnow_iso

_ITERATIONS = 310_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        _ITERATIONS,
        base64.urlsafe_b64encode(salt).decode().rstrip("="),
        base64.urlsafe_b64encode(digest).decode().rstrip("="),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_b64 + "=" * (-len(salt_b64) % 4))
        expected = base64.urlsafe_b64decode(digest_b64 + "=" * (-len(digest_b64) % 4))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def ensure_admin() -> None:
    now = utcnow_iso()
    with transaction() as conn:
        row = conn.execute("SELECT id FROM users WHERE username = ?", (settings.admin_user,)).fetchone()
        if row is None:
            conn.execute(
                """
                INSERT INTO users(username, password_hash, must_change_password, created_at, updated_at)
                VALUES (?, ?, 1, ?, ?)
                """,
                (settings.admin_user, hash_password(settings.admin_password), now, now),
            )


def create_session(user_id: int, session_version: int) -> str:
    token = secrets.token_urlsafe(40)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires = datetime.now(timezone.utc) + timedelta(days=settings.session_days)
    with transaction() as conn:
        conn.execute(
            "INSERT INTO sessions(token_hash, user_id, session_version, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
            (token_hash, user_id, session_version, expires.isoformat(), utcnow_iso()),
        )
    return token


def delete_session(token: str | None) -> None:
    if not token:
        return
    with transaction() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),))


def get_current_user(feeddock_session: str | None = Cookie(default=None)) -> dict:
    if not feeddock_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="NOT_AUTHENTICATED")
    token_hash = hashlib.sha256(feeddock_session.encode()).hexdigest()
    now = datetime.now(timezone.utc)
    with connect() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.username, u.must_change_password, u.session_version, s.expires_at,
                   s.session_version AS stored_session_version
            FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="INVALID_SESSION")
    if datetime.fromisoformat(row["expires_at"]) <= now or row["stored_session_version"] != row["session_version"]:
        delete_session(feeddock_session)
        raise HTTPException(status_code=401, detail="SESSION_EXPIRED")
    return dict(row)


def require_ready(user: dict = None):
    if user is None:
        user = get_current_user()
    if user["must_change_password"]:
        raise HTTPException(status_code=428, detail="PASSWORD_CHANGE_REQUIRED")
    return user

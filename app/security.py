from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .database import get_db
from .models import AdminAccount


SESSION_COOKIE = "feeddock_session"
_PASSWORD_SCHEME = "pbkdf2_sha256"
_PASSWORD_ITERATIONS = 600_000
PASSWORD_MIN_LENGTH = 10


@dataclass(frozen=True, slots=True)
class SessionIdentity:
    account_id: int
    username: str
    session_version: int
    expires_at: int


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str, *, iterations: int = _PASSWORD_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{_PASSWORD_SCHEME}${iterations}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, iterations_raw, salt_raw, digest_raw = encoded.split("$", 3)
        if scheme != _PASSWORD_SCHEME:
            return False
        iterations = int(iterations_raw)
        salt = _b64decode(salt_raw)
        expected = _b64decode(digest_raw)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def validate_new_password(password: str, username: str = "") -> None:
    if len(password) < PASSWORD_MIN_LENGTH:
        raise HTTPException(status_code=422, detail=f"新密码至少需要 {PASSWORD_MIN_LENGTH} 个字符")
    if password.strip() != password:
        raise HTTPException(status_code=422, detail="密码首尾不能包含空格")
    if username and password.casefold() == username.casefold():
        raise HTTPException(status_code=422, detail="密码不能与用户名相同")
    if password in {"change-me-now", "change-this-to-a-strong-password"}:
        raise HTTPException(status_code=422, detail="不能继续使用示例默认密码")


def initialize_admin(db: Session) -> AdminAccount:
    account = db.scalar(select(AdminAccount).order_by(AdminAccount.id).limit(1))
    if account:
        return account
    account = AdminAccount(
        username=settings.admin_user,
        password_hash=hash_password(settings.admin_password),
        must_change_password=True,
        session_version=1,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def _load_or_create_session_secret() -> bytes:
    configured = os.getenv("SESSION_SECRET", "").strip()
    if configured:
        return hashlib.sha256(configured.encode("utf-8")).digest()

    path = Path(settings.data_dir) / "session-secret.key"
    try:
        existing = path.read_bytes()
        if len(existing) >= 32:
            return existing
    except FileNotFoundError:
        pass

    secret = secrets.token_bytes(48)
    temp = path.with_suffix(".tmp")
    temp.write_bytes(secret)
    try:
        temp.chmod(0o600)
    except OSError:
        pass
    temp.replace(path)
    return secret


_SESSION_SECRET = _load_or_create_session_secret()


def create_session_token(account: AdminAccount) -> str:
    expires_at = int(time.time()) + settings.session_days * 86400
    payload = {
        "sub": account.id,
        "usr": account.username,
        "ver": account.session_version,
        "exp": expires_at,
        "nonce": secrets.token_urlsafe(8),
    }
    encoded = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _b64encode(hmac.new(_SESSION_SECRET, encoded.encode("ascii"), hashlib.sha256).digest())
    return f"{encoded}.{signature}"


def decode_session_token(token: str) -> SessionIdentity | None:
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected_signature = _b64encode(
            hmac.new(_SESSION_SECRET, encoded.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return None
        payload = json.loads(_b64decode(encoded))
        identity = SessionIdentity(
            account_id=int(payload["sub"]),
            username=str(payload["usr"]),
            session_version=int(payload["ver"]),
            expires_at=int(payload["exp"]),
        )
        if identity.expires_at < int(time.time()):
            return None
        return identity
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def resolve_admin(request: Request, db: Session) -> AdminAccount | None:
    token = request.cookies.get(SESSION_COOKIE, "")
    identity = decode_session_token(token) if token else None
    if not identity:
        return None
    account = db.get(AdminAccount, identity.account_id)
    if not account:
        return None
    if account.username != identity.username or account.session_version != identity.session_version:
        return None
    return account


def require_authenticated(
    request: Request,
    db: Session = Depends(get_db),
) -> AdminAccount:
    account = resolve_admin(request, db)
    if not account:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    return account


def require_admin(account: AdminAccount = Depends(require_authenticated)) -> AdminAccount:
    if account.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail="PASSWORD_CHANGE_REQUIRED",
        )
    return account

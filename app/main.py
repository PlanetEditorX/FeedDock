from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

from .config import settings
from .db import add_log, connect, init_db, transaction, utcnow_iso
from .mikan import (
    MikanError,
    apply_hidden,
    fetch_bangumi_detail,
    fetch_catalog,
    fetch_image,
    group_by_weekday,
    load_catalog,
    normalize_season,
    save_catalog,
)
from .qbittorrent import current_config, restore_config, save_config, test_connection
from .rss import refresh_all, refresh_subscription
from .runtime_config import clear_week_hidden, list_hidden, replace_week_hidden
from .security import (
    create_session,
    delete_session,
    ensure_admin,
    get_current_user,
    hash_password,
    verify_password,
)

COOKIE_NAME = "feeddock_session"


class LoginPayload(BaseModel):
    username: str
    password: str


class ChangePasswordPayload(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=256)


class QbitPayload(BaseModel):
    url: str = ""
    username: str = ""
    password: str = ""
    category: str = "rss"
    download_path: str = "/downloads/rss"


class SubscriptionPayload(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    reference_title: str = ""
    tmdb_title: str = ""
    bgm_url: str = ""
    release_date: str = ""
    season: int = Field(default=1, ge=1, le=99)
    primary_rss_name: str = ""
    primary_rss_url: str = Field(min_length=1)
    backup_rss_name: str = ""
    backup_rss_url: str = ""
    include_rules: str = ""
    exclude_rules: str = ""
    global_exclude_rules: str = ""
    episode_regex: str = ""
    episode_group: int = Field(default=0, ge=0, le=20)
    episode_offset: float = 0
    total_episodes: int = Field(default=0, ge=0, le=9999)
    download_path: str = ""
    missing_check: bool = False
    latest_only: bool = False
    enabled: bool = True


class HiddenEntry(BaseModel):
    bangumi_id: int = Field(gt=0)
    title: str = ""


class HiddenPayload(BaseModel):
    entries: list[HiddenEntry] = Field(default_factory=list)


async def scheduler_loop() -> None:
    while True:
        await asyncio.sleep(settings.poll_interval_minutes * 60)
        await refresh_all()


async def mikan_cache_loop() -> None:
    while True:
        await asyncio.sleep(60 * 60)
        with connect() as conn:
            keys = [row["cache_key"] for row in conn.execute("SELECT cache_key FROM mikan_cache").fetchall()]
        for key in keys:
            try:
                _, year, season = key.split(":", 2)
                cached = load_catalog(int(year), season)
                if cached and cached["stale"]:
                    items, source = await fetch_catalog(int(year), season)
                    save_catalog(int(year), season, items, source)
            except Exception as exc:
                add_log("warning", "Mikan 缓存后台更新失败", {"key": key, "error": str(exc)})


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    init_db()
    ensure_admin()
    tasks: list[asyncio.Task] = []
    if not settings.testing:
        tasks = [asyncio.create_task(scheduler_loop()), asyncio.create_task(mikan_cache_loop())]
    yield
    for task in tasks:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="FeedDock", version=settings.version, lifespan=lifespan)
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def ready_user(user: dict = Depends(get_current_user)) -> dict:
    if user["must_change_password"]:
        raise HTTPException(status_code=428, detail="PASSWORD_CHANGE_REQUIRED")
    return user


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": settings.version}


@app.post("/api/auth/login")
def login(payload: LoginPayload, response: Response) -> dict:
    with connect() as conn:
        user = conn.execute("SELECT * FROM users WHERE username=?", (payload.username,)).fetchone()
    if user is None or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = create_session(user["id"], user["session_version"])
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_days * 86400,
        path="/",
    )
    return {"username": user["username"], "must_change_password": bool(user["must_change_password"])}


@app.post("/api/auth/change-password")
def change_password(payload: ChangePasswordPayload, response: Response, user: dict = Depends(get_current_user)) -> dict:
    with connect() as conn:
        record = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    if record is None or not verify_password(payload.current_password, record["password_hash"]):
        raise HTTPException(status_code=400, detail="当前密码错误")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与当前密码相同")
    with transaction() as conn:
        conn.execute(
            "UPDATE users SET password_hash=?, must_change_password=0, session_version=session_version+1, updated_at=? WHERE id=?",
            (hash_password(payload.new_password), utcnow_iso(), user["id"]),
        )
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True, "message": "密码已修改，请重新登录"}


@app.post("/api/auth/logout")
def logout(response: Response, request: Request) -> dict:
    delete_session(request.cookies.get(COOKIE_NAME))
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@app.get("/api/me")
def me(user: dict = Depends(get_current_user)) -> dict:
    return {"username": user["username"], "must_change_password": bool(user["must_change_password"]), "version": settings.version}


@app.get("/api/dashboard")
def dashboard(_: dict = Depends(ready_user)) -> dict:
    with connect() as conn:
        subscriptions = conn.execute("SELECT COUNT(*) AS n FROM subscriptions").fetchone()["n"]
        enabled = conn.execute("SELECT COUNT(*) AS n FROM subscriptions WHERE enabled=1").fetchone()["n"]
        items = conn.execute("SELECT COUNT(*) AS n FROM rss_items").fetchone()["n"]
        errors = conn.execute("SELECT COUNT(*) AS n FROM rss_items WHERE status='error'").fetchone()["n"]
    return {"subscriptions": subscriptions, "enabled": enabled, "items": items, "errors": errors, "version": settings.version}


@app.get("/api/subscriptions")
def subscriptions(_: dict = Depends(ready_user)) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM subscriptions ORDER BY id DESC").fetchall()
    return [dict(row) for row in rows]


@app.post("/api/subscriptions")
def create_subscription(payload: SubscriptionPayload, _: dict = Depends(ready_user)) -> dict:
    now = utcnow_iso()
    values = payload.model_dump()
    values.update({"missing_check": int(payload.missing_check), "latest_only": int(payload.latest_only), "enabled": int(payload.enabled)})
    columns = list(values)
    with transaction() as conn:
        cursor = conn.execute(
            f"INSERT INTO subscriptions({','.join(columns)}, created_at, updated_at) VALUES ({','.join('?' for _ in columns)}, ?, ?)",
            [values[column] for column in columns] + [now, now],
        )
        subscription_id = cursor.lastrowid
    return {"id": subscription_id, "message": "订阅已保存"}


@app.put("/api/subscriptions/{subscription_id}")
def update_subscription(subscription_id: int, payload: SubscriptionPayload, _: dict = Depends(ready_user)) -> dict:
    values = payload.model_dump()
    values.update({"missing_check": int(payload.missing_check), "latest_only": int(payload.latest_only), "enabled": int(payload.enabled)})
    assignments = ",".join(f"{column}=?" for column in values)
    with transaction() as conn:
        cursor = conn.execute(
            f"UPDATE subscriptions SET {assignments}, updated_at=? WHERE id=?",
            [values[column] for column in values] + [utcnow_iso(), subscription_id],
        )
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="订阅不存在")
    return {"ok": True}


@app.delete("/api/subscriptions/{subscription_id}")
def delete_subscription(subscription_id: int, _: dict = Depends(ready_user)) -> dict:
    with transaction() as conn:
        conn.execute("DELETE FROM subscriptions WHERE id=?", (subscription_id,))
    return {"ok": True}


@app.post("/api/subscriptions/{subscription_id}/refresh")
async def refresh_one(subscription_id: int, _: dict = Depends(ready_user)) -> dict:
    try:
        return await refresh_subscription(subscription_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/logs")
def logs(limit: int = Query(default=100, ge=1, le=500), _: dict = Depends(ready_user)) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["context"] = json.loads(item["context"])
        except json.JSONDecodeError:
            pass
        result.append(item)
    return result


@app.get("/api/settings/qbittorrent")
def get_qbit(_: dict = Depends(ready_user)) -> dict:
    return current_config()


@app.put("/api/settings/qbittorrent")
async def put_qbit(payload: QbitPayload, test: bool = True, _: dict = Depends(ready_user)) -> dict:
    saved = save_config(payload.model_dump())
    result: dict[str, Any] = {"config": saved}
    if test:
        try:
            result["test"] = await test_connection()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"配置已保存，但连接测试失败：{exc}") from exc
    return result


@app.post("/api/settings/qbittorrent/test")
async def test_qbit(_: dict = Depends(ready_user)) -> dict:
    try:
        return await test_connection()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.delete("/api/settings/qbittorrent")
def reset_qbit(_: dict = Depends(ready_user)) -> dict:
    return restore_config()


@app.get("/api/update/status")
def update_status(_: dict = Depends(ready_user)) -> dict:
    return {"current_version": settings.version, "repository": settings.update_repository, "automatic_check": False}


@app.post("/api/update/check")
async def check_update(_: dict = Depends(ready_user)) -> dict:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "FeedDock/1.8"}
    if settings.update_github_token:
        headers["Authorization"] = f"Bearer {settings.update_github_token}"
    url = f"{settings.update_api_url}/repos/{settings.update_repository}/releases/latest"
    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        response = await client.get(url, headers=headers)
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="仓库尚未发布 Release")
    if response.status_code == 403 and "rate limit" in response.text.lower():
        reset_at = response.headers.get("x-ratelimit-reset", "")
        reset_text = ""
        if reset_at.isdigit():
            reset_text = datetime.fromtimestamp(int(reset_at), timezone.utc).astimezone().isoformat(timespec="minutes")
        raise HTTPException(status_code=429, detail=f"GitHub API 访问额度已用完。{('可在 ' + reset_text + ' 后重试。') if reset_text else ''}")
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail=f"检查更新失败：{exc}") from exc
    release = response.json()
    latest = str(release.get("tag_name") or "").lstrip("v")
    return {
        "current_version": settings.version,
        "latest_version": latest,
        "has_update": latest != settings.version,
        "name": release.get("name") or release.get("tag_name"),
        "body": release.get("body") or "",
        "published_at": release.get("published_at"),
    }


@app.get("/api/discovery/mikan/catalog")
async def mikan_catalog(
    year: int = Query(ge=2010, le=2100),
    season: str = Query(),
    include_hidden: bool = Query(default=False),
    force: bool = Query(default=False),
    _: dict = Depends(ready_user),
) -> dict:
    season = normalize_season(season)
    cached = None if force else load_catalog(year, season)
    source = "cache"
    if cached is None:
        try:
            items, source_url = await fetch_catalog(year, season)
            fetched_at = save_catalog(year, season, items, source_url)
            cached = {"items": items, "fetched_at": fetched_at, "source_url": source_url, "stale": False}
            source = "remote"
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    annotated, hidden_count = apply_hidden(cached["items"], year, season, include_hidden=True)
    visible_count = len(annotated) - hidden_count
    return {
        "year": year,
        "season": season,
        "groups": group_by_weekday(annotated, include_hidden=include_hidden),
        "total_count": len(cached["items"]),
        "visible_count": visible_count,
        "hidden_count": hidden_count,
        "fetched_at": cached["fetched_at"],
        "source_url": cached["source_url"],
        "stale": cached["stale"],
        "data_source": source,
        "cache_hours": settings.mikan_cache_hours,
    }


@app.post("/api/discovery/mikan/catalog/refresh")
async def refresh_mikan_catalog(
    year: int = Query(ge=2010, le=2100),
    season: str = Query(),
    include_hidden: bool = Query(default=False),
    _: dict = Depends(ready_user),
) -> dict:
    return await mikan_catalog(year, season, include_hidden, True, _)


@app.get("/api/discovery/mikan/bangumi/{bangumi_id}")
async def mikan_detail(
    bangumi_id: int,
    base_url: str = Query(default=""),
    _: dict = Depends(ready_user),
) -> dict:
    try:
        return await fetch_bangumi_detail(bangumi_id, base_url)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/discovery/mikan/image")
async def mikan_image(url: str = Query(), _: dict = Depends(ready_user)) -> FileResponse:
    try:
        path, media_type = await fetch_image(url)
        return FileResponse(path, media_type=media_type, headers={"Cache-Control": "public, max-age=86400"})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/discovery/mikan/filters")
def get_mikan_filters(
    year: int = Query(ge=2010, le=2100),
    season: str = Query(),
    weekday: int | None = Query(default=None, ge=0, le=7),
    _: dict = Depends(ready_user),
) -> dict:
    season = normalize_season(season)
    entries = list_hidden(year, season, weekday)
    return {"year": year, "season": season, "weekday": weekday, "entries": entries, "count": len(entries)}


@app.put("/api/discovery/mikan/filters/{weekday}")
def put_mikan_filters(
    weekday: int,
    payload: HiddenPayload,
    year: int = Query(ge=2010, le=2100),
    season: str = Query(),
    _: dict = Depends(ready_user),
) -> dict:
    if weekday < 0 or weekday > 7:
        raise HTTPException(status_code=400, detail="weekday 必须是 0–7")
    season = normalize_season(season)
    entries = replace_week_hidden(year, season, weekday, [entry.model_dump() for entry in payload.entries])
    return {"ok": True, "year": year, "season": season, "weekday": weekday, "entries": entries, "count": len(entries)}


@app.delete("/api/discovery/mikan/filters/{weekday}")
def delete_mikan_filters(
    weekday: int,
    year: int = Query(ge=2010, le=2100),
    season: str = Query(),
    _: dict = Depends(ready_user),
) -> dict:
    season = normalize_season(season)
    clear_week_hidden(year, season, weekday)
    return {"ok": True, "year": year, "season": season, "weekday": weekday, "count": 0}

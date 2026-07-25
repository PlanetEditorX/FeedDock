from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, SessionLocal, engine, ensure_schema, get_db
from .downloader import QBittorrentClient
from .discovery import DiscoveryService
from .models import AdminAccount, FeedItem, Subscription, SystemLog
from .rss_service import (
    calculate_missing_episodes,
    preview_subscription,
    refresh_all,
    retry_item,
)
from .runtime_config import (
    get_app_setting,
    load_qbittorrent_config,
    reset_qbittorrent_config,
    save_qbittorrent_config,
    set_app_setting,
)
from .scheduler import start_scheduler, stop_scheduler
from .schemas import (
    AuthStatusOut,
    ChangePasswordRequest,
    DiscoverySearchOut,
    FeedItemOut,
    GlobalRulesUpdate,
    LoginRequest,
    LogOut,
    MikanBangumiDetailOut,
    MikanCatalogOut,
    QBittorrentSettingsUpdate,
    SubscriptionCreate,
    SubscriptionOut,
    SubscriptionPreviewOut,
    SubscriptionPreviewRequest,
    SubscriptionUpdate,
    UpdateStatusOut,
)
from .security import (
    SESSION_COOKIE,
    create_session_token,
    hash_password,
    initialize_admin,
    require_admin,
    require_authenticated,
    resolve_admin,
    validate_new_password,
    verify_password,
)
from .update_service import UpdateService


STATIC_DIR = Path(__file__).parent / "static"


def _set_session_cookie(response: Response, account: AdminAccount) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(account),
        max_age=settings.session_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def _subscription_values(payload: SubscriptionCreate | SubscriptionUpdate | SubscriptionPreviewRequest) -> dict[str, Any]:
    values = payload.model_dump(exclude_unset=isinstance(payload, SubscriptionUpdate), exclude={"sample_title"})
    for key in ("rss_url", "backup_rss_url"):
        if key in values:
            values[key] = str(values[key]) if values[key] is not None else ""
    if "air_date" in values:
        values["air_date"] = values["air_date"].isoformat() if values["air_date"] else ""
    for key, value in list(values.items()):
        if isinstance(value, str):
            values[key] = value.strip()
    if values.get("include_keywords") in {"无", "none", "None"}:
        values["include_keywords"] = ""
    return values


def _subscription_out(db: Session, subscription: Subscription) -> SubscriptionOut:
    output = SubscriptionOut.model_validate(subscription)
    if subscription.missing_detection:
        output.missing_episodes = calculate_missing_episodes(db, subscription)
    return output


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    with SessionLocal() as db:
        initialize_admin(db)
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="自托管 RSS 自动订阅与 qBittorrent 推送工具",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index(request: Request, db: Session = Depends(get_db)) -> Response:
    account = resolve_admin(request, db)
    if not account:
        return RedirectResponse("/login", status_code=303)
    if account.must_change_password:
        return RedirectResponse("/change-password", status_code=303)
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/login", include_in_schema=False)
def login_page(request: Request, db: Session = Depends(get_db)) -> Response:
    account = resolve_admin(request, db)
    if account:
        target = "/change-password" if account.must_change_password else "/"
        return RedirectResponse(target, status_code=303)
    return FileResponse(STATIC_DIR / "login.html")


@app.get("/change-password", include_in_schema=False)
def change_password_page(request: Request, db: Session = Depends(get_db)) -> Response:
    account = resolve_admin(request, db)
    if not account:
        return RedirectResponse("/login", status_code=303)
    if not account.must_change_password:
        return RedirectResponse("/", status_code=303)
    return FileResponse(STATIC_DIR / "change-password.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": settings.app_version}


@app.get("/api/auth/status", response_model=AuthStatusOut)
def auth_status(request: Request, db: Session = Depends(get_db)) -> AuthStatusOut:
    account = resolve_admin(request, db)
    if not account:
        return AuthStatusOut(authenticated=False)
    return AuthStatusOut(
        authenticated=True,
        username=account.username,
        must_change_password=account.must_change_password,
    )


@app.post("/api/auth/login", response_model=AuthStatusOut)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> AuthStatusOut:
    account = db.scalar(select(AdminAccount).where(AdminAccount.username == payload.username))
    if not account or not verify_password(payload.password, account.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    _set_session_cookie(response, account)
    return AuthStatusOut(
        authenticated=True,
        username=account.username,
        must_change_password=account.must_change_password,
    )


@app.post("/api/auth/change-password", response_model=AuthStatusOut)
def change_password(
    payload: ChangePasswordRequest,
    response: Response,
    account: AdminAccount = Depends(require_authenticated),
    db: Session = Depends(get_db),
) -> AuthStatusOut:
    if not verify_password(payload.current_password, account.password_hash):
        raise HTTPException(status_code=400, detail="当前密码不正确")
    validate_new_password(payload.new_password, account.username)
    if verify_password(payload.new_password, account.password_hash):
        raise HTTPException(status_code=422, detail="新密码不能与当前密码相同")
    account.password_hash = hash_password(payload.new_password)
    account.must_change_password = False
    account.session_version += 1
    db.commit()
    db.refresh(account)
    _set_session_cookie(response, account)
    return AuthStatusOut(authenticated=True, username=account.username, must_change_password=False)


@app.post("/api/auth/logout")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@app.get("/api/config", dependencies=[Depends(require_admin)])
def get_config(db: Session = Depends(get_db)) -> dict[str, str | int | bool]:
    qbit = load_qbittorrent_config(db)
    return {
        "app_name": settings.app_name,
        "app_version": settings.app_version,
        "poll_interval_minutes": settings.poll_interval_minutes,
        **qbit.public_dict(),
        "timezone": settings.timezone,
        "update_repository": settings.update_repository,
        "updater_configured": bool(settings.watchtower_url and settings.watchtower_token),
        "deployed_image": settings.deployed_image,
    }


@app.get("/api/downloader/settings", dependencies=[Depends(require_admin)])
def get_downloader_settings(db: Session = Depends(get_db)) -> dict[str, str | bool]:
    return load_qbittorrent_config(db).public_dict()


@app.put("/api/downloader/settings", dependencies=[Depends(require_admin)])
def update_downloader_settings(
    payload: QBittorrentSettingsUpdate,
    db: Session = Depends(get_db),
) -> dict[str, str | bool]:
    try:
        config = save_qbittorrent_config(
            db,
            qbit_url=payload.qbit_url,
            qbit_username=payload.qbit_username,
            qbit_password=payload.qbit_password,
            clear_password=payload.clear_password,
            qbit_category=payload.qbit_category,
            download_path=payload.download_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return config.public_dict()


@app.delete("/api/downloader/settings", dependencies=[Depends(require_admin)])
def restore_downloader_settings(db: Session = Depends(get_db)) -> dict[str, str | bool]:
    return reset_qbittorrent_config(db).public_dict()


@app.get("/api/rules/global", dependencies=[Depends(require_admin)])
def get_global_rules(db: Session = Depends(get_db)) -> dict[str, str]:
    return {"exclude_rules": get_app_setting("global_exclude_rules", "", db)}


@app.put("/api/rules/global", dependencies=[Depends(require_admin)])
def update_global_rules(payload: GlobalRulesUpdate, db: Session = Depends(get_db)) -> dict[str, str]:
    value = set_app_setting(db, "global_exclude_rules", payload.exclude_rules.strip())
    return {"exclude_rules": value}


@app.get(
    "/api/discovery/mikan/catalog",
    response_model=MikanCatalogOut,
    dependencies=[Depends(require_admin)],
)
def mikan_catalog(
    year: int = Query(ge=2000, le=2100),
    season: str = Query(pattern="^(冬|春|夏|秋)$"),
    q: str = Query(default="", max_length=200),
) -> dict[str, Any]:
    try:
        return DiscoveryService().catalog(year, season, q)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Mikan 番剧目录解析失败：{exc}") from exc


@app.get(
    "/api/discovery/search",
    response_model=DiscoverySearchOut,
    dependencies=[Depends(require_admin)],
)
def search_sources(
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=20, ge=1, le=50),
) -> dict[str, Any]:
    return DiscoveryService().search(q, limit)


@app.get(
    "/api/discovery/mikan/{bangumi_id}",
    response_model=MikanBangumiDetailOut,
    dependencies=[Depends(require_admin)],
)
def mikan_bangumi_detail(
    bangumi_id: int,
    base_url: str = Query(default="", max_length=500),
    title: str = Query(default="", max_length=300),
) -> dict[str, Any]:
    try:
        return DiscoveryService().mikan_detail(bangumi_id, base_url, title)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Mikan 解析失败：{exc}") from exc


@app.get("/api/dashboard", dependencies=[Depends(require_admin)])
def dashboard(db: Session = Depends(get_db)) -> dict[str, int]:
    statuses = dict(db.execute(select(FeedItem.status, func.count()).group_by(FeedItem.status)).all())
    return {
        "subscriptions": db.scalar(select(func.count()).select_from(Subscription)) or 0,
        "enabled_subscriptions": db.scalar(
            select(func.count()).select_from(Subscription).where(Subscription.enabled.is_(True))
        ) or 0,
        "queued": int(statuses.get("queued", 0)),
        "skipped": int(statuses.get("skipped", 0)),
        "errors": int(statuses.get("error", 0)),
        "items": sum(int(value) for value in statuses.values()),
    }


@app.get("/api/subscriptions", response_model=list[SubscriptionOut], dependencies=[Depends(require_admin)])
def list_subscriptions(db: Session = Depends(get_db)) -> list[SubscriptionOut]:
    subscriptions = list(db.scalars(select(Subscription).order_by(desc(Subscription.id))))
    return [_subscription_out(db, subscription) for subscription in subscriptions]


@app.post("/api/subscriptions/preview", response_model=SubscriptionPreviewOut, dependencies=[Depends(require_admin)])
def preview_subscription_route(
    payload: SubscriptionPreviewRequest,
    db: Session = Depends(get_db),
) -> dict[str, str | bool]:
    values = _subscription_values(payload)
    subscription = Subscription(**values)
    sample_title = payload.sample_title or payload.reference_title or payload.name
    return preview_subscription(subscription, sample_title, db)


@app.post("/api/subscriptions", response_model=SubscriptionOut, dependencies=[Depends(require_admin)])
def create_subscription(payload: SubscriptionCreate, db: Session = Depends(get_db)) -> SubscriptionOut:
    subscription = Subscription(**_subscription_values(payload))
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return _subscription_out(db, subscription)


@app.patch(
    "/api/subscriptions/{subscription_id}",
    response_model=SubscriptionOut,
    dependencies=[Depends(require_admin)],
)
def update_subscription(
    subscription_id: int,
    payload: SubscriptionUpdate,
    db: Session = Depends(get_db),
) -> SubscriptionOut:
    subscription = db.get(Subscription, subscription_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="订阅不存在")
    for key, value in _subscription_values(payload).items():
        setattr(subscription, key, value)
    db.commit()
    db.refresh(subscription)
    return _subscription_out(db, subscription)


@app.delete("/api/subscriptions/{subscription_id}", dependencies=[Depends(require_admin)])
def delete_subscription(subscription_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    subscription = db.get(Subscription, subscription_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="订阅不存在")
    db.delete(subscription)
    db.commit()
    return {"ok": True}


@app.get("/api/items", response_model=list[FeedItemOut], dependencies=[Depends(require_admin)])
def list_items(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[FeedItem]:
    query = select(FeedItem).order_by(desc(FeedItem.created_at)).limit(limit)
    if status:
        query = query.where(FeedItem.status == status)
    return list(db.scalars(query))


@app.post("/api/items/{item_id}/retry", dependencies=[Depends(require_admin)])
def retry_feed_item(item_id: int, db: Session = Depends(get_db)) -> dict[str, bool | str]:
    item = db.get(FeedItem, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="条目不存在")
    ok, message = retry_item(db, item)
    return {"ok": ok, "message": message}


@app.get("/api/logs", response_model=list[LogOut], dependencies=[Depends(require_admin)])
def list_logs(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[SystemLog]:
    return list(db.scalars(select(SystemLog).order_by(desc(SystemLog.created_at)).limit(limit)))


@app.post("/api/actions/refresh", dependencies=[Depends(require_admin)])
def manual_refresh(background_tasks: BackgroundTasks) -> dict[str, bool | str]:
    background_tasks.add_task(refresh_all)
    return {"ok": True, "message": "刷新任务已启动"}


@app.post("/api/actions/test-downloader", dependencies=[Depends(require_admin)])
def test_downloader() -> dict[str, bool | str]:
    result = QBittorrentClient().test()
    return {"ok": result.ok, "message": result.message}


@app.get(
    "/api/update/status",
    response_model=UpdateStatusOut,
    dependencies=[Depends(require_admin)],
)
def update_status() -> dict[str, str | bool]:
    # This endpoint is intentionally only called by an explicit button click.
    return UpdateService().check().as_dict()


@app.post("/api/update/apply", dependencies=[Depends(require_admin)])
def apply_update() -> dict[str, bool | str]:
    ok, message = UpdateService().trigger_update()
    return {"ok": ok, "message": message}

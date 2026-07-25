from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, SessionLocal, engine, get_db
from .downloader import QBittorrentClient
from .models import AdminAccount, FeedItem, Subscription, SystemLog
from .rss_service import refresh_all, retry_item
from .scheduler import start_scheduler, stop_scheduler
from .schemas import (
    AuthStatusOut,
    ChangePasswordRequest,
    FeedItemOut,
    LoginRequest,
    LogOut,
    SubscriptionCreate,
    SubscriptionOut,
    SubscriptionUpdate,
    UpdateStatusOut,
)
from .security import (
    SESSION_COOKIE,
    create_session_token,
    initialize_admin,
    require_admin,
    require_authenticated,
    resolve_admin,
    validate_new_password,
    verify_password,
    hash_password,
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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
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
def get_config() -> dict[str, str | int | bool]:
    return {
        "app_name": settings.app_name,
        "app_version": settings.app_version,
        "poll_interval_minutes": settings.poll_interval_minutes,
        "qbit_url": settings.qbit_url,
        "qbit_username": settings.qbit_username,
        "qbit_password_configured": bool(settings.qbit_password),
        "qbit_category": settings.qbit_category,
        "download_path": settings.download_path,
        "timezone": settings.timezone,
        "update_repository": settings.update_repository,
        "updater_configured": bool(settings.watchtower_url and settings.watchtower_token),
    }


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
def list_subscriptions(db: Session = Depends(get_db)) -> list[Subscription]:
    return list(db.scalars(select(Subscription).order_by(desc(Subscription.id))))


@app.post("/api/subscriptions", response_model=SubscriptionOut, dependencies=[Depends(require_admin)])
def create_subscription(payload: SubscriptionCreate, db: Session = Depends(get_db)) -> Subscription:
    subscription = Subscription(
        name=payload.name,
        rss_url=str(payload.rss_url),
        include_keywords=payload.include_keywords,
        exclude_keywords=payload.exclude_keywords,
        episode_regex=payload.episode_regex,
        save_path_template=payload.save_path_template,
        enabled=payload.enabled,
    )
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return subscription


@app.patch(
    "/api/subscriptions/{subscription_id}",
    response_model=SubscriptionOut,
    dependencies=[Depends(require_admin)],
)
def update_subscription(
    subscription_id: int,
    payload: SubscriptionUpdate,
    db: Session = Depends(get_db),
) -> Subscription:
    subscription = db.get(Subscription, subscription_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="订阅不存在")
    values = payload.model_dump(exclude_unset=True)
    if "rss_url" in values:
        values["rss_url"] = str(values["rss_url"])
    for key, value in values.items():
        if isinstance(value, str):
            value = value.strip()
        setattr(subscription, key, value)
    db.commit()
    db.refresh(subscription)
    return subscription


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
    return UpdateService().check().as_dict()


@app.post("/api/update/apply", dependencies=[Depends(require_admin)])
def apply_update() -> dict[str, bool | str]:
    ok, message = UpdateService().trigger_update()
    return {"ok": ok, "message": message}

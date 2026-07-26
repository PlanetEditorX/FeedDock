from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, desc, func, select, update
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, SessionLocal, engine, ensure_schema, get_db
from .debug_logging import (
    debug_enabled,
    log_event,
    log_exception,
    normalize_log_level,
    runtime_log_level,
    safe_json,
    set_runtime_log_level,
)
from .downloader import QBittorrentClient
from .discovery import DiscoveryService
from .mikan_cache import MikanCacheService, fetch_cached_mikan_image
from .metadata_service import MetadataService
from .models import AdminAccount, FeedItem, Subscription, SystemLog
from .naming import canonical_title, media_folder_name
from .postprocess import normalize_pending_items
from .rss_service import (
    calculate_missing_episodes,
    dispatch_scheduled_downloads,
    preview_subscription,
    refresh_all,
    retry_item,
)
from .runtime_config import (
    get_app_setting,
    load_metadata_config,
    load_automation_config,
    load_proxy_config,
    load_mikan_hidden_filters,
    load_qbittorrent_config,
    reset_metadata_config,
    reset_automation_config,
    reset_proxy_config,
    reset_qbittorrent_config,
    save_metadata_config,
    save_automation_config,
    save_proxy_config,
    save_mikan_weekday_hidden_filter,
    save_qbittorrent_config,
    set_app_setting,
)
from .scheduler import scheduler, start_scheduler, stop_scheduler
from .schemas import (
    AuthStatusOut,
    AutomationSettingsUpdate,
    ChangePasswordRequest,
    DiscoverySearchOut,
    FeedItemOut,
    GlobalRulesUpdate,
    LoginRequest,
    LogOut,
    LogSettingsUpdate,
    MetadataApplyRequest,
    MetadataCandidateOut,
    MetadataRecordOut,
    MetadataSettingsUpdate,
    MetadataSyncRequest,
    MetadataReviewSkipRequest,
    MikanBangumiDetailOut,
    MikanCatalogOut,
    MikanWeekdayFilterOut,
    MikanWeekdayFilterUpdate,
    ProxySettingsUpdate,
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
from .outbound import external_get


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


def _subscription_values(
    payload: SubscriptionCreate | SubscriptionUpdate | SubscriptionPreviewRequest,
    db: Session | None = None,
) -> dict[str, Any]:
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
    if db is not None:
        # All subscriptions use the qBittorrent-visible download root.
        values["custom_download_path"] = load_qbittorrent_config(db).download_path
    return values



def _apply_mikan_hidden_filters(
    payload: dict[str, Any],
    db: Session,
    *,
    year: int,
    season: str,
) -> dict[str, Any]:
    """Annotate cached catalog items with local hidden state.

    Items remain in the API response so the browser can enter edit mode and
    restore them without another Mikan request. Normal display filtering is
    performed locally by the UI.
    """

    filters = load_mikan_hidden_filters(db, year=year, season=season)
    total_hidden = 0
    for row in payload.get("rows", []):
        weekday = str(row.get("weekday", "")).strip()
        hidden_ids = filters.get(weekday, set())
        row_hidden = 0
        for item in row.get("items", []):
            try:
                bangumi_id = int(item.get("bangumi_id", 0))
            except (TypeError, ValueError):
                bangumi_id = 0
            hidden = bangumi_id in hidden_ids
            item["hidden"] = hidden
            if hidden:
                row_hidden += 1
        row["hidden_count"] = row_hidden
        total_hidden += row_hidden
    payload["hidden_count"] = total_hidden
    return payload

def _subscription_out(db: Session, subscription: Subscription) -> SubscriptionOut:
    output = SubscriptionOut.model_validate(subscription)
    output.canonical_title = canonical_title(subscription)
    output.media_folder = media_folder_name(subscription)
    if subscription.missing_detection:
        output.missing_episodes = calculate_missing_episodes(db, subscription)
    return output


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    with SessionLocal() as db:
        initialize_admin(db)
        # Upgrade old subscriptions to the one-root model. qBittorrent and
        # FeedDock must see the same container path (normally /media).
        qbit_root = load_qbittorrent_config(db).download_path
        db.execute(update(Subscription).values(custom_download_path=qbit_root))
        db.commit()
        set_runtime_log_level(get_app_setting("log_level", settings.log_level, db))
    log_event("INFO", "日志系统已启动", f"当前级别：{runtime_log_level()}", persist=False)
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


@app.middleware("http")
async def debug_request_middleware(request: Request, call_next):
    request_id = uuid4().hex[:12]
    request.state.request_id = request_id
    request.state.debug_stage = "request"
    request.state.debug_context = {}
    started = perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        stage = str(getattr(request.state, "debug_stage", "request"))
        context = getattr(request.state, "debug_context", {}) or {}
        log_exception(
            f"未处理的服务器异常 [{request_id}]",
            exc,
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            stage=stage,
            context=context,
        )
        detail = f"服务器内部错误 [{request_id}]：{type(exc).__name__}: {exc}"
        response = JSONResponse(status_code=500, content={"detail": detail, "request_id": request_id})
    response.headers["X-Request-ID"] = request_id
    elapsed_ms = round((perf_counter() - started) * 1000, 2)
    if debug_enabled() and request.url.path.startswith("/api/") and response.status_code < 400:
        log_event(
            "DEBUG",
            f"{request.method} {request.url.path} -> {response.status_code}",
            safe_json({
                "request_id": request_id,
                "query": dict(request.query_params),
                "elapsed_ms": elapsed_ms,
                "stage": str(getattr(request.state, "debug_stage", "completed")),
            }),
        )
    return response


@app.exception_handler(HTTPException)
async def logged_http_exception(request: Request, exc: HTTPException):
    request_id = str(getattr(request.state, "request_id", uuid4().hex[:12]))
    stage = str(getattr(request.state, "debug_stage", "http-exception"))
    context = getattr(request.state, "debug_context", {}) or {}
    cause = exc.__cause__
    if exc.status_code >= 500 and cause is not None:
        log_exception(
            f"HTTP {exc.status_code} [{request_id}]",
            cause,
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            stage=stage,
            context={**context, "http_detail": exc.detail},
        )
    elif exc.status_code >= 500 or debug_enabled():
        log_event(
            "ERROR" if exc.status_code >= 500 else "DEBUG",
            f"HTTP {exc.status_code} [{request_id}] {request.method} {request.url.path}",
            safe_json({"detail": exc.detail, "stage": stage, "context": context}),
        )
    response = await http_exception_handler(request, exc)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(RequestValidationError)
async def logged_validation_exception(request: Request, exc: RequestValidationError):
    request_id = str(getattr(request.state, "request_id", uuid4().hex[:12]))
    if debug_enabled():
        log_event(
            "DEBUG",
            f"请求参数校验失败 [{request_id}] {request.method} {request.url.path}",
            safe_json({"errors": exc.errors(), "body": exc.body}),
        )
    response = await request_validation_exception_handler(request, exc)
    response.headers["X-Request-ID"] = request_id
    return response


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


@app.get("/api/auth/bootstrap")
def auth_bootstrap(db: Session = Depends(get_db)) -> dict[str, bool]:
    account = db.scalar(select(AdminAccount).order_by(AdminAccount.id))
    return {"initial_password_change_required": bool(account and account.must_change_password)}


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
def get_config(db: Session = Depends(get_db)) -> dict[str, Any]:
    qbit = load_qbittorrent_config(db)
    metadata = load_metadata_config(db)
    return {
        "app_name": settings.app_name,
        "app_version": settings.app_version,
        "poll_interval_minutes": settings.poll_interval_minutes,
        **qbit.public_dict(),
        "timezone": settings.timezone,
        "update_repository": settings.update_repository,
        "updater_configured": bool(settings.watchtower_url and settings.watchtower_token),
        "deployed_image": settings.deployed_image,
        "mikan_cache_hours": settings.mikan_cache_hours,
        "metadata_auto_sync_hours": settings.metadata_auto_sync_hours,
        **metadata.public_dict(),
        "automation": load_automation_config(db).public_dict(),
        "proxy": load_proxy_config(db).public_dict(),
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


@app.get("/api/metadata/settings", dependencies=[Depends(require_admin)])
def get_metadata_settings(db: Session = Depends(get_db)) -> dict[str, str | bool]:
    return load_metadata_config(db).public_dict()


@app.put("/api/metadata/settings", dependencies=[Depends(require_admin)])
def update_metadata_settings(
    payload: MetadataSettingsUpdate,
    db: Session = Depends(get_db),
) -> dict[str, str | bool]:
    try:
        config = save_metadata_config(
            db,
            tmdb_read_access_token=payload.tmdb_read_access_token,
            clear_tmdb_token=payload.clear_tmdb_token,
            bangumi_access_token=payload.bangumi_access_token,
            clear_bangumi_token=payload.clear_bangumi_token,
            metadata_language=payload.metadata_language,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return config.public_dict()


@app.delete("/api/metadata/settings", dependencies=[Depends(require_admin)])
def restore_metadata_settings(db: Session = Depends(get_db)) -> dict[str, str | bool]:
    return reset_metadata_config(db).public_dict()



@app.get("/api/automation/settings", dependencies=[Depends(require_admin)])
def get_automation_settings(db: Session = Depends(get_db)) -> dict[str, str | bool]:
    return load_automation_config(db).public_dict()


@app.put("/api/automation/settings", dependencies=[Depends(require_admin)])
def update_automation_settings(payload: AutomationSettingsUpdate, db: Session = Depends(get_db)) -> dict[str, str | bool]:
    try:
        return save_automation_config(db, download_enabled=payload.download_enabled, daily_time=payload.daily_time, timezone=payload.timezone).public_dict()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/automation/settings", dependencies=[Depends(require_admin)])
def restore_automation_settings(db: Session = Depends(get_db)) -> dict[str, str | bool]:
    return reset_automation_config(db).public_dict()


@app.post("/api/automation/run", dependencies=[Depends(require_admin)])
def run_automation_now() -> dict[str, Any]:
    return scheduler.run_daily_automation(force=True)


@app.get("/api/proxy/settings", dependencies=[Depends(require_admin)])
def get_proxy_settings(db: Session = Depends(get_db)) -> dict[str, str | bool]:
    return load_proxy_config(db).public_dict()


@app.put("/api/proxy/settings", dependencies=[Depends(require_admin)])
def update_proxy_settings(payload: ProxySettingsUpdate, db: Session = Depends(get_db)) -> dict[str, str | bool]:
    try:
        return save_proxy_config(db, enabled=payload.enabled, proxy_url=payload.proxy_url, clear_proxy_url=payload.clear_proxy_url, no_proxy=payload.no_proxy).public_dict()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/proxy/settings", dependencies=[Depends(require_admin)])
def restore_proxy_settings(db: Session = Depends(get_db)) -> dict[str, str | bool]:
    return reset_proxy_config(db).public_dict()


@app.post("/api/proxy/test", dependencies=[Depends(require_admin)])
def test_proxy(db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        response = external_get("https://api.bgm.tv/v0/calendar", db=db, timeout=settings.request_timeout_seconds, headers={"User-Agent": settings.rss_user_agent})
        return {"ok": response.status_code == 200, "message": f"代理连通测试 HTTP {response.status_code}"}
    except Exception as exc:
        return {"ok": False, "message": f"代理连通失败：{exc}"}


@app.get("/api/secrets/{secret_name}", dependencies=[Depends(require_admin)])
def reveal_secret(secret_name: str, db: Session = Depends(get_db)) -> dict[str, str]:
    qbit = load_qbittorrent_config(db)
    metadata = load_metadata_config(db)
    proxy = load_proxy_config(db)
    values = {
        "qbit_password": qbit.password,
        "tmdb_read_access_token": metadata.tmdb_read_access_token,
        "bangumi_access_token": metadata.bangumi_access_token,
        "proxy_url": proxy.url,
    }
    if secret_name not in values:
        raise HTTPException(status_code=404, detail="未知密钥字段")
    return {"value": values[secret_name]}


@app.get(
    "/api/metadata/search",
    response_model=list[MetadataCandidateOut],
    dependencies=[Depends(require_admin)],
)
def search_metadata(
    provider: str = Query(pattern="^(tmdb|bangumi|anilist)$"),
    q: str = Query(min_length=1, max_length=300),
    media_type: str = Query(default="tv", pattern="^(tv|movie)$"),
    year: int = Query(default=0, ge=0, le=9999),
    limit: int = Query(default=10, ge=1, le=20),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    try:
        return MetadataService().search(
            db, provider=provider, query=q, media_type=media_type, year=year, limit=limit
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"元数据搜索失败：{exc}") from exc


@app.get(
    "/api/metadata/detail",
    response_model=MetadataRecordOut,
    dependencies=[Depends(require_admin)],
)
def metadata_detail(
    provider: str = Query(pattern="^(tmdb|bangumi|anilist)$"),
    metadata_id: int = Query(gt=0),
    media_type: str = Query(default="tv", pattern="^(tv|movie)$"),
    season: int = Query(default=1, ge=0, le=999),
    season_mode: str = Query(default="title", pattern="^(manual|latest|title)$"),
    query_title: str = Query(default="", max_length=300),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return MetadataService().get(
            db,
            provider=provider,
            metadata_id=metadata_id,
            media_type=media_type,
            season=season,
            season_mode=season_mode,
            query_title=query_title,
        ).as_dict()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"元数据详情读取失败：{exc}") from exc


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
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        payload = MikanCacheService(DiscoveryService()).catalog(db, year, season, q)
        return _apply_mikan_hidden_filters(payload, db, year=year, season=season)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Mikan 番剧目录解析失败：{exc}") from exc


@app.post(
    "/api/discovery/mikan/catalog/refresh",
    response_model=MikanCatalogOut,
    dependencies=[Depends(require_admin)],
)
def refresh_mikan_catalog(
    year: int = Query(ge=2000, le=2100),
    season: str = Query(pattern="^(冬|春|夏|秋)$"),
    q: str = Query(default="", max_length=200),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        payload = MikanCacheService(DiscoveryService()).catalog(
            db, year, season, q, force_refresh=True
        )
        return _apply_mikan_hidden_filters(payload, db, year=year, season=season)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Mikan 强制更新失败：{exc}") from exc


@app.put(
    "/api/discovery/mikan/catalog/filters",
    response_model=MikanWeekdayFilterOut,
    dependencies=[Depends(require_admin)],
)
def update_mikan_weekday_filter(
    payload: MikanWeekdayFilterUpdate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        hidden_ids = save_mikan_weekday_hidden_filter(
            db,
            year=payload.year,
            season=payload.season,
            weekday=payload.weekday,
            hidden_bangumi_ids=payload.hidden_bangumi_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "year": payload.year,
        "season": payload.season,
        "weekday": payload.weekday,
        "hidden_bangumi_ids": sorted(hidden_ids),
    }


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
    "/api/discovery/mikan/image",
    dependencies=[Depends(require_admin)],
    include_in_schema=False,
)
def mikan_cover_image(
    base_url: str = Query(min_length=1, max_length=500),
    url: str = Query(min_length=1, max_length=2000),
) -> Response:
    try:
        content, content_type, cache_hit = fetch_cached_mikan_image(
            base_url, url, discovery=DiscoveryService()
        )
        return Response(
            content=content,
            media_type=content_type,
            headers={
                "Cache-Control": (
                    f"private, max-age={settings.mikan_image_cache_days * 86400}, "
                    "immutable, stale-if-error=604800"
                ),
                "X-FeedDock-Cache": "HIT" if cache_hit else "MISS",
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Mikan 封面加载失败：{exc}") from exc


@app.get(
    "/api/discovery/mikan/{bangumi_id}",
    response_model=MikanBangumiDetailOut,
    dependencies=[Depends(require_admin)],
)
def mikan_bangumi_detail(
    bangumi_id: int,
    base_url: str = Query(default="", max_length=500),
    title: str = Query(default="", max_length=300),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return MikanCacheService(DiscoveryService()).detail(
            db, bangumi_id, base_url, title
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Mikan 解析失败：{exc}") from exc


@app.post(
    "/api/discovery/mikan/{bangumi_id}/refresh",
    response_model=MikanBangumiDetailOut,
    dependencies=[Depends(require_admin)],
)
def refresh_mikan_bangumi_detail(
    bangumi_id: int,
    base_url: str = Query(default="", max_length=500),
    title: str = Query(default="", max_length=300),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return MikanCacheService(DiscoveryService()).detail(
            db, bangumi_id, base_url, title, force_refresh=True
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Mikan 字幕组强制更新失败：{exc}") from exc


@app.get("/api/dashboard", dependencies=[Depends(require_admin)])
def dashboard(db: Session = Depends(get_db)) -> dict[str, int]:
    statuses = dict(db.execute(select(FeedItem.status, func.count()).where(FeedItem.hidden.is_(False)).group_by(FeedItem.status)).all())
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
    values = _subscription_values(payload, db)
    subscription = Subscription(**values)
    sample_title = payload.sample_title or payload.reference_title or payload.name
    return preview_subscription(subscription, sample_title, db)


@app.post("/api/subscriptions", response_model=SubscriptionOut, dependencies=[Depends(require_admin)])
def create_subscription(
    payload: SubscriptionCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> SubscriptionOut:
    request.state.debug_context = {
        "operation": "create_subscription",
        "payload": payload.model_dump(mode="json"),
    }
    try:
        request.state.debug_stage = "subscription.build-values"
        subscription = Subscription(**_subscription_values(payload, db))
        request.state.debug_stage = "subscription.insert"
        db.add(subscription)
        request.state.debug_stage = "subscription.commit"
        db.commit()
        request.state.debug_stage = "subscription.refresh"
        db.refresh(subscription)
        request.state.debug_stage = "subscription.serialize"
        return _subscription_out(db, subscription)
    except Exception:
        db.rollback()
        raise


@app.post("/api/subscriptions/{subscription_id}/metadata/skip", response_model=SubscriptionOut, dependencies=[Depends(require_admin)])
def skip_subscription_metadata_review(subscription_id: int, payload: MetadataReviewSkipRequest, db: Session = Depends(get_db)) -> SubscriptionOut:
    subscription = db.get(Subscription, subscription_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="订阅不存在")
    subscription.metadata_review_skipped = payload.skipped
    subscription.metadata_confirmed = False
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
    request: Request,
    db: Session = Depends(get_db),
) -> SubscriptionOut:
    request.state.debug_context = {
        "operation": "update_subscription",
        "subscription_id": subscription_id,
        "payload": payload.model_dump(mode="json", exclude_unset=True),
    }
    request.state.debug_stage = "subscription.load"
    subscription = db.get(Subscription, subscription_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="订阅不存在")
    try:
        request.state.debug_stage = "subscription.apply-values"
        for key, value in _subscription_values(payload, db).items():
            setattr(subscription, key, value)
        request.state.debug_stage = "subscription.commit"
        db.commit()
        request.state.debug_stage = "subscription.refresh"
        db.refresh(subscription)
        request.state.debug_stage = "subscription.serialize"
        return _subscription_out(db, subscription)
    except Exception:
        db.rollback()
        raise


@app.post(
    "/api/subscriptions/{subscription_id}/metadata/apply",
    response_model=SubscriptionOut,
    dependencies=[Depends(require_admin)],
)
def apply_subscription_metadata(
    subscription_id: int,
    payload: MetadataApplyRequest,
    db: Session = Depends(get_db),
) -> SubscriptionOut:
    subscription = db.get(Subscription, subscription_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="订阅不存在")
    try:
        MetadataService().apply(
            db,
            subscription,
            provider=payload.provider,
            metadata_id=payload.metadata_id,
            media_type=payload.media_type,
            season=payload.season,
            season_mode=payload.season_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"元数据读取失败：{exc}") from exc
    return _subscription_out(db, subscription)


@app.post(
    "/api/subscriptions/{subscription_id}/metadata/sync",
    response_model=SubscriptionOut,
    dependencies=[Depends(require_admin)],
)
def sync_subscription_metadata(
    subscription_id: int,
    payload: MetadataSyncRequest,
    db: Session = Depends(get_db),
) -> SubscriptionOut:
    subscription = db.get(Subscription, subscription_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="订阅不存在")
    try:
        MetadataService().sync(db, subscription, payload.provider)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"元数据同步失败：{exc}") from exc
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
    query = select(FeedItem).where(FeedItem.hidden.is_(False)).order_by(desc(FeedItem.created_at)).limit(limit)
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


@app.delete("/api/items", dependencies=[Depends(require_admin)])
def clear_recent_items(
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict[str, int | bool | str]:
    """Hide history rows without deleting fingerprints used for RSS deduplication."""

    conditions = [FeedItem.hidden.is_(False)]
    if status:
        conditions.append(FeedItem.status == status)
    result = db.execute(update(FeedItem).where(*conditions).values(hidden=True))
    db.commit()
    count = int(result.rowcount or 0)
    return {"ok": True, "count": count, "message": f"已清理 {count} 条最近记录（不会重复下载）"}


@app.get("/api/logs/settings", dependencies=[Depends(require_admin)])
def get_log_settings(db: Session = Depends(get_db)) -> dict[str, str]:
    level = normalize_log_level(get_app_setting("log_level", settings.log_level, db))
    if level != runtime_log_level():
        set_runtime_log_level(level)
    return {"level": level, "file": str(settings.data_dir / "logs" / "feeddock.log")}


@app.put("/api/logs/settings", dependencies=[Depends(require_admin)])
def update_log_settings(
    payload: LogSettingsUpdate,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    level = set_runtime_log_level(payload.level)
    set_app_setting(db, "log_level", level)
    log_event("INFO", "日志级别已更新", f"当前级别：{level}")
    return {"level": level, "file": str(settings.data_dir / "logs" / "feeddock.log")}


@app.get("/api/logs", response_model=list[LogOut], dependencies=[Depends(require_admin)])
def list_logs(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[SystemLog]:
    return list(db.scalars(select(SystemLog).order_by(desc(SystemLog.created_at)).limit(limit)))


@app.delete("/api/logs", dependencies=[Depends(require_admin)])
def clear_logs(db: Session = Depends(get_db)) -> dict[str, int | bool | str]:
    result = db.execute(delete(SystemLog))
    db.commit()
    count = int(result.rowcount or 0)
    return {"ok": True, "count": count, "message": f"已清理 {count} 条系统日志"}


@app.post("/api/actions/refresh", dependencies=[Depends(require_admin)])
def manual_refresh(background_tasks: BackgroundTasks) -> dict[str, bool | str]:
    background_tasks.add_task(refresh_all)
    return {"ok": True, "message": "刷新任务已启动"}


@app.post("/api/actions/normalize-torrents", dependencies=[Depends(require_admin)])
def normalize_torrents_now() -> dict[str, Any]:
    return normalize_pending_items(limit=200)


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

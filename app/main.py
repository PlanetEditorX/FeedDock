from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, desc, func, or_, select, update
from sqlalchemy.orm import Session

from .config import settings
from .anime_catalog import AnimeCatalogCacheService, decorate_catalog
from .backup_service import (
    export_subscriptions_payload,
    export_system_backup,
    import_anime_preferences,
    import_app_settings,
    validate_system_backup,
)
from .anime_identity import (
    backfill_subscription_identities,
    build_subscription_index,
    decorate_item,
    normalize_title,
    prepare_subscription_identity,
    subscription_aliases,
    subscription_identity,
    subscriptions_related,
)
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
from .mikan_subscription import collect_subscribed_mikan_bangumi_ids
from .notification_config import (
    load_notification_config,
    reset_notification_config,
    save_notification_config,
)
from .notifications import send_notification
from .notification.service import preview_notification
from .metadata_service import MetadataService
from .metadata_tasks import refresh_all_metadata, scrape_completed_media
from .models import AdminAccount, AnimePreference, FeedItem, Subscription, SystemLog
from .naming import canonical_title, media_folder_name, title_with_year
from .postprocess import normalize_pending_items
from .download_cleanup import cleanup_completed_torrent_records
from .subscription_monitor import reset_monitor_state_for_changes
from .trial import (
    BULK_TRIAL_SAVE_PATH_TEMPLATE,
    LEGACY_BULK_TRIAL_SAVE_PATH_TEMPLATE,
    SINGLE_TRIAL_SAVE_PATH_TEMPLATE,
    SUBSCRIBED_SAVE_PATH_TEMPLATE,
    TRIAL_SKIP_REASON,
    select_trial_preset,
)
from .trial_migration import promote_trial_download
from .subscription_sources import (
    classify_subscription_source,
    get_subscription_source,
    subscription_source_catalog,
    subscription_source_label,
)
from .rss_candidates import search_subscription_rss_candidates
from .rss_service import (
    add_log,
    calculate_missing_episodes,
    dispatch_scheduled_downloads,
    preview_subscription,
    refresh_all,
    refresh_subscription,
    retry_item,
)
from .runtime_config import (
    get_app_setting,
    load_metadata_config,
    load_automation_config,
    load_proxy_config,
    load_rss_poll_config,
    load_mikan_hidden_filters,
    load_qbittorrent_config,
    reset_metadata_config,
    reset_automation_config,
    reset_proxy_config,
    reset_rss_poll_config,
    reset_qbittorrent_config,
    save_metadata_config,
    save_automation_config,
    save_proxy_config,
    save_rss_poll_config,
    save_mikan_weekday_hidden_filter,
    save_qbittorrent_config,
    set_app_setting,
)
from .settings_config import (
    load_application_preferences,
    normalize_tracker_text,
    reset_application_preferences,
    save_application_preferences,
    save_subscription_sort_preference,
    save_tracker_cache,
)
from .scheduler import scheduler, start_scheduler, stop_scheduler
from .schemas import (
    AnimePreferenceBatchUpdate,
    ApplicationPreferencesUpdate,
    SubscriptionSortUpdate,
    AuthStatusOut,
    AutomationSettingsUpdate,
    ChangePasswordRequest,
    DiscoverySearchOut,
    FeedItemOut,
    GlobalRulesUpdate,
    LoginRequest,
    LogOut,
    LogSettingsUpdate,
    ManualTrialStartRequest,
    MetadataApplyRequest,
    MetadataCandidateOut,
    MetadataRecordOut,
    MetadataSettingsUpdate,
    MetadataSyncRequest,
    MetadataReviewSkipRequest,
    NotificationPreviewRequest,
    NotificationSettingsUpdate,
    MikanBangumiDetailOut,
    MikanCatalogOut,
    MikanTrialRequest,
    MikanWeekdayFilterOut,
    SourceCatalogDetailQuery,
    MikanWeekdayFilterUpdate,
    ProxySettingsUpdate,
    QBittorrentSettingsUpdate,
    RssCandidateSearchRequest,
    RssPollSettingsUpdate,
    SubscriptionBatchRequest,
    SubscriptionCreate,
    SubscriptionImportRequest,
    SubscriptionOut,
    SubscriptionPreviewOut,
    SubscriptionPreviewRequest,
    SubscriptionUpdate,
    SystemBackupImportRequest,
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
from .system_control import terminate_process
from .outbound import external_get
from .network_diagnostics import diagnose_dns


STATIC_DIR = Path(__file__).parent / "static"


def _render_static_page(filename: str) -> HTMLResponse:
    """Render an HTML shell with a cache key tied to the running image build."""

    asset_version = (settings.app_revision[:12] or settings.app_version or "dev").replace("/", "-")
    html = (STATIC_DIR / filename).read_text(encoding="utf-8").replace(
        "__FEEDDOCK_ASSET_VERSION__",
        asset_version,
    )
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


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


def _validate_auto_skip_rename_requirement(
    db: Session,
    values: dict[str, Any],
    *,
    existing: Subscription | None = None,
) -> None:
    """Prevent subscriptions from violating global file-skip prerequisites.

    The browser disables invalid combinations, but imports, batch actions and
    direct API calls must enforce the same rule on the server.
    """

    if not load_application_preferences(db).rss.auto_skip_existing:
        return
    enabled = bool(values.get("enabled", existing.enabled if existing is not None else True))
    rename_enabled = bool(
        values.get("rename_enabled", existing.rename_enabled if existing is not None else True)
    )
    if enabled and not rename_enabled:
        raise HTTPException(
            status_code=422,
            detail='启用“文件已下载自动跳过”时，所有启用订阅都必须开启自动重命名',
        )


def _refresh_subscription_identity(db: Session, subscription: Subscription) -> None:
    values: dict[str, Any] = {}
    prepare_subscription_identity(values, existing=subscription)
    changed = False
    for field in ("source_type", "source_anime_id", "canonical_key", "bangumi_id"):
        if field not in values:
            continue
        value = values[field]
        if getattr(subscription, field) != value:
            setattr(subscription, field, value)
            changed = True
    if changed:
        db.commit()
        db.refresh(subscription)


def _subscription_values(
    payload: SubscriptionCreate | SubscriptionUpdate | SubscriptionPreviewRequest,
    db: Session | None = None,
    *,
    existing: Subscription | None = None,
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
    current_mode = existing.subscription_mode if existing is not None else "subscribed"
    next_mode = values.get("subscription_mode", current_mode)
    if existing is not None and current_mode == "trial" and values.get("enabled") is True and next_mode == "trial":
        next_mode = "subscribed"
        values["subscription_mode"] = "subscribed"
    if next_mode == "trial":
        values["enabled"] = False
        values["save_path_template"] = (
            BULK_TRIAL_SAVE_PATH_TEMPLATE
            if values.get("trial_bulk", existing.trial_bulk if existing is not None else False)
            else SINGLE_TRIAL_SAVE_PATH_TEMPLATE
        )
    elif existing is not None and current_mode == "trial" and next_mode == "subscribed":
        values["trial_bulk"] = False
        if (
            "save_path_template" not in values
            and existing.save_path_template in {
                LEGACY_BULK_TRIAL_SAVE_PATH_TEMPLATE,
                BULK_TRIAL_SAVE_PATH_TEMPLATE,
                SINGLE_TRIAL_SAVE_PATH_TEMPLATE,
            }
        ):
            values["save_path_template"] = SUBSCRIBED_SAVE_PATH_TEMPLATE
    prepare_subscription_identity(values, existing=existing)
    if db is not None:
        # qBittorrent, FeedDock scraping, and subscription rendering must use
        # one identical container path. Customize only the folder template.
        values["custom_download_path"] = load_qbittorrent_config(db).download_path
    return values


def _clear_trial_only_skips(db: Session, subscription: Subscription, values: dict[str, Any]) -> int:
    """Make episodes skipped only by trial mode eligible after promotion."""

    if subscription.subscription_mode != "trial":
        return 0
    if values.get("subscription_mode", subscription.subscription_mode) != "subscribed":
        return 0
    result = db.execute(
        delete(FeedItem).where(
            FeedItem.subscription_id == subscription.id,
            FeedItem.status == "skipped",
            FeedItem.reason == TRIAL_SKIP_REASON,
        )
    )
    return int(result.rowcount or 0)



def _migrate_started_trial_download(db: Session, subscription: Subscription) -> None:
    """Best-effort migration of the watched episode after trial promotion."""

    result = promote_trial_download(db, subscription)
    if not result.found:
        return
    level = "INFO" if result.moved or "目标位置" in result.message else "WARNING"
    details = (
        f"订阅 ID：{subscription.id}\n条目 ID：{result.item_id}\n"
        f"原试看路径：{result.source_path or '未记录'}\n"
        f"目标路径：{result.target_path or '未迁移'}\n结果：{result.message}"
    )
    add_log(db, level, f"试看文件迁移：{subscription.name}", details)


def _apply_mikan_hidden_filters(
    payload: dict[str, Any],
    db: Session,
    *,
    year: int,
    season: str,
) -> dict[str, Any]:
    """Decorate Mikan rows with cross-site subscriptions and unified hidden preferences."""

    legacy_filters = load_mikan_hidden_filters(db, year=year, season=season)
    subscriptions = list(db.scalars(select(Subscription)))
    preferences = list(db.scalars(select(AnimePreference).where(AnimePreference.hidden.is_(True))))
    subscription_index, alias_index = build_subscription_index(subscriptions)
    total_hidden = 0
    for row in payload.get("rows", []):
        weekday = str(row.get("weekday", "")).strip()
        legacy_hidden_ids = legacy_filters.get(weekday, set())
        row_hidden = 0
        decorated_items = []
        for raw in row.get("items", []):
            try:
                mikan_id = int(raw.get("bangumi_id", 0))
            except (TypeError, ValueError):
                mikan_id = 0
            item = dict(raw)
            item.update({
                "source_type": "mikan",
                "source_anime_id": str(mikan_id) if mikan_id else "",
                "subject_id": 0,
                "mikan_id": mikan_id,
                "aliases": [str(item.get("title", "") or "")],
            })
            item = decorate_item(
                item,
                current_source="mikan",
                subscription_index=subscription_index,
                alias_index=alias_index,
                preferences=preferences,
            )
            item["hidden"] = bool(item["hidden"] or mikan_id in legacy_hidden_ids)
            item["available"] = True
            item["action_text"] = "点击查看 Mikan 字幕组和 RSS"
            if item["hidden"]:
                row_hidden += 1
            decorated_items.append(item)
        row["items"] = decorated_items
        row["hidden_count"] = row_hidden
        total_hidden += row_hidden
    payload["hidden_count"] = total_hidden
    payload["source_id"] = "mikan"
    return payload


def _catalog_subscription_data(
    item: dict[str, Any],
    row: dict[str, Any],
    *,
    year: int,
) -> dict[str, Any]:
    """Copy already-loaded catalog data without invoking metadata providers."""

    def first_text(*keys: str) -> str:
        return next(
            (
                str(item.get(key) or "").strip()
                for key in keys
                if str(item.get(key) or "").strip()
            ),
            "",
        )

    try:
        rating = max(0.0, min(10.0, float(item.get("rating") or 0.0)))
    except (TypeError, ValueError):
        rating = 0.0
    try:
        metadata_year = int(item.get("year") or year)
    except (TypeError, ValueError):
        metadata_year = year

    return {
        "reference_title": first_text("title", "title_original", "title_english"),
        "poster_url": first_text("cover_proxy_url", "cover_url", "poster_url"),
        "metadata_overview": first_text(
            "metadata_overview",
            "overview",
            "description",
            "summary",
            "introduction",
            "synopsis",
        ),
        "metadata_rating": rating,
        "metadata_year": metadata_year,
        "catalog_weekday": first_text("weekday") or str(row.get("weekday") or "").strip(),
        "catalog_air_time": first_text("air_time", "update_at", "broadcast_time"),
    }


def _apply_catalog_subscription_data(
    subscription: Subscription,
    values: dict[str, Any],
) -> bool:
    """Backfill a trial from catalog fields without erasing richer values."""

    changed = False
    for field in (
        "reference_title",
        "poster_url",
        "metadata_overview",
        "catalog_weekday",
        "catalog_air_time",
    ):
        value = str(values.get(field) or "").strip()
        if value and getattr(subscription, field) != value:
            setattr(subscription, field, value)
            changed = True
    for field in ("metadata_rating", "metadata_year"):
        value = values.get(field) or 0
        if value and getattr(subscription, field) != value:
            setattr(subscription, field, value)
            changed = True
    return changed


def _create_mikan_trials(
    db: Session,
    *,
    year: int,
    season: str,
    payload: dict[str, Any] | None = None,
) -> list[Subscription]:
    """Use the first Mikan RSS group for each visible, unsubscribed title."""
    catalog = payload or MikanCacheService(DiscoveryService()).catalog(db, year, season)
    decorated = _apply_mikan_hidden_filters(catalog, db, year=year, season=season)
    service = MikanCacheService(DiscoveryService())
    created: list[Subscription] = []
    updated = 0

    trial_subscription_ids = set()
    for row in decorated.get("rows", []):
        for item in row.get("items", []):
            if item.get("hidden") or item.get("subscribed") or not int(item.get("bangumi_id") or 0):
                continue
            if item.get("trialed"):
                for match in item.get("subscriptions", []):
                    if match.get("subscription_mode") == "trial":
                        trial_subscription_ids.add(int(match["subscription_id"]))

    subscriptions_map = {}
    if trial_subscription_ids:
        subs = db.scalars(select(Subscription).where(Subscription.id.in_(trial_subscription_ids))).all()
        subscriptions_map = {sub.id: sub for sub in subs}

    existing_rss_urls = set(db.scalars(select(Subscription.rss_url)).all())

    for row in decorated.get("rows", []):
        for item in row.get("items", []):
            if item.get("hidden") or item.get("subscribed") or not int(item.get("bangumi_id") or 0):
                continue
            catalog_values = _catalog_subscription_data(item, row, year=year)
            if item.get("trialed"):
                for match in item.get("subscriptions", []):
                    if match.get("subscription_mode") != "trial":
                        continue
                    subscription = subscriptions_map.get(int(match["subscription_id"]))
                    if subscription and _apply_catalog_subscription_data(subscription, catalog_values):
                        updated += 1
                continue
            try:
                detail = service.detail(
                    db, int(item["bangumi_id"]), str(item.get("base_url") or ""), str(item.get("title") or "")
                )
            except Exception as exc:
                add_log(db, "WARNING", f"试看未能读取 Mikan RSS：{item.get('title') or '未命名番剧'}", str(exc))
                continue
            preset = select_trial_preset(detail.get("groups", []))
            if preset is None:
                continue
            values = dict(preset)
            values.update(catalog_values)
            values.update(subscription_mode="trial", trial_bulk=True)
            values = _subscription_values(SubscriptionCreate.model_validate(values), db)
            if str(values["rss_url"]) in existing_rss_urls:
                continue
            existing_rss_urls.add(str(values["rss_url"]))
            subscription = Subscription(**values)
            db.add(subscription)
            created.append(subscription)
    if created or updated:
        add_log(
            db,
            "INFO",
            f"已创建 {len(created)} 条 Mikan 试看订阅，补齐 {updated} 条目录数据",
            f"季度：{year} {season}",
        )
        db.commit()
    return created


def _create_catalog_trials(db: Session, *, source_id: str, year: int, season: str) -> list[Subscription]:
    """Create first-episode trial records for any supported native catalog."""
    service = AnimeCatalogCacheService()
    catalog = service.catalog(db, source_id, year, season)
    decorated = decorate_catalog(
        catalog,
        source_id,
        list(db.scalars(select(Subscription))),
        list(db.scalars(select(AnimePreference).where(AnimePreference.hidden.is_(True)))),
    )
    created: list[Subscription] = []
    updated = 0

    trial_subscription_ids = set()
    for row in decorated.get("rows", []):
        for item in row.get("items", []):
            if item.get("hidden") or item.get("subscribed"):
                continue
            if item.get("trialed"):
                for match in item.get("subscriptions", []):
                    if match.get("subscription_mode") == "trial":
                        trial_subscription_ids.add(int(match["subscription_id"]))

    subscriptions_map = {}
    if trial_subscription_ids:
        subs = db.scalars(select(Subscription).where(Subscription.id.in_(trial_subscription_ids))).all()
        subscriptions_map = {sub.id: sub for sub in subs}

    existing_rss_urls = set(db.scalars(select(Subscription.rss_url)).all())

    for row in decorated.get("rows", []):
        for item in row.get("items", []):
            if item.get("hidden") or item.get("subscribed"):
                continue
            catalog_values = _catalog_subscription_data(item, row, year=year)
            if item.get("trialed"):
                for match in item.get("subscriptions", []):
                    if match.get("subscription_mode") != "trial":
                        continue
                    subscription = subscriptions_map.get(int(match["subscription_id"]))
                    if subscription and _apply_catalog_subscription_data(subscription, catalog_values):
                        updated += 1
                continue
            try:
                detail = service.detail(db, source_id, item)
            except Exception as exc:
                add_log(db, "WARNING", f"试看未能读取 {source_id} RSS：{item.get('title') or '未命名番剧'}", str(exc))
                continue
            preset = select_trial_preset(detail.get("groups", []))
            if preset is None:
                continue
            values = dict(preset)
            values.update(catalog_values)
            values.update(subscription_mode="trial", trial_bulk=True)
            values = _subscription_values(SubscriptionCreate.model_validate(values), db)
            if str(values["rss_url"]) in existing_rss_urls:
                continue
            existing_rss_urls.add(str(values["rss_url"]))
            subscription = Subscription(**values)
            db.add(subscription)
            created.append(subscription)
    if created or updated:
        db.commit()
    return created


def _subscription_out(db: Session, subscription: Subscription) -> SubscriptionOut:
    output = SubscriptionOut.model_validate(subscription)
    output.source_type = subscription.source_type or classify_subscription_source(subscription.rss_url)
    output.source_label = get_subscription_source(output.source_type).label
    output.source_anime_id = subscription.source_anime_id
    output.canonical_key = subscription.canonical_key
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
        backfill_subscription_identities(db)
        # Trial entries are retained for manual promotion or deletion only.
        # Existing databases may still contain enabled trial rows from older versions.
        db.execute(
            update(Subscription)
            .where(Subscription.subscription_mode == "trial", Subscription.enabled.is_(True))
            .values(enabled=False)
        )
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
    return _render_static_page("index.html")


@app.get("/login", include_in_schema=False)
def login_page(request: Request, db: Session = Depends(get_db)) -> Response:
    account = resolve_admin(request, db)
    if account:
        target = "/change-password" if account.must_change_password else "/"
        return RedirectResponse(target, status_code=303)
    return _render_static_page("login.html")


@app.get("/change-password", include_in_schema=False)
def change_password_page(request: Request, db: Session = Depends(get_db)) -> Response:
    account = resolve_admin(request, db)
    if not account:
        return RedirectResponse("/login", status_code=303)
    return _render_static_page("change-password.html")


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
        "poll_interval_minutes": load_rss_poll_config(db).minutes,
        **qbit.public_dict(),
        "timezone": settings.timezone,
        "app_revision": settings.app_revision,
        "updater_configured": bool(settings.watchtower_url and settings.watchtower_token),
        "deployed_image": settings.deployed_image,
        "mikan_cache_hours": settings.mikan_cache_hours,
        "metadata_auto_sync_hours": settings.metadata_auto_sync_hours,
        **metadata.public_dict(),
        "preferences": load_application_preferences(db).public_dict(),
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
            qbit_auth_mode=payload.qbit_auth_mode,
            qbit_username=payload.qbit_username,
            qbit_password=payload.qbit_password,
            clear_password=payload.clear_password,
            qbit_api_key=payload.qbit_api_key,
            clear_api_key=payload.clear_api_key,
            qbit_category=payload.qbit_category,
            download_path=payload.download_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return config.public_dict()


@app.delete("/api/downloader/settings", dependencies=[Depends(require_admin)])
def restore_downloader_settings(db: Session = Depends(get_db)) -> dict[str, str | bool]:
    return reset_qbittorrent_config(db).public_dict()


@app.get("/api/application/settings", dependencies=[Depends(require_admin)])
def get_application_settings(db: Session = Depends(get_db)) -> dict[str, object]:
    return load_application_preferences(db).public_dict()


@app.put("/api/application/settings", dependencies=[Depends(require_admin)])
def update_application_settings(
    payload: ApplicationPreferencesUpdate,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        config = save_application_preferences(
            db,
            theme_color=payload.theme_color,
            subscription_sort=payload.subscription_sort,
            retry_count=payload.retry_count,
            concurrent_limit=payload.concurrent_limit,
            seeding_minutes=payload.seeding_minutes,
            cleanup_completed_enabled=payload.cleanup_completed_enabled,
            cleanup_completed_delay_minutes=payload.cleanup_completed_delay_minutes,
            rss_enabled=payload.rss_enabled,
            rss_timeout_seconds=payload.rss_timeout_seconds,
            auto_skip_existing=payload.auto_skip_existing,
            auto_disable_complete=payload.auto_disable_complete,
            trackers_enabled=payload.trackers_enabled,
            trackers_update_url=payload.trackers_update_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return config.public_dict()


@app.put("/api/application/settings/subscription-sort", dependencies=[Depends(require_admin)])
def update_subscription_sort(
    payload: SubscriptionSortUpdate,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        config = save_subscription_sort_preference(db, payload.subscription_sort)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return config.public_dict()


@app.delete("/api/application/settings", dependencies=[Depends(require_admin)])
def restore_application_settings(db: Session = Depends(get_db)) -> dict[str, object]:
    return reset_application_preferences(db).public_dict()


@app.post("/api/trackers/refresh", dependencies=[Depends(require_admin)])
def refresh_trackers(db: Session = Depends(get_db)) -> dict[str, object]:
    policy = load_application_preferences(db).trackers
    if not policy.enabled:
        raise HTTPException(status_code=422, detail="请先启用 Trackers")
    try:
        response = external_get(
            policy.update_url,
            db=db,
            timeout=load_application_preferences(db).rss.timeout_seconds,
            headers={"User-Agent": settings.rss_user_agent, "Accept": "text/plain,*/*"},
        )
        response.raise_for_status()
        trackers = normalize_tracker_text(response.text)
        if not trackers:
            raise ValueError("更新地址没有返回有效 Tracker")
        saved = save_tracker_cache(db, trackers)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Trackers 更新失败：{exc}") from exc
    return {"ok": True, "message": f"已更新 {len(trackers)} 个 Tracker", **saved.public_dict()}


@app.get("/api/metadata/settings", dependencies=[Depends(require_admin)])
def get_metadata_settings(db: Session = Depends(get_db)) -> dict[str, str | bool | int]:
    return load_metadata_config(db).public_dict()


@app.put("/api/metadata/settings", dependencies=[Depends(require_admin)])
def update_metadata_settings(
    payload: MetadataSettingsUpdate,
    db: Session = Depends(get_db),
) -> dict[str, str | bool | int]:
    try:
        config = save_metadata_config(
            db,
            tmdb_read_access_token=payload.tmdb_read_access_token,
            clear_tmdb_token=payload.clear_tmdb_token,
            bangumi_access_token=payload.bangumi_access_token,
            clear_bangumi_token=payload.clear_bangumi_token,
            metadata_language=payload.metadata_language,
            tmdb_api_base=payload.tmdb_api_base,
            tmdb_image_base=payload.tmdb_image_base,
            auto_scrape_enabled=payload.auto_scrape_enabled,
            follow_days=payload.follow_days,
            bangumi_ini_enabled=payload.bangumi_ini_enabled,
            media_local_root=payload.media_local_root,
            emby_url=payload.emby_url,
            emby_api_key=payload.emby_api_key,
            clear_emby_api_key=payload.clear_emby_api_key,
            tmm_url=payload.tmm_url,
            tmm_api_key=payload.tmm_api_key,
            clear_tmm_api_key=payload.clear_tmm_api_key,
            tmm_enabled=payload.tmm_enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return config.public_dict()


@app.delete("/api/metadata/settings", dependencies=[Depends(require_admin)])
def restore_metadata_settings(db: Session = Depends(get_db)) -> dict[str, str | bool | int]:
    return reset_metadata_config(db).public_dict()


@app.get("/api/automation/settings", dependencies=[Depends(require_admin)])
def get_automation_settings(db: Session = Depends(get_db)) -> dict[str, str | bool]:
    return load_automation_config(db).public_dict()


@app.put("/api/automation/settings", dependencies=[Depends(require_admin)])
def update_automation_settings(payload: AutomationSettingsUpdate, db: Session = Depends(get_db)) -> dict[str, str | bool]:
    try:
        return save_automation_config(db, download_enabled=payload.download_enabled, scrape_enabled=payload.scrape_enabled, daily_time=payload.daily_time, timezone=payload.timezone).public_dict()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/automation/settings", dependencies=[Depends(require_admin)])
def restore_automation_settings(db: Session = Depends(get_db)) -> dict[str, str | bool]:
    return reset_automation_config(db).public_dict()


@app.get("/api/rss-poll/settings", dependencies=[Depends(require_admin)])
def get_rss_poll_settings(db: Session = Depends(get_db)) -> dict[str, int | str]:
    return load_rss_poll_config(db).public_dict()


@app.put("/api/rss-poll/settings", dependencies=[Depends(require_admin)])
def update_rss_poll_settings(
    payload: RssPollSettingsUpdate,
    db: Session = Depends(get_db),
) -> dict[str, int | str]:
    try:
        return save_rss_poll_config(db, minutes=payload.minutes).public_dict()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/api/rss-poll/settings", dependencies=[Depends(require_admin)])
def restore_rss_poll_settings(db: Session = Depends(get_db)) -> dict[str, int | str]:
    return reset_rss_poll_config(db).public_dict()


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


@app.get("/api/notifications/settings", dependencies=[Depends(require_admin)])
def get_notification_settings(db: Session = Depends(get_db)) -> dict[str, object]:
    return load_notification_config(db).public_dict()


@app.put("/api/notifications/settings", dependencies=[Depends(require_admin)])
def update_notification_settings(
    payload: NotificationSettingsUpdate,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        config = save_notification_config(
            db,
            enabled=payload.enabled,
            events=payload.events,
            title_template=payload.title_template,
            body_template=payload.body_template,
            telegram_enabled=payload.telegram_enabled,
            telegram_bot_token=payload.telegram_bot_token,
            clear_telegram_bot_token=payload.clear_telegram_bot_token,
            telegram_chat_id=payload.telegram_chat_id,
            bark_enabled=payload.bark_enabled,
            bark_server_url=payload.bark_server_url,
            bark_device_key=payload.bark_device_key,
            clear_bark_device_key=payload.clear_bark_device_key,
            bark_encryption_enabled=payload.bark_encryption_enabled,
            bark_encryption_algorithm=payload.bark_encryption_algorithm,
            bark_encryption_mode=payload.bark_encryption_mode,
            bark_encryption_padding=payload.bark_encryption_padding,
            bark_encryption_key=payload.bark_encryption_key,
            clear_bark_encryption_key=payload.clear_bark_encryption_key,
            webhook_enabled=payload.webhook_enabled,
            webhook_url=payload.webhook_url,
            clear_webhook_url=payload.clear_webhook_url,
            webhook_headers_json=payload.webhook_headers_json,
            clear_webhook_headers=payload.clear_webhook_headers,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return config.public_dict()


@app.delete("/api/notifications/settings", dependencies=[Depends(require_admin)])
def restore_notification_settings(db: Session = Depends(get_db)) -> dict[str, object]:
    return reset_notification_config(db).public_dict()


@app.post("/api/notifications/preview", dependencies=[Depends(require_admin)])
def preview_notifications(payload: NotificationPreviewRequest) -> dict[str, Any]:
    try:
        # Validate through the same template rules used when settings are saved.
        from .notification.templates import validate_template

        title_template = validate_template(payload.title_template, "通知标题模板", max_length=1000)
        body_template = validate_template(payload.body_template, "通知正文模板", max_length=10000)
        return preview_notification(
            event=payload.event,
            title_template=title_template,
            body_template=body_template,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/notifications/test", dependencies=[Depends(require_admin)])
def test_notifications(db: Session = Depends(get_db)) -> dict[str, object]:
    result = send_notification(
        db,
        "download_started",
        "FeedDock 通知测试",
        "通知渠道连接正常。这是一条手动测试消息。",
        details={"test": True},
        force=True,
    )
    db.commit()
    return {"ok": result.ok, "message": result.message, "sent": result.sent, "errors": result.errors}


@app.get("/api/network/diagnostics", dependencies=[Depends(require_admin)])
def network_diagnostics() -> dict[str, Any]:
    return diagnose_dns()


@app.post("/api/proxy/test", dependencies=[Depends(require_admin)])
def test_proxy(db: Session = Depends(get_db)) -> dict[str, Any]:
    dns = diagnose_dns()
    try:
        response = external_get("https://api.bgm.tv/v0/calendar", db=db, timeout=settings.request_timeout_seconds, headers={"User-Agent": settings.rss_user_agent})
        return {
            "ok": response.status_code == 200,
            "message": f"外部请求测试 HTTP {response.status_code}",
            "dns": dns,
        }
    except Exception as exc:
        prefix = "容器 DNS 解析失败" if not dns["ok"] else "外部请求失败"
        return {"ok": False, "message": f"{prefix}：{exc}", "dns": dns}


@app.get("/api/secrets/{secret_name}", dependencies=[Depends(require_admin)])
def reveal_secret(secret_name: str, db: Session = Depends(get_db)) -> dict[str, str]:
    qbit = load_qbittorrent_config(db)
    metadata = load_metadata_config(db)
    proxy = load_proxy_config(db)
    notifications = load_notification_config(db)
    values = {
        "qbit_password": qbit.password,
        "qbit_api_key": qbit.api_key,
        "tmdb_read_access_token": metadata.tmdb_read_access_token,
        "bangumi_access_token": metadata.bangumi_access_token,
        "emby_api_key": metadata.emby_api_key,
        "tmm_api_key": metadata.tmm_api_key,
        "proxy_url": proxy.url,
        "notification_telegram_bot_token": notifications.telegram_bot_token,
        "notification_bark_device_key": notifications.bark_device_key,
        "notification_bark_encryption_key": notifications.bark_encryption_key,
        "notification_webhook_url": notifications.webhook_url,
        "notification_webhook_headers_json": notifications.webhook_headers_json,
    }
    if secret_name not in values:
        raise HTTPException(status_code=404, detail="未知密钥字段")
    return {"value": values[secret_name]}


class MetadataSearchQuery:
    def __init__(
        self,
        provider: str = Query(pattern="^(tmdb|bangumi|anilist)$"),
        q: str = Query(min_length=1, max_length=300),
        media_type: str = Query(default="tv", pattern="^(tv|movie)$"),
        year: int = Query(default=0, ge=0, le=9999),
        limit: int = Query(default=10, ge=1, le=20),
    ):
        self.provider = provider
        self.q = q
        self.media_type = media_type
        self.year = year
        self.limit = limit


@app.get(
    "/api/metadata/search",
    response_model=list[MetadataCandidateOut],
    dependencies=[Depends(require_admin)],
)
def search_metadata(
    query: MetadataSearchQuery = Depends(),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    try:
        return MetadataService().search(
            db, provider=query.provider, query=query.q, media_type=query.media_type, year=query.year, limit=query.limit
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"元数据搜索失败：{exc}") from exc


class MetadataDetailQuery:
    def __init__(
        self,
        provider: str = Query(pattern="^(tmdb|bangumi|anilist)$"),
        metadata_id: int = Query(gt=0),
        media_type: str = Query(default="tv", pattern="^(tv|movie)$"),
        season: int = Query(default=1, ge=0, le=999),
        season_mode: str = Query(default="title", pattern="^(manual|latest|title)$"),
        query_title: str = Query(default="", max_length=300),
    ):
        self.provider = provider
        self.metadata_id = metadata_id
        self.media_type = media_type
        self.season = season
        self.season_mode = season_mode
        self.query_title = query_title


@app.get(
    "/api/metadata/detail",
    response_model=MetadataRecordOut,
    dependencies=[Depends(require_admin)],
)
def metadata_detail(
    query: MetadataDetailQuery = Depends(),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return MetadataService().get(
            db,
            provider=query.provider,
            metadata_id=query.metadata_id,
            media_type=query.media_type,
            season=query.season,
            season_mode=query.season_mode,
            query_title=query.query_title,
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


@app.get("/api/discovery/catalog/{source_id}", dependencies=[Depends(require_admin)])
def source_catalog(
    source_id: str,
    year: int = Query(ge=2000, le=2100),
    season: str = Query(pattern="^(冬|春|夏|秋)$"),
    q: str = Query(default="", max_length=200),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        payload = AnimeCatalogCacheService().catalog(db, source_id, year, season, query=q)
        subscriptions = list(db.scalars(select(Subscription)))
        preferences = list(db.scalars(select(AnimePreference).where(AnimePreference.hidden.is_(True))))
        return decorate_catalog(payload, source_id, subscriptions, preferences, q)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"{source_id} 番剧周历读取失败：{exc}") from exc


@app.post("/api/discovery/catalog/{source_id}/trials", dependencies=[Depends(require_admin)])
def create_catalog_trials(
    source_id: str,
    payload: MikanTrialRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict[str, int | str]:
    if source_id not in {"anibt", "ag"}:
        raise HTTPException(status_code=422, detail="该目录不支持批量试看")
    created = _create_catalog_trials(db, source_id=source_id, year=payload.year, season=payload.season)
    for subscription in created:
        background_tasks.add_task(refresh_subscription, subscription.id, trigger=f"{source_id}-trial-batch")
    return {
        "created": len(created),
        "message": (
            f"已加入 {len(created)} 部{source_id}试看，首个可用剧集将保存到 试看/番剧名/"
            if created
            else "没有新增试看；已有试看订阅的目录数据已同步。"
        ),
    }


@app.post("/api/discovery/catalog/{source_id}/refresh", dependencies=[Depends(require_admin)])
def refresh_source_catalog(
    source_id: str,
    year: int = Query(ge=2000, le=2100),
    season: str = Query(pattern="^(冬|春|夏|秋)$"),
    q: str = Query(default="", max_length=200),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        payload = AnimeCatalogCacheService().catalog(db, source_id, year, season, query=q, force_refresh=True)
        subscriptions = list(db.scalars(select(Subscription)))
        preferences = list(db.scalars(select(AnimePreference).where(AnimePreference.hidden.is_(True))))
        return decorate_catalog(payload, source_id, subscriptions, preferences, q)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"{source_id} 番剧周历更新失败：{exc}") from exc


@app.get("/api/discovery/catalog/{source_id}/detail", dependencies=[Depends(require_admin)])
def source_catalog_detail(
    source_id: str,
    query: SourceCatalogDetailQuery = Depends(),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    item = {
        "title": query.title,
        "title_original": query.original_title or query.title,
        "title_english": query.english_title or query.original_title or query.title,
        "subject_id": query.subject_id,
        "source_anime_id": query.source_anime_id,
        "mikan_id": query.mikan_id,
        "aliases": [value.strip() for value in query.aliases.split("\n") if value.strip()] or [query.title],
    }
    try:
        return AnimeCatalogCacheService().detail(db, source_id, item, force_refresh=query.force_refresh)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"{source_id} 资源详情读取失败：{exc}") from exc


@app.put("/api/discovery/preferences/hidden", dependencies=[Depends(require_admin)])
def update_hidden_anime_preferences(
    payload: AnimePreferenceBatchUpdate,
    db: Session = Depends(get_db),
) -> dict[str, int]:
    hidden_count = 0
    for item in payload.items:
        key = item.canonical_key.strip()
        row = db.get(AnimePreference, key)
        if item.hidden:
            if row is None:
                row = AnimePreference(canonical_key=key)
                db.add(row)
            row.hidden = True
            row.bangumi_id = item.bangumi_id
            row.title_normalized = normalize_title(item.title)
            row.reason = item.reason.strip()
            hidden_count += 1
        else:
            normalized_title = normalize_title(item.title)
            clauses = [AnimePreference.canonical_key == key]
            if item.bangumi_id > 0:
                clauses.append(AnimePreference.bangumi_id == item.bangumi_id)
            if normalized_title:
                clauses.append(AnimePreference.title_normalized == normalized_title)
            matches = list(db.scalars(select(AnimePreference).where(or_(*clauses))))
            for match in matches:
                db.delete(match)
    db.commit()
    return {"updated": len(payload.items), "hidden": hidden_count}


_DELETED_SUBSCRIPTION_REASON_PREFIX = "subscription_deleted:"


def _subscription_preference_title(subscription: Subscription) -> str:
    return next(
        (
            str(value).strip()
            for value in (
                subscription.reference_title,
                subscription.manual_title,
                subscription.tmdb_title,
                subscription.name,
            )
            if str(value or "").strip()
        ),
        "",
    )


def _related_subscription_group(
    db: Session,
    subscription: Subscription,
    *,
    candidates: list[Subscription] | None = None,
) -> list[Subscription]:
    """Find the transitive set of subscription rows belonging to one anime."""

    rows = candidates if candidates is not None else list(db.scalars(select(Subscription)))
    related: dict[int, Subscription] = {}
    pending = [subscription]
    while pending:
        current = pending.pop()
        if current.id is None or current.id in related:
            continue
        related[current.id] = current
        for candidate in rows:
            if candidate.id is None or candidate.id in related:
                continue
            if subscriptions_related(current, candidate):
                pending.append(candidate)
    return list(related.values())


def _hide_deleted_subscriptions(
    db: Session,
    subscriptions: list[Subscription],
    *,
    preferred: Subscription | None = None,
) -> bool:
    """Consolidate one anime into a single hidden preference before deletion."""

    rows = [row for row in subscriptions if row is not None]
    if not rows:
        return False
    preferred = preferred or rows[0]

    identities = {key for row in rows if (key := subscription_identity(row))}
    aliases = set().union(*(subscription_aliases(row) for row in rows))
    bangumi_keys = sorted(key for key in identities if key.startswith("bgm:"))
    key = bangumi_keys[0] if bangumi_keys else subscription_identity(preferred)
    if not key:
        key = next(iter(sorted(identities)), "")
    if not key:
        return False

    title = _subscription_preference_title(preferred)
    if not title:
        title = next((_subscription_preference_title(row) for row in rows if _subscription_preference_title(row)), "")
    title_normalized = normalize_title(title)

    bangumi_ids: set[int] = set()
    for identity in identities:
        if not identity.startswith("bgm:"):
            continue
        try:
            bangumi_ids.add(int(identity.split(":", 1)[1]))
        except ValueError:
            continue
    bangumi_id = min(bangumi_ids) if bangumi_ids else 0

    matching_preferences = []
    for preference in db.scalars(select(AnimePreference)).all():
        if preference.canonical_key in identities:
            matching_preferences.append(preference)
        elif preference.bangumi_id > 0 and preference.bangumi_id in bangumi_ids:
            matching_preferences.append(preference)
        elif preference.title_normalized and preference.title_normalized in aliases:
            matching_preferences.append(preference)

    row = db.get(AnimePreference, key)
    if row is None:
        row = AnimePreference(canonical_key=key)
        db.add(row)
    for duplicate in matching_preferences:
        if duplicate is not row:
            db.delete(duplicate)

    row.hidden = True
    row.bangumi_id = bangumi_id
    row.title_normalized = title_normalized
    current_reason = str(row.reason or "").strip()
    if not current_reason or current_reason.startswith(_DELETED_SUBSCRIPTION_REASON_PREFIX):
        row.reason = f"{_DELETED_SUBSCRIPTION_REASON_PREFIX}{title}"
    return True


def _hide_deleted_subscription(db: Session, subscription: Subscription) -> bool:
    """Compatibility wrapper for callers that already resolved one row."""

    return _hide_deleted_subscriptions(db, [subscription], preferred=subscription)


def _hidden_preference_title(preference: AnimePreference) -> str:
    reason = str(preference.reason or "").strip()
    if reason.startswith(_DELETED_SUBSCRIPTION_REASON_PREFIX):
        title = reason.removeprefix(_DELETED_SUBSCRIPTION_REASON_PREFIX).strip()
        if title:
            return title
    return preference.title_normalized or preference.canonical_key


@app.get("/api/discovery/preferences/hidden", dependencies=[Depends(require_admin)])
def list_hidden_anime_preferences(db: Session = Depends(get_db)) -> dict[str, Any]:
    preferences = list(
        db.scalars(
            select(AnimePreference)
            .where(AnimePreference.hidden.is_(True))
            .order_by(desc(AnimePreference.updated_at), AnimePreference.canonical_key)
        )
    )
    return {
        "count": len(preferences),
        "items": [
            {
                "canonical_key": preference.canonical_key,
                "title": _hidden_preference_title(preference),
                "bangumi_id": preference.bangumi_id,
                "reason": (
                    "subscription_deleted"
                    if str(preference.reason or "").startswith(_DELETED_SUBSCRIPTION_REASON_PREFIX)
                    else "manual"
                ),
                "updated_at": preference.updated_at,
            }
            for preference in preferences
        ],
    }


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
    background_tasks: BackgroundTasks,
    year: int = Query(ge=2000, le=2100),
    season: str = Query(pattern="^(冬|春|夏|秋)$"),
    q: str = Query(default="", max_length=200),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        payload = MikanCacheService(DiscoveryService()).catalog(
            db, year, season, q, force_refresh=True
        )
        result = _apply_mikan_hidden_filters(payload, db, year=year, season=season)
        if get_app_setting("mikan_preorder_enabled", "0", db) == "1":
            created = _create_mikan_trials(db, year=year, season=season, payload=payload)
            for subscription in created:
                background_tasks.add_task(refresh_subscription, subscription.id, trigger="mikan-preorder")
            result["trial_created"] = len(created)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Mikan 强制更新失败：{exc}") from exc


@app.get("/api/discovery/mikan/preorder", dependencies=[Depends(require_admin)])
def get_mikan_preorder(db: Session = Depends(get_db)) -> dict[str, bool]:
    return {"enabled": get_app_setting("mikan_preorder_enabled", "0", db) == "1"}


@app.put("/api/discovery/mikan/preorder", dependencies=[Depends(require_admin)])
def set_mikan_preorder(enabled: bool, db: Session = Depends(get_db)) -> dict[str, bool]:
    set_app_setting(db, "mikan_preorder_enabled", "1" if enabled else "0")
    return {"enabled": enabled}


@app.post("/api/discovery/mikan/trials", dependencies=[Depends(require_admin)])
def create_mikan_trials(
    payload: MikanTrialRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict[str, int | str]:
    created = _create_mikan_trials(db, year=payload.year, season=payload.season)
    for subscription in created:
        background_tasks.add_task(refresh_subscription, subscription.id, trigger="mikan-trial-batch")
    if not created:
        return {
            "created": 0,
            "message": "没有新增试看；已有试看订阅的目录数据已同步。若仍有未加入作品，请查看系统日志。",
        }
    return {
        "created": len(created),
        "message": (
            f"已加入 {len(created)} 部 Mikan 试看，首个可用剧集将保存到 试看/番剧名/"
        ),
    }


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


@app.get("/api/subscription-sources", dependencies=[Depends(require_admin)])
def list_subscription_sources() -> dict[str, Any]:
    return {"sources": subscription_source_catalog()}


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
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> SubscriptionOut:
    request.state.debug_context = {
        "operation": "create_subscription",
        "payload": payload.model_dump(mode="json"),
    }
    try:
        request.state.debug_stage = "subscription.build-values"
        values = _subscription_values(payload, db)
        _validate_auto_skip_rename_requirement(db, values)
        subscription = Subscription(**values)
        request.state.debug_stage = "subscription.insert"
        db.add(subscription)
        request.state.debug_stage = "subscription.commit"
        db.commit()
        request.state.debug_stage = "subscription.refresh"
        db.refresh(subscription)
        output = _subscription_out(db, subscription)
        request.state.debug_stage = "subscription.schedule-initial-refresh"
        background_tasks.add_task(
            refresh_subscription,
            subscription.id,
            trigger="subscription-created",
        )
        request.state.debug_stage = "subscription.serialize"
        return output
    except Exception:
        db.rollback()
        raise


def _import_subscription_definitions(
    db: Session,
    subscriptions: list[SubscriptionCreate],
    *,
    conflict: str = "skip",
    replace: bool = False,
) -> dict[str, int]:
    created = 0
    updated = 0
    skipped = 0
    if replace:
        db.execute(delete(FeedItem))
        db.execute(delete(Subscription))
        db.flush()

    existing_subs_map = {}
    if not replace:
        rss_urls = [str(item.rss_url) for item in subscriptions]
        subs = db.scalars(select(Subscription).where(Subscription.rss_url.in_(rss_urls))).all()
        existing_subs_map = {sub.rss_url: sub for sub in subs}

    for item in subscriptions:
        rss_url = str(item.rss_url)
        existing = None if replace else existing_subs_map.get(rss_url)
        values = _subscription_values(item, db, existing=existing)
        _validate_auto_skip_rename_requirement(db, values, existing=existing)
        if existing is None:
            db.add(Subscription(**values))
            created += 1
            continue
        if conflict == "skip":
            skipped += 1
            continue
        _clear_trial_only_skips(db, existing, values)
        reset_monitor_state_for_changes(existing, values)
        for key, value in values.items():
            setattr(existing, key, value)
        updated += 1
    return {"created": created, "updated": updated, "skipped": skipped}


@app.get("/api/subscriptions/export", dependencies=[Depends(require_admin)])
def export_subscriptions(
    ids: list[int] = Query(default=[]),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return export_subscriptions_payload(db, ids=ids)


@app.post("/api/subscriptions/import", dependencies=[Depends(require_admin)])
def import_subscriptions(
    payload: SubscriptionImportRequest,
    db: Session = Depends(get_db),
) -> dict[str, int]:
    try:
        result = _import_subscription_definitions(
            db,
            payload.subscriptions,
            conflict=payload.conflict,
        )
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


@app.get("/api/system/backup/export", dependencies=[Depends(require_admin)])
def export_full_system_backup(
    include_secrets: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return export_system_backup(db, include_secrets=include_secrets)


@app.post("/api/system/backup/import", dependencies=[Depends(require_admin)])
def import_full_system_backup(
    payload: SystemBackupImportRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        backup = validate_system_backup(payload.backup)
        replace = payload.mode == "replace"
        settings_count = import_app_settings(
            db,
            backup.get("settings", {}),
            replace=replace,
            preserve_sensitive=not bool(backup.get("secrets_included")),
        )
        preference_count = import_anime_preferences(
            db,
            backup.get("anime_preferences", []),
            replace=replace,
        )
        subscriptions = [
            SubscriptionCreate.model_validate(item)
            for item in backup.get("subscriptions", [])
        ]
        subscription_result = _import_subscription_definitions(
            db,
            subscriptions,
            conflict=payload.subscription_conflict,
            replace=replace,
        )
        db.commit()
        backfill_subscription_identities(db)
        return {
            "ok": True,
            "mode": payload.mode,
            "settings": settings_count,
            "anime_preferences": preference_count,
            **subscription_result,
            "message": (
                f"系统配置已导入：{settings_count} 项设置，"
                f"订阅新增 {subscription_result['created']}、更新 {subscription_result['updated']}、"
                f"跳过 {subscription_result['skipped']}"
            ),
        }
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise


@app.post("/api/subscriptions/batch", dependencies=[Depends(require_admin)])
def batch_subscriptions(
    payload: SubscriptionBatchRequest,
    db: Session = Depends(get_db),
) -> dict[str, int | str]:
    subscriptions = list(db.scalars(select(Subscription).where(Subscription.id.in_(payload.ids))))
    if not subscriptions:
        raise HTTPException(status_code=404, detail="未找到所选订阅")
    if payload.action == "enable" and any(
        subscription.subscription_mode == "trial" for subscription in subscriptions
    ):
        raise HTTPException(
            status_code=409,
            detail="试看订阅必须逐个选择匹配的元数据后启动",
        )
    hidden = 0
    affected = len(subscriptions)
    if payload.action == "delete":
        all_subscriptions = list(db.scalars(select(Subscription)))
        processed_ids: set[int] = set()
        delete_rows: dict[int, Subscription] = {}
        for subscription in subscriptions:
            if subscription.id in processed_ids:
                continue
            group = _related_subscription_group(db, subscription, candidates=all_subscriptions)
            processed_ids.update(row.id for row in group if row.id is not None)
            delete_rows.update({row.id: row for row in group if row.id is not None})
            hidden += int(_hide_deleted_subscriptions(db, group, preferred=subscription))
        for subscription in delete_rows.values():
            db.delete(subscription)
        affected = len(delete_rows)
    else:
        enabled = payload.action == "enable"
        for subscription in subscriptions:
            if enabled:
                _validate_auto_skip_rename_requirement(
                    db,
                    {"enabled": True},
                    existing=subscription,
                )
            subscription.enabled = enabled
    db.commit()
    return {"action": payload.action, "affected": affected, "hidden": hidden}


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
    if (
        subscription.subscription_mode == "trial"
        and payload.enabled is True
    ):
        raise HTTPException(
            status_code=409,
            detail="试看订阅必须先选择匹配的元数据后启动",
        )
    try:
        request.state.debug_stage = "subscription.apply-values"
        values = _subscription_values(payload, db, existing=subscription)
        _validate_auto_skip_rename_requirement(db, values, existing=subscription)
        _clear_trial_only_skips(db, subscription, values)
        reset_monitor_state_for_changes(subscription, values)
        for key, value in values.items():
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


@app.post("/api/subscriptions/{subscription_id}/rss-candidates", dependencies=[Depends(require_admin)])
def search_subscription_rss(
    subscription_id: int,
    payload: RssCandidateSearchRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    subscription = db.get(Subscription, subscription_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="订阅不存在")
    try:
        result = search_subscription_rss_candidates(
            db,
            subscription,
            query=payload.query,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"RSS 候选搜索失败：{exc}") from exc
    if not result.get("candidates") and result.get("errors"):
        result["message"] = "没有找到可用 RSS；部分站点读取失败，请查看站点错误后重试"
    elif not result.get("candidates"):
        result["message"] = "没有找到相关 RSS，请尝试修改搜索词"
    else:
        result["message"] = f"已找到 {len(result['candidates'])} 个相关 RSS"
    return result


@app.post("/api/subscriptions/{subscription_id}/refresh", dependencies=[Depends(require_admin)])
def refresh_single_subscription(
    subscription_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict[str, bool | int | str]:
    subscription = db.get(Subscription, subscription_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="订阅不存在")
    background_tasks.add_task(refresh_subscription, subscription_id, trigger="rss-updated")
    return {
        "ok": True,
        "subscription_id": subscription_id,
        "message": f"RSS 已保存，正在检查订阅：{subscription.name}",
    }


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
    if subscription.trial_bulk:
        raise HTTPException(status_code=409, detail="批量试看不收集元数据或刮削")
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
        _refresh_subscription_identity(db, subscription)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"元数据读取失败：{exc}") from exc
    return _subscription_out(db, subscription)


@app.post(
    "/api/subscriptions/{subscription_id}/trial/start",
    response_model=SubscriptionOut,
    dependencies=[Depends(require_admin)],
)
def start_trial_subscription(
    subscription_id: int,
    payload: MetadataApplyRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> SubscriptionOut:
    """Refresh selected metadata, then promote and enable a trial subscription."""

    subscription = db.get(Subscription, subscription_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="订阅不存在")
    if subscription.subscription_mode != "trial":
        raise HTTPException(status_code=409, detail="该订阅不是试看订阅")
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
        _refresh_subscription_identity(db, subscription)
        values = _subscription_values(
            SubscriptionUpdate(enabled=True),
            db,
            existing=subscription,
        )
        _validate_auto_skip_rename_requirement(db, values, existing=subscription)
        _clear_trial_only_skips(db, subscription, values)
        reset_monitor_state_for_changes(subscription, values)
        for key, value in values.items():
            setattr(subscription, key, value)
        _migrate_started_trial_download(db, subscription)
        db.commit()
        db.refresh(subscription)
        background_tasks.add_task(
            refresh_subscription,
            subscription.id,
            trigger="trial-started",
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=502, detail=f"元数据刷新或试看启动失败：{exc}") from exc
    return _subscription_out(db, subscription)


@app.post(
    "/api/subscriptions/{subscription_id}/trial/start-manual",
    response_model=SubscriptionOut,
    dependencies=[Depends(require_admin)],
)
def start_trial_subscription_manual(
    subscription_id: int,
    payload: ManualTrialStartRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> SubscriptionOut:
    """Store user-confirmed metadata, then promote and enable a trial."""

    subscription = db.get(Subscription, subscription_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="订阅不存在")
    if subscription.subscription_mode != "trial":
        raise HTTPException(status_code=409, detail="该订阅不是试看订阅")
    try:
        subscription.name = title_with_year(payload.title, payload.year)
        subscription.reference_title = payload.title
        subscription.manual_title = payload.title
        subscription.tmdb_title = ""
        subscription.naming_mode = "manual"
        subscription.media_type = payload.media_type
        subscription.season = payload.season
        subscription.season_mode = "manual"
        subscription.metadata_year = payload.year
        subscription.metadata_rating = payload.rating
        subscription.metadata_source = "manual"
        subscription.metadata_overview = payload.overview or subscription.metadata_overview
        subscription.poster_url = payload.poster_url or subscription.poster_url
        subscription.backdrop_url = payload.backdrop_url or subscription.backdrop_url
        subscription.metadata_last_synced_at = datetime.now(timezone.utc)
        subscription.metadata_confirmed = True
        subscription.metadata_review_skipped = False
        subscription.auto_metadata = False
        subscription.tmdb_id = 0
        subscription.bangumi_id = 0
        subscription.anilist_id = 0
        subscription.bgm_url = ""
        if payload.air_date:
            subscription.air_date = payload.air_date.isoformat()
        if payload.total_episodes > 0:
            subscription.total_episodes = payload.total_episodes
            subscription.total_episodes_source = "manual"
            subscription.total_episodes_locked = True
        _refresh_subscription_identity(db, subscription)
        values = _subscription_values(
            SubscriptionUpdate(enabled=True),
            db,
            existing=subscription,
        )
        _validate_auto_skip_rename_requirement(db, values, existing=subscription)
        _clear_trial_only_skips(db, subscription, values)
        reset_monitor_state_for_changes(subscription, values)
        for key, value in values.items():
            setattr(subscription, key, value)
        _migrate_started_trial_download(db, subscription)
        db.commit()
        db.refresh(subscription)
        background_tasks.add_task(
            refresh_subscription,
            subscription.id,
            trigger="trial-started",
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"手动元数据保存或试看启动失败：{exc}") from exc
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
    if subscription.trial_bulk:
        raise HTTPException(status_code=409, detail="批量试看不收集元数据或刮削")
    try:
        MetadataService().sync(db, subscription, payload.provider)
        _refresh_subscription_identity(db, subscription)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"元数据同步失败：{exc}") from exc
    return _subscription_out(db, subscription)


@app.delete("/api/subscriptions/{subscription_id}", dependencies=[Depends(require_admin)])
def delete_subscription(subscription_id: int, db: Session = Depends(get_db)) -> dict[str, bool | int]:
    subscription = db.get(Subscription, subscription_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="订阅不存在")
    group = _related_subscription_group(db, subscription)
    hidden = _hide_deleted_subscriptions(db, group, preferred=subscription)
    for related in group:
        db.delete(related)
    db.commit()
    return {"ok": True, "hidden": hidden, "deleted": len(group)}


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


@app.post("/api/actions/refresh-metadata", dependencies=[Depends(require_admin)])
def manual_metadata_refresh(background_tasks: BackgroundTasks) -> dict[str, bool | str]:
    background_tasks.add_task(refresh_all_metadata)
    return {"ok": True, "message": "订阅元数据同步任务已启动"}


@app.post("/api/actions/scrape-completed", dependencies=[Depends(require_admin)])
def manual_media_scrape(background_tasks: BackgroundTasks) -> dict[str, bool | str]:
    background_tasks.add_task(scrape_completed_media)
    return {"ok": True, "message": "媒体库刮削任务已启动"}


@app.post("/api/subscriptions/{subscription_id}/scrape", dependencies=[Depends(require_admin)])
def scrape_subscription_media(
    subscription_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> dict[str, bool | str | int]:
    subscription = db.get(Subscription, subscription_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="订阅不存在")
    if subscription.trial_bulk:
        raise HTTPException(status_code=409, detail="批量试看不收集元数据或刮削")
    completed_count = int(
        db.scalar(
            select(func.count())
            .select_from(FeedItem)
            .where(
                FeedItem.subscription_id == subscription_id,
                FeedItem.completed_at.is_not(None),
            )
        )
        or 0
    )
    if completed_count == 0:
        raise HTTPException(status_code=422, detail="该订阅没有已完成的下载条目可刮削")
    background_tasks.add_task(scrape_completed_media, subscription_id)
    return {
        "ok": True,
        "subscription_id": subscription_id,
        "items": completed_count,
        "message": f"“{subscription.name}”刮削任务已启动",
    }


@app.post("/api/actions/normalize-torrents", dependencies=[Depends(require_admin)])
def normalize_torrents_now() -> dict[str, Any]:
    return normalize_pending_items(limit=200)


@app.post(
    "/api/actions/cleanup-completed-torrents",
    dependencies=[Depends(require_admin)],
)
def cleanup_completed_torrents_now() -> dict[str, Any]:
    """Check and remove qBittorrent records whose configured delay has elapsed."""

    return cleanup_completed_torrent_records(limit=500)


@app.post("/api/actions/test-downloader", dependencies=[Depends(require_admin)])
def test_downloader() -> dict[str, bool | str]:
    result = QBittorrentClient().test()
    return {"ok": result.ok, "message": result.message}


@app.get("/api/system/status", dependencies=[Depends(require_admin)])
def system_status() -> dict[str, Any]:
    return {
        "actions_allowed": settings.allow_system_actions,
        "restart_supported": settings.allow_system_actions,
        "shutdown_supported": settings.allow_system_actions,
        "message": (
            "系统操作已启用；容器是否重新启动由 Docker restart 策略决定"
            if settings.allow_system_actions
            else "系统重启与关闭默认禁用；设置 FEEDDOCK_ALLOW_SYSTEM_ACTIONS=true 后启用"
        ),
    }


@app.post("/api/system/restart", dependencies=[Depends(require_admin)])
def restart_system(background_tasks: BackgroundTasks) -> dict[str, bool | str]:
    if not settings.allow_system_actions:
        raise HTTPException(status_code=403, detail="系统操作未启用")
    background_tasks.add_task(terminate_process, restart=True)
    return {"ok": True, "message": "FeedDock 正在退出；容器编排器将按重启策略恢复服务"}


@app.post("/api/system/shutdown", dependencies=[Depends(require_admin)])
def shutdown_system(background_tasks: BackgroundTasks) -> dict[str, bool | str]:
    if not settings.allow_system_actions:
        raise HTTPException(status_code=403, detail="系统操作未启用")
    background_tasks.add_task(terminate_process, restart=False)
    return {"ok": True, "message": "FeedDock 正在关闭；如配置自动重启，容器可能再次启动"}


@app.get(
    "/api/update/status",
    response_model=UpdateStatusOut,
    dependencies=[Depends(require_admin)],
)
def update_status(force: bool = False, db: Session = Depends(get_db)) -> dict[str, str | bool]:
    return UpdateService().check(db, force=force).as_dict()


@app.post("/api/update/apply", dependencies=[Depends(require_admin)])
def apply_update() -> dict[str, bool | str]:
    ok, message = UpdateService().trigger_update()
    return {"ok": ok, "message": message}

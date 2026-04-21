import asyncio
import json
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from config.settings import get_settings
from core.container import Container
from services.admin_guardrails import (
    MAX_BROADCAST_RECIPIENTS,
    build_broadcast_confirmation_token,
    build_broadcast_preview,
    normalize_broadcast_user_ids,
)
from services.ai_profile_service import resolve_ai_profile
from services.admin_metrics_service import AdminMetricsService
from services.release_service import build_health_warnings, load_release_info
from services.response_guardrails import (
    analyze_response_style,
    apply_ptsd_response_guardrails,
)
from services.telegram_formatting import (
    TelegramFormattingOptions,
    escape_plain_text_for_telegram,
    format_model_response_for_telegram,
)


security = HTTPBasic()
settings = get_settings()
container = Container(settings)


class DashboardMessageDeliveryError(Exception):
    def __init__(self, detail: str, status_code: int = 400):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def require_auth(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    username_ok = secrets.compare_digest(
        credentials.username,
        settings.admin_dashboard_username,
    )
    password_ok = secrets.compare_digest(
        credentials.password,
        settings.admin_dashboard_password,
    )

    if not (username_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username


@asynccontextmanager
async def lifespan(app: FastAPI):
    await container.db.connect()
    await container.user_service.init_table()
    await container.state_repository.init_table()
    await container.user_preference_repository.init_table()
    await container.long_term_memory_service.init_table()
    await container.proactive_repository.init_table()
    await container.ai_service.start()
    app.state.bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    container.admin_metrics = AdminMetricsService(
        user_service=container.user_service,
        message_repository=container.message_repository,
        payment_repository=container.payment_repository,
        monetization_repository=container.monetization_repository,
        referral_service=container.referral_service,
        state_repository=container.state_repository,
        ai_service=container.ai_service,
        chat_session_service=container.chat_session_service,
        proactive_repository=container.proactive_repository,
        user_preference_repository=container.user_preference_repository,
        redis=container.redis,
        cache_ttl=settings.admin_dashboard_cache_ttl,
    )

    yield

    await app.state.bot.session.close()
    await container.ai_service.close()
    await container.openai_client.close()
    await container.db.close()
    if container.redis is not None:
        await container.redis.aclose()


app = FastAPI(title="Админка бота", lifespan=lifespan)


def _ensure_admin_metrics() -> AdminMetricsService:
    if not hasattr(container, "admin_metrics"):
        container.admin_metrics = AdminMetricsService(
            user_service=container.user_service,
            message_repository=container.message_repository,
            payment_repository=container.payment_repository,
            monetization_repository=container.monetization_repository,
            referral_service=container.referral_service,
            state_repository=container.state_repository,
            ai_service=container.ai_service,
            chat_session_service=container.chat_session_service,
            proactive_repository=container.proactive_repository,
            user_preference_repository=container.user_preference_repository,
            redis=container.redis,
            cache_ttl=settings.admin_dashboard_cache_ttl,
        )
    return container.admin_metrics


def _parse_json_field(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Некорректный JSON: {exc}") from exc


def _parse_history(value: Any) -> list[dict[str, str]]:
    if value in (None, ""):
        return []

    if isinstance(value, list):
        history = []
        for item in value:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role", "")).strip().lower()
            content = str(item.get("content", "")).strip()
            if role in {"user", "assistant"} and content:
                history.append({"role": role, "content": content})
        return history

    history: list[dict[str, str]] = []
    for line in str(value).splitlines():
        normalized = line.strip()
        if not normalized or ":" not in normalized:
            continue
        role, content = normalized.split(":", 1)
        role = role.strip().lower()
        content = content.strip()
        if role in {"user", "assistant"} and content:
            history.append({"role": role, "content": content})
    return history


async def _invalidate_metrics_cache() -> None:
    await _ensure_admin_metrics().invalidate_cache()


def _get_dashboard_bot() -> Bot:
    bot = getattr(app.state, "bot", None)
    if bot is None:
        raise HTTPException(status_code=503, detail="Telegram bot is not initialized")
    return bot


def _build_formatting_options(active_mode: str) -> TelegramFormattingOptions:
    mode_config = container.admin_settings_service.get_modes().get(active_mode, {})
    return TelegramFormattingOptions(
        allow_bold=bool(mode_config.get("allow_bold", False)),
        allow_italic=bool(mode_config.get("allow_italic", False)),
    )


def _broadcast_secret() -> str:
    return settings.bot_token or settings.admin_dashboard_password or "broadcast-secret"


def _normalize_broadcast_targets(raw_user_ids: Any) -> list[int]:
    if not isinstance(raw_user_ids, list):
        raise HTTPException(status_code=400, detail="Передай список user_ids")

    user_ids = normalize_broadcast_user_ids(
        raw_user_ids,
        max_recipients=MAX_BROADCAST_RECIPIENTS + 1,
    )
    if not user_ids:
        raise HTTPException(status_code=400, detail="Не выбраны получатели")
    if len(user_ids) > MAX_BROADCAST_RECIPIENTS:
        raise HTTPException(
            status_code=400,
            detail=f"За один раз можно отправить максимум {MAX_BROADCAST_RECIPIENTS} сообщений",
        )
    return user_ids


async def _deliver_dashboard_message(
    user_id: int,
    text: str,
    *,
    invalidate_metrics: bool = True,
) -> dict[str, Any]:
    user = await container.user_service.get_user(user_id)
    if user is None:
        raise DashboardMessageDeliveryError("Пользователь не найден", status_code=404)

    state_payload = await container.state_repository.get(user_id)
    active_mode = str(
        state_payload.get("active_mode")
        or user.get("active_mode")
        or "base"
    ).strip() or "base"
    formatting_options = _build_formatting_options(active_mode)
    formatted_text = format_model_response_for_telegram(text, formatting_options)
    outbound_text = formatted_text or escape_plain_text_for_telegram(text)
    bot = _get_dashboard_bot()

    try:
        try:
            await bot.send_message(chat_id=user_id, text=outbound_text)
        except TelegramBadRequest:
            await bot.send_message(
                chat_id=user_id,
                text=escape_plain_text_for_telegram(text),
            )
    except TelegramForbiddenError as exc:
        raise DashboardMessageDeliveryError(
            f"Нельзя написать пользователю: {exc}",
            status_code=403,
        ) from exc
    except Exception as exc:
        raise DashboardMessageDeliveryError(
            f"Не удалось отправить сообщение: {exc}",
            status_code=502,
        ) from exc

    new_state = container.human_memory_service.apply_assistant_message(
        state_payload,
        text,
        source="reply",
    )
    try:
        async with container.db.transaction():
            await container.state_repository.save(user_id, new_state, commit=False)
            await container.message_repository.save(user_id, "assistant", text, commit=False)
    except Exception as exc:
        raise DashboardMessageDeliveryError(
            f"Сообщение отправлено, но не сохранилось в базе: {exc}",
            status_code=500,
        ) from exc

    if invalidate_metrics:
        await _invalidate_metrics_cache()

    try:
        container.conversation_summary_service.schedule_refresh(user_id, new_state)
    except Exception:
        pass

    return {
        "ok": True,
        "user_id": user_id,
        "text": text,
        "active_mode": active_mode,
    }


async def _build_health() -> dict[str, Any]:
    db_status = {"ok": True, "detail": "Подключено"}
    try:
        cursor = await container.db.connection.execute("SELECT 1")
        await cursor.fetchone()
    except Exception as exc:
        db_status = {"ok": False, "detail": str(exc)}

    redis_url = settings.redis_url
    redis_parts = urlparse(redis_url)
    redis_endpoint = redis_parts.hostname or "localhost"
    if redis_parts.port:
        redis_endpoint = f"{redis_endpoint}:{redis_parts.port}"
    redis_db = (redis_parts.path or "/0").lstrip("/") or "0"

    if container.redis is None:
        redis_status = {
            "ok": False,
            "mode": "fallback",
            "detail": "Используется in-memory fallback, Redis не подключен",
            "endpoint": redis_endpoint,
            "url": redis_url,
            "database": redis_db,
            "latency_ms": None,
        }
    else:
        try:
            started = time.perf_counter()
            await container.redis.ping()
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            redis_status = {
                "ok": True,
                "mode": "connected",
                "detail": "Redis доступен",
                "endpoint": redis_endpoint,
                "url": redis_url,
                "database": redis_db,
                "latency_ms": latency_ms,
            }
        except Exception as exc:
            redis_status = {
                "ok": False,
                "mode": "error",
                "detail": str(exc),
                "endpoint": redis_endpoint,
                "url": redis_url,
                "database": redis_db,
                "latency_ms": None,
            }

    config_files = {}
    for name, path in {
        "runtime": container.admin_settings_service.runtime_path,
        "prompts": container.admin_settings_service.prompts_path,
        "modes": container.admin_settings_service.modes_path,
        "mode_catalog": container.admin_settings_service.mode_catalog_path,
        "log": container.admin_settings_service.log_path,
    }.items():
        file_path = Path(path)
        config_files[name] = {
            "path": str(file_path),
            "exists": file_path.exists(),
            "size_bytes": file_path.stat().st_size if file_path.exists() else 0,
        }

    runtime_stats = container.ai_service.get_runtime_stats()
    chat_runtime = container.chat_session_service.get_runtime_stats()
    release_info = load_release_info(container.admin_settings_service.config_dir)
    warnings = build_health_warnings(
        admin_dashboard_password=settings.admin_dashboard_password,
        redis_ok=bool(redis_status.get("ok")),
        release_info=release_info,
        runtime_stats=runtime_stats,
    )

    return {
        "db": db_status,
        "redis": redis_status,
        "ai_runtime": runtime_stats,
        "chat_runtime": chat_runtime,
        "config_files": config_files,
        "modes_count": len(container.admin_settings_service.get_mode_catalog()),
        "release": release_info,
        "warnings": warnings,
    }


async def _prepare_test_context(payload: dict[str, Any]) -> dict[str, Any]:
    user_message = str(payload.get("user_message") or "").strip()
    state = _parse_json_field(payload.get("state"), default={})
    if not isinstance(state, dict):
        raise HTTPException(status_code=400, detail="Поле state должно быть объектом JSON")

    active_mode = str(payload.get("active_mode") or state.get("active_mode") or "base").strip()
    state.setdefault("active_mode", active_mode)

    memory_enriched_state = container.keyword_memory_service.apply(state.copy(), user_message)
    memory_enriched_state = container.human_memory_service.apply_user_message(
        memory_enriched_state,
        user_message,
    )
    updated_state = (
        container.state_engine.update_state(memory_enriched_state, user_message)
        if user_message
        else memory_enriched_state
    )
    runtime_settings = container.admin_settings_service.get_runtime_settings()
    effective_mode = container.ai_service._resolve_effective_mode(updated_state, runtime_settings)  # noqa: SLF001

    access_level = str(
        payload.get("access_level")
        or container.access_engine.update_access_level(updated_state)
    ).strip()
    memory_context = await container.ai_service._build_memory_context(  # noqa: SLF001
        updated_state,
        user_id=0,
        history=[],
    )
    grounding_kind = container.keyword_memory_service.detect_grounding_need(user_message)

    return {
        "user_message": user_message,
        "active_mode": effective_mode,
        "access_level": access_level,
        "updated_state": updated_state,
        "memory_context": memory_context,
        "grounding_kind": grounding_kind,
    }


@app.get("/api/overview")
async def api_overview(_: str = Depends(require_auth)):
    return await _ensure_admin_metrics().get_overview()


@app.get("/api/health")
async def api_health(_: str = Depends(require_auth)):
    return await _build_health()


@app.get("/api/settings")
async def api_settings(_: str = Depends(require_auth)):
    return container.admin_settings_service.export_all()


@app.get("/api/export")
async def api_export(_: str = Depends(require_auth)):
    return container.admin_settings_service.export_all()


@app.put("/api/settings/runtime")
async def api_runtime_settings(request: Request, _: str = Depends(require_auth)):
    payload = await request.json()
    try:
        data = container.admin_settings_service.update_runtime_settings(payload)
        await _invalidate_metrics_cache()
        return data
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/settings/prompts")
async def api_prompt_settings(request: Request, _: str = Depends(require_auth)):
    payload = await request.json()
    try:
        data = container.admin_settings_service.update_prompt_templates(payload)
        await _invalidate_metrics_cache()
        return data
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/settings/modes")
async def api_mode_settings(request: Request, _: str = Depends(require_auth)):
    payload = await request.json()
    try:
        data = container.admin_settings_service.update_modes(payload)
        await _invalidate_metrics_cache()
        return data
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/settings/mode-catalog")
async def api_mode_catalog_settings(request: Request, _: str = Depends(require_auth)):
    payload = await request.json()
    try:
        data = container.admin_settings_service.update_mode_catalog(payload)
        await _invalidate_metrics_cache()
        return data
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/users")
async def api_users(
    query: str = "",
    limit: int = 50,
    sort_by: str = "created_desc",
    filter_by: str = "all",
    _: str = Depends(require_auth),
):
    return {
        "matched_count": await container.user_service.count_users(
            query=query,
            filter_by=filter_by,
        ),
        "segments": await container.user_service.get_subscription_segments_overview(),
        "items": await container.user_service.search_users(
            query=query,
            limit=limit,
            sort_by=sort_by,
            filter_by=filter_by,
        ),
        "query": query,
        "limit": limit,
        "sort_by": sort_by,
        "filter_by": filter_by,
    }


@app.get("/api/users/{user_id}")
async def api_user_details(user_id: int, _: str = Depends(require_auth)):
    user = await container.user_service.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return user


@app.put("/api/users/{user_id}")
async def api_user_update(user_id: int, request: Request, _: str = Depends(require_auth)):
    payload = await request.json()
    modes = container.admin_settings_service.get_mode_catalog()

    active_mode = str(payload.get("active_mode") or "base").strip() or "base"
    if active_mode not in modes:
        raise HTTPException(status_code=400, detail="Неизвестный режим")

    try:
        user = await container.user_service.upsert_user_access(
            user_id,
            active_mode=active_mode,
            is_premium=bool(payload.get("is_premium")),
            is_admin=bool(payload.get("is_admin")),
        )
        await container.state_repository.set_active_mode(user_id, active_mode)
        await _invalidate_metrics_cache()
        return user
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/users/{user_id}/message")
async def api_user_send_message(
    user_id: int,
    request: Request,
    _: str = Depends(require_auth),
):
    payload = await request.json()
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Текст сообщения не может быть пустым")

    try:
        return await _deliver_dashboard_message(user_id, text)
    except DashboardMessageDeliveryError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/api/users/broadcast/preview")
async def api_users_broadcast_preview(
    request: Request,
    _: str = Depends(require_auth),
):
    payload = await request.json()
    text = str(payload.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Текст сообщения не может быть пустым")

    user_ids = _normalize_broadcast_targets(payload.get("user_ids"))
    return build_broadcast_preview(
        user_ids,
        text,
        secret=_broadcast_secret(),
    )


@app.post("/api/users/broadcast")
async def api_users_broadcast(
    request: Request,
    _: str = Depends(require_auth),
):
    payload = await request.json()
    text = str(payload.get("text") or "").strip()
    confirmation_token = str(payload.get("confirmation_token") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Текст сообщения не может быть пустым")
    user_ids = _normalize_broadcast_targets(payload.get("user_ids"))
    expected_token = build_broadcast_confirmation_token(
        user_ids,
        text,
        secret=_broadcast_secret(),
    )
    if not confirmation_token or not secrets.compare_digest(confirmation_token, expected_token):
        raise HTTPException(
            status_code=400,
            detail="Сначала запроси preview и подтверди рассылку этим же составом получателей.",
        )

    sent: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []

    for index, user_id in enumerate(user_ids):
        try:
            result = await _deliver_dashboard_message(
                user_id,
                text,
                invalidate_metrics=False,
            )
            sent.append(
                {
                    "user_id": user_id,
                    "active_mode": result["active_mode"],
                }
            )
        except DashboardMessageDeliveryError as exc:
            failed.append(
                {
                    "user_id": user_id,
                    "status_code": exc.status_code,
                    "error": exc.detail,
                }
            )
        except Exception as exc:
            failed.append(
                {
                    "user_id": user_id,
                    "status_code": 500,
                    "error": f"Неожиданная ошибка: {exc}",
                }
            )

        if index < len(user_ids) - 1:
            await asyncio.sleep(0.05)

    if sent:
        try:
            await _invalidate_metrics_cache()
        except Exception:
            pass

    return {
        "ok": not failed,
        "requested_count": len(user_ids),
        "sent_count": len(sent),
        "failed_count": len(failed),
        "sent": sent,
        "failed": failed,
    }


@app.get("/api/users/{user_id}/conversation")
async def api_user_conversation(
    user_id: int,
    limit: int = 100,
    _: str = Depends(require_auth),
):
    user = await container.user_service.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    safe_limit = max(1, min(limit, 200))
    messages = await container.message_repository.get_user_messages(
        user_id,
        limit=safe_limit,
    )
    stats = await container.message_repository.get_user_message_stats(user_id)
    state_payload = await container.state_repository.get(user_id)
    history = await container.message_repository.get_last_messages(
        user_id=user_id,
        limit=max(
            safe_limit,
            container.admin_settings_service.get_runtime_settings()["ai"]["history_message_limit"],
        ),
    )
    durable_memory_preview = await container.long_term_memory_service.build_prompt_context(
        user_id,
    )
    state_memory_preview = container.keyword_memory_service.build_prompt_context(
        state_payload,
        history=history,
    )
    ai_settings = container.admin_settings_service.get_runtime_settings()["ai"]

    return {
        "user": user,
        "stats": stats,
        "messages": messages,
        "state": state_payload,
        "memory_preview": "\n".join(
            part.strip()
            for part in (durable_memory_preview, state_memory_preview)
            if part and part.strip()
        ),
        "long_term_memories": await container.long_term_memory_service.get_user_memories(
            user_id,
            limit=80,
        ),
        "settings": {
            "history_message_limit": int(ai_settings.get("history_message_limit", 20)),
            "memory_max_tokens": int(ai_settings.get("memory_max_tokens", 1500)),
            "long_term_memory_enabled": bool(ai_settings.get("long_term_memory_enabled", True)),
            "long_term_memory_max_items": int(ai_settings.get("long_term_memory_max_items", 12)),
            "long_term_memory_auto_prune_enabled": bool(
                ai_settings.get("long_term_memory_auto_prune_enabled", True)
            ),
            "long_term_memory_soft_limit": int(
                ai_settings.get("long_term_memory_soft_limit", 60)
            ),
            "episodic_summary_enabled": bool(ai_settings.get("episodic_summary_enabled", True)),
            "memory_categories": container.long_term_memory_service.get_category_options(),
        },
    }


@app.post("/api/users/{user_id}/memories")
async def api_memory_create(
    user_id: int,
    request: Request,
    _: str = Depends(require_auth),
):
    user = await container.user_service.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ РЅРµ РЅР°Р№РґРµРЅ")

    payload = await request.json()
    try:
        memory = await container.long_term_memory_service.save_manual_memory(
            user_id=user_id,
            category=str(payload.get("category") or ""),
            value=str(payload.get("value") or ""),
            weight=payload.get("weight"),
            pinned=bool(payload.get("pinned")),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "memory": memory}


@app.post("/api/memories/{memory_id}/pin")
async def api_memory_pin(memory_id: int, request: Request, _: str = Depends(require_auth)):
    payload = await request.json()
    await container.long_term_memory_service.set_pinned(
        memory_id,
        bool(payload.get("pinned")),
    )
    return {"ok": True, "memory_id": memory_id, "pinned": bool(payload.get("pinned"))}


@app.put("/api/memories/{memory_id}")
async def api_memory_update(
    memory_id: int,
    request: Request,
    _: str = Depends(require_auth),
):
    payload = await request.json()
    try:
        memory = await container.long_term_memory_service.save_manual_memory(
            memory_id=memory_id,
            user_id=int(payload.get("user_id") or 0),
            category=str(payload.get("category") or ""),
            value=str(payload.get("value") or ""),
            weight=payload.get("weight"),
            pinned=bool(payload.get("pinned")),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "memory": memory}


@app.delete("/api/memories/{memory_id}")
async def api_memory_delete(memory_id: int, _: str = Depends(require_auth)):
    deleted = await container.long_term_memory_service.delete_memory(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"ok": True, "memory_id": memory_id}


@app.post("/api/users/{user_id}/memories/prune")
async def api_user_memories_prune(
    user_id: int,
    _: str = Depends(require_auth),
):
    user = await container.user_service.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="РџРѕР»СЊР·РѕРІР°С‚РµР»СЊ РЅРµ РЅР°Р№РґРµРЅ")
    return await container.long_term_memory_service.auto_prune(user_id)


@app.post("/api/actions/cache/invalidate")
async def api_invalidate_cache(_: str = Depends(require_auth)):
    await _invalidate_metrics_cache()
    return {"ok": True}


@app.post("/api/test/prompt")
async def api_test_prompt(request: Request, _: str = Depends(require_auth)):
    payload = await request.json()
    context = await _prepare_test_context(payload)
    history = _parse_history(payload.get("history"))
    runtime_settings = container.admin_settings_service.get_runtime_settings()
    ai_profile = resolve_ai_profile(runtime_settings["ai"], context["active_mode"])
    system_prompt = container.ai_service.conversation_engine.build_system_prompt(
        state=context["updated_state"],
        access_level=context["access_level"],
        active_mode=context["active_mode"],
        memory_context=context["memory_context"],
        user_message=context["user_message"],
        base_instruction=ai_profile["prompt_suffix"],
        history=history,
    )
    return {
        "prompt": system_prompt,
        "updated_state": context["updated_state"],
        "access_level": context["access_level"],
        "grounding_kind": context["grounding_kind"],
    }


@app.post("/api/test/state")
async def api_test_state(request: Request, _: str = Depends(require_auth)):
    payload = await request.json()
    context = await _prepare_test_context(payload)
    return {
        "updated_state": context["updated_state"],
        "memory_context": context["memory_context"],
        "access_level": context["access_level"],
        "grounding_kind": context["grounding_kind"],
        "grounding_response": (
            container.keyword_memory_service.build_grounding_response(context["grounding_kind"])
            if context["grounding_kind"]
            else ""
        ),
    }


@app.post("/api/test/reply")
async def api_test_reply(request: Request, _: str = Depends(require_auth)):
    payload = await request.json()
    context = await _prepare_test_context(payload)
    history = _parse_history(payload.get("history"))
    runtime_settings = container.admin_settings_service.get_runtime_settings()
    chat_settings = runtime_settings.get("chat", {})

    if not context["user_message"]:
        raise HTTPException(status_code=400, detail="Для live-теста нужно сообщение пользователя")

    if context["grounding_kind"] is not None:
        response_text = container.keyword_memory_service.build_grounding_response(context["grounding_kind"])
        guarded_response = apply_ptsd_response_guardrails(
            response_text,
            active_mode=context["active_mode"],
            emotional_tone=str(context["updated_state"].get("emotional_tone") or "neutral"),
            enabled=bool(chat_settings.get("response_guardrails_enabled", True)),
            blocked_phrases=list(chat_settings.get("response_guardrail_blocked_phrases") or []),
        )
        return {
            "response": guarded_response,
            "prompt": None,
            "grounding_kind": context["grounding_kind"],
            "tokens_used": None,
            "updated_state": context["updated_state"],
            "response_audit": analyze_response_style(
                guarded_response,
                blocked_phrases=list(chat_settings.get("response_guardrail_blocked_phrases") or []),
            ),
        }

    ai_settings = runtime_settings["ai"]
    ai_profile = resolve_ai_profile(ai_settings, context["active_mode"])
    system_prompt = container.ai_service.conversation_engine.build_system_prompt(
        state=context["updated_state"],
        access_level=context["access_level"],
        active_mode=context["active_mode"],
        memory_context=context["memory_context"],
        user_message=context["user_message"],
        base_instruction=ai_profile["prompt_suffix"],
        history=history,
    )
    messages = [{"role": "system", "content": system_prompt}] + history + [
        {"role": "user", "content": context["user_message"]},
    ]
    response_text, tokens_used = await container.openai_client.generate(
        messages=messages,
        model=ai_profile["model"],
        temperature=ai_profile["temperature"],
        top_p=ai_settings["top_p"],
        frequency_penalty=ai_settings["frequency_penalty"],
        presence_penalty=ai_settings["presence_penalty"],
        max_completion_tokens=ai_profile["max_completion_tokens"],
        reasoning_effort=ai_settings["reasoning_effort"] or None,
        verbosity=ai_settings["verbosity"] or None,
        user="admin-live-test",
    )
    guarded_response = container.ai_service._apply_ptsd_response_contract(  # noqa: SLF001
        response_text,
        active_mode=context["active_mode"],
        emotional_tone=str(context["updated_state"].get("emotional_tone") or "neutral"),
        enabled=bool(chat_settings.get("response_guardrails_enabled", True)),
        blocked_phrases=list(chat_settings.get("response_guardrail_blocked_phrases") or []),
        user_id=0,
        source="admin-test-reply",
    )
    guarded_response = container.ai_service.conversation_engine.guard_response(
        guarded_response,
        user_message=context["user_message"],
        active_mode=context["active_mode"],
        history=history,
    )
    return {
        "response": guarded_response,
        "prompt": system_prompt,
        "grounding_kind": None,
        "tokens_used": tokens_used,
        "updated_state": context["updated_state"],
        "response_audit": analyze_response_style(
            guarded_response,
            blocked_phrases=list(chat_settings.get("response_guardrail_blocked_phrases") or []),
        ),
    }


@app.post("/api/test/reengagement")
async def api_test_reengagement(request: Request, _: str = Depends(require_auth)):
    payload = await request.json()
    history = _parse_history(payload.get("history"))
    state = _parse_json_field(payload.get("state"), {})
    user_id = int(payload.get("user_id") or 0)

    result = await container.ai_service.generate_reengagement(
        user_id=user_id,
        history=history,
        state=state,
    )
    return {
        "response": result.response,
        "tokens_used": result.tokens_used,
        "updated_state": result.new_state,
    }


@app.get("/api/logs")
async def api_logs(lines: int = 200, _: str = Depends(require_auth)):
    return container.admin_settings_service.get_logs(lines=lines)


def _dashboard_html() -> str:
    return """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Админка бота</title>
  <style>
    :root{--bg:#08111b;--bg2:#13283c;--panel:rgba(9,19,32,.84);--soft:rgba(255,255,255,.05);--text:#eef6ff;--muted:#9bb0c8;--accent:#85df96;--accent-2:#59c9a8;--warn:#f7c971;--danger:#ff7b72;--border:rgba(255,255,255,.08);--shadow:0 18px 48px rgba(0,0,0,.24);--content-max:1600px}
    *{box-sizing:border-box}body{margin:0;color:var(--text);font-family:"Trebuchet MS","Segoe UI",sans-serif;background:radial-gradient(circle at top left,rgba(133,223,150,.12),transparent 26%),radial-gradient(circle at top right,rgba(247,201,113,.12),transparent 24%),linear-gradient(145deg,var(--bg),var(--bg2))}
    .layout{display:grid;grid-template-columns:272px minmax(0,1fr);min-height:100vh}.sidebar{padding:18px 14px;border-right:1px solid var(--border);background:rgba(5,12,20,.8);backdrop-filter:blur(14px)}.sidebar-inner{position:sticky;top:18px;display:grid;gap:16px}.main{padding:20px;display:grid;gap:14px;min-width:0}.main>*{width:100%;max-width:var(--content-max);margin:0 auto}
    .brand-card{padding:18px;border:1px solid var(--border);border-radius:22px;background:linear-gradient(180deg,rgba(255,255,255,.05),rgba(255,255,255,.02));box-shadow:var(--shadow)}.brand-eyebrow{font-size:11px;text-transform:uppercase;letter-spacing:.14em;color:var(--warn);margin-bottom:10px}.brand-title{margin:0 0 10px;font-size:28px;line-height:1.05}.brand-copy{margin:0;color:var(--muted);line-height:1.5}
    .nav{display:grid;gap:8px}.nav button,.toolbar button,.actions button{border:1px solid var(--border);background:var(--soft);color:var(--text);border-radius:14px;padding:10px 13px;cursor:pointer;font-weight:600;transition:transform .15s ease,background .15s ease,border-color .15s ease,box-shadow .15s ease}.nav button{text-align:left;width:100%}.nav button:hover,.toolbar button:hover,.actions button:hover{transform:translateY(-1px);border-color:rgba(255,255,255,.16)}.nav button.active,.toolbar .primary,.actions .primary{background:linear-gradient(135deg,var(--accent),var(--accent-2));color:#082112;border:0;box-shadow:0 10px 24px rgba(89,201,168,.24)}
    .sidebar-panels{display:grid;gap:12px}.compact-panel{padding:14px 16px}.sidebar-meta{display:flex;flex-wrap:wrap;gap:8px}.sidebar-chip{display:inline-flex;align-items:center;padding:6px 10px;border-radius:999px;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.08);font-size:12px;color:var(--muted)}
    .toolbar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:14px}.toolbar input,.toolbar select{flex:1 1 220px;min-width:0}.toolbar button{flex:0 0 auto}.top-toolbar{position:sticky;top:12px;z-index:3;padding:14px 16px;margin-bottom:0;border:1px solid var(--border);border-radius:20px;background:rgba(7,15,24,.86);backdrop-filter:blur(16px);box-shadow:var(--shadow)}
    .hero{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(280px,.8fr);gap:16px;align-items:stretch;padding:20px 22px;background:linear-gradient(160deg,rgba(133,223,150,.12),rgba(255,255,255,.02) 38%,rgba(247,201,113,.08));box-shadow:var(--shadow)}.hero-main{display:grid;gap:8px;align-content:start}.hero-kicker{font-size:11px;text-transform:uppercase;letter-spacing:.16em;color:var(--warn)}.hero-title{margin:0;font-size:34px;line-height:1.04}.hero-subtitle{margin:0;max-width:74ch;line-height:1.5}.hero-actions{display:grid;gap:12px;align-content:start}.hero-meta-grid{display:grid;gap:12px}.hero-meta{padding:14px 16px;border:1px solid rgba(255,255,255,.08);border-radius:18px;background:rgba(255,255,255,.04)}.hero-meta-label{font-size:11px;text-transform:uppercase;letter-spacing:.12em;color:var(--muted);margin-bottom:8px}.hero-meta-value{font-size:15px;line-height:1.45}
    .page{display:none;gap:14px}.page.active{display:grid}.panel,.card{background:var(--panel);border:1px solid var(--border);border-radius:20px;padding:16px;box-shadow:var(--shadow)}.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(210px,1fr))}.cols{display:grid;gap:16px;grid-template-columns:repeat(2,minmax(0,1fr));align-items:start}.users-layout{grid-template-columns:minmax(320px,420px) minmax(0,1fr)}.conversations-layout{grid-template-columns:minmax(380px,520px) minmax(0,1fr)}.two{display:grid;gap:12px;grid-template-columns:repeat(2,minmax(0,1fr))}.three{display:grid;gap:12px;grid-template-columns:repeat(3,minmax(0,1fr))}
    h1,h2,h3,p{margin-top:0}.muted{color:var(--muted)}.stat-label{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:7px}.stat-value{font-size:30px;font-weight:700}
    label{display:block;margin-bottom:12px}input,textarea,select{width:100%;margin-top:6px;padding:10px 12px;border-radius:12px;border:1px solid rgba(255,255,255,.12);background:rgba(8,17,29,.92);color:var(--text);font:inherit}textarea{min-height:104px;resize:vertical}
    .checkbox{display:flex;align-items:center;gap:10px;margin:8px 0 14px}.checkbox input{width:auto;margin:0}.notice{display:none;padding:12px 14px;border-radius:14px;margin-bottom:14px}.notice.ok{display:block;background:rgba(96,210,124,.12);border:1px solid rgba(96,210,124,.22)}.notice.error{display:block;background:rgba(255,123,114,.12);border:1px solid rgba(255,123,114,.24)}
    pre{white-space:pre-wrap;word-break:break-word;font-family:Consolas,"Courier New",monospace;font-size:13px}.mode-card{border:1px solid var(--border);border-radius:16px;padding:14px;background:rgba(255,255,255,.03);margin-bottom:12px}.mode-head{display:flex;justify-content:space-between;gap:10px;align-items:center;margin-bottom:10px}.badge{padding:5px 10px;border-radius:999px;background:rgba(255,255,255,.08);font-size:12px}
    .stack{display:grid;gap:12px}.mini-grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(140px,1fr))}.metric{padding:12px 14px;border-radius:16px;border:1px solid var(--border);background:rgba(255,255,255,.03)}.metric .stat-label{margin-bottom:6px}.metric-value-small{font-size:20px;font-weight:700}.kv-list{display:grid;gap:10px}.kv-row{display:flex;justify-content:space-between;gap:16px;padding:10px 12px;border-radius:14px;border:1px solid var(--border);background:rgba(255,255,255,.03)}.kv-key{color:var(--muted)}.kv-value{text-align:right;word-break:break-word}.status-pill{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:999px;font-size:12px;font-weight:700}.status-pill.ok{background:rgba(96,210,124,.14);color:#9ff0af}.status-pill.bad{background:rgba(255,123,114,.14);color:#ffb0a8}.status-pill.warn{background:rgba(247,201,113,.14);color:#ffd993}.panel h3{margin-bottom:10px}.section-note{margin-bottom:12px}.package-grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}.soft-panel{padding:14px;border-radius:16px;border:1px solid var(--border);background:rgba(255,255,255,.03)}.preset-bar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}.preset-bar button{border-radius:999px}.readiness-list{display:grid;gap:10px}.readiness-item{display:grid;grid-template-columns:auto 1fr auto;gap:10px;align-items:start;padding:12px;border:1px solid var(--border);border-radius:16px;background:rgba(255,255,255,.03)}.readiness-dot{width:10px;height:10px;border-radius:50%;margin-top:6px;background:var(--muted)}.readiness-dot.ok{background:#60d27c}.readiness-dot.warn{background:#f7c971}.readiness-dot.bad{background:#ff7b72}.qa-note{display:grid;gap:8px;margin-top:12px}.qa-note .kv-row{align-items:flex-start}.shortcut-grid{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(190px,1fr))}
    table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:9px 8px;border-bottom:1px solid rgba(255,255,255,.08);text-align:left;vertical-align:top}th{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--warn)}
    .conversation-feed{display:grid;gap:12px;max-height:56vh;overflow:auto;padding-right:4px}.message-card{padding:14px;border-radius:16px;border:1px solid var(--border);background:rgba(255,255,255,.03)}.message-card.user{border-color:rgba(133,223,150,.24);background:rgba(133,223,150,.08)}.message-card.assistant{border-color:rgba(155,176,200,.2)}.message-meta{display:flex;justify-content:space-between;gap:12px;margin-bottom:8px;font-size:12px;color:var(--muted)}.memory-box{min-height:120px;max-height:220px;overflow:auto;background:rgba(8,17,29,.92);border:1px solid rgba(255,255,255,.08);border-radius:16px;padding:14px}.memory-row-actions{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}.memory-editor-form{display:grid;gap:12px}.memory-actions{display:flex;gap:10px;flex-wrap:wrap}.state-panel{display:grid;gap:12px}.state-section{padding:14px;border-radius:16px;border:1px solid var(--border);background:rgba(255,255,255,.03)}.state-section h4{margin:0 0 10px;font-size:14px}.state-raw{margin-top:6px}.state-raw summary{cursor:pointer;color:var(--muted);margin-bottom:10px}.state-raw[open] summary{margin-bottom:12px}.memory-preview-panel{display:grid;gap:12px}.memory-preview-item{padding:14px;border-radius:16px;border:1px solid var(--border);background:rgba(255,255,255,.03)}.memory-preview-item h4{margin:0 0 10px;font-size:14px}.memory-preview-item ul{margin:0;padding-left:18px}.memory-preview-item li+li{margin-top:6px}.composer{display:grid;gap:12px}.composer textarea{min-height:96px}.composer-meta{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap}.template-list{display:flex;gap:8px;flex-wrap:wrap}.template-chip{border:1px solid var(--border);background:rgba(255,255,255,.04);color:var(--text);border-radius:999px;padding:7px 11px;cursor:pointer}.template-chip.active{background:rgba(247,201,113,.18);border-color:rgba(247,201,113,.42);color:#ffe6a6}.bulk-summary{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap;margin:8px 0 12px}.bulk-result{min-height:96px;max-height:180px}.table-wrap{overflow:auto}.table-wrap table{min-width:860px}.overview-hero-grid{grid-template-columns:repeat(auto-fit,minmax(180px,1fr))}.overview-table table{min-width:0}.overview-details .panel{background:rgba(255,255,255,.02)}.users-search-toolbar input{flex:2 1 320px}.details-panel{padding:0;overflow:hidden}.details-panel summary{list-style:none;cursor:pointer;padding:16px 18px;font-weight:700}.details-panel summary::-webkit-details-marker{display:none}.details-panel[open] summary{background:rgba(255,255,255,.03);border-bottom:1px solid var(--border)}.details-content{padding:16px 18px}.segment-summary{margin-bottom:4px}.user-select-cell{width:42px}.inline-checkbox{width:auto;margin:0}
    @media (max-width:1380px){.users-layout,.conversations-layout,.hero{grid-template-columns:1fr}}
    @media (max-width:1180px){.layout{grid-template-columns:1fr}.sidebar-inner{position:static}.cols,.two,.three{grid-template-columns:1fr}.main{padding:16px}.toolbar input,.toolbar select,.toolbar button{flex:1 1 100%}}
  </style>
</head>
<body>
  <div class="layout">
    <aside class="sidebar">
      <div class="sidebar-inner">
        <div class="brand-card">
          <div class="brand-eyebrow">Пульт SaaS-бота</div>
          <h1 class="brand-title">Пульт управления</h1>
          <p class="brand-copy">Один экран для состояния продукта, живых настроек, промптов, режимов, оплаты и проверки поведения бота.</p>
        </div>
        <div class="nav">
          <button class="active" data-view="overview">Обзор</button>
          <button data-view="setup">Настройка</button>
          <button data-view="users">Пользователи</button>
          <button data-view="conversations">Диалоги</button>
          <button data-view="runtime">ИИ и интерфейс</button>
          <button data-view="safety">Безопасность</button>
          <button data-view="prompts">Промпты</button>
          <button data-view="modes">Режимы</button>
          <button data-view="payments">Оплата</button>
          <button data-view="testing">Тесты</button>
          <button data-view="logs">Логи</button>
        </div>
        <div class="sidebar-panels">
          <div class="panel compact-panel">
            <div class="stat-label">Состояние</div>
            <div id="sidebar-health" class="muted">Загрузка...</div>
          </div>
          <div class="panel compact-panel">
            <div class="stat-label">Контекст</div>
            <div id="sidebar-meta" class="sidebar-meta"><span class="sidebar-chip">Ждём первую синхронизацию…</span></div>
          </div>
        </div>
      </div>
    </aside>
    <main class="main">
      <div class="toolbar top-toolbar">
        <button class="primary" id="refresh-all">Обновить все</button>
        <button id="export-json">Экспорт JSON</button>
        <label class="checkbox" style="margin:0"><input id="export-raw-json" type="checkbox">Raw export</label>
        <button id="invalidate-cache">Сбросить кеш</button>
      </div>
      <section class="hero panel">
        <div class="hero-main">
          <div class="hero-kicker" id="header-kicker">Операционный центр</div>
          <h2 class="hero-title" id="header-title">Обзор продукта</h2>
          <p class="hero-subtitle muted" id="header-subtitle">Метрики пользователей, платежей, поддержки и состояние инфраструктуры в одном ритме.</p>
        </div>
        <div class="hero-actions">
          <div class="hero-meta-grid">
            <div class="hero-meta">
              <div class="hero-meta-label">Релиз</div>
              <div class="hero-meta-value" id="header-release">Ждём данные о релизе…</div>
            </div>
            <div class="hero-meta">
              <div class="hero-meta-label">Синхронизация</div>
              <div class="hero-meta-value" id="header-sync">Ждём первую загрузку…</div>
            </div>
            <div class="hero-meta">
              <div class="hero-meta-label">Контекст</div>
              <div class="hero-meta-value" id="header-context">После загрузки здесь появятся база, активная аудитория и текущий фокус страницы.</div>
            </div>
          </div>
        </div>
      </section>
      <div id="notice" class="notice"></div>

      <section class="page active" data-view="overview">
        <div>
          <h2>Обзор</h2>
          <p class="muted">Метрики пользователей, платежей, поддержки и состояние инфраструктуры.</p>
        </div>
        <div class="panel">
          <div class="mode-head">
            <div>
              <h3>Готовность к запуску</h3>
              <p class="muted section-note">Быстрая SaaS-проверка: можно ли показывать этот бот оператору и запускать первых пользователей.</p>
            </div>
            <button data-open-view="setup">Открыть настройку</button>
          </div>
          <div id="overview-launch-readiness"></div>
        </div>
        <div id="overview-cards" class="grid overview-hero-grid"></div>
        <div class="three">
          <div class="panel"><h3>Аудитория</h3><div id="overview-audience"></div></div>
          <div class="panel"><h3>Выручка и оплаты</h3><div id="overview-revenue"></div></div>
          <div class="panel"><h3>Активность и система</h3><div id="overview-runtime"></div></div>
        </div>
        <div class="cols">
          <div class="panel"><h3>Новые пользователи</h3><div id="recent-users"></div></div>
          <div class="panel"><h3>Последние оплаты</h3><div id="recent-payments"></div></div>
        </div>
        <div class="cols">
          <div class="panel"><h3>Поддержка</h3><div id="support-summary"></div></div>
          <div class="panel"><h3>Монетизация 30 дней</h3><div id="monetization-summary"></div></div>
        </div>
        <details class="panel details-panel overview-details">
          <summary>Подробная аналитика обзора</summary>
          <div class="details-content stack">
            <div class="cols">
              <div class="panel"><h3>Система и релиз</h3><div id="health-summary"></div></div>
              <div class="panel"><h3>Последние события монетизации</h3><div id="recent-monetization"></div></div>
            </div>
            <div class="cols">
              <div class="panel"><h3>По триггеру оффера</h3><div id="monetization-by-trigger"></div></div>
              <div class="panel"><h3>По A/B варианту</h3><div id="monetization-by-variant"></div></div>
            </div>
          </div>
        </details>
      </section>

      <section class="page" data-view="setup">
        <div><h2>Настройка и запуск</h2><p class="muted">Срез для оператора SaaS: что настроено, что мешает запуску и куда идти править.</p></div>
        <div class="cols">
          <div class="panel">
            <h3>Готовность к запуску</h3>
            <div id="setup-readiness"></div>
          </div>
          <div class="panel">
            <h3>Образ бота</h3>
            <div id="setup-identity"></div>
          </div>
        </div>
        <div class="panel">
          <h3>Быстрые переходы</h3>
          <p class="muted section-note">Это не отдельная копия настроек, а навигация по тем местам, где оператор реально готовит запуск.</p>
          <div class="shortcut-grid">
            <button data-open-view="runtime">Тексты старта и меню</button>
            <button data-open-view="modes">Режимы и платность</button>
            <button data-open-view="payments">Тарифы и paywall</button>
            <button data-open-view="testing">Лаборатория диалога</button>
            <button data-open-view="users">Пользователи и сегменты</button>
            <button data-open-view="logs">Health и логи</button>
          </div>
        </div>
        <div class="panel">
          <h3>Фокус SaaS-MVP</h3>
          <div id="setup-saas-summary"></div>
        </div>
      </section>

      <section class="page" data-view="users">
        <div><h2>Пользователи и права</h2><p class="muted">Добавляй администраторов, меняй премиум-статус и назначай активный режим для конкретного пользователя.</p></div>
        <div class="cols users-layout">
          <div class="panel">
            <h3>Карточка пользователя</h3>
            <p class="muted section-note">Ручное управление конкретным пользователем: права, premium и активный режим.</p>
            <div class="two">
              <label>ID пользователя<input id="user_user_id" type="number" min="1" placeholder="Например, 123456789"></label>
              <label>Активный режим<select id="user_active_mode"></select></label>
              <label>Имя пользователя<input id="user_username" readonly></label>
              <label>Имя<input id="user_first_name" readonly></label>
            </div>
            <label class="checkbox"><input id="user_is_admin" type="checkbox">Администратор</label>
            <label class="checkbox"><input id="user_is_premium" type="checkbox">Премиум-доступ</label>
            <p class="muted" id="user_meta">Можно ввести ID вручную и сохранить: запись создастся даже если пользователь ещё не появился в таблице.</p>
            <div class="actions">
              <button id="load-user">Загрузить</button>
              <button id="open-user-conversation">Открыть диалог</button>
              <button class="primary" id="save-user">Сохранить пользователя</button>
            </div>
          </div>
          <div class="panel">
            <h3>Поиск и список</h3>
            <p class="muted section-note">Быстрый поиск, сегменты premium и действия по выбранным пользователям.</p>
            <div class="toolbar users-search-toolbar">
              <input id="user-search" placeholder="ID, имя пользователя или имя">
              <select id="user-sort">
                <option value="created_desc">Новые сначала</option>
                <option value="premium_active_first">С Premium наверху</option>
                <option value="premium_expiry_asc">Подписка скоро закончится</option>
                <option value="premium_expiry_desc">Подписка закончится нескоро</option>
                <option value="premium_expiring_soon">Скоро истекают наверху</option>
                <option value="premium_expired">Истекшие наверху</option>
              </select>
              <button class="primary" id="search-users">Найти</button>
              <button id="reset-users">Сбросить</button>
            </div>
            <div class="template-list" id="user-filter-buttons">
              <button type="button" class="template-chip active" data-user-filter="all">Все</button>
              <button type="button" class="template-chip" data-user-filter="premium_active">Платные активны</button>
              <button type="button" class="template-chip" data-user-filter="premium_expiring_3d">Истекают за 3 дня</button>
              <button type="button" class="template-chip" data-user-filter="premium_expired">Истекли</button>
              <button type="button" class="template-chip" data-user-filter="without_premium">Free и истекшие</button>
            </div>
            <div id="user-segment-summary" class="segment-summary"></div>
            <p class="muted" id="users-result-meta">Здесь появится сводка по списку пользователей.</p>
            <details class="details-panel" style="margin-bottom:16px">
              <summary>&#1056;&#1072;&#1089;&#1089;&#1099;&#1083;&#1082;&#1072; &#1080; &#1096;&#1072;&#1073;&#1083;&#1086;&#1085;&#1099;</summary>
              <div class="details-content">
            <div class="composer">
              <h4>Рассылка выбранным пользователям</h4>
              <label>Текст рассылки
                <textarea id="bulk_message_text" placeholder="Сообщение уйдет только выбранным пользователям"></textarea>
              </label>
              <div id="bulk-message-templates" class="template-list"></div>
              <div class="bulk-summary">
                <div class="muted" id="selected-users-count">Выбрано пользователей: 0</div>
                <div class="actions">
                  <button id="select-visible-users">Выбрать видимых</button>
                  <button id="clear-selected-users">Снять выбор</button>
                  <button class="primary" id="send-bulk-message">Отправить выбранным</button>
                </div>
              </div>
              <pre id="bulk-message-results" class="memory-box bulk-result">Здесь появится отчет по рассылке.</pre>
              <div class="state-section">
                <h4>Шаблоны сообщений</h4>
                <p class="muted">Один шаблон отделяй пустой строкой. Эти шаблоны используются и для личной отправки, и для рассылки.</p>
                <label>Редактор шаблонов<textarea id="message_templates_editor" placeholder="Первый шаблон&#10;&#10;Второй шаблон"></textarea></label>
                <div class="actions">
                  <button class="primary" id="save-message-templates">Сохранить шаблоны</button>
                  <button id="reset-message-templates">Сбросить изменения</button>
                </div>
              </div>
            </div>
              </div>
            </details>
            <div id="users-table" class="table-wrap"></div>
          </div>
        </div>
      </section>

      <section class="page" data-view="conversations">
        <div><h2>Диалоги и память</h2><p class="muted">Отдельный просмотр истории сообщений, долговременной памяти и текущего состояния пользователя.</p></div>
        <div class="cols conversations-layout">
          <div class="panel">
            <h3>Пользователь</h3>
            <div class="toolbar">
              <input id="conversation_user_id" type="number" min="1" placeholder="ID пользователя">
              <input id="conversation_limit" type="number" min="10" max="200" value="80" placeholder="Лимит сообщений">
              <button class="primary" id="load-conversation">Загрузить диалог</button>
            </div>
            <p class="muted" id="conversation-meta">Выберите пользователя, чтобы увидеть историю и память.</p>
            <div id="conversation-stats"></div>
            <div style="margin-top:16px">
              <h3>Память в промпте</h3>
              <p class="muted">Здесь показан уже безопасный preview памяти, который реально может попасть в модель. Инструкции, role-like строки и лишний шум отфильтровываются.</p>
              <div id="conversation-memory-preview-summary" class="memory-preview-panel"><div class="muted">Пока нет данных.</div></div>
              <details class="state-raw">
                <summary>Показать полный безопасный preview</summary>
                <pre id="conversation-memory-preview" class="memory-box">Пока нет данных.</pre>
              </details>
            </div>
            <div style="margin-top:16px">
              <h3>Долговременная память</h3>
              <div id="conversation-long-term-memories" class="memory-box"><div class="muted">Пока нет данных.</div></div>
            </div>
            <div style="margin-top:16px">
              <h3>Редактор памяти</h3>
              <div class="memory-editor-form">
                <input id="memory_editor_id" type="hidden">
                <div class="two">
                  <label>Категория<select id="memory_editor_category"></select></label>
                  <label>Вес<input id="memory_editor_weight" type="number" min="0.1" max="25" step="0.1" value="1.0"></label>
                </div>
                <label>Текст памяти<textarea id="memory_editor_value" style="min-height:100px"></textarea></label>
                <div class="muted">Сохраняйте краткие факты и наблюдения. Инструкции вроде system/developer prompt в памяти всё равно будут отфильтрованы перед использованием в ИИ.</div>
                <label class="checkbox"><input id="memory_editor_pinned" type="checkbox">Закрепить в памяти</label>
                <div class="memory-actions">
                  <button id="memory-editor-new">Новая</button>
                  <button class="primary" id="memory-editor-save">Сохранить</button>
                  <button id="memory-editor-delete">Удалить</button>
                  <button id="memory-editor-prune">Очистить слабые</button>
                </div>
              </div>
            </div>
            <div style="margin-top:16px">
              <h3>Состояние пользователя</h3>
              <div id="conversation-state-summary" class="state-panel"><div class="muted">Пока нет данных.</div></div>
              <details class="state-raw">
                <summary>Показать исходный JSON</summary>
                <pre id="conversation-state" class="memory-box">Пока нет данных.</pre>
              </details>
            </div>
          </div>
          <div class="panel">
            <h3>История сообщений и отправка</h3>
            <div class="composer">
              <h4>Личное сообщение пользователю</h4>
              <label>Текст сообщения<textarea id="conversation_outbound_text" placeholder="Написать пользователю от имени бота"></textarea></label>
              <div id="conversation-message-templates" class="template-list"></div>
              <div class="composer-meta">
                <div class="muted">Сообщение уйдет в Telegram и сохранится в историю как ответ бота.</div>
                <button class="primary" id="send-conversation-message">Отправить сообщение</button>
              </div>
            </div>
            <div id="conversation-messages" class="conversation-feed"><div class="muted">Пока нет данных.</div></div>
          </div>
        </div>
      </section>

      <section class="page" data-view="runtime">
        <div><h2>ИИ и интерфейс</h2><p class="muted">Основная модель, тексты чата, инициативные сообщения и всё, что пользователь видит в Telegram.</p></div>
        <div class="cols">
          <div class="panel">
            <h3>Ядро ИИ</h3>
            <p class="muted section-note">Базовые параметры ответа, памяти и ретраев. Это общие настройки, которые влияют почти на все режимы.</p>
            <div class="two">
              <label>Модель<input id="ai_openai_model"></label>
              <label>Язык ответа<input id="ai_response_language"></label>
              <label>Температура<input id="ai_temperature" type="number" step="0.1"></label>
              <label>Top P<input id="ai_top_p" type="number" step="0.05" min="0" max="1"></label>
              <label>Штраф за повторы<input id="ai_frequency_penalty" type="number" step="0.05" min="-2" max="2"></label>
              <label>Штраф за новые темы<input id="ai_presence_penalty" type="number" step="0.05" min="-2" max="2"></label>
              <label>Макс. токенов ответа<input id="ai_max_completion_tokens" type="number"></label>
              <label>Глубина рассуждения<input id="ai_reasoning_effort"></label>
              <label>Подробность ответа<input id="ai_verbosity"></label>
              <label>Таймаут<input id="ai_timeout_seconds" type="number"></label>
              <label>Повторы<input id="ai_max_retries" type="number"></label>
              <label>Память, токены<input id="ai_memory_max_tokens" type="number"></label>
              <label>История сообщений<input id="ai_history_message_limit" type="number"></label>
              <label>Элементов долгой памяти<input id="ai_long_term_memory_max_items" type="number" min="4"></label>
              <label>Мягкий лимит долгой памяти<input id="ai_long_term_memory_soft_limit" type="number" min="12"></label>
              <label>Debug user ID<input id="ai_debug_prompt_user_id" type="number"></label>
            </div>
            <div class="soft-panel">
              <label class="checkbox"><input id="ai_long_term_memory_enabled" type="checkbox">Включить долговременную память</label>
              <label class="checkbox"><input id="ai_long_term_memory_auto_prune_enabled" type="checkbox">Автоочистка слабых записей памяти</label>
              <label class="checkbox"><input id="ai_episodic_summary_enabled" type="checkbox">Включить episodic summary</label>
              <label class="checkbox"><input id="ai_log_full_prompt" type="checkbox">Логировать системный промпт</label>
              <div class="muted">Даже при включённом логировании чувствительные блоки памяти и state summary редактируются, но на проде этот режим лучше держать выключенным.</div>
            </div>
          </div>
          <div class="panel">
            <h3>Чат и ответы</h3>
            <p class="muted section-note">Пользовательские сообщения, тексты ошибок и поведение бота во время ответа.</p>
            <div class="soft-panel">
              <label class="checkbox"><input id="chat_typing_action_enabled" type="checkbox">Показывать индикатор набора</label>
              <label class="checkbox"><input id="chat_response_guardrails_enabled" type="checkbox">Включить PTSD/anti-canned response guardrails</label>
            </div>
            <div class="two">
              <label>Не-текстовое сообщение<textarea id="chat_non_text_message"></textarea></label>
              <label>Перегрузка<textarea id="chat_busy_message"></textarea></label>
              <label>Ошибка ИИ<textarea id="chat_ai_error_message"></textarea></label>
              <label>Текст кнопки «Написать»<textarea id="chat_write_prompt_message"></textarea></label>
            </div>
            <label>Фразы, которые лучше переписывать<textarea id="chat_response_guardrail_blocked_phrases"></textarea></label>
            <div class="muted">По одной фразе на строку. Эти фразы автоматически смягчаются в уязвимых состояниях вместо шаблонной терапевтичной подачи.</div>
          </div>
        </div>
        <div class="cols">
          <div class="panel">
            <h3>Переопределения по режимам</h3>
            <p class="muted section-note">Здесь можно задать отдельную модель, память, температуру и доп. инструкцию только для конкретного режима.</p>
            <div id="ai-mode-overrides"></div>
          </div>
          <div class="panel">
            <h3>Инициативные сообщения</h3>
            <p class="muted section-note">Единственный живой механизм, который пишет первым. Старый proactive worker оставлен как legacy-код, но в проде не запускается.</p>
            <div class="soft-panel">
              <label class="checkbox"><input id="initiative_enabled" type="checkbox">Бот может иногда написать первым</label>
            </div>
            <div class="three">
              <label>Пауза до инициативы, часов<input id="initiative_idle_hours" type="number" min="1"></label>
              <label>Пауза между инициативами, часов<input id="initiative_min_hours_between" type="number" min="1"></label>
              <label>Окно активности, дней<input id="initiative_recent_window_days" type="number" min="1"></label>
              <label>Проверка воркера, секунд<input id="initiative_poll_seconds" type="number" min="30"></label>
              <label>Макс сообщений за цикл<input id="initiative_batch_size" type="number" min="1"></label>
              <label>Начало тихих часов<input id="initiative_quiet_hours_start" type="number" min="0" max="23"></label>
              <label>Конец тихих часов<input id="initiative_quiet_hours_end" type="number" min="0" max="23"></label>
            </div>
            <div class="two">
              <label class="checkbox"><input id="initiative_quiet_hours_enabled" type="checkbox">Не писать в quiet hours</label>
              <label>Часовой пояс для тихих часов<input id="initiative_timezone"></label>
            </div>
            <div class="soft-panel">
              <h3>Стиль инициативы</h3>
              <div class="three">
                <label>Макс. длина, символов<input id="initiative_style_max_chars" type="number" min="120" max="500"></label>
                <label>Макс. токенов<input id="initiative_style_max_completion_tokens" type="number" min="32" max="300"></label>
                <label class="checkbox"><input id="initiative_style_allow_question" type="checkbox">Можно завершать лёгким вопросом</label>
              </div>
              <div class="two">
                <label class="checkbox"><input id="initiative_style_prefer_callback_thread" type="checkbox">Можно подхватить прошлую нить</label>
              </div>
              <div class="preset-bar">
                <button type="button" data-initiative-preset="warm">Тёплый старт</button>
                <button type="button" data-initiative-preset="balanced">Сбалансированный</button>
                <button type="button" data-initiative-preset="tight">Короткий и плотный</button>
              </div>
              <div class="two">
                <label class="checkbox"><input id="initiative_family_soft_presence" type="checkbox">Soft presence</label>
                <label class="checkbox"><input id="initiative_family_callback_thread" type="checkbox">Подхват прошлой нити</label>
                <label class="checkbox"><input id="initiative_family_mood_ping" type="checkbox">Mood ping</label>
                <label class="checkbox"><input id="initiative_family_playful_hook" type="checkbox">Playful hook</label>
              </div>
            </div>
          </div>
        </div>
        <div class="cols">
          <div class="panel">
            <h3>Лаборатория диалога</h3>
            <p class="muted section-note">Настройки коротких живых ответов, которые тянут разговор дальше вместо лекций.</p>
            <div class="preset-bar">
              <button type="button" id="preset_dialogue_balanced">Баланс</button>
              <button type="button" id="preset_dialogue_live">Живее</button>
              <button type="button" id="preset_dialogue_compact">Коротко</button>
            </div>
            <div class="three">
              <label>Фраз в hook-ответе<input id="dialogue_hook_max_sentences" type="number" min="1" max="6"></label>
              <label>Лимит символов<input id="dialogue_hook_max_chars" type="number" min="120" max="500"></label>
              <label class="checkbox"><input id="dialogue_hook_require_follow_up_question" type="checkbox">Разрешать follow-up, когда он нужен</label>
            </div>
            <div class="two">
              <label class="checkbox"><input id="dialogue_hook_topic_questions_enabled" type="checkbox">Разрешать тематические вопросы</label>
              <label class="checkbox"><input id="dialogue_risky_scene_compact_redirect" type="checkbox">Сжимать рискованные лекции</label>
              <label class="checkbox"><input id="dialogue_charged_probe_compact_redirect" type="checkbox">Сжимать заряженные мини-лекции</label>
            </div>
          </div>
          <div class="panel">
            <h3>Быстрая линия</h3>
            <p class="muted section-note">Тонкая настройка скорости, длины ответа и объёма контекста для коротких сообщений.</p>
            <div class="soft-panel">
              <div class="three">
                <label class="checkbox"><input id="fast_lane_enabled" type="checkbox">Включить fast lane</label>
                <label class="checkbox"><input id="fast_lane_force_low_verbosity" type="checkbox">Принудительно low verbosity</label>
                <label class="checkbox"><input id="fast_lane_force_low_reasoning" type="checkbox">Принудительно low reasoning</label>
              </div>
            </div>
            <div class="soft-panel">
              <h3>Hook turns</h3>
              <div class="three">
                <label>Токены<input id="fast_lane_hook_max_completion_tokens" type="number" min="32"></label>
                <label>Память<input id="fast_lane_hook_memory_max_tokens" type="number" min="64"></label>
                <label>История<input id="fast_lane_hook_history_message_limit" type="number" min="1"></label>
                <label>Timeout<input id="fast_lane_hook_timeout_seconds" type="number" min="1"></label>
                <label>Retries<input id="fast_lane_hook_max_retries" type="number" min="0"></label>
              </div>
            </div>
            <div class="soft-panel">
              <h3>Continuation</h3>
              <div class="three">
                <label>Токены<input id="fast_lane_continuation_max_completion_tokens" type="number" min="32"></label>
                <label>Память<input id="fast_lane_continuation_memory_max_tokens" type="number" min="64"></label>
                <label>История<input id="fast_lane_continuation_history_message_limit" type="number" min="1"></label>
                <label>Timeout<input id="fast_lane_continuation_timeout_seconds" type="number" min="1"></label>
                <label>Retries<input id="fast_lane_continuation_max_retries" type="number" min="0"></label>
              </div>
            </div>
            <div class="soft-panel">
              <h3>Scene</h3>
              <div class="three">
                <label>Токены<input id="fast_lane_scene_max_completion_tokens" type="number" min="32"></label>
                <label>Память<input id="fast_lane_scene_memory_max_tokens" type="number" min="64"></label>
                <label>История<input id="fast_lane_scene_history_message_limit" type="number" min="1"></label>
                <label>Timeout<input id="fast_lane_scene_timeout_seconds" type="number" min="1"></label>
                <label>Retries<input id="fast_lane_scene_max_retries" type="number" min="0"></label>
              </div>
            </div>
            <div class="soft-panel">
              <h3>Generic</h3>
              <div class="three">
                <label>Токены<input id="fast_lane_generic_max_completion_tokens" type="number" min="32"></label>
                <label>Память<input id="fast_lane_generic_memory_max_tokens" type="number" min="64"></label>
                <label>История<input id="fast_lane_generic_history_message_limit" type="number" min="1"></label>
                <label>Timeout<input id="fast_lane_generic_timeout_seconds" type="number" min="1"></label>
                <label>Retries<input id="fast_lane_generic_max_retries" type="number" min="0"></label>
              </div>
            </div>
          </div>
        </div>
        <div class="panel">
          <h3>Интерфейс Telegram</h3>
          <p class="muted section-note">Кнопки, заголовки, системные тексты и приветствия. Всё, что формирует оболочку диалога.</p>
          <div class="cols">
            <div class="soft-panel">
              <h3>Кнопки и навигация</h3>
              <div class="three">
                <label>Кнопка написать<input id="ui_write_button_text"></label>
                <label>Кнопка режимов<input id="ui_modes_button_text"></label>
                <label>Кнопка Premium<input id="ui_premium_button_text"></label>
              </div>
              <div class="two">
                <label>Плейсхолдер<input id="ui_input_placeholder"></label>
                <label>Путь к стартовому аватару<input id="ui_start_avatar_path" placeholder="assets/bot-avatar.png"></label>
                <label>Заголовок режимов<input id="ui_modes_title"></label>
                <label>Маркер premium-режима<input id="ui_modes_premium_marker"></label>
                <label>Всплывающее уведомление<input id="ui_mode_saved_toast"></label>
              </div>
              <label>Шаблон смены режима<textarea id="ui_mode_saved_template"></textarea></label>
            </div>
            <div class="soft-panel">
              <h3>Системные тексты</h3>
              <div class="two">
                <label>Пользователь не найден<textarea id="ui_user_not_found_text"></textarea></label>
                <label>Неизвестный режим<textarea id="ui_unknown_mode_text"></textarea></label>
                <label>Текст блокировки premium-режима<textarea id="ui_mode_locked_text"></textarea></label>
                <label>Приветствие пользователя<textarea id="ui_welcome_user_text"></textarea></label>
                <label>Онбординг follow-up<textarea id="ui_welcome_followup_text"></textarea></label>
                <label>Кнопки быстрого старта<textarea id="ui_onboarding_prompt_buttons"></textarea></label>
              </div>
              <label>Приветствие администратора<textarea id="ui_welcome_admin_text"></textarea></label>
            </div>
          </div>
          <div class="actions"><button class="primary" id="save-runtime">Сохранить раздел</button></div>
        </div>
      </section>
      <section class="page" data-view="safety">
        <div><h2>Безопасность и движок состояния</h2><p class="muted">Антиспам, поведенческие лимиты, уровни доступа и коэффициенты изменения состояния диалога.</p></div>
        <div class="cols">
          <div class="panel">
            <h3>Антиспам</h3>
            <p class="muted section-note">Быстрые ограничения на входящие сообщения и тексты, которые видит пользователь при отказе.</p>
            <div class="soft-panel">
              <div class="two">
                <label>Rate limit, сек<input id="safety_throttle_rate_limit_seconds" type="number" step="0.1"></label>
                <label>Интервал предупреждений<input id="safety_throttle_warning_interval_seconds" type="number" step="0.1"></label>
                <label>Макс длина<input id="safety_max_message_length" type="number"></label>
              </div>
              <label class="checkbox"><input id="safety_reject_suspicious_messages" type="checkbox">Включить фильтр ссылок</label>
            </div>
            <div class="two">
              <label>Предупреждение<textarea id="safety_throttle_warning_text"></textarea></label>
              <label>Слишком длинное сообщение<textarea id="safety_message_too_long_text"></textarea></label>
              <label>Отклонение фильтром<textarea id="safety_suspicious_rejection_text"></textarea></label>
              <label>Ключевые слова<textarea id="safety_suspicious_keywords"></textarea></label>
            </div>
          </div>
          <div class="panel">
            <h3>Состояние диалога</h3>
            <p class="muted section-note">Стартовые значения и словари сигналов, из которых собирается внутренняя модель состояния пользователя.</p>
            <div class="soft-panel">
              <div id="state-defaults-grid" class="two"></div>
            </div>
            <div class="two">
              <label>Позитивные слова<textarea id="state_positive_keywords"></textarea></label>
              <label>Негативные слова<textarea id="state_negative_keywords"></textarea></label>
            </div>
            <label>Слова близости<textarea id="state_attraction_keywords"></textarea></label>
          </div>
        </div>
        <div class="cols">
          <div class="panel">
            <h3>Уровни доступа</h3>
            <p class="muted section-note">Пороговые значения, которые переводят пользователя между observation, analysis, tension и другими слоями.</p>
            <div class="two">
              <label>Принудительный уровень<input id="access_forced_level"></label>
              <label>Уровень по умолчанию<input id="access_default_level"></label>
              <label>Порог observation по interest<input id="access_interest_observation_threshold" type="number" step="0.01"></label>
              <label>Порог rare_layer по instability<input id="access_rare_layer_instability_threshold" type="number" step="0.01"></label>
              <label>Порог rare_layer по attraction<input id="access_rare_layer_attraction_threshold" type="number" step="0.01"></label>
              <label>Порог personal_focus по attraction<input id="access_personal_focus_attraction_threshold" type="number" step="0.01"></label>
              <label>Порог personal_focus по interest<input id="access_personal_focus_interest_threshold" type="number" step="0.01"></label>
              <label>Порог tension по attraction<input id="access_tension_attraction_threshold" type="number" step="0.01"></label>
              <label>Порог tension по control<input id="access_tension_control_threshold" type="number" step="0.01"></label>
              <label>Порог analysis по interest<input id="access_analysis_interest_threshold" type="number" step="0.01"></label>
              <label>Порог analysis по control<input id="access_analysis_control_threshold" type="number" step="0.01"></label>
            </div>
          </div>
          <div class="panel">
            <h3>Лимиты сообщений</h3>
            <p class="muted section-note">Бесплатный и premium-лимиты, preview premium-режимов и тексты paywall после исчерпания доступа.</p>
            <div class="soft-panel">
              <label class="checkbox"><input id="limits_free_daily_messages_enabled" type="checkbox">Включить дневной лимит для бесплатных пользователей</label>
              <label class="checkbox"><input id="limits_premium_daily_messages_enabled" type="checkbox">Включить дневной лимит для premium-пользователей</label>
              <label class="checkbox"><input id="limits_admins_bypass_daily_limits" type="checkbox">Админы обходят лимиты сообщений</label>
            </div>
            <div class="two">
              <label>Лимит бесплатных сообщений в день<input id="limits_free_daily_messages_limit" type="number" min="1"></label>
              <label>Лимит premium-сообщений в день<input id="limits_premium_daily_messages_limit" type="number" min="1"></label>
              <label>Текст при исчерпании бесплатного лимита<textarea id="limits_free_daily_limit_message"></textarea></label>
              <label>Текст при исчерпании premium-лимита<textarea id="limits_premium_daily_limit_message"></textarea></label>
            </div>
            <div class="soft-panel">
              <label class="checkbox"><input id="limits_mode_preview_enabled" type="checkbox">Разрешить бесплатный предпросмотр платных режимов</label>
              <div class="two">
                <label>Лимит preview по умолчанию<input id="limits_mode_preview_default_limit" type="number" min="0"></label>
                <label>Текст при исчерпании предпросмотра<textarea id="limits_mode_preview_exhausted_message"></textarea></label>
              </div>
              <label>Лимиты по режимам
                <textarea id="limits_mode_daily_limits" placeholder="comfort=2&#10;mentor=3"></textarea>
              </label>
            </div>
          </div>
        </div>
        <details class="panel details-panel">
          <summary>Дополнительная динамика состояния и вовлечения</summary>
          <div class="details-content stack">
            <div class="soft-panel">
              <h3>Коэффициенты</h3>
              <p class="muted section-note">Как именно входящее сообщение меняет interest, attraction, instability и другие внутренние сигналы.</p>
              <div id="state-effects-grid" class="three"></div>
            </div>
            <div class="soft-panel">
              <h3>Мягкая адаптация режима</h3>
              <p class="muted section-note">Здесь осталась только adaptive mode. Все настройки первого сообщения теперь живут во вкладке «ИИ и интерфейс».</p>
              <div class="two">
                <label class="checkbox"><input id="engagement_adaptive_mode_enabled" type="checkbox">Включить мягкую адаптацию режима</label>
              </div>
            </div>
          </div>
        </details>
        <div class="actions"><button class="primary" id="save-safety">Сохранить раздел</button></div>
      </section>
      <section class="page" data-view="prompts">
        <div><h2>Промпты</h2><p class="muted">Редактор legacy prompt templates и safety-блоков. Обычный reply path сейчас идет через ConversationEngineV2.</p></div>
        <div class="panel">
          <label>Личность<textarea id="prompt_personality_core"></textarea></label>
          <label>Безопасность<textarea id="prompt_safety_block"></textarea></label>
          <label>Стиль ответа<textarea id="prompt_response_style"></textarea></label>
          <label>Правила ведения диалога<textarea id="prompt_engagement_rules"></textarea></label>
          <label>Промпт режима ПТСР<textarea id="prompt_ptsd_mode_prompt"></textarea></label>
          <div class="two">
            <label>Память<input id="prompt_memory_intro"></label>
            <label>Состояние<input id="prompt_state_intro"></label>
            <label>Режим<input id="prompt_mode_intro"></label>
            <label>Доступ<input id="prompt_access_intro"></label>
          </div>
          <label>Финальная инструкция<textarea id="prompt_final_instruction"></textarea></label>
        </div>
        <div class="panel">
          <div class="two">
            <label>Правило observation<textarea id="access_observation"></textarea></label>
            <label>Правило analysis<textarea id="access_analysis"></textarea></label>
            <label>Правило tension<textarea id="access_tension"></textarea></label>
            <label>Правило personal_focus<textarea id="access_personal_focus"></textarea></label>
            <label>Правило rare_layer<textarea id="access_rare_layer"></textarea></label>
          </div>
          <div class="actions"><button class="primary" id="save-prompts">Сохранить раздел</button></div>
        </div>
      </section>

      <section class="page" data-view="modes">
        <div><h2>Режимы</h2><p class="muted">Название, иконка, премиум-статус, текст активации и шкалы поведения.</p></div>
        <div class="panel">
          <div id="modes-container"></div>
          <div class="actions"><button class="primary" id="save-modes">Сохранить раздел</button></div>
        </div>
      </section>

      <section class="page" data-view="payments">
        <div><h2>Тарифы и оплата</h2><p class="muted">Тарифы конечного пользователя, paywall, провайдер и реферальная программа в одном разделе монетизации.</p></div>
        <div class="cols">
          <div class="panel">
            <h3>Основное</h3>
            <p class="muted section-note">Базовые настройки провайдера, валюты и продукта, которые влияют на весь платёжный сценарий.</p>
            <div class="two">
              <label>Токен провайдера<textarea id="payment_provider_token"></textarea></label>
              <label>Режим оплаты
                <select id="payment_mode">
                  <option value="virtual">Виртуальная</option>
                  <option value="telegram">Telegram</option>
                </select>
              </label>
              <label>Валюта<input id="payment_currency"></label>
              <label>Пакет по умолчанию
                <select id="payment_default_package_key">
                  <option value="day">1 день</option>
                  <option value="week">7 дней</option>
                  <option value="month">30 дней</option>
                  <option value="year">365 дней</option>
                </select>
              </label>
              <label>Название<input id="payment_product_title"></label>
            </div>
            <label class="checkbox"><input id="payment_recurring_stars_enabled" type="checkbox">Автопродление через Stars при валюте XTR</label>
            <label>Описание<textarea id="payment_product_description"></textarea></label>
          </div>
          <div class="panel">
            <h3>Короткий оффер</h3>
            <p class="muted section-note">Главные тексты, которые чаще всего видит пользователь при покупке и ошибках оплаты.</p>
            <label>Преимущества платного плана<textarea id="payment_premium_benefits_text"></textarea></label>
            <label>CTA оплаты<input id="payment_buy_cta_text"></label>
            <label>Недоступно<textarea id="payment_unavailable_message"></textarea></label>
            <label>Ошибка счета<textarea id="payment_invoice_error_message"></textarea></label>
            <label>Успешная оплата<textarea id="payment_success_message"></textarea></label>
          </div>
        </div>
        <details class="panel details-panel">
          <summary>Тексты меню тарифов и paywall</summary>
          <div class="details-content stack">
            <div class="soft-panel">
              <h3>Меню тарифов</h3>
              <label>Оффер при исчерпании preview<textarea id="payment_offer_preview_exhausted_template"></textarea></label>
              <label>Описание меню тарифов<textarea id="payment_premium_menu_description_template"></textarea></label>
              <div class="two">
                <label>Заголовок блока тарифов<input id="payment_premium_menu_packages_title"></label>
                <label>Кнопка назад из premium-меню<input id="payment_premium_menu_back_button_text"></label>
                <label>Шаблон строки тарифа<input id="payment_premium_menu_package_line_template"></label>
                <label>Шаблон кнопки тарифа<input id="payment_premium_menu_package_button_template"></label>
              </div>
              <label>Текст preview в premium-меню<textarea id="payment_premium_menu_preview_template"></textarea></label>
            </div>
            <div class="soft-panel">
              <h3>Виртуальная и recurring-оплата</h3>
              <label>Текст виртуальной оплаты<textarea id="payment_virtual_payment_description_template"></textarea></label>
              <div class="two">
                <label>Кнопка виртуальной оплаты<input id="payment_virtual_payment_button_template"></label>
                <label>Текст после подтверждения<input id="payment_virtual_payment_completed_message"></label>
                <label>Текст кнопки подписки<input id="payment_recurring_button_text"></label>
              </div>
            </div>
          </div>
        </details>
        <div class="panel">
          <h3>Пакеты тарифов</h3>
          <p class="muted section-note">Именно эти варианты увидит пользователь в едином меню платных планов.</p>
          <div class="package-grid">
            <div class="mode-card">
              <div class="mode-head"><strong>1 день</strong><span class="badge">day</span></div>
              <label class="checkbox"><input id="payment_package_day_enabled" type="checkbox">Показывать пакет</label>
              <label class="checkbox"><input id="payment_package_day_recurring_stars_enabled" type="checkbox">Разрешить автопродление через Stars</label>
              <div class="three">
                <label>Название<input id="payment_package_day_title"></label>
                <label>Цена<input id="payment_package_day_price_minor_units" type="number" min="1"></label>
                <label>Дней<input id="payment_package_day_access_duration_days" type="number" min="1"></label>
                <label>Порядок<input id="payment_package_day_sort_order" type="number"></label>
                <label>Бейдж<input id="payment_package_day_badge"></label>
              </div>
              <label>Описание<textarea id="payment_package_day_description"></textarea></label>
            </div>
            <div class="mode-card">
              <div class="mode-head"><strong>7 дней</strong><span class="badge">week</span></div>
              <label class="checkbox"><input id="payment_package_week_enabled" type="checkbox">Показывать пакет</label>
              <label class="checkbox"><input id="payment_package_week_recurring_stars_enabled" type="checkbox">Разрешить автопродление через Stars</label>
              <div class="three">
                <label>Название<input id="payment_package_week_title"></label>
                <label>Цена<input id="payment_package_week_price_minor_units" type="number" min="1"></label>
                <label>Дней<input id="payment_package_week_access_duration_days" type="number" min="1"></label>
                <label>Порядок<input id="payment_package_week_sort_order" type="number"></label>
                <label>Бейдж<input id="payment_package_week_badge"></label>
              </div>
              <label>Описание<textarea id="payment_package_week_description"></textarea></label>
            </div>
            <div class="mode-card">
              <div class="mode-head"><strong>30 дней</strong><span class="badge">month</span></div>
              <label class="checkbox"><input id="payment_package_month_enabled" type="checkbox">Показывать пакет</label>
              <label class="checkbox"><input id="payment_package_month_recurring_stars_enabled" type="checkbox">Разрешить автопродление через Stars</label>
              <div class="three">
                <label>Название<input id="payment_package_month_title"></label>
                <label>Цена<input id="payment_package_month_price_minor_units" type="number" min="1"></label>
                <label>Дней<input id="payment_package_month_access_duration_days" type="number" min="1"></label>
                <label>Порядок<input id="payment_package_month_sort_order" type="number"></label>
                <label>Бейдж<input id="payment_package_month_badge"></label>
              </div>
              <label>Описание<textarea id="payment_package_month_description"></textarea></label>
            </div>
            <div class="mode-card">
              <div class="mode-head"><strong>365 дней</strong><span class="badge">year</span></div>
              <label class="checkbox"><input id="payment_package_year_enabled" type="checkbox">Показывать пакет</label>
              <label class="checkbox"><input id="payment_package_year_recurring_stars_enabled" type="checkbox">Разрешить автопродление через Stars</label>
              <div class="three">
                <label>Название<input id="payment_package_year_title"></label>
                <label>Цена<input id="payment_package_year_price_minor_units" type="number" min="1"></label>
                <label>Дней<input id="payment_package_year_access_duration_days" type="number" min="1"></label>
                <label>Порядок<input id="payment_package_year_sort_order" type="number"></label>
                <label>Бейдж<input id="payment_package_year_badge"></label>
              </div>
              <label>Описание<textarea id="payment_package_year_description"></textarea></label>
            </div>
          </div>
        </div>
        <div class="cols">
          <div class="panel">
            <h3>Реферальная программа</h3>
            <p class="muted section-note">Настройки приглашений и условий начисления бонусов за первую оплату.</p>
            <label class="checkbox"><input id="referral_enabled" type="checkbox">Включить реферальную программу</label>
            <div class="two">
              <label>Префикс для /start<input id="referral_start_parameter_prefix"></label>
              <label>Заголовок<input id="referral_program_title"></label>
            </div>
            <label class="checkbox"><input id="referral_allow_self_referral" type="checkbox">Разрешить приглашать самого себя</label>
            <label class="checkbox"><input id="referral_require_first_paid_invoice" type="checkbox">Засчитывать только после первой оплаты</label>
            <label class="checkbox"><input id="referral_award_referrer_premium" type="checkbox">Выдавать премиум рефереру</label>
            <label class="checkbox"><input id="referral_award_referred_user_premium" type="checkbox">Выдавать премиум приглашенному</label>
            <label>Описание<textarea id="referral_program_description"></textarea></label>
            <label>Шаблон ссылки (`{ref_link}`)<textarea id="referral_share_text_template"></textarea></label>
            <label>Текст для приглашенного<textarea id="referral_referred_welcome_message"></textarea></label>
            <label>Текст награды<textarea id="referral_referrer_reward_message"></textarea></label>
          </div>
          <div class="panel">
            <h3>Последние рефералы</h3>
            <p class="muted section-note">Быстрая проверка, как реферальная программа выглядит в живых данных.</p>
            <pre id="recent-referrals" class="memory-box">Здесь появятся последние рефералы.</pre>
          </div>
        </div>
        <div class="actions"><button class="primary" id="save-payments">Сохранить раздел</button></div>
      </section>

      <section class="page" data-view="testing">
        <div><h2>Лаборатория диалога</h2><p class="muted">Проверка промпта, состояния и живости ответа до запуска. Здесь видно не только JSON, но и качество диалогового цикла.</p></div>
        <div class="cols">
          <div class="panel">
            <h3>Тестовый диалог</h3>
            <div class="two">
              <label>Активный режим<input id="test_active_mode"></label>
              <label>Уровень доступа<input id="test_access_level"></label>
              <label>User ID<input id="test_user_id" type="number" min="0"></label>
            </div>
            <div class="template-list" id="test-case-buttons">
              <button type="button" class="template-chip" data-test-case="start">Первое сообщение</button>
              <button type="button" class="template-chip" data-test-case="advice">Полезный разбор</button>
              <button type="button" class="template-chip" data-test-case="short">Короткий ответ</button>
              <button type="button" class="template-chip" data-test-case="sensitive">Сложный край</button>
            </div>
            <label>Сообщение<textarea id="test_user_message"></textarea></label>
            <label>История (`user:` / `assistant:`)<textarea id="test_history"></textarea></label>
            <label>JSON состояния<textarea id="test_state">{}</textarea></label>
            <div class="actions">
              <button class="primary" id="test-prompt">Промпт</button>
              <button id="test-state-btn">Состояние</button>
              <button id="test-live-reply">Живой ответ</button>
              <button id="test-reengagement">Инициатива</button>
            </div>
          </div>
          <div class="panel">
            <h3>Оценка качества</h3>
            <div id="test-quality">Запусти живой ответ, чтобы увидеть оценку.</div>
            <h3 style="margin-top:16px">Результат</h3>
            <pre id="test-result">Здесь появится результат.</pre>
          </div>
        </div>
      </section>

      <section class="page" data-view="logs">
        <div><h2>Логи и сервисы</h2><p class="muted">Проверка файлов конфигурации, здоровья и хвоста логов.</p></div>
        <div class="cols">
          <div class="panel"><h3>Health</h3><div id="full-health"></div></div>
          <div class="panel"><h3>Файлы</h3><div id="config-files"></div></div>
        </div>
        <div class="panel">
          <div class="toolbar">
            <button class="primary" id="reload-logs">Обновить логи</button>
            <select id="log-lines"><option value="100">100</option><option value="200" selected>200</option><option value="500">500</option></select>
            <label class="checkbox" style="margin:0"><input id="log-redact-sensitive" type="checkbox" checked>Redact logs</label>
          </div>
          <pre id="logs-output">Загрузка логов...</pre>
        </div>
      </section>
    </main>
  </div>
  <script>
    const DEFAULT_MESSAGE_TEMPLATES=[
      'Привет. Я на связи, если захочется продолжить разговор.',
      'Как ты сегодня? Можешь ответить в любом темпе.',
      'Если хочешь, можем спокойно вернуться к тому, на чем остановились.'
    ];
    const state={settings:null,overview:null,health:null,logs:null,users:null,currentUser:null,currentConversation:null,currentMemoryId:null,selectedUserIds:new Set(),lastBroadcastPreview:null,lastBroadcastResult:null,lastTestResult:null,activeView:'overview',lastSyncedAt:null};
    const VIEW_META={
      overview:{kicker:'Операционный центр',title:'Обзор продукта',subtitle:'Метрики пользователей, платежей, поддержки и состояние инфраструктуры без переключения между отдельными тулзами.'},
      setup:{kicker:'Готовность к запуску',title:'Настройка и запуск',subtitle:'SaaS-срез для оператора: что настроено, что мешает запуску и где править перед первым трафиком.'},
      users:{kicker:'CRM и аудитория',title:'Пользователи и сегменты',subtitle:'Поиск, фильтры, массовые действия и быстрый переход к конкретной карточке без лишнего кликанья.'},
      conversations:{kicker:'Операции с диалогами',title:'Диалоги и память',subtitle:'История сообщений, memory preview, ручные сообщения и редактирование долговременной памяти в одном рабочем окне.'},
      runtime:{kicker:'Настройки рантайма',title:'ИИ и интерфейс',subtitle:'Живые runtime-параметры модели, лимитов, инициативы и редактора шаблонов без похода в JSON вручную.'},
      safety:{kicker:'Guardrails',title:'Безопасность и ограничения',subtitle:'Guardrails, кризисные настройки и стоп-линии, которые реально формируют поведение бота на проде.'},
      prompts:{kicker:'Prompt control plane',title:'Промпты и шаблоны',subtitle:'Редактирование базовых инструкций, fallback-слоёв и prompt-контура без расползания по legacy-конфигам.'},
      modes:{kicker:'Mode engine',title:'Режимы и голос',subtitle:'Каталог режимов, model overrides и UX-параметры, которые определяют, как бот звучит для пользователя.'},
      payments:{kicker:'Монетизация',title:'Тарифы и оплата',subtitle:'Тарифы, провайдеры и монетизация в одной витрине без ощущения недоделанной панели.'},
      testing:{kicker:'Лаборатория диалога',title:'Тесты качества диалога',subtitle:'Проверка промпта, состояния и ответа прямо из админки, чтобы поведение можно было валидировать до выката.'},
      logs:{kicker:'Runtime trace',title:'Логи и сигналы',subtitle:'Последние записи сервиса, быстрый экспорт и просмотр проблем без отдельного захода на сервер.'},
    };
    const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
    const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
    const escText=v=>esc(v).replaceAll('\\n','<br>');
    const setValue=(selector,value)=>{const el=$(selector);if(el)el.value=value??''};
    const setChecked=(selector,value)=>{const el=$(selector);if(el)el.checked=!!value};
    const num=v=>Number(v??0).toLocaleString('ru-RU');
    const on=(selector,event,handler)=>{const el=$(selector);if(!el){console.warn(`Missing element: ${selector}`);return null}el.addEventListener(event,handler);return el};
    const onAll=(selector,event,handler)=>{$$(selector).forEach(el=>el.addEventListener(event,handler))};
    async function api(path,options={}){const r=await fetch(path,{credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json',...(options.headers||{})},...options});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||`Ошибка запроса: ${path}`);return d}
    function notice(text,kind='ok'){const n=$('#notice');n.textContent=text;n.className='notice '+kind}
    function redactSensitiveString(value){return String(value??'').replace(/[\\w.+-]+@[\\w.-]+\\.[A-Za-z]{2,}/g,'[redacted-email]').replace(/\\b(?:\\+?\\d[\\d\\s().-]{7,}\\d)\\b/g,'[redacted-phone]')}
    function redactSensitiveObject(value){
      if(Array.isArray(value))return value.map(redactSensitiveObject);
      if(!value||typeof value!=='object')return typeof value==='string'?redactSensitiveString(value):value;
      const out={};
      for(const [key,item] of Object.entries(value)){
        const lower=String(key).toLowerCase();
        if(['provider_token','api_key','secret','password','token','access_token','refresh_token','debug_prompt_user_id'].includes(lower)){out[key]='[redacted]';continue}
        out[key]=redactSensitiveObject(item);
      }
      return out
    }
    function redactLogLine(line){return redactSensitiveString(String(line||'')).replace(/\\b(user_id|chat_id|message_id|phone|email)=([^\\s,;]+)/gi,'$1=[redacted]').replace(/\\b\\d{6,}\\b/g,'[redacted-id]')}
    function currentMessageTemplates(){const templates=state.settings?.runtime?.ui?.message_templates;return Array.isArray(templates)&&templates.length?templates:DEFAULT_MESSAGE_TEMPLATES}
    function parseTemplateEditorText(text){return String(text||'').split(/\\n\\s*\\n+/).map(item=>item.trim()).filter(Boolean)}
    function formatTemplateEditorText(items){return (items||[]).map(item=>String(item||'').trim()).filter(Boolean).join('\\n\\n')}
    function normalizeUserId(value){const id=String(value??'').trim();return /^\\d+$/.test(id)&&Number(id)>0?id:''}
    function selectedUserIds(){return [...state.selectedUserIds].sort((a,b)=>Number(a)-Number(b))}
    function selectedVisibleUserIds(){return (state.users?.items||[]).map(user=>normalizeUserId(user.id)).filter(Boolean)}
    function syncSelectedUsersUi(){const ids=selectedUserIds();const visibleIds=selectedVisibleUserIds();const selectedVisible=visibleIds.filter(id=>state.selectedUserIds.has(id));const countEl=$('#selected-users-count');if(countEl)countEl.textContent=`Выбрано пользователей: ${ids.length}${visibleIds.length?` • видимых: ${selectedVisible.length}/${visibleIds.length}`:''}`;const master=$('#users-select-all-visible');if(master){master.checked=!!visibleIds.length&&selectedVisible.length===visibleIds.length;master.indeterminate=selectedVisible.length>0&&selectedVisible.length<visibleIds.length}$$('[data-user-select]').forEach(input=>{input.checked=state.selectedUserIds.has(String(input.dataset.userSelect))})}
    function setSelectedUsers(ids,selected=true){(ids||[]).map(normalizeUserId).filter(Boolean).forEach(id=>{if(selected)state.selectedUserIds.add(id);else state.selectedUserIds.delete(id)});syncSelectedUsersUi()}
    function renderMessageTemplates(){const html=currentMessageTemplates().map((text,index)=>`<button type="button" class="template-chip" data-template-index="${index}">Шаблон ${index+1}</button>`).join('');const bulk=$('#bulk-message-templates');if(bulk)bulk.innerHTML=html;const conversation=$('#conversation-message-templates');if(conversation)conversation.innerHTML=html}
    function renderTemplateEditor(){const editor=$('#message_templates_editor');if(editor)editor.value=formatTemplateEditorText(currentMessageTemplates())}
    function applyTemplate(textareaSelector,index){const textarea=$(textareaSelector);if(!textarea)return;const template=currentMessageTemplates()[index];if(!template)return;textarea.value=template;textarea.focus()}
    function renderBroadcastResult(result){const el=$('#bulk-message-results');if(!el)return;if(!result){el.textContent='Здесь появится preview и отчет по рассылке.';return}if(result.phase==='preview'){const lines=[`Preview: ${result.requested_count??0} получателей`,`Текст: ${result.preview_text||''}${result.truncated?'...':''}`];if((result.warnings||[]).length){lines.push('','Предупреждения:');(result.warnings||[]).forEach(item=>lines.push(`- ${item}`))}lines.push('','После подтверждения эта рассылка уйдет выбранным пользователям.');el.textContent=lines.join('\\n');return}const lines=[`Запрошено: ${result.requested_count??0}`,`Отправлено: ${result.sent_count??0}`,`Ошибок: ${result.failed_count??0}`];if((result.sent||[]).length)lines.push('',`Успешно: ${(result.sent||[]).map(item=>`${item.user_id} (${item.active_mode||'base'})`).join(', ')}`);if((result.failed||[]).length){lines.push('','Ошибки:');(result.failed||[]).forEach(item=>lines.push(`${item.user_id}: ${item.error||'неизвестно'}`))}el.textContent=lines.join('\\n')}
    function table(cols,rows){if(!rows||!rows.length)return '<div class="muted">Пока нет данных.</div>';return `<table><thead><tr>${cols.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${cols.map(c=>`<td>${esc(r[c])}</td>`).join('')}</tr>`).join('')}</tbody></table>`}
    function statusPill(ok,okText='OK',badText='Ошибка'){return `<span class="status-pill ${ok?'ok':'bad'}">${ok?esc(okText):esc(badText)}</span>`}
    function kvList(items){const rows=(items||[]).filter(item=>item&&item[1]!==undefined&&item[1]!==null&&item[1]!=='');if(!rows.length)return '<div class="muted">Пока нет данных.</div>';return `<div class="kv-list">${rows.map(([label,value])=>`<div class="kv-row"><div class="kv-key">${esc(label)}</div><div class="kv-value">${value}</div></div>`).join('')}</div>`}
    function metricCards(items){const rows=(items||[]).filter(Boolean);if(!rows.length)return '<div class="muted">Пока нет данных.</div>';return `<div class="mini-grid">${rows.map(([label,value,caption])=>`<div class="metric"><div class="stat-label">${esc(label)}</div><div class="metric-value-small">${esc(value)}</div><div class="muted">${esc(caption||'')}</div></div>`).join('')}</div>`}
    function healthSummary(ai){const queue=ai?.queue_size??0,capacity=ai?.queue_capacity??0,workers=ai?.workers??0,busy=ai?.busy_workers??0;return metricCards([['Очередь',`${queue}/${capacity}`,'Задачи ИИ в очереди'],['Воркеры',String(workers),`Занято: ${busy}`],['Режимов',String(state.health?.modes_count??0),'Загружено в панели']])}
    function enabledPackages(payment){return Object.values(payment?.packages||{}).filter(item=>item&&item.enabled)}
    function launchReadinessItems(){
      const runtime=state.settings?.runtime||{},ui=runtime.ui||{},payment=runtime.payment||{},limits=runtime.limits||{},catalog=state.settings?.mode_catalog||{},health=state.health||{};
      const modeItems=Object.values(catalog||{}),paidModes=modeItems.filter(item=>item&&item.is_premium),packages=enabledPackages(payment);
      const hasProvider=String(payment.provider_token||'').trim()||payment.mode==='virtual';
      const items=[
        {key:'identity',label:'Образ бота',ok:String(ui.welcome_user_text||'').trim()&&String(ui.write_button_text||'').trim(),detail:'Приветствие, главные кнопки и первый сценарий настроены.',action:'runtime'},
        {key:'onboarding',label:'Подсказки онбординга',ok:(ui.onboarding_prompt_buttons||[]).filter(Boolean).length>0,detail:'Примеры запросов помогают холодному пользователю начать без догадок.',action:'runtime',warn:true},
        {key:'modes',label:'Бесплатные и платные режимы',ok:modeItems.length>=2&&paidModes.length>=1,detail:`Режимов: ${modeItems.length}, платных: ${paidModes.length}.`,action:'modes'},
        {key:'plans',label:'Тарифы и paywall',ok:packages.length>0&&String(payment.buy_cta_text||'').trim(),detail:`Включено пакетов: ${packages.length}. По умолчанию: ${payment.default_package_key||'—'}.`,action:'payments'},
        {key:'payment',label:'Режим оплаты',ok:!!hasProvider,detail:`Режим: ${payment.mode||'telegram'}${payment.mode==='virtual'?' (тестовая оплата)':''}.`,action:'payments',warn:payment.mode==='virtual'},
        {key:'limits',label:'Лимиты использования',ok:!!(limits.free_daily_messages_enabled||limits.premium_daily_messages_enabled||limits.mode_preview_enabled),detail:'Лимиты удерживают стоимость AI и платный доступ предсказуемыми.',action:'safety',warn:true},
        {key:'lab',label:'Лаборатория диалога',ok:true,detail:'Прогоните стартовые запросы перед трафиком.',action:'testing'},
        {key:'system',label:'Состояние системы',ok:!!(health.db?.ok&&(health.redis?.ok||health.redis?.mode==='fallback')),detail:`БД: ${health.db?.ok?'норма':'проверить'}, Redis: ${health.redis?.ok?'норма':(health.redis?.mode||'проверить')}.`,action:'logs'},
      ];
      return items.map(item=>({...item,status:item.ok?(item.warn?'warn':'ok'):'bad'}));
    }
    function renderReadiness(items){return `<div class="readiness-list">${(items||[]).map(item=>`<div class="readiness-item"><span class="readiness-dot ${esc(item.status)}"></span><div><strong>${esc(item.label)}</strong><div class="muted">${esc(item.detail)}</div></div><button data-open-view="${esc(item.action)}">${item.status==='bad'?'Исправить':'Открыть'}</button></div>`).join('')}</div>`}
    function renderLaunchReadiness(){
      const items=launchReadinessItems(),bad=items.filter(item=>item.status==='bad').length,warn=items.filter(item=>item.status==='warn').length,ok=items.filter(item=>item.status==='ok').length;
      const summary=metricCards([['Готово',String(ok),`${bad} блокеров • ${warn} предупреждений`],['Тарифы',String(enabledPackages(state.settings?.runtime?.payment||{}).length),'Включённые платные пакеты'],['Режимы',String(Object.keys(state.settings?.mode_catalog||{}).length),'Настроенные режимы бота']]);
      return `<div class="stack">${summary}${renderReadiness(items)}</div>`;
    }
    function renderSetup(){
      if(!state.settings)return;
      const runtime=state.settings.runtime||{},ui=runtime.ui||{},payment=runtime.payment||{},catalog=state.settings.mode_catalog||{},paidModes=Object.values(catalog).filter(item=>item&&item.is_premium);
      $('#setup-readiness').innerHTML=renderLaunchReadiness();
      $('#setup-identity').innerHTML=`<div class="stack">${metricCards([['Меню',`${esc(ui.write_button_text||'—')} / ${esc(ui.modes_button_text||'—')}`,esc(ui.premium_button_text||'нет CTA тарифа')],['Режимы',String(Object.keys(catalog).length),`Платных режимов: ${paidModes.length}`],['Оплата',esc(payment.mode||'telegram'),`Пакет по умолчанию: ${payment.default_package_key||'—'}`]])}${kvList([['Приветствие',escText(String(ui.welcome_user_text||'').slice(0,280)||'—')],['Следующее сообщение',escText(String(ui.welcome_followup_text||'').slice(0,220)||'—')],['Путь к аватару',esc(ui.start_avatar_path||'—')],['CTA paywall',esc(payment.buy_cta_text||'—')]])}</div>`;
      $('#setup-saas-summary').innerHTML=kvList([['Продукт',esc('Пульт для запуска и монетизации Telegram AI-компаньона')],['Обещание оператору',esc('Настроить образ, режимы, тарифы, тесты качества, пользователей, рассылки и состояние системы из одной панели.')],['Следующий фокус',esc('Готовность запуска -> лаборатория диалога -> ясность тарифов -> smoke-тест деплоя')]]);
    }
    function fileTable(files){const rows=Object.entries(files||{}).map(([name,info])=>({name,path:info?.path||'',exists:info?.exists?'Да':'Нет',size:info?.exists?`${num(info?.size_bytes)} B`:'-'}));return table(['name','path','exists','size'],rows)}
    function prettyStateLabel(key){return ({active_mode:'Активный режим',interaction_count:'Число взаимодействий',conversation_phase:'Фаза диалога',emotional_tone:'Эмоциональный тон',premium_features_used:'Использований премиума',enabled:'Инициатива бота',updated_at:'Обновлено',timezone:'Часовой пояс',goals:'Цели',interests:'Интересы',personality_traits:'Черты',identity_facts:'Имена и связи',current_focus:'Что сейчас особенно живо',recent_topics:'Недавние темы',open_loops:'Незавершённые темы',support_profile:'Профиль поддержки',support_stats:'Статистика поддержки',episodic_summary:'Сводка эпизода',episodic_summary_meta:'Мета сводки',recent_arc:'Недавняя дуга',emotional_direction:'Эмоциональное направление',response_hint:'Подсказка для ответа',response_preferences:'Предпочтения по ответу',shared_threads:'Нити прошлых разговоров',callback_candidates:'Что можно мягко вспомнить позже',recent_thread:'Последняя живая нить'})[key]||key.replaceAll('_',' ')}
    function hasStateValue(value){if(value===undefined||value===null||value==='')return false;if(Array.isArray(value))return value.length>0;if(typeof value==='object')return Object.keys(value||{}).length>0;return true}
    function formatStateObject(value){const entries=Object.entries(value||{}).filter(([,item])=>item!==undefined&&item!==null&&item!=='');if(!entries.length)return '—';if('value' in value){const meta=['score','weight','times_seen','source','source_kind','updated_at'].map(key=>value[key]).filter(item=>item!==undefined&&item!==null&&item!=='');return `${esc(String(value.value||'—'))}${meta.length?`<div class="muted">${esc(meta.join(' • '))}</div>`:''}`}return `<div class="stack" style="gap:8px">${entries.map(([key,item])=>`<div class="kv-row"><div class="kv-key">${esc(prettyStateLabel(key))}</div><div class="kv-value">${prettyStateValue(item)}</div></div>`).join('')}</div>`}
    function prettyStateValue(value){if(value===true)return 'Да';if(value===false)return 'Нет';if(value===null||value===undefined||value==='')return '—';if(Array.isArray(value))return value.length?`<div class="stack" style="gap:6px">${value.map(item=>`<div class="soft-panel" style="padding:8px 10px">${prettyStateValue(item)}</div>`).join('')}</div>`:'—';if(typeof value==='object')return formatStateObject(value);return esc(String(value))}
    function renderStateSection(title,items){const rows=(items||[]).filter(item=>item&&hasStateValue(item[1]));if(!rows.length)return '';return `<div class="state-section"><h4>${esc(title)}</h4>${kvList(rows.map(([label,value])=>[prettyStateLabel(label),prettyStateValue(value)]))}</div>`}
    function renderStateSummary(statePayload){if(!statePayload||typeof statePayload!=='object')return '<div class="muted">Пока нет данных.</div>';const proactive=statePayload.proactive_preferences&&typeof statePayload.proactive_preferences==='object'?statePayload.proactive_preferences:{};const profile=statePayload.user_profile&&typeof statePayload.user_profile==='object'?statePayload.user_profile:{};const memoryFlags=statePayload.memory_flags&&typeof statePayload.memory_flags==='object'?statePayload.memory_flags:{};const relationship=statePayload.relationship_state&&typeof statePayload.relationship_state==='object'?statePayload.relationship_state:{};const supportProfile=memoryFlags.support_profile&&typeof memoryFlags.support_profile==='object'?memoryFlags.support_profile:{};const supportStats=memoryFlags.support_stats&&typeof memoryFlags.support_stats==='object'?memoryFlags.support_stats:{};const episodicSummary=memoryFlags.episodic_summary&&typeof memoryFlags.episodic_summary==='object'?memoryFlags.episodic_summary:{};const episodicSummaryMeta=memoryFlags.episodic_summary_meta&&typeof memoryFlags.episodic_summary_meta==='object'?memoryFlags.episodic_summary_meta:{};const memoryOverview=[['current_focus',memoryFlags.current_focus],['recent_topics',memoryFlags.recent_topics],['open_loops',memoryFlags.open_loops]];const hiddenMemoryKeys=new Set(['current_focus','recent_topics','open_loops','support_profile','support_stats','episodic_summary','episodic_summary_meta']);const mainRows=[['active_mode',statePayload.active_mode],['interaction_count',statePayload.interaction_count],['conversation_phase',statePayload.conversation_phase],['emotional_tone',statePayload.emotional_tone],['premium_features_used',statePayload.premium_features_used]];const sections=[renderStateSection('Основное состояние',mainRows),renderStateSection('Инициатива бота',Object.entries(proactive)),renderStateSection('Профиль пользователя',Object.entries(profile)),renderStateSection('Контекст памяти',memoryOverview),renderStateSection('Профиль поддержки',Object.entries(supportProfile)),renderStateSection('Статистика поддержки',Object.entries(supportStats)),renderStateSection('Сводка эпизода',Object.entries(episodicSummary)),renderStateSection('Мета сводки',Object.entries(episodicSummaryMeta)),renderStateSection('Связь и отклик',Object.entries(relationship)),renderStateSection('Прочие флаги памяти',Object.entries(memoryFlags).filter(([key])=>!hiddenMemoryKeys.has(key)))].filter(Boolean);return sections.length?sections.join(''):'<div class="muted">Пока нет данных.</div>'}
    function renderMemoryPreview(rawText){const text=String(rawText||'').trim();if(!text)return '<div class="muted">Пока нет данных.</div>';const items=text.split('\\n').map(line=>line.trim()).filter(Boolean);const cards=items.map(line=>{const cleaned=line.startsWith('- ')?line.slice(2):line;const separator=cleaned.indexOf(':');if(separator===-1)return {title:'Контекст памяти',values:[cleaned]};const title=cleaned.slice(0,separator).trim();const values=cleaned.slice(separator+1).split(';').map(part=>part.trim()).filter(Boolean);return {title:title||'Контекст памяти',values:values.length?values:[cleaned.slice(separator+1).trim()]}}).filter(card=>card.values.length);if(!cards.length)return '<div class="muted">Пока нет данных.</div>';return cards.map(card=>`<div class="memory-preview-item"><h4>${esc(card.title)}</h4><ul>${card.values.map(value=>`<li>${esc(value)}</li>`).join('')}</ul></div>`).join('')}
    function monetizationSegmentTable(segmented){const segments=segmented?.segments||{};const rows=Object.entries(segments).map(([segment,data])=>{const stages=data?.stages||{},conversion=data?.conversion||{};return {segment,offer_users:stages.offer_shown?.users??0,invoice_users:stages.invoice_opened?.users??0,paid_users:stages.paid?.users??0,renewed_users:stages.renewed?.users??0,offer_to_invoice_pct:`${conversion.offer_to_invoice_pct??0}%`,invoice_to_paid_pct:`${conversion.invoice_to_paid_pct??0}%`,paid_to_renewed_pct:`${conversion.paid_to_renewed_pct??0}%`}});return table(['segment','offer_users','invoice_users','paid_users','renewed_users','offer_to_invoice_pct','invoice_to_paid_pct','paid_to_renewed_pct'],rows)}
    function parseUtcTimestamp(value){const raw=String(value||'').trim();const match=raw.match(/^(\\d{4})-(\\d{2})-(\\d{2}) (\\d{2}):(\\d{2}):(\\d{2})$/);if(!match)return null;const [,year,month,day,hour,minute,second]=match;return new Date(Date.UTC(Number(year),Number(month)-1,Number(day),Number(hour),Number(minute),Number(second)))}
    function premiumExpiryMeta(user){const expiresText=String(user?.premium_expires_at||'').trim();if(!expiresText)return {tone:'bad',label:'Не активен',dateText:'—'};const expiresAt=parseUtcTimestamp(expiresText);if(!expiresAt||Number.isNaN(expiresAt.getTime()))return {tone:'warn',label:'Срок не распознан',dateText:expiresText};const msLeft=expiresAt.getTime()-Date.now();if(msLeft<=0)return {tone:'bad',label:'Истёк',dateText:expiresText};const daysLeft=msLeft/(24*60*60*1000);if(daysLeft<=3)return {tone:'warn',label:'Скоро закончится',dateText:expiresText};return {tone:'ok',label:'Активен',dateText:expiresText}}
    function renderPremiumExpiryCell(user){const meta=premiumExpiryMeta(user);return `<div class="stack" style="gap:6px"><span class="status-pill ${meta.tone}">${esc(meta.label)}</span><div class="muted">${esc(meta.dateText)}</div></div>`}
    function renderPremiumExpiryInline(user){const meta=premiumExpiryMeta(user);return `<span class="status-pill ${meta.tone}">${esc(meta.label)}</span> <span class="muted">${esc(meta.dateText)}</span>`}
    function recentUsersTable(items){if(!items||!items.length)return '<div class="muted">Пока нет данных.</div>';return `<table><thead><tr><th>ID</th><th>Имя пользователя</th><th>Имя</th><th>Режим</th><th>Премиум</th><th>Premium до</th><th>Админ</th><th>Создан</th></tr></thead><tbody>${items.map(user=>`<tr><td>${esc(user.id)}</td><td>${esc(user.username||'')}</td><td>${esc(user.first_name||'')}</td><td>${esc(user.active_mode||'base')}</td><td>${user.is_premium?'Да':'Нет'}</td><td>${renderPremiumExpiryCell(user)}</td><td>${user.is_admin?'Да':'Нет'}</td><td>${esc(user.created_at||'—')}</td></tr>`).join('')}</tbody></table>`}
    function currentUserFilter(){return $('#user-filter-buttons .template-chip.active')?.dataset.userFilter||'all'}
    function userFilterLabel(filterBy){return ({all:'Все пользователи',premium_active:'Платные активны',premium_expiring_3d:'Истекают за 3 дня',premium_expired:'Истекли',without_premium:'Free и истекшие'})[filterBy]||'Все пользователи'}
    function userSortLabel(sortBy){return ({created_desc:'новые сначала',premium_active_first:'premium наверху',premium_expiry_asc:'срок истекает раньше',premium_expiry_desc:'срок истекает позже',premium_expiring_soon:'скоро истекают наверху',premium_expired:'истекшие наверху'})[sortBy]||'новые сначала'}
    function setUserFilterButtons(filterBy='all'){const segments=state.users?.segments||{};$$('#user-filter-buttons .template-chip').forEach(button=>{const key=button.dataset.userFilter||'all';const baseLabel=button.dataset.baseLabel||button.textContent.replace(/\\s+\\(\\d+\\)$/,'');button.dataset.baseLabel=baseLabel;const count=segments[key];button.textContent=typeof count==='number'?`${baseLabel} (${count})`:baseLabel;button.classList.toggle('active',key===filterBy)})}
    function renderUserSegments(){const segments=state.users?.segments||{};const items=[['Всего',segments.all??0,'Все пользователи в базе'],['Платные активны',segments.paid_active??segments.premium_active??0,'Сейчас имеют активный Pro или Premium'],['Pro активны',segments.pro_active??0,'Базовый платный план'],['Premium активны',segments.premium_active??0,'Глубокий платный план'],['Истекают 3 дня',segments.paid_expiring_3d??segments.premium_expiring_3d??0,'Нуждаются в продлении'],['Истекли',segments.paid_expired??segments.premium_expired??0,'Можно возвращать оффером'],['Free',segments.free??segments.without_premium??0,'Потенциал на первую продажу']];const summary=$('#user-segment-summary');if(summary)summary.innerHTML=metricCards(items);const meta=$('#users-result-meta');if(meta){const matched=state.users?.matched_count??0;const query=String(state.users?.query||'').trim();const queryText=query?` • поиск: ${query}`:'';meta.textContent=`Найдено: ${matched} • фильтр: ${userFilterLabel(state.users?.filter_by||currentUserFilter())} • сортировка: ${userSortLabel(state.users?.sort_by||currentUserSort())}${queryText}`}}
    function renderChrome(){
      const viewKey=state.activeView||'overview';
      const meta=VIEW_META[viewKey]||VIEW_META.overview;
      const setText=(selector,value)=>{const el=$(selector);if(el)el.textContent=value};
      setText('#header-kicker',meta.kicker);
      setText('#header-title',meta.title);
      setText('#header-subtitle',meta.subtitle);
      const release=state.health?.release||{};
      const releaseParts=[release.branch,release.commit_short||release.commit,release.deployed_at].map(part=>String(part||'').trim()).filter(Boolean);
      setText('#header-release',releaseParts.length?releaseParts.join(' • '):'Релиз ещё не загружен');
      const warningCount=(state.health?.warnings||[]).length;
      const syncParts=[];
      if(state.lastSyncedAt)syncParts.push(`Обновлено ${state.lastSyncedAt}`);
      const syncLabel=state.health?.db?`${syncParts[0]||'Синхронизация выполнена'} • БД ${state.health.db.ok?'в норме':'нужна проверка'} • Redis ${state.health.redis?.ok?'в норме':(state.health.redis?.mode||'недоступен')}${warningCount?` • предупреждений: ${warningCount}`:''}`:(syncParts[0]||'Ждём первую загрузку...');
      setText('#header-sync',syncLabel);
      const currentUser=state.currentConversation?.user||state.currentUser||null;
      const userSummary=state.overview?.users?`${num(state.overview.users.total??0)} пользователей • premium ${num(state.overview.users.premium_total??0)}`:'База ещё не загружена';
      const currentFocus=currentUser?(currentUser.first_name||currentUser.username||`user ${currentUser.id}`):meta.title;
      setText('#header-context',`${userSummary} • в фокусе ${currentFocus}`);
      const chips=[];
      if(state.overview?.users)chips.push(`<span class="sidebar-chip">${num(state.overview.users.total??0)} пользователей</span>`);
      if(state.overview?.users)chips.push(`<span class="sidebar-chip">premium ${num(state.overview.users.premium_total??0)}</span>`);
      if(state.health?.release?.commit_short)chips.push(`<span class="sidebar-chip">release ${esc(state.health.release.commit_short)}</span>`);
      if(state.health?.warnings?.length)chips.push(`<span class="sidebar-chip">${num(state.health.warnings.length)} предупреждений</span>`);
      if(currentUser?.id)chips.push(`<span class="sidebar-chip">user ${esc(currentUser.id)}</span>`);
      const sidebarMeta=$('#sidebar-meta');
      if(sidebarMeta)sidebarMeta.innerHTML=chips.join('')||'<span class="sidebar-chip">Ждём данные...</span>';
    }
    function openView(name){state.activeView=name||'overview';$$('.nav button').forEach(b=>b.classList.toggle('active',b.dataset.view===state.activeView));$$('.page').forEach(p=>p.classList.toggle('active',p.dataset.view===state.activeView));renderChrome()}
    function formatModeLimitsMap(map){return Object.entries(map||{}).map(([key,value])=>`${key}=${value}`).join('\\n')}
    function parseModeLimitsMap(text){const out={};String(text||'').split('\\n').map(line=>line.trim()).filter(Boolean).forEach(line=>{const [key,...rest]=line.split('=');const value=Number(rest.join('=').trim());if(key&&Number.isFinite(value))out[key.trim()]=value});return out}
    const PAYMENT_PACKAGE_KEYS=['day','week','month','year']
    function packageInputId(key,field){return `#payment_package_${key}_${field}`}
    function renderPaymentPackages(packages){
      PAYMENT_PACKAGE_KEYS.forEach(key=>{
        const item=(packages&&packages[key])||{}
        setChecked(packageInputId(key,'enabled'),!!item.enabled)
        setChecked(packageInputId(key,'recurring_stars_enabled'),!!item.recurring_stars_enabled)
        setValue(packageInputId(key,'title'),item.title||'')
        setValue(packageInputId(key,'price_minor_units'),item.price_minor_units??'')
        setValue(packageInputId(key,'access_duration_days'),item.access_duration_days??'')
        setValue(packageInputId(key,'sort_order'),item.sort_order??'')
        setValue(packageInputId(key,'badge'),item.badge||'')
        setValue(packageInputId(key,'description'),item.description||'')
      })
    }
    function collectPaymentPackages(){
      const packages={}
      PAYMENT_PACKAGE_KEYS.forEach(key=>{
        packages[key]={
          enabled:$(packageInputId(key,'enabled'))?.checked||false,
          recurring_stars_enabled:$(packageInputId(key,'recurring_stars_enabled'))?.checked||false,
          title:$(packageInputId(key,'title'))?.value||'',
          price_minor_units:Number($(packageInputId(key,'price_minor_units'))?.value||0),
          access_duration_days:Number($(packageInputId(key,'access_duration_days'))?.value||0),
          sort_order:Number($(packageInputId(key,'sort_order'))?.value||0),
          badge:$(packageInputId(key,'badge'))?.value||'',
          description:$(packageInputId(key,'description'))?.value||'',
        }
      })
      return packages
    }
    function renderModeOverrides(ai,catalog){const overrides=ai.mode_overrides||{};const globalModel=ai.openai_model||'';const keys=Object.keys(catalog||{}).sort((a,b)=>(catalog[a].sort_order||0)-(catalog[b].sort_order||0));$('#ai-mode-overrides').innerHTML=keys.map(key=>{const meta=catalog[key]||{};const value=overrides[key]||{};const effectiveModel=value.model||globalModel||'—';return `<div class="mode-card"><div class="mode-head"><div><strong>${esc(meta.icon||'')} ${esc(meta.name||key)}</strong><div class="muted">${esc(key)} • сейчас: ${esc(effectiveModel)}</div></div></div><div class="three"><label>Модель<input data-ai-override="${key}.model" value="${esc(value.model||'')}"></label><label>Температура<input data-ai-override="${key}.temperature" type="number" step="0.1" value="${esc(value.temperature??'')}"></label><label>Макс. токены<input data-ai-override="${key}.max_completion_tokens" type="number" value="${esc(value.max_completion_tokens??'')}"></label><label>Память<input data-ai-override="${key}.memory_max_tokens" type="number" value="${esc(value.memory_max_tokens??'')}"></label><label>История<input data-ai-override="${key}.history_message_limit" type="number" value="${esc(value.history_message_limit??'')}"></label><label>Таймаут<input data-ai-override="${key}.timeout_seconds" type="number" value="${esc(value.timeout_seconds??'')}"></label></div><div class="three"><label>Повторы<input data-ai-override="${key}.max_retries" type="number" value="${esc(value.max_retries??'')}"></label></div><label>Доп. инструкция<textarea data-ai-override="${key}.prompt_suffix">${esc(value.prompt_suffix||'')}</textarea></label></div>`}).join('')}
    function renderOverview(){
      if(!state.overview)return;
      const o=state.overview,users=o.users||{},content=o.content||{},payments=o.payments||{},funnel7=o.monetization?.funnel_7d||{},funnel30=o.monetization?.funnel_30d||{},byTrigger30=o.monetization?.by_trigger_30d||{},byVariant30=o.monetization?.by_variant_30d||{},growth=o.growth||{},runtime=o.runtime||{},chatRuntime=runtime.chat_sessions||{},support=o.support||{},episodes=support.episode_counts||{},proactive=o.proactive||{},preferences=o.preferences||{},referrals=o.referrals||{},recent=o.recent||{};
      const funnel7Stages=funnel7.stages||{},funnel30Stages=funnel30.stages||{},funnel7Conversion=funnel7.conversion||{},funnel30Conversion=funnel30.conversion||{};
      const paymentProviders=payments.providers||{},virtualProvider=paymentProviders.virtual||{},telegramProvider=paymentProviders.telegram||{};
      const growthEvents=growth.events_30d||{},acquisitionBySource=growth.acquisition_by_source_30d?.segments||{},acquisitionByCampaign=growth.acquisition_by_campaign_30d?.segments||{};
      const topSourceEntry=Object.entries(acquisitionBySource).sort((a,b)=>(b[1]?.events??0)-(a[1]?.events??0))[0]||[];
      const topCampaignEntry=Object.entries(acquisitionByCampaign).sort((a,b)=>(b[1]?.events??0)-(a[1]?.events??0))[0]||[];
      const cards=[['Пользователи',num(users.total??0),'Всего в базе'],['Активации 30д',num(growthEvents.activation_reached?.users??0),`Онбординг завершили: ${num(growthEvents.onboarding_completed?.users??0)}`],['Платные активны',num(users.subscription_segments?.paid_active??0),`Pro: ${num(users.subscription_segments?.pro_active??0)} • Premium: ${num(users.subscription_segments?.premium_active??0)}`],['Выручка',num(payments.revenue??0),`Оплат: ${num(payments.successful_payments??0)}`],['Оплаты 30д',num(funnel30Stages.paid?.users??0),`Продления: ${num(funnel30Stages.renewed?.users??0)}`],['Система',`${runtime.queue_size??0}/${runtime.queue_capacity??0}`,`OpenAI: ${runtime.openai_in_flight_requests??0}/${runtime.openai_configured_limit??0}`]];
      if(state.settings)$('#overview-launch-readiness').innerHTML=renderLaunchReadiness();
      $('#overview-cards').innerHTML=cards.map(x=>`<div class="card"><div class="stat-label">${x[0]}</div><div class="stat-value">${x[1]}</div><div class="muted">${x[2]}</div></div>`).join('');
      $('#overview-audience').innerHTML=`<div class="stack">${metricCards([['Всего пользователей',num(users.total??0),'База пользователей'],['Новые за 1 день',num(users.new_1d??0),'Свежие регистрации'],['Онбординг старт',num(growthEvents.onboarding_started?.users??0),'Стартовали за 30 дней'],['Активации 30д',num(growthEvents.activation_reached?.users??0),'Дошли до целевого первого опыта']])}${kvList([['Сообщений всего',esc(num(content.messages_total??0))],['Активных платных',esc(num(users.active_with_messages??0))],['Рефералов',esc(num(referrals.total??0))],['Конверсий рефералки',esc(num(referrals.converted??0))],['Топ source',esc(topSourceEntry[0]||'—')],['Топ campaign',esc(topCampaignEntry[0]||'—')]])}</div>`;
      $('#overview-revenue').innerHTML=`<div class="stack">${metricCards([['Успешные оплаты',num(payments.successful_payments??0),'Все провайдеры'],['Виртуальные',num(virtualProvider.successful_payments??0),`Выручка: ${num(virtualProvider.revenue??0)}`],['Telegram',num(telegramProvider.successful_payments??0),`Выручка: ${num(telegramProvider.revenue??0)}`],['Офферы 30д',num(funnel30Stages.offer_shown?.users??0),`Оплаты: ${num(funnel30Stages.paid?.users??0)}`]])}${kvList([['Конверсия оффер -> инвойс (30д)',esc(`${funnel30Conversion.offer_to_invoice_pct??0}%`)],['Конверсия инвойс -> paid (30д)',esc(`${funnel30Conversion.invoice_to_paid_pct??0}%`)],['Конверсия paid -> renewed (30д)',esc(`${funnel30Conversion.paid_to_renewed_pct??0}%`)],['Продления 30д',esc(num(funnel30Stages.renewed?.users??0))],['Referral menu opens',esc(num(growthEvents.referral_menu_opened?.events??0))],['Insight shares',esc(num(growthEvents.insight_shared?.events??0))]])}</div>`;
      $('#overview-runtime').innerHTML=`<div class="stack">${metricCards([['AI очередь',`${runtime.queue_size??0}/${runtime.queue_capacity??0}`,`busy: ${runtime.busy_workers??0}/${runtime.workers??0}`],['OpenAI',`${runtime.openai_in_flight_requests??0}/${runtime.openai_configured_limit??0}`,`ждут: ${runtime.openai_waiting_requests??0}`],['Chat locks',num(chatRuntime.active_sessions??0),`waits: ${num(chatRuntime.wait_events??0)}`],['Инициативные 1д',num(proactive.sent_1d??0),`ответы: ${proactive.reply_after_proactive_rate??0}%`]])}${kvList([['Поддержка',esc(num(support.users_with_support_profile??0))],['Паника',esc(num(episodes.panic??0))],['Часовые пояса',esc(num(preferences.users_with_timezone??0))],['Отказались от инициативы',esc(num(preferences.proactive_disabled_users??0))]])}</div>`;
      const recentUsersRows=(recent.users||[]).map(user=>({'ID':user.id,'Имя':user.first_name||'—','Username':user.username||'—','Premium':user.is_premium?'Да':'Нет','Создан':user.created_at||'—'}));
      $('#recent-users').innerHTML=`<div class="table-wrap overview-table">${table(['ID','Имя','Username','Premium','Создан'],recentUsersRows)}</div>`;
      const recentPaymentsRows=(recent.payments||[]).map(item=>({'Пользователь':item.user_id??'—','Пакет':item.package_title||'—','Сумма':item.amount!=null?`${item.amount} ${item.currency||''}`.trim():'—','Провайдер':item.provider||'—','Статус':item.status||'—','Время':item.event_time||'—'}));
      $('#recent-payments').innerHTML=`<div class="table-wrap overview-table">${table(['Пользователь','Пакет','Сумма','Провайдер','Статус','Время'],recentPaymentsRows)}</div>`;
      const recentMonetizationRows=(recent.monetization||[]).map(item=>({'Пользователь':item.user_id??'—','Событие':item.event_name||'—','Trigger':item.offer_trigger||'—','Source':item.metadata?.source||'—','Campaign':item.metadata?.campaign||'—','Время':item.created_at||'—'}));
      $('#recent-monetization').innerHTML=`<div class="table-wrap overview-table">${table(['Пользователь','Событие','Trigger','Source','Campaign','Время'],recentMonetizationRows)}</div>`;
      $('#monetization-by-trigger').innerHTML=monetizationSegmentTable(byTrigger30);
      $('#monetization-by-variant').innerHTML=monetizationSegmentTable(byVariant30);
      $('#support-summary').innerHTML=`<div class="stack">${metricCards([['Профили поддержки',String(support.users_with_support_profile??0),'Пользователи с профилем поддержки'],['Рефералы',String(referrals.total??0),`Конверсий: ${referrals.converted??0}`],['Инициативные пользователи',String(proactive.users_contacted_7d??0),'Кому бот писал за 7 дней']])}${kvList([['Эпизоды паники',esc(num(episodes.panic??0))],['Эпизоды флэшбэков',esc(num(episodes.flashback??0))],['Эпизоды бессонницы',esc(num(episodes.insomnia??0))],['Флаги самоповреждения',esc(num(support.self_harm_flags??0))],['Отправлено инициативных',esc(num(proactive.sent_total??0))],['Ошибок инициативных',esc(num(proactive.failed_total??0))],['Ответы после инициативных',esc(`${proactive.reply_after_proactive_total??0} (${proactive.reply_after_proactive_rate??0}%)`)],['Отказы после инициативных',esc(`${proactive.opt_out_after_proactive_total??0} (${proactive.opt_out_after_proactive_rate??0}%)`)],['Пользователи с часовым поясом',esc(num(preferences.users_with_timezone??0))],['Пользователи с отказом',esc(num(preferences.proactive_disabled_users??0))],['Последнее обновление',esc(support.last_updated_at||'Нет данных')]])}</div>`;
      $('#monetization-summary').innerHTML=`<div class="stack">${metricCards([['Офферы 7д',String(funnel7Stages.offer_shown?.users??0),`Инвойс: ${funnel7Stages.invoice_opened?.users??0}`],['Оплаты 7д',String(funnel7Stages.paid?.users??0),`Продления: ${funnel7Stages.renewed?.users??0}`],['Онбординг 30д',String(growthEvents.onboarding_completed?.users??0),`Активации: ${growthEvents.activation_reached?.users??0}`],['Acquisition 30д',String(growthEvents.acquisition_attributed?.users??0),`Share: ${growthEvents.insight_shared?.events??0}`]])}${kvList([['Конверсия оффер -> инвойс (7д)',esc(`${funnel7Conversion.offer_to_invoice_pct??0}%`)],['Конверсия инвойс -> paid (7д)',esc(`${funnel7Conversion.invoice_to_paid_pct??0}%`)],['Конверсия paid -> renewed (7д)',esc(`${funnel7Conversion.paid_to_renewed_pct??0}%`)],['Events offer_shown / invoice_opened (30д)',esc(`${funnel30Stages.offer_shown?.events??0} / ${funnel30Stages.invoice_opened?.events??0}`)],['Events paid / renewed (30д)',esc(`${funnel30Stages.paid?.events??0} / ${funnel30Stages.renewed?.events??0}`)],['Top source events',esc(topSourceEntry.length?`${topSourceEntry[0]} • ${topSourceEntry[1]?.events??0}`:'—')],['Top campaign events',esc(topCampaignEntry.length?`${topCampaignEntry[0]} • ${topCampaignEntry[1]?.events??0}`:'—')]])}</div>`;
    }
    function renderHealth(){
      if(!state.health)return;
      const db=state.health.db||{},redis=state.health.redis||{},ai=state.health.ai_runtime||{},chat=state.health.chat_runtime||{},release=state.health.release||{},warnings=state.health.warnings||[];
      const redisMode=redis.mode||'unknown';
      const redisSummaryLabel=redis.ok?'Redis в норме':(redisMode==='fallback'?'Redis в fallback':'Redis недоступен');
      const redisStatusLabel=redis.ok?'Норма':(redisMode==='fallback'?'Fallback':'Ошибка');
      const redisLatency=redis.latency_ms==null?'—':`${redis.latency_ms} мс`;
      const aiQueueWait=ai.last_queue_wait_ms==null?'—':`${ai.last_queue_wait_ms} мс`;
      const aiRunLatency=ai.last_run_ms==null?'—':`${ai.last_run_ms} мс`;
      const openaiWait=ai.openai_last_wait_ms==null?'—':`${ai.openai_last_wait_ms} мс`;
      const openaiLatency=ai.openai_last_latency_ms==null?'—':`${ai.openai_last_latency_ms} мс`;
      const chatWait=chat.last_wait_ms==null?'—':`${chat.last_wait_ms} мс`;
      const warningSummary=warnings.length?statusPill(false,`${warnings.length} предупреждений`,`${warnings.length} предупреждений`):statusPill(true,'Без предупреждений','');
      const warningList=warnings.length?`<div class="stack">${warnings.map(item=>`<div class="message-card"><div class="message-meta"><strong>${esc(item.severity||'info')}</strong><span>${esc(item.code||'warning')}</span></div><div>${esc(item.message||'')}</div></div>`).join('')}</div>`:'<div class="muted">Критичных предупреждений сейчас нет.</div>';
      $('#sidebar-health').innerHTML=`${statusPill(db.ok,'БД в норме','БД недоступна')} ${statusPill(redis.ok,redisSummaryLabel,redisSummaryLabel)}`;
      $('#health-summary').innerHTML=`<div class="stack">${healthSummary(ai)}${kvList([["База данных",`${statusPill(db.ok,'Подключено','Ошибка')}<div class="muted">${esc(db.detail||'')}</div>`],["Redis",`${statusPill(redis.ok,redisSummaryLabel,redisSummaryLabel)}<div class="muted">${esc(redis.detail||'')}</div>`],["Redis endpoint",`<span>${esc(redis.endpoint||'—')}</span><div class="muted">DB ${esc(String(redis.database??'—'))} • ${esc(redisLatency)}</div>`],["AI очередь",`<span>${esc(`${ai.queue_size??0}/${ai.queue_capacity??0}`)}</span><div class="muted">busy ${esc(String(ai.busy_workers??0))}/${esc(String(ai.workers??0))} • wait ${esc(aiQueueWait)}</div>`],["OpenAI pool",`<span>${esc(`${ai.openai_in_flight_requests??0}/${ai.openai_configured_limit??0}`)}</span><div class="muted">waiters ${esc(String(ai.openai_waiting_requests??0))} • latency ${esc(openaiLatency)}</div>`],["Chat sessions",`<span>${esc(String(chat.active_sessions??0))}</span><div class="muted">waits ${esc(String(chat.wait_events??0))} • last ${esc(chatWait)}</div>`],["Модель ИИ",esc(ai.model||ai.openai_model||'Не указана')],["Релиз",release.available?`${esc(release.branch||'') || 'branch?'}<div class="muted">${esc((release.commit||'').slice(0,12)||'commit?')} • ${esc(release.deployed_at||'')}</div>`:`<span class="muted">release.json не найден</span>`],["Предупреждения",warningSummary]])}</div>`;
      $('#full-health').innerHTML=`<div class="stack">${metricCards([["Очередь ИИ",`${ai.queue_size??0}/${ai.queue_capacity??0}`,"Текущее давление"],["OpenAI in-flight",`${ai.openai_in_flight_requests??0}/${ai.openai_configured_limit??0}`,"Глобальный лимит клиента"],["Chat sessions",String(chat.active_sessions??0),"Сколько пользовательских сессий сейчас в работе"],["Режимов",String(state.health.modes_count??0),"Доступно в каталоге"]])}${kvList([["Статус БД",`${statusPill(db.ok,'Норма','Ошибка')}<div class="muted">${esc(db.detail||'')}</div>`],["Статус Redis",`${statusPill(redis.ok,redisStatusLabel,redisStatusLabel)}<div class="muted">${esc(redis.detail||'')}</div>`],["Режим Redis",esc(redisMode)],["Redis endpoint",esc(redis.endpoint||'—')],["Redis DB",esc(String(redis.database??'—'))],["Redis URL",esc(redis.url||'—')],["Latency Redis",esc(redisLatency)],["Воркеров всего",esc(String(ai.workers??0))],["Воркеров занято",esc(String(ai.busy_workers??0))],["Запросов начато",esc(String(ai.requests_started??0))],["Запросов завершено",esc(String(ai.requests_completed??0))],["Ошибок AI",esc(String(ai.requests_failed??0))],["Reject из очереди",esc(String(ai.requests_rejected??0))],["Timeout в очереди",esc(String(ai.requests_queue_timed_out??0))],["Ожидание в очереди",esc(aiQueueWait)],["Латентность AI",esc(aiRunLatency)],["OpenAI waiters",esc(String(ai.openai_waiting_requests??0))],["OpenAI wait",esc(openaiWait)],["OpenAI latency",esc(openaiLatency)],["Chat active",esc(String(chat.active_sessions??0))],["Chat tracked users",esc(String(chat.tracked_users??0))],["Chat waits",esc(String(chat.wait_events??0))],["Chat wait latency",esc(chatWait)],["Ветка",esc(release.branch||'—')],["Коммит",esc((release.commit||'').slice(0,12)||'—')],["Задеплоено",esc(release.deployed_at||'—')]])}<div><div class="stat-label">Предупреждения</div>${warningList}</div></div>`;
      $('#config-files').innerHTML=fileTable(state.health.config_files)
    }
    function renderUserModeOptions(){const select=$('#user_active_mode');if(!select||!state.settings||!state.settings.mode_catalog)return;const catalog=state.settings.mode_catalog||{};const keys=Object.keys(catalog).sort((a,b)=>(catalog[a].sort_order||0)-(catalog[b].sort_order||0));select.innerHTML=keys.map(key=>{const mode=catalog[key]||{};const suffix=mode.is_premium?' (Премиум)':' (Бесплатно)';return `<option value="${esc(key)}">${esc((mode.icon||'')+' '+(mode.name||key)+suffix)}</option>`}).join('')}
    function renderUsers(){renderUserModeOptions();if(!state.users)return;renderUserSegments();$('#users-table').innerHTML=usersTable(state.users.items||[]);if(state.currentUser){setValue('#user_active_mode',state.currentUser.active_mode||'base')}syncSelectedUsersUi();renderBroadcastResult(state.lastBroadcastResult);renderTemplateEditor()}
    function conversationMessages(items){if(!items||!items.length)return '<div class="muted">У пользователя пока нет сообщений.</div>';return items.map(item=>`<div class="message-card ${item.role==='user'?'user':'assistant'}"><div class="message-meta"><strong>${item.role==='user'?'Пользователь':'Бот'}</strong><span>${esc(item.created_at||'')}</span></div><div>${escText(item.text||'')}</div></div>`).join('')}
    function fillUserForm(user){state.currentUser=user||null;renderUserModeOptions();setValue('#user_user_id',user?.id??'');setValue('#conversation_user_id',user?.id??$('#conversation_user_id')?.value??'');setValue('#user_username',user?.username??'');setValue('#user_first_name',user?.first_name??'');setValue('#user_active_mode',user?.active_mode??'base');setChecked('#user_is_admin',user?.is_admin);setChecked('#user_is_premium',user?.is_premium);$('#user_meta').innerHTML=user?`Создан: ${esc(user.created_at||'неизвестно')} • ${renderPremiumExpiryInline(user)}`:'Можно ввести ID вручную и сохранить: запись создастся даже если пользователь ещё не появился в таблице.';renderChrome()}
    function usersTable(items){if(!items||!items.length)return '<div class="muted">Пока нет данных.</div>';const visibleIds=items.map(user=>normalizeUserId(user.id)).filter(Boolean);const allVisibleSelected=!!visibleIds.length&&visibleIds.every(id=>state.selectedUserIds.has(id));return `<table><thead><tr><th class="user-select-cell"><input id="users-select-all-visible" class="inline-checkbox" type="checkbox" ${allVisibleSelected?'checked':''}></th><th>ID</th><th>Имя пользователя</th><th>Имя</th><th>Режим</th><th>Премиум</th><th>Premium до</th><th>Админ</th><th>Действие</th></tr></thead><tbody>${items.map(user=>{const userId=normalizeUserId(user.id);const checked=userId&&state.selectedUserIds.has(userId)?'checked':'';return `<tr><td class="user-select-cell"><input class="inline-checkbox" type="checkbox" data-user-select="${esc(userId)}" ${checked}></td><td>${esc(user.id)}</td><td>${esc(user.username||'')}</td><td>${esc(user.first_name||'')}</td><td>${esc(user.active_mode||'base')}</td><td>${user.is_premium?'Да':'Нет'}</td><td>${renderPremiumExpiryCell(user)}</td><td>${user.is_admin?'Да':'Нет'}</td><td><button data-user-pick="${esc(user.id)}">Выбрать</button></td></tr>`}).join('')}</tbody></table>`}
    function memoryCategoryOptions(items){return (items||[]).map(item=>`<option value="${esc(item.key)}">${esc(item.label)}</option>`).join('')}
    function resetMemoryEditor(categories){const categorySelect=$('#memory_editor_category');const categoryList=categories||state.currentConversation?.settings?.memory_categories||[];categorySelect.innerHTML=memoryCategoryOptions(categoryList);setValue('#memory_editor_id','');setValue('#memory_editor_weight','1.0');setValue('#memory_editor_value','');setChecked('#memory_editor_pinned',false);if(categoryList.length){setValue('#memory_editor_category',categoryList[0].key)}state.currentMemoryId=null}
    function fillMemoryEditor(memory,categories){if(!memory){resetMemoryEditor(categories);return}const categoryList=categories||state.currentConversation?.settings?.memory_categories||[];$('#memory_editor_category').innerHTML=memoryCategoryOptions(categoryList);setValue('#memory_editor_id',memory.id);setValue('#memory_editor_category',memory.category||'');setValue('#memory_editor_weight',memory.weight??1.0);setValue('#memory_editor_value',memory.value||'');setChecked('#memory_editor_pinned',memory.pinned);state.currentMemoryId=memory.id}
    function formatLongTermMemories(items){if(!items||!items.length)return '<div class="muted">Пока нет данных.</div>';return items.map(item=>`<div class="kv-row"><div class="kv-key"><strong>${esc(item.category)}</strong><div class="muted">${esc(item.value)}</div><div class="muted">score=${esc(item.score)} | weight=${esc(item.weight)} | seen=${esc(item.times_seen)} | updated=${esc(item.updated_at||'-')}</div></div><div class="kv-value"><div class="memory-row-actions"><button data-memory-edit="${esc(item.id)}">Редактировать</button><button data-memory-pin="${esc(item.id)}" data-pinned="${item.pinned?0:1}">${item.pinned?'Открепить':'Закрепить'}</button></div></div></div>`).join('')}
    function renderConversation(){const view=state.currentConversation,categories=view?.settings?.memory_categories||[];if(!view){$('#conversation-meta').textContent='Выберите пользователя, чтобы увидеть историю и память.';$('#conversation-stats').innerHTML='';$('#conversation-memory-preview-summary').innerHTML='<div class="muted">Пока нет данных.</div>';$('#conversation-memory-preview').textContent='Пока нет данных.';$('#conversation-long-term-memories').innerHTML='<div class="muted">Пока нет данных.</div>';$('#conversation-state-summary').innerHTML='<div class="muted">Пока нет данных.</div>';$('#conversation-state').textContent='Пока нет данных.';$('#conversation-messages').innerHTML='<div class="muted">Пока нет данных.</div>';resetMemoryEditor([]);renderChrome();return}const user=view.user||{},stats=view.stats||{},cfg=view.settings||{};setValue('#conversation_user_id',user.id??'');$('#conversation-meta').textContent=`Пользователь: ${user.first_name||user.username||user.id||'неизвестно'} • ID ${user.id||'-'} • Сообщений: ${stats.total_messages??0}`;$('#conversation-stats').innerHTML=metricCards([['Всего сообщений',String(stats.total_messages??0),`пользователь: ${stats.user_messages??0}, бот: ${stats.assistant_messages??0}`],['Первое сообщение',String(stats.first_message_at||'—'),'Начало истории'],['Последнее сообщение',String(stats.last_message_at||'—'),'Последняя активность'],['Долгая память',cfg.long_term_memory_enabled?'вкл':'выкл',`Элементов в контексте: ${cfg.long_term_memory_max_items??0}`],['Автоочистка',cfg.long_term_memory_auto_prune_enabled?'вкл':'выкл',`Мягкий лимит: ${cfg.long_term_memory_soft_limit??0}`],['Лимит истории',String(cfg.history_message_limit??0),`Токенов памяти: ${cfg.memory_max_tokens??0}`],['Сводная память',cfg.episodic_summary_enabled?'вкл':'выкл','Слой суммаризации']]);$('#conversation-memory-preview-summary').innerHTML=renderMemoryPreview(view.memory_preview||'');$('#conversation-memory-preview').textContent=view.memory_preview||'Память пока пустая.';$('#conversation-long-term-memories').innerHTML=formatLongTermMemories(view.long_term_memories||[]);$('#conversation-state-summary').innerHTML=renderStateSummary(view.state||{});$('#conversation-state').textContent=JSON.stringify(view.state||{},null,2);$('#conversation-messages').innerHTML=conversationMessages(view.messages||[]);const selected=(view.long_term_memories||[]).find(item=>String(item.id)===String(state.currentMemoryId));if(selected){fillMemoryEditor(selected,categories)}else{resetMemoryEditor(categories)}renderChrome()}
    function collectInitiativeFamilies(){return ['soft_presence','callback_thread','mood_ping','playful_hook'].filter(name=>$(`#initiative_family_${name}`)?.checked)}
    function applyDialoguePreset(name){
      const presets={
        balanced:{sentences:2,chars:240,followUp:false,topicQuestions:true,risky:true,charged:true},
        live:{sentences:3,chars:280,followUp:true,topicQuestions:true,risky:false,charged:false},
        compact:{sentences:2,chars:190,followUp:false,topicQuestions:false,risky:true,charged:true}
      };
      const preset=presets[name]||presets.balanced;
      setValue('#dialogue_hook_max_sentences',preset.sentences);
      setValue('#dialogue_hook_max_chars',preset.chars);
      setChecked('#dialogue_hook_require_follow_up_question',preset.followUp);
      setChecked('#dialogue_hook_topic_questions_enabled',preset.topicQuestions);
      setChecked('#dialogue_risky_scene_compact_redirect',preset.risky);
      setChecked('#dialogue_charged_probe_compact_redirect',preset.charged);
    }
    function applyInitiativePreset(name){
      const presets={
        warm:{maxChars:240,maxCompletionTokens:120,allowQuestion:false,preferCallback:false,families:['soft_presence','mood_ping']},
        balanced:{maxChars:220,maxCompletionTokens:110,allowQuestion:false,preferCallback:false,families:['soft_presence','mood_ping','playful_hook']},
        tight:{maxChars:170,maxCompletionTokens:90,allowQuestion:false,preferCallback:false,families:['soft_presence','mood_ping']}
      };
      const preset=presets[name]||presets.balanced;
      setValue('#initiative_style_max_chars',preset.maxChars);
      setValue('#initiative_style_max_completion_tokens',preset.maxCompletionTokens);
      setChecked('#initiative_style_allow_question',preset.allowQuestion);
      setChecked('#initiative_style_prefer_callback_thread',preset.preferCallback);
      ['soft_presence','callback_thread','mood_ping','playful_hook'].forEach(key=>setChecked(`#initiative_family_${key}`,preset.families.includes(key)));
    }
    function renderRuntime(){
      if(!state.settings||!state.settings.runtime)return;
      const r=state.settings.runtime,a=r.ai||{},c=r.chat||{},e=r.engagement||{},u=r.ui||{},dialogue=a.dialogue||{},fastLane=a.fast_lane||{},style=e.reengagement_style||{};
      setValue('#ai_openai_model',a.openai_model);
      setValue('#ai_response_language',a.response_language);
      setValue('#ai_temperature',a.temperature);
      setValue('#ai_top_p',a.top_p);
      setValue('#ai_frequency_penalty',a.frequency_penalty);
      setValue('#ai_presence_penalty',a.presence_penalty);
      setValue('#ai_max_completion_tokens',a.max_completion_tokens);
      setValue('#ai_reasoning_effort',a.reasoning_effort||'');
      setValue('#ai_verbosity',a.verbosity||'');
      setValue('#ai_timeout_seconds',a.timeout_seconds);
      setValue('#ai_max_retries',a.max_retries);
      setValue('#ai_memory_max_tokens',a.memory_max_tokens);
      setValue('#ai_history_message_limit',a.history_message_limit);
      setValue('#ai_long_term_memory_max_items',a.long_term_memory_max_items);
      setValue('#ai_long_term_memory_soft_limit',a.long_term_memory_soft_limit);
      setValue('#ai_debug_prompt_user_id',a.debug_prompt_user_id||'');
      setChecked('#ai_long_term_memory_enabled',a.long_term_memory_enabled);
      setChecked('#ai_long_term_memory_auto_prune_enabled',a.long_term_memory_auto_prune_enabled);
      setChecked('#ai_episodic_summary_enabled',a.episodic_summary_enabled);
      setChecked('#ai_log_full_prompt',a.log_full_prompt);
      renderModeOverrides(a,state.settings.mode_catalog||{});
      setChecked('#chat_typing_action_enabled',c.typing_action_enabled);
      setChecked('#chat_response_guardrails_enabled',c.response_guardrails_enabled);
      setValue('#chat_non_text_message',c.non_text_message);
      setValue('#chat_busy_message',c.busy_message);
      setValue('#chat_ai_error_message',c.ai_error_message);
      setValue('#chat_write_prompt_message',c.write_prompt_message);
      setValue('#chat_response_guardrail_blocked_phrases',(c.response_guardrail_blocked_phrases||[]).join('\\n'));
      setChecked('#initiative_enabled',!!e.reengagement_enabled);
      setValue('#initiative_idle_hours',e.reengagement_idle_hours??'');
      setValue('#initiative_min_hours_between',e.reengagement_min_hours_between??'');
      setValue('#initiative_recent_window_days',e.reengagement_recent_window_days??'');
      setValue('#initiative_poll_seconds',e.reengagement_poll_seconds??'');
      setValue('#initiative_batch_size',e.reengagement_batch_size??'');
      setChecked('#initiative_quiet_hours_enabled',!!e.quiet_hours_enabled);
      setValue('#initiative_quiet_hours_start',e.quiet_hours_start??'');
      setValue('#initiative_quiet_hours_end',e.quiet_hours_end??'');
      setValue('#initiative_timezone',e.timezone||'');
      setValue('#initiative_style_max_chars',style.max_chars??220);
      setValue('#initiative_style_max_completion_tokens',style.max_completion_tokens??120);
      setChecked('#initiative_style_allow_question',style.allow_question===true);
      setChecked('#initiative_style_prefer_callback_thread',style.prefer_callback_thread===true);
      ['soft_presence','callback_thread','mood_ping','playful_hook'].forEach(key=>setChecked(`#initiative_family_${key}`,(style.enabled_families||[]).includes(key)));
      setValue('#dialogue_hook_max_sentences',dialogue.hook_max_sentences??2);
      setValue('#dialogue_hook_max_chars',dialogue.hook_max_chars??260);
      setChecked('#dialogue_hook_require_follow_up_question',dialogue.hook_require_follow_up_question===true);
      setChecked('#dialogue_hook_topic_questions_enabled',dialogue.hook_topic_questions_enabled!==false);
      setChecked('#dialogue_risky_scene_compact_redirect',dialogue.risky_scene_compact_redirect!==false);
      setChecked('#dialogue_charged_probe_compact_redirect',dialogue.charged_probe_compact_redirect!==false);
      setChecked('#fast_lane_enabled',fastLane.enabled!==false);
      setChecked('#fast_lane_force_low_verbosity',fastLane.force_low_verbosity!==false);
      setChecked('#fast_lane_force_low_reasoning',fastLane.force_low_reasoning!==false);
      ['hook','continuation','scene','generic'].forEach(name=>{
        setValue(`#fast_lane_${name}_max_completion_tokens`,fastLane[`${name}_max_completion_tokens`]??'');
        setValue(`#fast_lane_${name}_memory_max_tokens`,fastLane[`${name}_memory_max_tokens`]??'');
        setValue(`#fast_lane_${name}_history_message_limit`,fastLane[`${name}_history_message_limit`]??'');
        setValue(`#fast_lane_${name}_timeout_seconds`,fastLane[`${name}_timeout_seconds`]??'');
        setValue(`#fast_lane_${name}_max_retries`,fastLane[`${name}_max_retries`]??'');
      });
      setValue('#ui_write_button_text',u.write_button_text);
      setValue('#ui_modes_button_text',u.modes_button_text);
      setValue('#ui_premium_button_text',u.premium_button_text);
      setValue('#ui_input_placeholder',u.input_placeholder);
      setValue('#ui_start_avatar_path',u.start_avatar_path||'');
      setValue('#ui_modes_title',u.modes_title);
      setValue('#ui_modes_premium_marker',u.modes_premium_marker||'');
      setValue('#ui_user_not_found_text',u.user_not_found_text);
      setValue('#ui_unknown_mode_text',u.unknown_mode_text);
      setValue('#ui_mode_locked_text',u.mode_locked_text);
      setValue('#ui_mode_saved_toast',u.mode_saved_toast);
      setValue('#ui_mode_saved_template',u.mode_saved_template);
      setValue('#ui_welcome_user_text',u.welcome_user_text);
      setValue('#ui_welcome_followup_text',u.welcome_followup_text||'');
      setValue('#ui_onboarding_prompt_buttons',(u.onboarding_prompt_buttons||[]).join('\n'));
      setValue('#ui_welcome_admin_text',u.welcome_admin_text);
    }
    function renderSafety(){
      if(!state.settings||!state.settings.runtime)return;
      const r=state.settings.runtime,s=r.safety,se=r.state_engine,a=r.access,l=r.limits||{},e=r.engagement||{};
      $('#safety_throttle_rate_limit_seconds').value=s.throttle_rate_limit_seconds;
      $('#safety_throttle_warning_interval_seconds').value=s.throttle_warning_interval_seconds;
      $('#safety_max_message_length').value=s.max_message_length;
      $('#safety_reject_suspicious_messages').checked=!!s.reject_suspicious_messages;
      $('#safety_throttle_warning_text').value=s.throttle_warning_text;
      $('#safety_message_too_long_text').value=s.message_too_long_text;
      $('#safety_suspicious_rejection_text').value=s.suspicious_rejection_text;
      $('#safety_suspicious_keywords').value=(s.suspicious_keywords||[]).join('\\n');
      $('#state-defaults-grid').innerHTML=Object.entries(se.defaults).map(([k,v])=>`<label>${k}<input data-state-default="${k}" type="number" step="0.01" value="${v}"></label>`).join('');
      $('#state_positive_keywords').value=(se.positive_keywords||[]).join('\\n');
      $('#state_negative_keywords').value=(se.negative_keywords||[]).join('\\n');
      $('#state_attraction_keywords').value=(se.attraction_keywords||[]).join('\\n');
      $('#state-effects-grid').innerHTML=Object.entries(se.message_effects).map(([k,v])=>`<label>${k}<input data-state-effect="${k}" type="number" step="0.01" value="${v}"></label>`).join('');
      $('#access_forced_level').value=a.forced_level||'';
      $('#access_default_level').value=a.default_level;
      $('#access_interest_observation_threshold').value=a.interest_observation_threshold;
      $('#access_rare_layer_instability_threshold').value=a.rare_layer_instability_threshold;
      $('#access_rare_layer_attraction_threshold').value=a.rare_layer_attraction_threshold;
      $('#access_personal_focus_attraction_threshold').value=a.personal_focus_attraction_threshold;
      $('#access_personal_focus_interest_threshold').value=a.personal_focus_interest_threshold;
      $('#access_tension_attraction_threshold').value=a.tension_attraction_threshold;
      $('#access_tension_control_threshold').value=a.tension_control_threshold;
      $('#access_analysis_interest_threshold').value=a.analysis_interest_threshold;
      $('#access_analysis_control_threshold').value=a.analysis_control_threshold;
      $('#limits_free_daily_messages_enabled').checked=!!l.free_daily_messages_enabled;
      $('#limits_premium_daily_messages_enabled').checked=!!l.premium_daily_messages_enabled;
      $('#limits_admins_bypass_daily_limits').checked=!!l.admins_bypass_daily_limits;
      $('#limits_free_daily_messages_limit').value=l.free_daily_messages_limit??'';
      $('#limits_premium_daily_messages_limit').value=l.premium_daily_messages_limit??'';
      $('#limits_free_daily_limit_message').value=l.free_daily_limit_message||'';
      $('#limits_premium_daily_limit_message').value=l.premium_daily_limit_message||'';
      $('#limits_mode_preview_enabled').checked=!!l.mode_preview_enabled;
      $('#limits_mode_preview_default_limit').value=l.mode_preview_default_limit??'';
      $('#limits_mode_daily_limits').value=formatModeLimitsMap(l.mode_daily_limits||{});
      $('#limits_mode_preview_exhausted_message').value=l.mode_preview_exhausted_message||'';
      $('#engagement_adaptive_mode_enabled').checked=!!e.adaptive_mode_enabled;
    }
    function renderPrompts(){if(!state.settings||!state.settings.prompts)return;const p=state.settings.prompts,accessRules=p.access_rules||{};setValue('#prompt_personality_core',p.personality_core);setValue('#prompt_safety_block',p.safety_block);setValue('#prompt_response_style',p.response_style||'');setValue('#prompt_engagement_rules',p.engagement_rules||'');setValue('#prompt_ptsd_mode_prompt',p.ptsd_mode_prompt||'');setValue('#prompt_memory_intro',p.memory_intro);setValue('#prompt_state_intro',p.state_intro);setValue('#prompt_mode_intro',p.mode_intro);setValue('#prompt_access_intro',p.access_intro);setValue('#prompt_final_instruction',p.final_instruction);setValue('#access_observation',accessRules.observation);setValue('#access_analysis',accessRules.analysis);setValue('#access_tension',accessRules.tension);setValue('#access_personal_focus',accessRules.personal_focus);setValue('#access_rare_layer',accessRules.rare_layer)}
    function renderModes(){if(!state.settings||!state.settings.modes||!state.settings.mode_catalog)return;const m=state.settings.modes,c=state.settings.mode_catalog,runtimeAi=state.settings.runtime?.ai||{},modeOverrides=runtimeAi.mode_overrides||{},globalModel=runtimeAi.openai_model||'';const keys=Object.keys(c).sort((a,b)=>(c[a].sort_order||0)-(c[b].sort_order||0));const modeScaleLabel=k=>({warmth:'Теплота',flirt:'Флирт',depth:'Глубина',structure:'Структура',dominance:'Доминирование',initiative:'Инициатива',emoji_level:'Эмодзи',allow_bold:'Жирный текст',allow_italic:'Курсив'}[k]||k);$('#modes-container').innerHTML=keys.map(k=>{const meta=c[k]||{},scale=m[k]||{},override=modeOverrides[k]||{},numericEntries=Object.entries(scale).filter(([,mv])=>typeof mv==='number'),booleanEntries=Object.entries(scale).filter(([,mv])=>typeof mv==='boolean');return `<div class="mode-card"><div class="mode-head"><div><strong>${esc(meta.icon)} ${esc(meta.name)}</strong><div class="muted">${esc(k)} • GPT: ${esc(override.model||globalModel||'—')}</div></div><span class="badge">${meta.is_premium?'Премиум':'Бесплатно'}</span></div><div class="three"><label>Название<input data-catalog="${k}.name" value="${esc(meta.name)}"></label><label>Иконка<input data-catalog="${k}.icon" value="${esc(meta.icon)}"></label><label>Порядок<input data-catalog="${k}.sort_order" type="number" value="${meta.sort_order??0}"></label></div><div class="two"><label>GPT-модель<input data-mode-model="${k}" value="${esc(override.model||'')}" placeholder="${esc(globalModel||'gpt-4o-mini')}"></label><div class="muted">Пусто = общая модель. Детальные override можно править во вкладке «ИИ и интерфейс».</div></div><label class="checkbox"><input data-catalog="${k}.is_premium" type="checkbox" ${meta.is_premium?'checked':''}>Премиум</label><label>Описание<textarea data-catalog="${k}.description">${esc(meta.description)}</textarea></label><label>Тон<input data-catalog="${k}.tone" value="${esc(meta.tone)}"></label><label>Эмоциональное состояние<input data-catalog="${k}.emotional_state" value="${esc(meta.emotional_state)}"></label><label>Правила<textarea data-catalog="${k}.behavior_rules">${esc(meta.behavior_rules)}</textarea></label><label>Фраза активации<textarea data-catalog="${k}.activation_phrase">${esc(meta.activation_phrase)}</textarea></label><div class="three">${numericEntries.map(([mk,mv])=>`<label>${esc(modeScaleLabel(mk))}<input data-mode-scale="${k}.${mk}" type="number" min="0" max="10" value="${mv}"></label>`).join('')}</div>${booleanEntries.length?`<div class="two">${booleanEntries.map(([mk,mv])=>`<label class="checkbox"><input data-mode-scale="${k}.${mk}" type="checkbox" ${mv?'checked':''}>${esc(modeScaleLabel(mk))}</label>`).join('')}</div>`:''}</div>`}).join('')}
    function renderPayments(){
      if(!state.settings||!state.settings.runtime)return
      const p=state.settings.runtime.payment,ref=state.settings.runtime.referral
      setValue('#payment_provider_token',p.provider_token)
      setValue('#payment_mode',p.mode||'telegram')
      setValue('#payment_currency',p.currency)
      setValue('#payment_default_package_key',p.default_package_key||'month')
      setChecked('#payment_recurring_stars_enabled',!!p.recurring_stars_enabled)
      setValue('#payment_product_title',p.product_title)
      setValue('#payment_product_description',p.product_description)
      setValue('#payment_premium_benefits_text',p.premium_benefits_text)
      setValue('#payment_buy_cta_text',p.buy_cta_text)
      setValue('#payment_offer_preview_exhausted_template',p.offer_preview_exhausted_template||'')
      setValue('#payment_premium_menu_description_template',p.premium_menu_description_template||'')
      setValue('#payment_premium_menu_packages_title',p.premium_menu_packages_title||'')
      setValue('#payment_premium_menu_package_line_template',p.premium_menu_package_line_template||'')
      setValue('#payment_premium_menu_package_button_template',p.premium_menu_package_button_template||'')
      setValue('#payment_premium_menu_preview_template',p.premium_menu_preview_template||'')
      setValue('#payment_premium_menu_back_button_text',p.premium_menu_back_button_text||'')
      setValue('#payment_virtual_payment_description_template',p.virtual_payment_description_template||'')
      setValue('#payment_virtual_payment_button_template',p.virtual_payment_button_template||'')
      setValue('#payment_virtual_payment_completed_message',p.virtual_payment_completed_message||'')
      setValue('#payment_recurring_button_text',p.recurring_button_text||'')
      setValue('#payment_unavailable_message',p.unavailable_message)
      setValue('#payment_invoice_error_message',p.invoice_error_message)
      setValue('#payment_success_message',p.success_message)
      renderPaymentPackages(p.packages||{})
      setChecked('#referral_enabled',!!ref.enabled)
      setValue('#referral_start_parameter_prefix',ref.start_parameter_prefix)
      setValue('#referral_program_title',ref.program_title)
      setChecked('#referral_allow_self_referral',!!ref.allow_self_referral)
      setChecked('#referral_require_first_paid_invoice',!!ref.require_first_paid_invoice)
      setChecked('#referral_award_referrer_premium',!!ref.award_referrer_premium)
      setChecked('#referral_award_referred_user_premium',!!ref.award_referred_user_premium)
      setValue('#referral_program_description',ref.program_description)
      setValue('#referral_share_text_template',ref.share_text_template)
      setValue('#referral_referred_welcome_message',ref.referred_welcome_message)
      setValue('#referral_referrer_reward_message',ref.referrer_reward_message)
      $('#recent-referrals').textContent=JSON.stringify((state.overview&&state.overview.recent&&state.overview.recent.referrals)||[],null,2)
    }
    function renderLogs(){if(!state.logs)return;const redact=$('#log-redact-sensitive')?.checked!==false;const lines=(state.logs.lines||[]).map(line=>redact?redactLogLine(line):String(line||''));$('#logs-output').textContent=lines.join('\\n')||'Лог пуст.'}
    function runtimePayload(){
      const modeOverrides={};
      document.querySelectorAll('[data-ai-override]').forEach(i=>{
        const [mode,key]=i.dataset.aiOverride.split('.');
        const raw=i.value;
        let value=raw;
        if(i.type==='number'){
          if(raw==='')return;
          value=Number(raw);
          if(!Number.isFinite(value))return;
        }else if(!String(raw).trim()){
          return;
        }
        modeOverrides[mode]??={};
        modeOverrides[mode][key]=value;
      });
      const fastLane={enabled:$('#fast_lane_enabled').checked,force_low_verbosity:$('#fast_lane_force_low_verbosity').checked,force_low_reasoning:$('#fast_lane_force_low_reasoning').checked};
      ['hook','continuation','scene','generic'].forEach(name=>{
        fastLane[`${name}_max_completion_tokens`]=Number($(`#fast_lane_${name}_max_completion_tokens`).value);
        fastLane[`${name}_memory_max_tokens`]=Number($(`#fast_lane_${name}_memory_max_tokens`).value);
        fastLane[`${name}_history_message_limit`]=Number($(`#fast_lane_${name}_history_message_limit`).value);
        fastLane[`${name}_timeout_seconds`]=Number($(`#fast_lane_${name}_timeout_seconds`).value);
        fastLane[`${name}_max_retries`]=Number($(`#fast_lane_${name}_max_retries`).value);
      });
      return {ai:{openai_model:$('#ai_openai_model').value.trim(),response_language:$('#ai_response_language').value.trim(),temperature:Number($('#ai_temperature').value),top_p:Number($('#ai_top_p').value),frequency_penalty:Number($('#ai_frequency_penalty').value),presence_penalty:Number($('#ai_presence_penalty').value),max_completion_tokens:Number($('#ai_max_completion_tokens').value),reasoning_effort:$('#ai_reasoning_effort').value.trim(),verbosity:$('#ai_verbosity').value.trim(),timeout_seconds:Number($('#ai_timeout_seconds').value),max_retries:Number($('#ai_max_retries').value),memory_max_tokens:Number($('#ai_memory_max_tokens').value),history_message_limit:Number($('#ai_history_message_limit').value),long_term_memory_enabled:$('#ai_long_term_memory_enabled').checked,long_term_memory_max_items:Number($('#ai_long_term_memory_max_items').value),long_term_memory_auto_prune_enabled:$('#ai_long_term_memory_auto_prune_enabled').checked,long_term_memory_soft_limit:Number($('#ai_long_term_memory_soft_limit').value),episodic_summary_enabled:$('#ai_episodic_summary_enabled').checked,debug_prompt_user_id:$('#ai_debug_prompt_user_id').value.trim()||null,log_full_prompt:$('#ai_log_full_prompt').checked,mode_overrides:modeOverrides,dialogue:{hook_max_sentences:Number($('#dialogue_hook_max_sentences').value),hook_max_chars:Number($('#dialogue_hook_max_chars').value),hook_require_follow_up_question:$('#dialogue_hook_require_follow_up_question').checked,hook_topic_questions_enabled:$('#dialogue_hook_topic_questions_enabled').checked,risky_scene_compact_redirect:$('#dialogue_risky_scene_compact_redirect').checked,charged_probe_compact_redirect:$('#dialogue_charged_probe_compact_redirect').checked},fast_lane:fastLane},chat:{typing_action_enabled:$('#chat_typing_action_enabled').checked,response_guardrails_enabled:$('#chat_response_guardrails_enabled').checked,non_text_message:$('#chat_non_text_message').value,busy_message:$('#chat_busy_message').value,ai_error_message:$('#chat_ai_error_message').value,write_prompt_message:$('#chat_write_prompt_message').value,response_guardrail_blocked_phrases:$('#chat_response_guardrail_blocked_phrases').value},engagement:{reengagement_enabled:$('#initiative_enabled').checked,reengagement_idle_hours:Number($('#initiative_idle_hours').value),reengagement_min_hours_between:Number($('#initiative_min_hours_between').value),reengagement_recent_window_days:Number($('#initiative_recent_window_days').value),reengagement_poll_seconds:Number($('#initiative_poll_seconds').value),reengagement_batch_size:Number($('#initiative_batch_size').value),quiet_hours_enabled:$('#initiative_quiet_hours_enabled').checked,quiet_hours_start:Number($('#initiative_quiet_hours_start').value),quiet_hours_end:Number($('#initiative_quiet_hours_end').value),timezone:$('#initiative_timezone').value.trim(),reengagement_style:{enabled_families:collectInitiativeFamilies(),prefer_callback_thread:$('#initiative_style_prefer_callback_thread').checked,allow_question:$('#initiative_style_allow_question').checked,max_chars:Number($('#initiative_style_max_chars').value),max_completion_tokens:Number($('#initiative_style_max_completion_tokens').value)}},ui:{write_button_text:$('#ui_write_button_text').value,modes_button_text:$('#ui_modes_button_text').value,premium_button_text:$('#ui_premium_button_text').value,input_placeholder:$('#ui_input_placeholder').value,start_avatar_path:$('#ui_start_avatar_path').value.trim(),modes_title:$('#ui_modes_title').value,modes_premium_marker:$('#ui_modes_premium_marker').value,user_not_found_text:$('#ui_user_not_found_text').value,unknown_mode_text:$('#ui_unknown_mode_text').value,mode_locked_text:$('#ui_mode_locked_text').value,mode_saved_toast:$('#ui_mode_saved_toast').value,mode_saved_template:$('#ui_mode_saved_template').value,welcome_user_text:$('#ui_welcome_user_text').value,welcome_followup_text:$('#ui_welcome_followup_text').value,onboarding_prompt_buttons:parseTemplateEditorText($('#ui_onboarding_prompt_buttons')?.value||''),welcome_admin_text:$('#ui_welcome_admin_text').value,message_templates:parseTemplateEditorText($('#message_templates_editor')?.value||'')}}}
    function safetyPayload(){
      const defaults={},effects={};
      document.querySelectorAll('[data-state-default]').forEach(i=>defaults[i.dataset.stateDefault]=Number(i.value));
      document.querySelectorAll('[data-state-effect]').forEach(i=>effects[i.dataset.stateEffect]=Number(i.value));
      return {safety:{throttle_rate_limit_seconds:Number($('#safety_throttle_rate_limit_seconds').value),throttle_warning_interval_seconds:Number($('#safety_throttle_warning_interval_seconds').value),max_message_length:Number($('#safety_max_message_length').value),reject_suspicious_messages:$('#safety_reject_suspicious_messages').checked,throttle_warning_text:$('#safety_throttle_warning_text').value,message_too_long_text:$('#safety_message_too_long_text').value,suspicious_rejection_text:$('#safety_suspicious_rejection_text').value,suspicious_keywords:$('#safety_suspicious_keywords').value},state_engine:{defaults,positive_keywords:$('#state_positive_keywords').value,negative_keywords:$('#state_negative_keywords').value,attraction_keywords:$('#state_attraction_keywords').value,message_effects:effects},access:{forced_level:$('#access_forced_level').value.trim(),default_level:$('#access_default_level').value.trim(),interest_observation_threshold:Number($('#access_interest_observation_threshold').value),rare_layer_instability_threshold:Number($('#access_rare_layer_instability_threshold').value),rare_layer_attraction_threshold:Number($('#access_rare_layer_attraction_threshold').value),personal_focus_attraction_threshold:Number($('#access_personal_focus_attraction_threshold').value),personal_focus_interest_threshold:Number($('#access_personal_focus_interest_threshold').value),tension_attraction_threshold:Number($('#access_tension_attraction_threshold').value),tension_control_threshold:Number($('#access_tension_control_threshold').value),analysis_interest_threshold:Number($('#access_analysis_interest_threshold').value),analysis_control_threshold:Number($('#access_analysis_control_threshold').value)},limits:{free_daily_messages_enabled:$('#limits_free_daily_messages_enabled').checked,premium_daily_messages_enabled:$('#limits_premium_daily_messages_enabled').checked,admins_bypass_daily_limits:$('#limits_admins_bypass_daily_limits').checked,free_daily_messages_limit:Number($('#limits_free_daily_messages_limit').value),premium_daily_messages_limit:Number($('#limits_premium_daily_messages_limit').value),free_daily_limit_message:$('#limits_free_daily_limit_message').value,premium_daily_limit_message:$('#limits_premium_daily_limit_message').value,mode_preview_enabled:$('#limits_mode_preview_enabled').checked,mode_preview_default_limit:Number($('#limits_mode_preview_default_limit').value),mode_daily_limits:parseModeLimitsMap($('#limits_mode_daily_limits').value),mode_preview_exhausted_message:$('#limits_mode_preview_exhausted_message').value},engagement:{adaptive_mode_enabled:$('#engagement_adaptive_mode_enabled').checked}}}
    function promptsPayload(){return {personality_core:$('#prompt_personality_core').value,safety_block:$('#prompt_safety_block').value,response_style:$('#prompt_response_style').value,engagement_rules:$('#prompt_engagement_rules').value,ptsd_mode_prompt:$('#prompt_ptsd_mode_prompt').value,memory_intro:$('#prompt_memory_intro').value,state_intro:$('#prompt_state_intro').value,mode_intro:$('#prompt_mode_intro').value,access_intro:$('#prompt_access_intro').value,final_instruction:$('#prompt_final_instruction').value,access_rules:{observation:$('#access_observation').value,analysis:$('#access_analysis').value,tension:$('#access_tension').value,personal_focus:$('#access_personal_focus').value,rare_layer:$('#access_rare_layer').value}}}
    function modesPayload(){const modes={},catalog={},modeModels={};document.querySelectorAll('[data-mode-scale]').forEach(i=>{const [m,k]=i.dataset.modeScale.split('.');modes[m]??={};modes[m][k]=i.type==='checkbox'?i.checked:Number(i.value)});document.querySelectorAll('[data-catalog]').forEach(i=>{const [m,k]=i.dataset.catalog.split('.');catalog[m]??={};catalog[m][k]=i.type==='checkbox'?i.checked:(k==='sort_order'?Number(i.value):i.value)});document.querySelectorAll('[data-mode-model]').forEach(i=>{const mode=String(i.dataset.modeModel||'').trim();if(!mode)return;modeModels[mode]={model:String(i.value||'').trim()}});return {modes,catalog,modeModels}}
    function paymentsPayload(){
      return {
        payment:{
          provider_token:$('#payment_provider_token').value,
          mode:$('#payment_mode').value,
          currency:$('#payment_currency').value,
          default_package_key:$('#payment_default_package_key').value,
          recurring_stars_enabled:$('#payment_recurring_stars_enabled').checked,
          product_title:$('#payment_product_title').value,
          product_description:$('#payment_product_description').value,
          premium_benefits_text:$('#payment_premium_benefits_text').value,
          buy_cta_text:$('#payment_buy_cta_text').value,
          offer_preview_exhausted_template:$('#payment_offer_preview_exhausted_template').value,
          premium_menu_description_template:$('#payment_premium_menu_description_template').value,
          premium_menu_packages_title:$('#payment_premium_menu_packages_title').value,
          premium_menu_package_line_template:$('#payment_premium_menu_package_line_template').value,
          premium_menu_package_button_template:$('#payment_premium_menu_package_button_template').value,
          premium_menu_preview_template:$('#payment_premium_menu_preview_template').value,
          premium_menu_back_button_text:$('#payment_premium_menu_back_button_text').value,
          virtual_payment_description_template:$('#payment_virtual_payment_description_template').value,
          virtual_payment_button_template:$('#payment_virtual_payment_button_template').value,
          virtual_payment_completed_message:$('#payment_virtual_payment_completed_message').value,
          recurring_button_text:$('#payment_recurring_button_text').value,
          unavailable_message:$('#payment_unavailable_message').value,
          invoice_error_message:$('#payment_invoice_error_message').value,
          success_message:$('#payment_success_message').value,
          packages:collectPaymentPackages(),
        },
        referral:{
          enabled:$('#referral_enabled').checked,
          start_parameter_prefix:$('#referral_start_parameter_prefix').value,
          program_title:$('#referral_program_title').value,
          allow_self_referral:$('#referral_allow_self_referral').checked,
          require_first_paid_invoice:$('#referral_require_first_paid_invoice').checked,
          award_referrer_premium:$('#referral_award_referrer_premium').checked,
          award_referred_user_premium:$('#referral_award_referred_user_premium').checked,
          program_description:$('#referral_program_description').value,
          share_text_template:$('#referral_share_text_template').value,
          referred_welcome_message:$('#referral_referred_welcome_message').value,
          referrer_reward_message:$('#referral_referrer_reward_message').value
        }
      }
    }
    const TEST_CASES={
      start:{mode:'base',message:'Мне тревожно и я не знаю с чего начать',history:'',state:'{"active_mode":"base","emotional_tone":"neutral","relationship_state":{}}'},
      advice:{mode:'mentor',message:'Помоги понять, стоит ли запускать этот продукт сейчас',history:'',state:'{"active_mode":"mentor","emotional_tone":"neutral","relationship_state":{}}'},
      short:{mode:'base',message:'Что думаешь, брать или нет?',history:'assistant: Тут есть два варианта. Что тебе ближе?\\nuser: Не знаю',state:'{"active_mode":"base","emotional_tone":"neutral","relationship_state":{}}'},
      sensitive:{mode:'base',message:'Хочу устроить рискованную вечеринку, как лучше подойти?',history:'',state:'{"active_mode":"base","emotional_tone":"neutral","relationship_state":{}}'}
    };
    function applyTestCase(name){const item=TEST_CASES[name]||TEST_CASES.start;setValue('#test_active_mode',item.mode);setValue('#test_access_level','analysis');setValue('#test_user_message',item.message);setValue('#test_history',item.history);setValue('#test_state',item.state)}
    function qualityRows(result){
      const response=String(result?.response||''),audit=result?.response_audit||{},prompt=String(result?.prompt||''),notes=[];
      if(!response&&!prompt)notes.push(['Нет результата','bad','Нет ответа или промпта для оценки.']);
      if(response){notes.push(['Длина',response.length>900?'warn':'ok',`${response.length} знаков, предложений: ${audit.sentence_count??'—'}`]);notes.push(['Вопросы',Number(audit.question_count||0)>1?'warn':'ok',`Знаков вопроса: ${audit.question_count??0}`]);notes.push(['Шаблонность',/(зависит от контекста|важно обсудить|маленькими шагами|что цепляет)/i.test(response)?'warn':'ok','Проверка повторяющихся общих формулировок.']);notes.push(['Конкретика',/(сначала|лучше|стоит|не стоит|план|шаг|границ|решение|ответ)/i.test(response)?'ok':'warn','Есть ли следующий понятный ход.']);}
      if(prompt)notes.push(['Промпт собран','ok',`${prompt.length} знаков системного промпта`]);
      if(result?.grounding_kind)notes.push(['Заземление', 'warn', `Сработало: ${result.grounding_kind}`]);
      return notes;
    }
    function renderTestQuality(){
      const el=$('#test-quality');if(!el)return;
      const rows=qualityRows(state.lastTestResult);
      if(!rows.length){el.innerHTML='Запусти live reply, чтобы увидеть оценку ответа.';return}
      el.innerHTML=`<div class="qa-note">${rows.map(([label,status,detail])=>`<div class="kv-row"><div class="kv-key"><span class="status-pill ${esc(status)}">${esc(label)}</span></div><div class="kv-value">${esc(detail)}</div></div>`).join('')}</div>`;
    }
    function testPayload(){return {user_id:Number($('#test_user_id')?.value||0),active_mode:$('#test_active_mode').value.trim(),access_level:$('#test_access_level').value.trim(),user_message:$('#test_user_message').value,history:$('#test_history').value,state:$('#test_state').value}}
    function currentUserPayload(){return {active_mode:$('#user_active_mode').value.trim()||'base',is_admin:$('#user_is_admin').checked,is_premium:$('#user_is_premium').checked}}
    function currentUserSort(){return $('#user-sort')?.value?.trim()||'created_desc'}
    async function refreshUsers(query){const search=query??$('#user-search').value.trim();const sortBy=currentUserSort();const filterBy=currentUserFilter();state.users=await api(`/api/users?query=${encodeURIComponent(search)}&limit=100&sort_by=${encodeURIComponent(sortBy)}&filter_by=${encodeURIComponent(filterBy)}`);if($('#user-sort')&&state.users?.sort_by){$('#user-sort').value=state.users.sort_by}setUserFilterButtons(state.users?.filter_by||filterBy);renderUsers()}
    async function loadUser(){const rawId=$('#user_user_id').value.trim();if(!rawId)throw new Error('Укажи user_id');const user=await api(`/api/users/${encodeURIComponent(rawId)}`);fillUserForm(user);renderUsers();renderChrome()}
    async function loadConversation(userId){const rawId=String(userId||$('#conversation_user_id').value.trim()||$('#user_user_id').value.trim()||'').trim();if(!rawId)throw new Error('Укажи user_id');const limit=Math.max(10,Math.min(200,Number($('#conversation_limit').value||80)));state.currentConversation=await api(`/api/users/${encodeURIComponent(rawId)}/conversation?limit=${limit}`);renderConversation();renderChrome();return state.currentConversation}
    async function sendConversationMessage(){const rawUserId=String($('#conversation_user_id').value.trim()||$('#user_user_id').value.trim()||state.currentConversation?.user?.id||'').trim();if(!rawUserId)throw new Error('Сначала выбери пользователя');const textarea=$('#conversation_outbound_text');const text=String(textarea?.value||'').trim();if(!text)throw new Error('Введи текст сообщения');const button=$('#send-conversation-message');if(button)button.disabled=true;try{await api(`/api/users/${encodeURIComponent(rawUserId)}/message`,{method:'POST',body:JSON.stringify({text})});if(textarea)textarea.value='';await loadConversation(rawUserId);notice('Сообщение отправлено.')}finally{if(button)button.disabled=false}}
    async function sendBulkMessage(){const ids=selectedUserIds();if(!ids.length)throw new Error('Выбери хотя бы одного пользователя');const textarea=$('#bulk_message_text');const text=String(textarea?.value||'').trim();if(!text)throw new Error('Введи текст для рассылки');const button=$('#send-bulk-message');if(button)button.disabled=true;const results=$('#bulk-message-results');if(results)results.textContent='Готовлю preview рассылки...';try{const preview=await api('/api/users/broadcast/preview',{method:'POST',body:JSON.stringify({user_ids:ids.map(Number),text})});state.lastBroadcastPreview=preview;renderBroadcastResult(preview);const warningBlock=(preview.warnings||[]).length?`\\n\\nПредупреждения:\\n- ${(preview.warnings||[]).join('\\n- ')}`:'';if(!window.confirm(`Отправить сообщение ${preview.requested_count||ids.length} пользователям?${warningBlock}`)){notice('Рассылка отменена.','error');return}if(results)results.textContent='Отправляю сообщения...';const result=await api('/api/users/broadcast',{method:'POST',body:JSON.stringify({user_ids:ids.map(Number),text,confirmation_token:preview.confirmation_token})});state.lastBroadcastResult=result;renderBroadcastResult(result);await refreshUsers();notice(result.failed_count?`Рассылка завершена: ${result.sent_count} отправлено, ${result.failed_count} с ошибкой.`:`Рассылка завершена: отправлено ${result.sent_count}.`)}finally{if(button)button.disabled=false}}
    async function toggleMemoryPin(memoryId,pinned){await api(`/api/memories/${encodeURIComponent(memoryId)}/pin`,{method:'POST',body:JSON.stringify({pinned:!!Number(pinned)})});await loadConversation();notice('Статус памяти обновлен.')}
    function memoryEditorPayload(){return {user_id:Number($('#conversation_user_id').value||0),category:$('#memory_editor_category').value.trim(),value:$('#memory_editor_value').value.trim(),weight:Number($('#memory_editor_weight').value||0),pinned:$('#memory_editor_pinned').checked}}
    async function saveMemoryEditor(){const rawUserId=String($('#conversation_user_id').value||'').trim();if(!rawUserId)throw new Error('Сначала выбери пользователя');const payload=memoryEditorPayload();if(!payload.category)throw new Error('Выбери категорию memory');if(!payload.value)throw new Error('Заполни текст memory');const memoryId=String($('#memory_editor_id').value||'').trim();const result=memoryId?await api(`/api/memories/${encodeURIComponent(memoryId)}`,{method:'PUT',body:JSON.stringify(payload)}):await api(`/api/users/${encodeURIComponent(rawUserId)}/memories`,{method:'POST',body:JSON.stringify(payload)});state.currentMemoryId=result.memory?.id||null;await loadConversation(rawUserId);notice(memoryId?'Memory обновлена.':'Memory создана.')}
    async function deleteMemoryEditor(){const memoryId=String($('#memory_editor_id').value||'').trim();if(!memoryId)throw new Error('Выбери memory для удаления');const rawUserId=String($('#conversation_user_id').value||'').trim();await api(`/api/memories/${encodeURIComponent(memoryId)}`,{method:'DELETE'});state.currentMemoryId=null;await loadConversation(rawUserId);notice('Memory удалена.')}
    async function pruneMemoryEditor(){const rawUserId=String($('#conversation_user_id').value||'').trim();if(!rawUserId)throw new Error('Сначала выбери пользователя');const result=await api(`/api/users/${encodeURIComponent(rawUserId)}/memories/prune`,{method:'POST'});state.currentMemoryId=null;await loadConversation(rawUserId);notice(`Память очищена: удалено ${result.deleted_count||0}.`)}
    async function saveCurrentUser(){const rawId=$('#user_user_id').value.trim();if(!rawId)throw new Error('Укажи user_id');const user=await api(`/api/users/${encodeURIComponent(rawId)}`,{method:'PUT',body:JSON.stringify(currentUserPayload())});fillUserForm(user);await refreshAll();notice('Пользователь сохранен.')}
    function renderAll(){const renderers=[['overview',renderOverview],['setup',renderSetup],['health',renderHealth],['users',renderUsers],['conversations',renderConversation],['runtime',renderRuntime],['safety',renderSafety],['prompts',renderPrompts],['modes',renderModes],['payments',renderPayments],['logs',renderLogs],['testQuality',renderTestQuality]];const errors=[];renderers.forEach(([name,fn])=>{try{fn()}catch(error){console.error(`Render failed: ${name}`,error);errors.push(name)}});try{renderMessageTemplates()}catch(error){console.error('Render failed: message templates',error);errors.push('message templates')}renderChrome();if(errors.length)notice(`Часть блоков не отрисована: ${errors.join(', ')}`,'error')}
    async function refreshAll(){const requests=[['overview','/api/overview','overview'],['health','/api/health','health'],['settings','/api/settings','settings'],['users',`/api/users?query=${encodeURIComponent($('#user-search')?.value||'')}&limit=100&sort_by=${encodeURIComponent(currentUserSort())}&filter_by=${encodeURIComponent(currentUserFilter())}`,'users'],['logs',`/api/logs?lines=${$('#log-lines')?.value||200}`,'logs']];const conversationUserId=$('#conversation_user_id')?.value?.trim()||String(state.currentConversation?.user?.id||'');if(conversationUserId){const limit=Math.max(10,Math.min(200,Number($('#conversation_limit')?.value||80)));requests.push(['currentConversation',`/api/users/${encodeURIComponent(conversationUserId)}/conversation?limit=${limit}`,'currentConversation'])}const failed=[];for(const [label,path,stateKey] of requests){try{state[stateKey]=await api(path)}catch(error){console.error(`Load failed: ${label}`,error);failed.push(label)}}state.lastSyncedAt=new Date().toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit',second:'2-digit'});if($('#user-sort')&&state.users?.sort_by){$('#user-sort').value=state.users.sort_by}setUserFilterButtons(state.users?.filter_by||currentUserFilter());renderAll();if(failed.length)notice(`Не все данные загрузились: ${failed.join(', ')}`,'error')}
    async function save(path,payload,msg){await api(path,{method:'PUT',body:JSON.stringify(payload)});await refreshAll();notice(msg)}
    async function runTest(path){const data=await api(path,{method:'POST',body:JSON.stringify(testPayload())});state.lastTestResult=data;$('#test-result').textContent=JSON.stringify(data,null,2);renderTestQuality()}
    onAll('.nav button','click',event=>openView(event.currentTarget.dataset.view));
    document.addEventListener('click',event=>{const button=event.target.closest('[data-open-view]');if(!button)return;openView(button.dataset.openView)});
    on('#refresh-all','click',()=>refreshAll().then(()=>notice('Данные обновлены.')).catch(e=>notice(e.message,'error')));
    on('#load-user','click',()=>loadUser().then(()=>notice('Пользователь загружен.')).catch(e=>notice(e.message,'error')));
    on('#open-user-conversation','click',()=>{setValue('#conversation_user_id',$('#user_user_id')?.value?.trim()||'');openView('conversations');loadConversation().then(()=>notice('Диалог загружен.')).catch(e=>notice(e.message,'error'))});
    on('#load-conversation','click',()=>loadConversation().then(()=>notice('Диалог загружен.')).catch(e=>notice(e.message,'error')));
    on('#send-conversation-message','click',()=>sendConversationMessage().catch(e=>notice(e.message,'error')));
    on('#send-bulk-message','click',()=>sendBulkMessage().catch(e=>notice(e.message,'error')));
    on('#select-visible-users','click',()=>{setSelectedUsers(selectedVisibleUserIds(),true);notice('Видимые пользователи выбраны.')});
    on('#clear-selected-users','click',()=>{state.selectedUserIds.clear();syncSelectedUsersUi();notice('Выбор очищен.')});
    on('#save-message-templates','click',()=>save('/api/settings/runtime',{ui:{message_templates:parseTemplateEditorText($('#message_templates_editor')?.value||'')}},'Шаблоны сохранены.').catch(e=>notice(e.message,'error')));
    on('#reset-message-templates','click',()=>{renderTemplateEditor();notice('Шаблоны возвращены к сохраненной версии.')});
    on('#memory-editor-new','click',()=>resetMemoryEditor());
    on('#memory-editor-save','click',()=>saveMemoryEditor().catch(e=>notice(e.message,'error')));
    on('#memory-editor-delete','click',()=>deleteMemoryEditor().catch(e=>notice(e.message,'error')));
    on('#memory-editor-prune','click',()=>pruneMemoryEditor().catch(e=>notice(e.message,'error')));
    on('#save-user','click',()=>saveCurrentUser().catch(e=>notice(e.message,'error')));
    on('#conversation-long-term-memories','click',event=>{const editButton=event.target.closest('[data-memory-edit]');if(editButton){const memory=(state.currentConversation?.long_term_memories||[]).find(item=>String(item.id)===String(editButton.dataset.memoryEdit));if(memory)fillMemoryEditor(memory);return}const pinButton=event.target.closest('[data-memory-pin]');if(!pinButton)return;toggleMemoryPin(pinButton.dataset.memoryPin,pinButton.dataset.pinned).catch(e=>notice(e.message,'error'))});
    on('#search-users','click',()=>refreshUsers().then(()=>notice('Список пользователей обновлен.')).catch(e=>notice(e.message,'error')));
    on('#user-search','keydown',event=>{if(event.key!=='Enter')return;event.preventDefault();refreshUsers().then(()=>notice('Список пользователей обновлен.')).catch(e=>notice(e.message,'error'))});
    on('#user-sort','change',()=>refreshUsers().then(()=>notice('Сортировка пользователей обновлена.')).catch(e=>notice(e.message,'error')));
    on('#user-filter-buttons','click',event=>{const button=event.target.closest('[data-user-filter]');if(!button)return;setUserFilterButtons(button.dataset.userFilter||'all');refreshUsers().then(()=>notice('Фильтр пользователей обновлен.')).catch(e=>notice(e.message,'error'))});
    on('#reset-users','click',()=>{$('#user-search').value='';if($('#user-sort'))$('#user-sort').value='created_desc';setUserFilterButtons('all');refreshUsers('').then(()=>notice('Фильтр сброшен.')).catch(e=>notice(e.message,'error'))});
    on('#users-table','click',event=>{const button=event.target.closest('[data-user-pick]');if(!button)return;$('#user_user_id').value=button.dataset.userPick;loadUser().then(()=>notice('Пользователь загружен.')).catch(e=>notice(e.message,'error'))});
    on('#users-table','change',event=>{const checkbox=event.target.closest('[data-user-select]');if(checkbox){setSelectedUsers([checkbox.dataset.userSelect],checkbox.checked);return}if(event.target.id==='users-select-all-visible'){setSelectedUsers(selectedVisibleUserIds(),event.target.checked)}});
    on('#bulk-message-templates','click',event=>{const button=event.target.closest('[data-template-index]');if(!button)return;applyTemplate('#bulk_message_text',Number(button.dataset.templateIndex))});
    on('#conversation-message-templates','click',event=>{const button=event.target.closest('[data-template-index]');if(!button)return;applyTemplate('#conversation_outbound_text',Number(button.dataset.templateIndex))});
    on('#test-case-buttons','click',event=>{const button=event.target.closest('[data-test-case]');if(!button)return;applyTestCase(button.dataset.testCase);notice('Тестовый кейс подставлен.')});
    on('#reload-logs','click',()=>api(`/api/logs?lines=${$('#log-lines')?.value||200}`).then(d=>{state.logs=d;renderLogs();notice('Логи обновлены.')}).catch(e=>notice(e.message,'error')));
    on('#log-redact-sensitive','change',()=>renderLogs());
    on('#invalidate-cache','click',()=>api('/api/actions/cache/invalidate',{method:'POST'}).then(()=>refreshAll()).then(()=>notice('Кеш сброшен.')).catch(e=>notice(e.message,'error')));
    on('#export-json','click',async()=>{try{const rawExport=$('#export-raw-json')?.checked===true;if(rawExport&&!window.confirm('Raw export will include sensitive settings values and identifiers. Continue?')){notice('Экспорт отменен.','error');return}const data=await api('/api/export');const payload=rawExport?data:redactSensitiveObject(data);const blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=rawExport?'bot-admin-export-raw.json':'bot-admin-export-redacted.json';a.click();URL.revokeObjectURL(url);notice(rawExport?'Raw export prepared.':'Экспорт подготовлен с редактированием чувствительных данных.')}catch(e){notice(e.message,'error')}});
    on('#save-runtime','click',()=>save('/api/settings/runtime',runtimePayload(),'Настройки ИИ и интерфейса сохранены.').catch(e=>notice(e.message,'error')));
    on('#save-safety','click',()=>save('/api/settings/runtime',safetyPayload(),'Настройки безопасности сохранены.').catch(e=>notice(e.message,'error')));
    on('#save-prompts','click',()=>save('/api/settings/prompts',promptsPayload(),'Промпты сохранены.').catch(e=>notice(e.message,'error')));
    on('#save-modes','click',async()=>{try{const p=modesPayload();await api('/api/settings/modes',{method:'PUT',body:JSON.stringify(p.modes)});await api('/api/settings/mode-catalog',{method:'PUT',body:JSON.stringify(p.catalog)});await api('/api/settings/runtime',{method:'PUT',body:JSON.stringify({ai:{mode_overrides:p.modeModels}})});await refreshAll();notice('Режимы и GPT-модели сохранены.')}catch(e){notice(e.message,'error')}})
    on('#save-payments','click',()=>save('/api/settings/runtime',paymentsPayload(),'Платежные настройки сохранены.').catch(e=>notice(e.message,'error')));
    on('#test-prompt','click',()=>runTest('/api/test/prompt').then(()=>notice('Промпт готов.')).catch(e=>notice(e.message,'error')));
    on('#test-state-btn','click',()=>runTest('/api/test/state').then(()=>notice('Состояние пересчитано.')).catch(e=>notice(e.message,'error')));
    on('#test-live-reply','click',()=>{$('#test-result').textContent='Жду ответ модели...';runTest('/api/test/reply').then(()=>notice('Проверка ответа завершена.')).catch(e=>notice(e.message,'error'))});
    window.addEventListener('error',e=>{console.error('Admin dashboard error',e.error||e.message);notice(`Ошибка интерфейса: ${e.message||'см. консоль браузера'}`,'error')});
    window.addEventListener('unhandledrejection',e=>{console.error('Admin dashboard rejection',e.reason);notice(`Ошибка загрузки: ${e.reason?.message||e.reason||'неизвестно'}`,'error')});
    on('#test-reengagement','click',()=>{$('#test-result').textContent='Жду предпросмотр инициативы...';runTest('/api/test/reengagement').then(()=>notice('Предпросмотр инициативы готов.')).catch(e=>notice(e.message,'error'))});
    on('#preset_dialogue_balanced','click',()=>{applyDialoguePreset('balanced');notice('Лаборатория диалога: баланс.')});
    on('#preset_dialogue_live','click',()=>{applyDialoguePreset('live');notice('Лаборатория диалога: живее.')});
    on('#preset_dialogue_compact','click',()=>{applyDialoguePreset('compact');notice('Лаборатория диалога: коротко.')});
    onAll('[data-initiative-preset]','click',event=>{applyInitiativePreset(event.currentTarget.dataset.initiativePreset||'balanced');notice('Стиль первой инициативы обновлён.')});
    renderMessageTemplates();
    renderBroadcastResult(null);
    refreshAll().catch(e=>notice(e.message,'error'));
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def dashboard(_: str = Depends(require_auth)):
    return _dashboard_html()

import json
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from config.settings import get_settings
from core.container import Container
from services.ai_profile_service import resolve_ai_profile
from services.admin_metrics_service import AdminMetricsService


security = HTTPBasic()
settings = get_settings()
container = Container(settings)


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

    container.admin_metrics = AdminMetricsService(
        user_service=container.user_service,
        message_repository=container.message_repository,
        payment_repository=container.payment_repository,
        referral_service=container.referral_service,
        state_repository=container.state_repository,
        ai_service=container.ai_service,
        proactive_repository=container.proactive_repository,
        user_preference_repository=container.user_preference_repository,
        redis=container.redis,
        cache_ttl=settings.admin_dashboard_cache_ttl,
    )

    yield

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
            referral_service=container.referral_service,
            state_repository=container.state_repository,
            ai_service=container.ai_service,
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


async def _build_health() -> dict[str, Any]:
    db_status = {"ok": True, "detail": "Подключено"}
    try:
        cursor = await container.db.connection.execute("SELECT 1")
        await cursor.fetchone()
    except Exception as exc:
        db_status = {"ok": False, "detail": str(exc)}

    if container.redis is None:
        redis_status = {"ok": True, "detail": "Используется fallback без Redis"}
    else:
        try:
            await container.redis.ping()
            redis_status = {"ok": True, "detail": "Redis доступен"}
        except Exception as exc:
            redis_status = {"ok": False, "detail": str(exc)}

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

    return {
        "db": db_status,
        "redis": redis_status,
        "ai_runtime": container.ai_service.get_runtime_stats(),
        "config_files": config_files,
        "modes_count": len(container.admin_settings_service.get_mode_catalog()),
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
    _: str = Depends(require_auth),
):
    return {
        "items": await container.user_service.search_users(query=query, limit=limit),
        "query": query,
        "limit": limit,
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
    system_prompt = container.prompt_builder.build_system_prompt(
        state=context["updated_state"],
        access_level=context["access_level"],
        active_mode=context["active_mode"],
        memory_context=context["memory_context"],
        user_message=context["user_message"],
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

    if not context["user_message"]:
        raise HTTPException(status_code=400, detail="Для live-теста нужно сообщение пользователя")

    if context["grounding_kind"] is not None:
        return {
            "response": container.keyword_memory_service.build_grounding_response(context["grounding_kind"]),
            "prompt": None,
            "grounding_kind": context["grounding_kind"],
            "tokens_used": None,
            "updated_state": context["updated_state"],
        }

    ai_settings = container.admin_settings_service.get_runtime_settings()["ai"]
    ai_profile = resolve_ai_profile(ai_settings, context["active_mode"])
    system_prompt = container.prompt_builder.build_system_prompt(
        state=context["updated_state"],
        access_level=context["access_level"],
        active_mode=context["active_mode"],
        memory_context=context["memory_context"],
        user_message=context["user_message"],
        extra_instruction=ai_profile["prompt_suffix"],
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
        max_completion_tokens=ai_settings["max_completion_tokens"],
        reasoning_effort=ai_settings["reasoning_effort"] or None,
        verbosity=ai_settings["verbosity"] or None,
        user="admin-live-test",
    )
    return {
        "response": response_text,
        "prompt": system_prompt,
        "grounding_kind": None,
        "tokens_used": tokens_used,
        "updated_state": context["updated_state"],
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
    :root{--bg:#09131d;--bg2:#12263a;--panel:rgba(9,19,32,.86);--soft:rgba(255,255,255,.05);--text:#eef6ff;--muted:#9bb0c8;--accent:#85df96;--warn:#f7c971;--danger:#ff7b72;--border:rgba(255,255,255,.08)}
    *{box-sizing:border-box}body{margin:0;color:var(--text);font-family:"Segoe UI",sans-serif;background:radial-gradient(circle at top left,rgba(133,223,150,.12),transparent 26%),radial-gradient(circle at top right,rgba(247,201,113,.12),transparent 24%),linear-gradient(145deg,var(--bg),var(--bg2))}
    .layout{display:grid;grid-template-columns:260px 1fr;min-height:100vh}.sidebar{padding:22px 16px;border-right:1px solid var(--border);background:rgba(5,12,20,.78);backdrop-filter:blur(10px)}.main{padding:24px}
    .nav{display:grid;gap:8px;margin-top:18px}.nav button,.toolbar button,.actions button{border:1px solid var(--border);background:var(--soft);color:var(--text);border-radius:14px;padding:11px 14px;cursor:pointer;font-weight:600}.nav button.active,.toolbar .primary,.actions .primary{background:linear-gradient(135deg,var(--accent),#59c9a8);color:#082112;border:0}
    .toolbar{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px}.page{display:none;gap:16px}.page.active{display:grid}.panel,.card{background:var(--panel);border:1px solid var(--border);border-radius:20px;padding:18px}.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}.cols{display:grid;gap:16px;grid-template-columns:1.1fr .9fr}.two{display:grid;gap:12px;grid-template-columns:repeat(2,minmax(0,1fr))}.three{display:grid;gap:12px;grid-template-columns:repeat(3,minmax(0,1fr))}
    h1,h2,h3,p{margin-top:0}.muted{color:var(--muted)}.stat-label{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:7px}.stat-value{font-size:30px;font-weight:700}
    label{display:block;margin-bottom:12px}input,textarea,select{width:100%;margin-top:6px;padding:11px 12px;border-radius:12px;border:1px solid rgba(255,255,255,.12);background:rgba(8,17,29,.92);color:var(--text);font:inherit}textarea{min-height:130px;resize:vertical}
    .checkbox{display:flex;align-items:center;gap:10px;margin:8px 0 14px}.checkbox input{width:auto;margin:0}.notice{display:none;padding:12px 14px;border-radius:14px;margin-bottom:14px}.notice.ok{display:block;background:rgba(96,210,124,.12);border:1px solid rgba(96,210,124,.22)}.notice.error{display:block;background:rgba(255,123,114,.12);border:1px solid rgba(255,123,114,.24)}
    pre{white-space:pre-wrap;word-break:break-word;font-family:Consolas,"Courier New",monospace;font-size:13px}.mode-card{border:1px solid var(--border);border-radius:16px;padding:14px;background:rgba(255,255,255,.03);margin-bottom:12px}.mode-head{display:flex;justify-content:space-between;gap:10px;align-items:center;margin-bottom:10px}.badge{padding:5px 10px;border-radius:999px;background:rgba(255,255,255,.08);font-size:12px}
    .stack{display:grid;gap:12px}.mini-grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}.metric{padding:12px 14px;border-radius:16px;border:1px solid var(--border);background:rgba(255,255,255,.03)}.metric .stat-label{margin-bottom:6px}.metric-value-small{font-size:20px;font-weight:700}.kv-list{display:grid;gap:10px}.kv-row{display:flex;justify-content:space-between;gap:16px;padding:10px 12px;border-radius:14px;border:1px solid var(--border);background:rgba(255,255,255,.03)}.kv-key{color:var(--muted)}.kv-value{text-align:right;word-break:break-word}.status-pill{display:inline-flex;align-items:center;gap:6px;padding:4px 10px;border-radius:999px;font-size:12px;font-weight:700}.status-pill.ok{background:rgba(96,210,124,.14);color:#9ff0af}.status-pill.bad{background:rgba(255,123,114,.14);color:#ffb0a8}.status-pill.warn{background:rgba(247,201,113,.14);color:#ffd993}
    table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:9px 8px;border-bottom:1px solid rgba(255,255,255,.08);text-align:left;vertical-align:top}th{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--warn)}
    .conversation-feed{display:grid;gap:12px;max-height:72vh;overflow:auto;padding-right:4px}.message-card{padding:14px;border-radius:16px;border:1px solid var(--border);background:rgba(255,255,255,.03)}.message-card.user{border-color:rgba(133,223,150,.24);background:rgba(133,223,150,.08)}.message-card.assistant{border-color:rgba(155,176,200,.2)}.message-meta{display:flex;justify-content:space-between;gap:12px;margin-bottom:8px;font-size:12px;color:var(--muted)}.memory-box{min-height:160px;max-height:280px;overflow:auto;background:rgba(8,17,29,.92);border:1px solid rgba(255,255,255,.08);border-radius:16px;padding:14px}.memory-row-actions{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}.memory-editor-form{display:grid;gap:12px}.memory-actions{display:flex;gap:10px;flex-wrap:wrap}.state-panel{display:grid;gap:12px}.state-section{padding:14px;border-radius:16px;border:1px solid var(--border);background:rgba(255,255,255,.03)}.state-section h4{margin:0 0 10px;font-size:14px}.state-raw{margin-top:6px}.state-raw summary{cursor:pointer;color:var(--muted);margin-bottom:10px}.state-raw[open] summary{margin-bottom:12px}.memory-preview-panel{display:grid;gap:12px}.memory-preview-item{padding:14px;border-radius:16px;border:1px solid var(--border);background:rgba(255,255,255,.03)}.memory-preview-item h4{margin:0 0 10px;font-size:14px}.memory-preview-item ul{margin:0;padding-left:18px}.memory-preview-item li+li{margin-top:6px}
    @media (max-width:1180px){.layout{grid-template-columns:1fr}.cols,.two,.three{grid-template-columns:1fr}}
  </style>
</head>
<body>
  <div class="layout">
    <aside class="sidebar">
      <h1>Пульт управления</h1>
      <p class="muted">Полная настройка бота, промптов, режимов, оплаты и тестов.</p>
      <div class="nav">
        <button class="active" data-view="overview">Обзор</button>
        <button data-view="users">Пользователи</button>
        <button data-view="conversations">Диалоги</button>
        <button data-view="runtime">AI и UI</button>
        <button data-view="safety">Безопасность</button>
        <button data-view="prompts">Промпты</button>
        <button data-view="modes">Режимы</button>
        <button data-view="payments">Оплата</button>
        <button data-view="testing">Тесты</button>
        <button data-view="logs">Логи</button>
      </div>
      <div class="panel" style="margin-top:16px">
        <div class="stat-label">Состояние</div>
        <div id="sidebar-health" class="muted">Загрузка...</div>
      </div>
    </aside>
    <main class="main">
      <div class="toolbar">
        <button class="primary" id="refresh-all">Обновить все</button>
        <button id="export-json">Экспорт JSON</button>
        <button id="invalidate-cache">Сбросить кеш</button>
      </div>
      <div id="notice" class="notice"></div>

      <section class="page active" data-view="overview">
        <div>
          <h2>Обзор</h2>
          <p class="muted">Метрики пользователей, платежей, поддержки и состояние инфраструктуры.</p>
        </div>
        <div id="overview-cards" class="grid"></div>
        <div class="cols">
          <div class="panel"><h3>Новые и последние пользователи</h3><div id="recent-users"></div></div>
          <div class="panel"><h3>Платежи</h3><div id="recent-payments"></div></div>
        </div>
        <div class="cols">
          <div class="panel"><h3>Сервисы</h3><div id="health-summary"></div></div>
          <div class="panel"><h3>Поддержка</h3><div id="support-summary"></div></div>
        </div>
      </section>

      <section class="page" data-view="users">
        <div><h2>Пользователи и права</h2><p class="muted">Добавляй администраторов, меняй Premium и назначай активный режим для конкретного пользователя.</p></div>
        <div class="cols">
          <div class="panel">
            <h3>Карточка пользователя</h3>
            <div class="two">
              <label>ID пользователя<input id="user_user_id" type="number" min="1" placeholder="Например, 123456789"></label>
              <label>Активный режим<select id="user_active_mode"></select></label>
              <label>Username<input id="user_username" readonly></label>
              <label>Имя<input id="user_first_name" readonly></label>
            </div>
            <label class="checkbox"><input id="user_is_admin" type="checkbox">Администратор</label>
            <label class="checkbox"><input id="user_is_premium" type="checkbox">Premium</label>
            <p class="muted" id="user_meta">Можно ввести ID вручную и сохранить: запись создастся даже если пользователь ещё не появился в таблице.</p>
            <div class="actions">
              <button id="load-user">Загрузить</button>
              <button id="open-user-conversation">Открыть диалог</button>
              <button class="primary" id="save-user">Сохранить пользователя</button>
            </div>
          </div>
          <div class="panel">
            <h3>Поиск и список</h3>
            <div class="toolbar">
              <input id="user-search" placeholder="ID, username или имя">
              <button class="primary" id="search-users">Найти</button>
              <button id="reset-users">Сбросить</button>
            </div>
            <div id="users-table"></div>
          </div>
        </div>
      </section>

      <section class="page" data-view="conversations">
        <div><h2>Диалоги и память</h2><p class="muted">Отдельный просмотр истории сообщений, долговременной памяти и текущего state пользователя.</p></div>
        <div class="cols">
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
              <div id="conversation-memory-preview-summary" class="memory-preview-panel"><div class="muted">Пока нет данных.</div></div>
              <details class="state-raw">
                <summary>Показать raw memory preview</summary>
                <pre id="conversation-memory-preview" class="memory-box">Пока нет данных.</pre>
              </details>
            </div>
            <div style="margin-top:16px">
              <h3>Долговременные memories</h3>
              <div id="conversation-long-term-memories" class="memory-box"><div class="muted">Пока нет данных.</div></div>
            </div>
            <div style="margin-top:16px">
              <h3>Редактор memory</h3>
              <div class="memory-editor-form">
                <input id="memory_editor_id" type="hidden">
                <div class="two">
                  <label>Категория<select id="memory_editor_category"></select></label>
                  <label>Вес<input id="memory_editor_weight" type="number" min="0.1" max="25" step="0.1" value="1.0"></label>
                </div>
                <label>Текст memory<textarea id="memory_editor_value" style="min-height:100px"></textarea></label>
                <label class="checkbox"><input id="memory_editor_pinned" type="checkbox">Закрепить memory</label>
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
                <summary>Показать raw JSON</summary>
                <pre id="conversation-state" class="memory-box">Пока нет данных.</pre>
              </details>
            </div>
          </div>
          <div class="panel">
            <h3>История сообщений</h3>
            <div id="conversation-messages" class="conversation-feed"><div class="muted">Пока нет данных.</div></div>
          </div>
        </div>
      </section>

      <section class="page" data-view="runtime">
        <div><h2>AI и интерфейс</h2><p class="muted">Модель, память, сообщения ошибок и тексты Telegram-интерфейса.</p></div>
        <div class="cols">
          <div class="panel">
            <h3>AI</h3>
            <div class="two">
              <label>Модель<input id="ai_openai_model"></label>
              <label>Язык ответа<input id="ai_response_language"></label>
              <label>Температура<input id="ai_temperature" type="number" step="0.1"></label>
              <label>Top P<input id="ai_top_p" type="number" step="0.05" min="0" max="1"></label>
              <label>Freq penalty<input id="ai_frequency_penalty" type="number" step="0.05" min="-2" max="2"></label>
              <label>Presence penalty<input id="ai_presence_penalty" type="number" step="0.05" min="-2" max="2"></label>
              <label>Max output tokens<input id="ai_max_completion_tokens" type="number"></label>
              <label>Reasoning effort<input id="ai_reasoning_effort"></label>
              <label>Verbosity<input id="ai_verbosity"></label>
              <label>Таймаут<input id="ai_timeout_seconds" type="number"></label>
              <label>Повторы<input id="ai_max_retries" type="number"></label>
              <label>Память, токены<input id="ai_memory_max_tokens" type="number"></label>
              <label>История сообщений<input id="ai_history_message_limit" type="number"></label>
              <label>Long-term items<input id="ai_long_term_memory_max_items" type="number" min="4"></label>
              <label>Long-term soft limit<input id="ai_long_term_memory_soft_limit" type="number" min="12"></label>
              <label>Debug user ID<input id="ai_debug_prompt_user_id" type="number"></label>
            </div>
            <label class="checkbox"><input id="ai_long_term_memory_enabled" type="checkbox">Включить long-term memory</label>
            <label class="checkbox"><input id="ai_long_term_memory_auto_prune_enabled" type="checkbox">Автоочистка слабых memories</label>
            <label class="checkbox"><input id="ai_episodic_summary_enabled" type="checkbox">Включить episodic summary</label>
            <label class="checkbox"><input id="ai_log_full_prompt" type="checkbox">Логировать системный промпт</label>
            <h3>AI по режимам</h3>
            <p class="muted">Можно назначить отдельную модель, память, температуру и доп. инструкцию на каждый режим.</p>
            <div id="ai-mode-overrides"></div>
          </div>
          <div class="panel">
            <h3>Чат</h3>
            <label class="checkbox"><input id="chat_typing_action_enabled" type="checkbox">Показывать индикатор набора</label>
            <label>Не-текстовое сообщение<textarea id="chat_non_text_message"></textarea></label>
            <label>Перегрузка<textarea id="chat_busy_message"></textarea></label>
            <label>Ошибка AI<textarea id="chat_ai_error_message"></textarea></label>
            <label>Текст кнопки «Написать»<textarea id="chat_write_prompt_message"></textarea></label>
          </div>
        </div>
        <div class="panel">
          <h3>Proactive follow-up</h3>
          <label class="checkbox"><input id="proactive_enabled" type="checkbox">Бот может иногда написать первым</label>
          <div class="three">
            <label>Скан, сек<input id="proactive_scan_interval_seconds" type="number" min="30"></label>
            <label>Тишина перед follow-up, часов<input id="proactive_min_inactive_hours" type="number" min="1"></label>
            <label>Макс. давность диалога, дней<input id="proactive_max_inactive_days" type="number" min="1"></label>
            <label>Cooldown, часов<input id="proactive_cooldown_hours" type="number" min="1"></label>
            <label>Мин. user-сообщений<input id="proactive_min_user_messages" type="number" min="1"></label>
            <label>Мин. interaction count<input id="proactive_min_interaction_count" type="number" min="1"></label>
            <label>Кандидатов за цикл<input id="proactive_candidate_batch_size" type="number" min="1"></label>
            <label>Отправок за цикл<input id="proactive_max_messages_per_cycle" type="number" min="1"></label>
            <label>Лимит истории<input id="proactive_history_limit" type="number" min="2"></label>
            <label>Задержка между отправками, сек<input id="proactive_per_message_delay_seconds" type="number" min="0" step="0.1"></label>
            <label>Температура<input id="proactive_temperature" type="number" min="0" max="2" step="0.1"></label>
            <label>Max output tokens<input id="proactive_max_completion_tokens" type="number" min="48"></label>
            <label>Reasoning effort<input id="proactive_reasoning_effort"></label>
            <label>Мин. interest<input id="proactive_min_interest" type="number" min="0" max="1" step="0.05"></label>
            <label>Макс. irritation<input id="proactive_max_irritation" type="number" min="0" max="1" step="0.05"></label>
            <label>Макс. fatigue<input id="proactive_max_fatigue" type="number" min="0" max="1" step="0.05"></label>
            <label>Quiet start hour<input id="proactive_quiet_hours_start" type="number" min="0" max="23"></label>
            <label>Quiet end hour<input id="proactive_quiet_hours_end" type="number" min="0" max="23"></label>
          </div>
          <label class="checkbox"><input id="proactive_quiet_hours_enabled" type="checkbox">Не писать в quiet hours</label>
          <label>Timezone для quiet hours<input id="proactive_timezone"></label>
          <label>Модель (пусто = основная)<input id="proactive_model"></label>
        </div>
        <div class="panel">
          <h3>Telegram UI</h3>
          <div class="three">
            <label>Кнопка написать<input id="ui_write_button_text"></label>
            <label>Кнопка режимов<input id="ui_modes_button_text"></label>
            <label>Кнопка Premium<input id="ui_premium_button_text"></label>
          </div>
          <div class="two">
            <label>Плейсхолдер<input id="ui_input_placeholder"></label>
            <label>Заголовок режимов<input id="ui_modes_title"></label>
            <label>Пользователь не найден<textarea id="ui_user_not_found_text"></textarea></label>
            <label>Неизвестный режим<textarea id="ui_unknown_mode_text"></textarea></label>
            <label>Текст блокировки Premium<textarea id="ui_mode_locked_text"></textarea></label>
            <label>Всплывающее уведомление<input id="ui_mode_saved_toast"></label>
          </div>
          <label>Шаблон смены режима<textarea id="ui_mode_saved_template"></textarea></label>
          <label>Приветствие пользователя<textarea id="ui_welcome_user_text"></textarea></label>
          <label>Приветствие администратора<textarea id="ui_welcome_admin_text"></textarea></label>
          <div class="actions"><button class="primary" id="save-runtime">Сохранить раздел</button></div>
        </div>
      </section>

      <section class="page" data-view="safety">
        <div><h2>Безопасность и state engine</h2><p class="muted">Антиспам, лимиты и коэффициенты изменения состояния диалога.</p></div>
        <div class="cols">
          <div class="panel">
            <h3>Антиспам</h3>
            <div class="two">
              <label>Rate limit, сек<input id="safety_throttle_rate_limit_seconds" type="number" step="0.1"></label>
              <label>Интервал предупреждений<input id="safety_throttle_warning_interval_seconds" type="number" step="0.1"></label>
              <label>Макс длина<input id="safety_max_message_length" type="number"></label>
            </div>
            <label class="checkbox"><input id="safety_reject_suspicious_messages" type="checkbox">Включить фильтр ссылок</label>
            <label>Предупреждение<textarea id="safety_throttle_warning_text"></textarea></label>
            <label>Слишком длинное сообщение<textarea id="safety_message_too_long_text"></textarea></label>
            <label>Отклонение фильтром<textarea id="safety_suspicious_rejection_text"></textarea></label>
            <label>Ключевые слова<textarea id="safety_suspicious_keywords"></textarea></label>
          </div>
          <div class="panel">
            <h3>Состояние</h3>
            <div id="state-defaults-grid" class="two"></div>
            <label>Позитивные слова<textarea id="state_positive_keywords"></textarea></label>
            <label>Негативные слова<textarea id="state_negative_keywords"></textarea></label>
            <label>Слова близости<textarea id="state_attraction_keywords"></textarea></label>
          </div>
        </div>
        <div class="panel">
          <h3>Коэффициенты</h3>
          <div id="state-effects-grid" class="three"></div>
        </div>
        <div class="panel">
          <h3>Уровни доступа и лимиты</h3>
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
          <label class="checkbox"><input id="limits_free_daily_messages_enabled" type="checkbox">Включить дневной лимит для бесплатных пользователей</label>
          <label class="checkbox"><input id="limits_premium_daily_messages_enabled" type="checkbox">Включить дневной лимит для Premium-пользователей</label>
          <label class="checkbox"><input id="limits_admins_bypass_daily_limits" type="checkbox">Админы обходят лимиты сообщений</label>
          <div class="two">
            <label>Лимит free-сообщений в день<input id="limits_free_daily_messages_limit" type="number" min="1"></label>
            <label>Лимит premium-сообщений в день<input id="limits_premium_daily_messages_limit" type="number" min="1"></label>
          </div>
          <label>Текст при исчерпании free-лимита<textarea id="limits_free_daily_limit_message"></textarea></label>
          <label>Текст при исчерпании premium-лимита<textarea id="limits_premium_daily_limit_message"></textarea></label>
          <label class="checkbox"><input id="limits_mode_preview_enabled" type="checkbox">Разрешить бесплатный preview платных режимов</label>
          <label>Лимиты по режимам
            <textarea id="limits_mode_daily_limits" placeholder="passion=5&#10;mentor=3"></textarea>
          </label>
          <label>Текст при исчерпании preview<textarea id="limits_mode_preview_exhausted_message"></textarea></label>
          <div class="two">
            <label class="checkbox"><input id="engagement_adaptive_mode_enabled" type="checkbox">Включить мягкую адаптацию режима</label>
            <label class="checkbox"><input id="engagement_reengagement_enabled" type="checkbox">Включить инициативные сообщения после паузы</label>
            <label>Пауза до инициативы, часов<input id="engagement_reengagement_idle_hours" type="number" min="1"></label>
            <label>Пауза между инициативами, часов<input id="engagement_reengagement_min_hours_between" type="number" min="1"></label>
            <label>Окно активности, дней<input id="engagement_reengagement_recent_window_days" type="number" min="1"></label>
            <label>Проверка воркера, секунд<input id="engagement_reengagement_poll_seconds" type="number" min="30"></label>
            <label>Макс сообщений за цикл<input id="engagement_reengagement_batch_size" type="number" min="1"></label>
          </div>
          <div class="actions"><button class="primary" id="save-safety">Сохранить раздел</button></div>
        </div>
      </section>

      <section class="page" data-view="prompts">
        <div><h2>Промпты</h2><p class="muted">Редактор характера, рамок и правил доступа.</p></div>
        <div class="panel">
          <label>Личность<textarea id="prompt_personality_core"></textarea></label>
          <label>Безопасность<textarea id="prompt_safety_block"></textarea></label>
          <label>Response style<textarea id="prompt_response_style"></textarea></label>
          <label>Engagement rules<textarea id="prompt_engagement_rules"></textarea></label>
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
        <div><h2>Режимы</h2><p class="muted">Название, иконка, Premium, текст активации и шкалы поведения.</p></div>
        <div class="panel">
          <div id="modes-container"></div>
          <div class="actions"><button class="primary" id="save-modes">Сохранить раздел</button></div>
        </div>
      </section>

      <section class="page" data-view="payments">
        <div><h2>Оплата</h2><p class="muted">Управление токеном провайдера, ценой, валютой и сообщениями по Premium.</p></div>
        <div class="panel">
          <div class="two">
            <label>Токен провайдера<textarea id="payment_provider_token"></textarea></label>
            <label>Валюта<input id="payment_currency"></label>
            <label>Цена<input id="payment_price_minor_units" type="number"></label>
            <label>Название<input id="payment_product_title"></label>
          </div>
          <label>Описание<textarea id="payment_product_description"></textarea></label>
          <label>Преимущества Premium<textarea id="payment_premium_benefits_text"></textarea></label>
          <label>CTA оплаты<input id="payment_buy_cta_text"></label>
          <label>Недоступно<textarea id="payment_unavailable_message"></textarea></label>
          <label>Ошибка счета<textarea id="payment_invoice_error_message"></textarea></label>
          <label>Успешная оплата<textarea id="payment_success_message"></textarea></label>
        </div>
        <div class="panel">
          <h3>Реферальная программа</h3>
          <label class="checkbox"><input id="referral_enabled" type="checkbox">Включить реферальную программу</label>
          <div class="two">
            <label>Префикс для /start<input id="referral_start_parameter_prefix"></label>
            <label>Заголовок<input id="referral_program_title"></label>
          </div>
          <label class="checkbox"><input id="referral_allow_self_referral" type="checkbox">Разрешить приглашать самого себя</label>
          <label class="checkbox"><input id="referral_require_first_paid_invoice" type="checkbox">Засчитывать только после первой оплаты</label>
          <label class="checkbox"><input id="referral_award_referrer_premium" type="checkbox">Выдавать Premium рефереру</label>
          <label class="checkbox"><input id="referral_award_referred_user_premium" type="checkbox">Выдавать Premium приглашенному</label>
          <label>Описание<textarea id="referral_program_description"></textarea></label>
          <label>Шаблон ссылки (`{ref_link}`)<textarea id="referral_share_text_template"></textarea></label>
          <label>Текст для приглашенного<textarea id="referral_referred_welcome_message"></textarea></label>
          <label>Текст награды<textarea id="referral_referrer_reward_message"></textarea></label>
          <h3>Последние рефералы</h3>
          <pre id="recent-referrals"></pre>
          <div class="actions"><button class="primary" id="save-payments">Сохранить раздел</button></div>
        </div>
      </section>

      <section class="page" data-view="testing">
        <div><h2>Тестирование</h2><p class="muted">Проверка промпта, state и live-ответа модели из текущих настроек.</p></div>
        <div class="cols">
          <div class="panel">
            <div class="two">
              <label>Активный режим<input id="test_active_mode"></label>
              <label>Уровень доступа<input id="test_access_level"></label>
            </div>
            <label>Сообщение<textarea id="test_user_message"></textarea></label>
            <label>История (`user:` / `assistant:`)<textarea id="test_history"></textarea></label>
            <label>State JSON<textarea id="test_state">{}</textarea></label>
            <div class="actions">
              <button class="primary" id="test-prompt">Промпт</button>
              <button id="test-state-btn">State</button>
              <button id="test-live-reply">Live reply</button>
            </div>
          </div>
          <div class="panel"><h3>Результат</h3><pre id="test-result">Здесь появится результат.</pre></div>
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
          </div>
          <pre id="logs-output">Загрузка логов...</pre>
        </div>
      </section>
    </main>
  </div>
  <script>
    const state={settings:null,overview:null,health:null,logs:null,users:null,currentUser:null,currentConversation:null,currentMemoryId:null};
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
    function table(cols,rows){if(!rows||!rows.length)return '<div class="muted">Пока нет данных.</div>';return `<table><thead><tr>${cols.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${cols.map(c=>`<td>${esc(r[c])}</td>`).join('')}</tr>`).join('')}</tbody></table>`}
    function statusPill(ok,okText='OK',badText='Ошибка'){return `<span class="status-pill ${ok?'ok':'bad'}">${ok?esc(okText):esc(badText)}</span>`}
    function kvList(items){const rows=(items||[]).filter(item=>item&&item[1]!==undefined&&item[1]!==null&&item[1]!=='');if(!rows.length)return '<div class="muted">Пока нет данных.</div>';return `<div class="kv-list">${rows.map(([label,value])=>`<div class="kv-row"><div class="kv-key">${esc(label)}</div><div class="kv-value">${value}</div></div>`).join('')}</div>`}
    function metricCards(items){const rows=(items||[]).filter(Boolean);if(!rows.length)return '<div class="muted">Пока нет данных.</div>';return `<div class="mini-grid">${rows.map(([label,value,caption])=>`<div class="metric"><div class="stat-label">${esc(label)}</div><div class="metric-value-small">${esc(value)}</div><div class="muted">${esc(caption||'')}</div></div>`).join('')}</div>`}
    function healthSummary(ai){const queue=ai?.queue_size??0,capacity=ai?.queue_capacity??0,workers=ai?.workers??0,busy=ai?.busy_workers??0;return metricCards([['Очередь',`${queue}/${capacity}`,'AI задачи в очереди'],['Воркеры',String(workers),`Занято: ${busy}`],['Режимов',String(state.health?.modes_count??0),'Загружено в панели']])}
    function fileTable(files){const rows=Object.entries(files||{}).map(([name,info])=>({name,path:info?.path||'',exists:info?.exists?'Да':'Нет',size:info?.exists?`${num(info?.size_bytes)} B`:'-'}));return table(['name','path','exists','size'],rows)}
    function prettyStateLabel(key){return ({active_mode:'Активный режим',interaction_count:'Число взаимодействий',conversation_phase:'Фаза диалога',emotional_tone:'Эмоциональный тон',premium_features_used:'Premium использований',enabled:'Инициатива бота',updated_at:'Обновлено',timezone:'Часовой пояс',goals:'Цели',interests:'Интересы',personality_traits:'Черты'})[key]||key.replaceAll('_',' ')}
    function prettyStateValue(value){if(value===true)return 'Да';if(value===false)return 'Нет';if(value===null||value===undefined||value==='')return '—';if(Array.isArray(value))return value.length?value.map(item=>esc(String(item))).join('<br>'):'—';if(typeof value==='object')return `<pre style="margin:0;white-space:pre-wrap">${esc(JSON.stringify(value,null,2))}</pre>`;return esc(String(value))}
    function renderStateSection(title,items){const rows=(items||[]).filter(item=>item&&item[1]!==undefined);if(!rows.length)return '';return `<div class="state-section"><h4>${esc(title)}</h4>${kvList(rows.map(([label,value])=>[prettyStateLabel(label),prettyStateValue(value)]))}</div>`}
    function renderStateSummary(statePayload){if(!statePayload||typeof statePayload!=='object')return '<div class="muted">Пока нет данных.</div>';const proactive=statePayload.proactive_preferences&&typeof statePayload.proactive_preferences==='object'?statePayload.proactive_preferences:{};const profile=statePayload.user_profile&&typeof statePayload.user_profile==='object'?statePayload.user_profile:{};const memoryFlags=statePayload.memory_flags&&typeof statePayload.memory_flags==='object'?statePayload.memory_flags:{};const mainRows=[['active_mode',statePayload.active_mode],['interaction_count',statePayload.interaction_count],['conversation_phase',statePayload.conversation_phase],['emotional_tone',statePayload.emotional_tone],['premium_features_used',statePayload.premium_features_used]];const sections=[renderStateSection('Основное состояние',mainRows),renderStateSection('Инициатива бота',Object.entries(proactive)),renderStateSection('Профиль пользователя',Object.entries(profile)),renderStateSection('Флаги памяти',Object.entries(memoryFlags))].filter(Boolean);return sections.length?sections.join(''):'<div class="muted">Пока нет данных.</div>'}
    function renderMemoryPreview(rawText){const text=String(rawText||'').trim();if(!text)return '<div class="muted">Пока нет данных.</div>';const items=text.split('\\n').map(line=>line.trim()).filter(Boolean);const cards=items.map(line=>{const cleaned=line.startsWith('- ')?line.slice(2):line;const separator=cleaned.indexOf(':');if(separator===-1)return {title:'Контекст памяти',values:[cleaned]};const title=cleaned.slice(0,separator).trim();const values=cleaned.slice(separator+1).split(';').map(part=>part.trim()).filter(Boolean);return {title:title||'Контекст памяти',values:values.length?values:[cleaned.slice(separator+1).trim()]}}).filter(card=>card.values.length);if(!cards.length)return '<div class="muted">Пока нет данных.</div>';return cards.map(card=>`<div class="memory-preview-item"><h4>${esc(card.title)}</h4><ul>${card.values.map(value=>`<li>${esc(value)}</li>`).join('')}</ul></div>`).join('')}
    function openView(name){$$('.nav button').forEach(b=>b.classList.toggle('active',b.dataset.view===name));$$('.page').forEach(p=>p.classList.toggle('active',p.dataset.view===name))}
    function formatModeLimitsMap(map){return Object.entries(map||{}).map(([key,value])=>`${key}=${value}`).join('\\n')}
    function parseModeLimitsMap(text){const out={};String(text||'').split('\\n').map(line=>line.trim()).filter(Boolean).forEach(line=>{const [key,...rest]=line.split('=');const value=Number(rest.join('=').trim());if(key&&Number.isFinite(value))out[key.trim()]=value});return out}
    function renderModeOverrides(ai,catalog){const overrides=ai.mode_overrides||{};const keys=Object.keys(catalog||{}).sort((a,b)=>(catalog[a].sort_order||0)-(catalog[b].sort_order||0));$('#ai-mode-overrides').innerHTML=keys.map(key=>{const meta=catalog[key]||{};const value=overrides[key]||{};return `<div class="mode-card"><div class="mode-head"><div><strong>${esc(meta.icon||'')} ${esc(meta.name||key)}</strong><div class="muted">${esc(key)}</div></div></div><div class="three"><label>Модель<input data-ai-override="${key}.model" value="${esc(value.model||'')}"></label><label>Температура<input data-ai-override="${key}.temperature" type="number" step="0.1" value="${esc(value.temperature??'')}"></label><label>Память<input data-ai-override="${key}.memory_max_tokens" type="number" value="${esc(value.memory_max_tokens??'')}"></label><label>История<input data-ai-override="${key}.history_message_limit" type="number" value="${esc(value.history_message_limit??'')}"></label><label>Таймаут<input data-ai-override="${key}.timeout_seconds" type="number" value="${esc(value.timeout_seconds??'')}"></label><label>Повторы<input data-ai-override="${key}.max_retries" type="number" value="${esc(value.max_retries??'')}"></label></div><label>Доп. инструкция<textarea data-ai-override="${key}.prompt_suffix">${esc(value.prompt_suffix||'')}</textarea></label></div>`}).join('')}
    function renderOverview(){if(!state.overview)return;const o=state.overview,users=o.users||{},content=o.content||{},payments=o.payments||{},runtime=o.runtime||{},support=o.support||{},episodes=support.episode_counts||{},proactive=o.proactive||{},preferences=o.preferences||{},referrals=o.referrals||{},recent=o.recent||{};const cards=[["Пользователи",users.total??0,`Всего в базе`],["Новые за 1 день",users.new_1d??0,`Регистрации за сутки`],["Новые за 7 дней",users.new_7d??0,`Регистрации за неделю`],["Premium",users.premium_total??0,`Активных: ${users.active_with_messages??0}`],["Админы",users.admins_total??0,`Через env и панель`],["Сообщения",content.messages_total??0,`Новые за 30д: ${users.new_30d??0}`],["Платежи",payments.successful_payments??0,`Выручка: ${payments.revenue??0}`],["AI",`${runtime.queue_size??0}/${runtime.queue_capacity??0}`,`Workers: ${runtime.workers??0}`],["Support",support.users_with_support_profile??0,`panic: ${episodes.panic??0}`],["Proactive",proactive.sent_1d??0,`reply rate: ${proactive.reply_after_proactive_rate??0}%`],["Prefs TZ",preferences.users_with_timezone??0,`opt-out now: ${preferences.proactive_disabled_users??0}`],["Рефералы",referrals.total??0,`Конверсий: ${referrals.converted??0}`]];$('#overview-cards').innerHTML=cards.map(x=>`<div class="card"><div class="stat-label">${x[0]}</div><div class="stat-value">${x[1]}</div><div class="muted">${x[2]}</div></div>`).join('');$('#recent-users').innerHTML=table(['id','username','first_name','active_mode','is_premium','is_admin','created_at'],recent.users||[]);$('#recent-payments').innerHTML=table(['user_id','amount','currency','status','event_time'],recent.payments||[]);$('#support-summary').innerHTML=`<div class="stack">${metricCards([["Профили поддержки",String(support.users_with_support_profile??0),"Пользователи с support profile"],["Рефералы",String(referrals.total??0),`Конверсий: ${referrals.converted??0}`],["Proactive users",String(proactive.users_contacted_7d??0),"Кому бот писал за 7 дней"]])}${kvList([["Panic эпизоды",esc(num(episodes.panic??0))],["Flashback эпизоды",esc(num(episodes.flashback??0))],["Insomnia эпизоды",esc(num(episodes.insomnia??0))],["Self-harm флаги",esc(num(support.self_harm_flags??0))],["Proactive sent",esc(num(proactive.sent_total??0))],["Proactive failed",esc(num(proactive.failed_total??0))],["Reply after proactive",esc(`${proactive.reply_after_proactive_total??0} (${proactive.reply_after_proactive_rate??0}%)`)],["Opt-out after proactive",esc(`${proactive.opt_out_after_proactive_total??0} (${proactive.opt_out_after_proactive_rate??0}%)`)],["Users with timezone",esc(num(preferences.users_with_timezone??0))],["Current opt-out users",esc(num(preferences.proactive_disabled_users??0))],["Последнее обновление",esc(support.last_updated_at||'Нет данных')]])}</div>`}
    function renderHealth(){if(!state.health)return;const db=state.health.db||{},redis=state.health.redis||{},ai=state.health.ai_runtime||{};$('#sidebar-health').innerHTML=`${statusPill(db.ok,'DB OK','DB error')} ${statusPill(redis.ok,'Redis OK','Redis error')}`;$('#health-summary').innerHTML=`<div class="stack">${healthSummary(ai)}${kvList([["База данных",`${statusPill(db.ok,'Подключено','Ошибка')}<div class="muted">${esc(db.detail||'')}</div>`],["Redis",`${statusPill(redis.ok,redis.detail||'OK',redis.detail||'Ошибка')}<div class="muted">${esc(redis.detail||'')}</div>`],["AI модель",esc(ai.model||ai.openai_model||'Не указана')],["Занято воркеров",esc(String(ai.busy_workers??0))]])}</div>`;$('#full-health').innerHTML=`<div class="stack">${metricCards([["Кэш метрик",String(ai.cache_hits??0),"Попадания в runtime, если доступны"],["Очередь AI",`${ai.queue_size??0}/${ai.queue_capacity??0}`,"Текущее давление"],["Режимов",String(state.health.modes_count??0),"Доступно в каталоге"]])}${kvList([["DB статус",`${statusPill(db.ok,'OK','Ошибка')}<div class="muted">${esc(db.detail||'')}</div>`],["Redis статус",`${statusPill(redis.ok,'OK','Ошибка')}<div class="muted">${esc(redis.detail||'')}</div>`],["Воркеров всего",esc(String(ai.workers??0))],["Воркеров занято",esc(String(ai.busy_workers??0))],["Очередь",esc(`${ai.queue_size??0}/${ai.queue_capacity??0}`)]])}</div>`;$('#config-files').innerHTML=fileTable(state.health.config_files)}
    function renderUserModeOptions(){const select=$('#user_active_mode');if(!select||!state.settings||!state.settings.mode_catalog)return;const catalog=state.settings.mode_catalog||{};const keys=Object.keys(catalog).sort((a,b)=>(catalog[a].sort_order||0)-(catalog[b].sort_order||0));select.innerHTML=keys.map(key=>{const mode=catalog[key]||{};const suffix=mode.is_premium?' (Premium)':' (Free)';return `<option value="${esc(key)}">${esc((mode.icon||'')+' '+(mode.name||key)+suffix)}</option>`}).join('')}
    function fillUserForm(user){state.currentUser=user||null;renderUserModeOptions();setValue('#user_user_id',user?.id??'');setValue('#conversation_user_id',user?.id??$('#conversation_user_id')?.value??'');setValue('#user_username',user?.username??'');setValue('#user_first_name',user?.first_name??'');setValue('#user_active_mode',user?.active_mode??'base');setChecked('#user_is_admin',user?.is_admin);setChecked('#user_is_premium',user?.is_premium);$('#user_meta').textContent=user?`Создан: ${user.created_at||'неизвестно'}`:'Можно ввести ID вручную и сохранить: запись создастся даже если пользователь ещё не появился в таблице.'}
    function usersTable(items){if(!items||!items.length)return '<div class="muted">Пока нет данных.</div>';return `<table><thead><tr><th>ID</th><th>Username</th><th>Имя</th><th>Режим</th><th>Premium</th><th>Админ</th><th>Действие</th></tr></thead><tbody>${items.map(user=>`<tr><td>${esc(user.id)}</td><td>${esc(user.username||'')}</td><td>${esc(user.first_name||'')}</td><td>${esc(user.active_mode||'base')}</td><td>${user.is_premium?'Да':'Нет'}</td><td>${user.is_admin?'Да':'Нет'}</td><td><button data-user-pick="${esc(user.id)}">Выбрать</button></td></tr>`).join('')}</tbody></table>`}
    function renderUsers(){renderUserModeOptions();if(!state.users)return;$('#users-table').innerHTML=usersTable(state.users.items||[]);if(state.currentUser){setValue('#user_active_mode',state.currentUser.active_mode||'base')}}
    function conversationMessages(items){if(!items||!items.length)return '<div class="muted">У пользователя пока нет сообщений.</div>';return items.map(item=>`<div class="message-card ${item.role==='user'?'user':'assistant'}"><div class="message-meta"><strong>${item.role==='user'?'Пользователь':'Бот'}</strong><span>${esc(item.created_at||'')}</span></div><div>${escText(item.text||'')}</div></div>`).join('')}
    function memoryCategoryOptions(items){return (items||[]).map(item=>`<option value="${esc(item.key)}">${esc(item.label)}</option>`).join('')}
    function resetMemoryEditor(categories){const categorySelect=$('#memory_editor_category');const categoryList=categories||state.currentConversation?.settings?.memory_categories||[];categorySelect.innerHTML=memoryCategoryOptions(categoryList);setValue('#memory_editor_id','');setValue('#memory_editor_weight','1.0');setValue('#memory_editor_value','');setChecked('#memory_editor_pinned',false);if(categoryList.length){setValue('#memory_editor_category',categoryList[0].key)}state.currentMemoryId=null}
    function fillMemoryEditor(memory,categories){if(!memory){resetMemoryEditor(categories);return}const categoryList=categories||state.currentConversation?.settings?.memory_categories||[];$('#memory_editor_category').innerHTML=memoryCategoryOptions(categoryList);setValue('#memory_editor_id',memory.id);setValue('#memory_editor_category',memory.category||'');setValue('#memory_editor_weight',memory.weight??1.0);setValue('#memory_editor_value',memory.value||'');setChecked('#memory_editor_pinned',memory.pinned);state.currentMemoryId=memory.id}
    function formatLongTermMemories(items){if(!items||!items.length)return '<div class="muted">Пока нет данных.</div>';return items.map(item=>`<div class="kv-row"><div class="kv-key"><strong>${esc(item.category)}</strong><div class="muted">${esc(item.value)}</div><div class="muted">score=${esc(item.score)} | weight=${esc(item.weight)} | seen=${esc(item.times_seen)} | updated=${esc(item.updated_at||'-')}</div></div><div class="kv-value"><div class="memory-row-actions"><button data-memory-edit="${esc(item.id)}">Редактировать</button><button data-memory-pin="${esc(item.id)}" data-pinned="${item.pinned?0:1}">${item.pinned?'Открепить':'Закрепить'}</button></div></div></div>`).join('')}
    function renderConversation(){const view=state.currentConversation,categories=view?.settings?.memory_categories||[];if(!view){$('#conversation-meta').textContent='Выберите пользователя, чтобы увидеть историю и память.';$('#conversation-stats').innerHTML='';$('#conversation-memory-preview-summary').innerHTML='<div class="muted">Пока нет данных.</div>';$('#conversation-memory-preview').textContent='Пока нет данных.';$('#conversation-long-term-memories').innerHTML='<div class="muted">Пока нет данных.</div>';$('#conversation-state-summary').innerHTML='<div class="muted">Пока нет данных.</div>';$('#conversation-state').textContent='Пока нет данных.';$('#conversation-messages').innerHTML='<div class="muted">Пока нет данных.</div>';resetMemoryEditor([]);return}const user=view.user||{},stats=view.stats||{},cfg=view.settings||{};setValue('#conversation_user_id',user.id??'');$('#conversation-meta').textContent=`Пользователь: ${user.first_name||user.username||user.id||'неизвестно'} • ID ${user.id||'-'} • Сообщений: ${stats.total_messages??0}`;$('#conversation-stats').innerHTML=metricCards([['Всего сообщений',String(stats.total_messages??0),`user: ${stats.user_messages??0}, bot: ${stats.assistant_messages??0}`],['Первое сообщение',String(stats.first_message_at||'—'),'Начало истории'],['Последнее сообщение',String(stats.last_message_at||'—'),'Последняя активность'],['Long-term memory',cfg.long_term_memory_enabled?'on':'off',`Prompt items: ${cfg.long_term_memory_max_items??0}`],['Auto-prune',cfg.long_term_memory_auto_prune_enabled?'on':'off',`Soft limit: ${cfg.long_term_memory_soft_limit??0}`],['History limit',String(cfg.history_message_limit??0),`Memory tokens: ${cfg.memory_max_tokens??0}`],['Summary memory',cfg.episodic_summary_enabled?'on':'off','Summary layer']]);$('#conversation-memory-preview-summary').innerHTML=renderMemoryPreview(view.memory_preview||'');$('#conversation-memory-preview').textContent=view.memory_preview||'Память пока пустая.';$('#conversation-long-term-memories').innerHTML=formatLongTermMemories(view.long_term_memories||[]);$('#conversation-state-summary').innerHTML=renderStateSummary(view.state||{});$('#conversation-state').textContent=JSON.stringify(view.state||{},null,2);$('#conversation-messages').innerHTML=conversationMessages(view.messages||[]);const selected=(view.long_term_memories||[]).find(item=>String(item.id)===String(state.currentMemoryId));if(selected){fillMemoryEditor(selected,categories)}else{resetMemoryEditor(categories)}}
    function renderRuntime(){
      if(!state.settings||!state.settings.runtime)return;
      const r=state.settings.runtime,a=r.ai||{},c=r.chat||{},p=r.proactive||{},u=r.ui||{};
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
      setValue('#chat_non_text_message',c.non_text_message);
      setValue('#chat_busy_message',c.busy_message);
      setValue('#chat_ai_error_message',c.ai_error_message);
      setValue('#chat_write_prompt_message',c.write_prompt_message);
      setChecked('#proactive_enabled',p.enabled);
      setValue('#proactive_scan_interval_seconds',p.scan_interval_seconds);
      setValue('#proactive_min_inactive_hours',p.min_inactive_hours);
      setValue('#proactive_max_inactive_days',p.max_inactive_days);
      setValue('#proactive_cooldown_hours',p.cooldown_hours);
      setValue('#proactive_min_user_messages',p.min_user_messages);
      setValue('#proactive_min_interaction_count',p.min_interaction_count);
      setValue('#proactive_candidate_batch_size',p.candidate_batch_size);
      setValue('#proactive_max_messages_per_cycle',p.max_messages_per_cycle);
      setValue('#proactive_history_limit',p.history_limit);
      setValue('#proactive_per_message_delay_seconds',p.per_message_delay_seconds);
      setValue('#proactive_temperature',p.temperature);
      setValue('#proactive_max_completion_tokens',p.max_completion_tokens);
      setValue('#proactive_reasoning_effort',p.reasoning_effort||'');
      setValue('#proactive_min_interest',p.min_interest);
      setValue('#proactive_max_irritation',p.max_irritation);
      setValue('#proactive_max_fatigue',p.max_fatigue);
      setChecked('#proactive_quiet_hours_enabled',p.quiet_hours_enabled);
      setValue('#proactive_quiet_hours_start',p.quiet_hours_start);
      setValue('#proactive_quiet_hours_end',p.quiet_hours_end);
      setValue('#proactive_timezone',p.timezone||'');
      setValue('#proactive_model',p.model||'');
      setValue('#ui_write_button_text',u.write_button_text);
      setValue('#ui_modes_button_text',u.modes_button_text);
      setValue('#ui_premium_button_text',u.premium_button_text);
      setValue('#ui_input_placeholder',u.input_placeholder);
      setValue('#ui_modes_title',u.modes_title);
      setValue('#ui_user_not_found_text',u.user_not_found_text);
      setValue('#ui_unknown_mode_text',u.unknown_mode_text);
      setValue('#ui_mode_locked_text',u.mode_locked_text);
      setValue('#ui_mode_saved_toast',u.mode_saved_toast);
      setValue('#ui_mode_saved_template',u.mode_saved_template);
      setValue('#ui_welcome_user_text',u.welcome_user_text);
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
      $('#limits_mode_daily_limits').value=formatModeLimitsMap(l.mode_daily_limits||{});
      $('#limits_mode_preview_exhausted_message').value=l.mode_preview_exhausted_message||'';
      $('#engagement_adaptive_mode_enabled').checked=!!e.adaptive_mode_enabled;
      $('#engagement_reengagement_enabled').checked=!!e.reengagement_enabled;
      $('#engagement_reengagement_idle_hours').value=e.reengagement_idle_hours??'';
      $('#engagement_reengagement_min_hours_between').value=e.reengagement_min_hours_between??'';
      $('#engagement_reengagement_recent_window_days').value=e.reengagement_recent_window_days??'';
      $('#engagement_reengagement_poll_seconds').value=e.reengagement_poll_seconds??'';
      $('#engagement_reengagement_batch_size').value=e.reengagement_batch_size??'';
    }
    function renderPrompts(){if(!state.settings||!state.settings.prompts)return;const p=state.settings.prompts,accessRules=p.access_rules||{};setValue('#prompt_personality_core',p.personality_core);setValue('#prompt_safety_block',p.safety_block);setValue('#prompt_response_style',p.response_style||'');setValue('#prompt_engagement_rules',p.engagement_rules||'');setValue('#prompt_memory_intro',p.memory_intro);setValue('#prompt_state_intro',p.state_intro);setValue('#prompt_mode_intro',p.mode_intro);setValue('#prompt_access_intro',p.access_intro);setValue('#prompt_final_instruction',p.final_instruction);setValue('#access_observation',accessRules.observation);setValue('#access_analysis',accessRules.analysis);setValue('#access_tension',accessRules.tension);setValue('#access_personal_focus',accessRules.personal_focus);setValue('#access_rare_layer',accessRules.rare_layer)}
    function renderModes(){if(!state.settings||!state.settings.modes||!state.settings.mode_catalog)return;const m=state.settings.modes,c=state.settings.mode_catalog;const keys=Object.keys(c).sort((a,b)=>(c[a].sort_order||0)-(c[b].sort_order||0));const modeScaleLabel=k=>({allow_bold:'Жирный текст',allow_italic:'Курсив'}[k]||k);$('#modes-container').innerHTML=keys.map(k=>{const meta=c[k]||{},scale=m[k]||{},numericEntries=Object.entries(scale).filter(([,mv])=>typeof mv==='number'),booleanEntries=Object.entries(scale).filter(([,mv])=>typeof mv==='boolean');return `<div class="mode-card"><div class="mode-head"><div><strong>${esc(meta.icon)} ${esc(meta.name)}</strong><div class="muted">${esc(k)}</div></div><span class="badge">${meta.is_premium?'Premium':'Free'}</span></div><div class="three"><label>Название<input data-catalog="${k}.name" value="${esc(meta.name)}"></label><label>Иконка<input data-catalog="${k}.icon" value="${esc(meta.icon)}"></label><label>Порядок<input data-catalog="${k}.sort_order" type="number" value="${meta.sort_order??0}"></label></div><label class="checkbox"><input data-catalog="${k}.is_premium" type="checkbox" ${meta.is_premium?'checked':''}>Premium</label><label>Описание<textarea data-catalog="${k}.description">${esc(meta.description)}</textarea></label><label>Тон<input data-catalog="${k}.tone" value="${esc(meta.tone)}"></label><label>Эмоциональное состояние<input data-catalog="${k}.emotional_state" value="${esc(meta.emotional_state)}"></label><label>Правила<textarea data-catalog="${k}.behavior_rules">${esc(meta.behavior_rules)}</textarea></label><label>Фраза активации<textarea data-catalog="${k}.activation_phrase">${esc(meta.activation_phrase)}</textarea></label><div class="three">${numericEntries.map(([mk,mv])=>`<label>${mk}<input data-mode-scale="${k}.${mk}" type="number" min="0" max="10" value="${mv}"></label>`).join('')}</div>${booleanEntries.length?`<div class="two">${booleanEntries.map(([mk,mv])=>`<label class="checkbox"><input data-mode-scale="${k}.${mk}" type="checkbox" ${mv?'checked':''}>${esc(modeScaleLabel(mk))}</label>`).join('')}</div>`:''}</div>`}).join('')}
    function renderPayments(){if(!state.settings||!state.settings.runtime)return;const p=state.settings.runtime.payment,ref=state.settings.runtime.referral;$('#payment_provider_token').value=p.provider_token;$('#payment_currency').value=p.currency;$('#payment_price_minor_units').value=p.price_minor_units;$('#payment_product_title').value=p.product_title;$('#payment_product_description').value=p.product_description;$('#payment_premium_benefits_text').value=p.premium_benefits_text;$('#payment_buy_cta_text').value=p.buy_cta_text;$('#payment_unavailable_message').value=p.unavailable_message;$('#payment_invoice_error_message').value=p.invoice_error_message;$('#payment_success_message').value=p.success_message;$('#referral_enabled').checked=!!ref.enabled;$('#referral_start_parameter_prefix').value=ref.start_parameter_prefix;$('#referral_program_title').value=ref.program_title;$('#referral_allow_self_referral').checked=!!ref.allow_self_referral;$('#referral_require_first_paid_invoice').checked=!!ref.require_first_paid_invoice;$('#referral_award_referrer_premium').checked=!!ref.award_referrer_premium;$('#referral_award_referred_user_premium').checked=!!ref.award_referred_user_premium;$('#referral_program_description').value=ref.program_description;$('#referral_share_text_template').value=ref.share_text_template;$('#referral_referred_welcome_message').value=ref.referred_welcome_message;$('#referral_referrer_reward_message').value=ref.referrer_reward_message;$('#recent-referrals').textContent=JSON.stringify((state.overview&&state.overview.recent&&state.overview.recent.referrals)||[],null,2)}
    function renderLogs(){if(state.logs)$('#logs-output').textContent=(state.logs.lines||[]).join('\\n')||'Лог пуст.'}
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
      return {ai:{openai_model:$('#ai_openai_model').value.trim(),response_language:$('#ai_response_language').value.trim(),temperature:Number($('#ai_temperature').value),top_p:Number($('#ai_top_p').value),frequency_penalty:Number($('#ai_frequency_penalty').value),presence_penalty:Number($('#ai_presence_penalty').value),max_completion_tokens:Number($('#ai_max_completion_tokens').value),reasoning_effort:$('#ai_reasoning_effort').value.trim(),verbosity:$('#ai_verbosity').value.trim(),timeout_seconds:Number($('#ai_timeout_seconds').value),max_retries:Number($('#ai_max_retries').value),memory_max_tokens:Number($('#ai_memory_max_tokens').value),history_message_limit:Number($('#ai_history_message_limit').value),long_term_memory_enabled:$('#ai_long_term_memory_enabled').checked,long_term_memory_max_items:Number($('#ai_long_term_memory_max_items').value),long_term_memory_auto_prune_enabled:$('#ai_long_term_memory_auto_prune_enabled').checked,long_term_memory_soft_limit:Number($('#ai_long_term_memory_soft_limit').value),episodic_summary_enabled:$('#ai_episodic_summary_enabled').checked,debug_prompt_user_id:$('#ai_debug_prompt_user_id').value.trim()||null,log_full_prompt:$('#ai_log_full_prompt').checked,mode_overrides:modeOverrides},chat:{typing_action_enabled:$('#chat_typing_action_enabled').checked,non_text_message:$('#chat_non_text_message').value,busy_message:$('#chat_busy_message').value,ai_error_message:$('#chat_ai_error_message').value,write_prompt_message:$('#chat_write_prompt_message').value},proactive:{enabled:$('#proactive_enabled').checked,scan_interval_seconds:Number($('#proactive_scan_interval_seconds').value),min_inactive_hours:Number($('#proactive_min_inactive_hours').value),max_inactive_days:Number($('#proactive_max_inactive_days').value),cooldown_hours:Number($('#proactive_cooldown_hours').value),min_user_messages:Number($('#proactive_min_user_messages').value),min_interaction_count:Number($('#proactive_min_interaction_count').value),candidate_batch_size:Number($('#proactive_candidate_batch_size').value),max_messages_per_cycle:Number($('#proactive_max_messages_per_cycle').value),history_limit:Number($('#proactive_history_limit').value),per_message_delay_seconds:Number($('#proactive_per_message_delay_seconds').value),temperature:Number($('#proactive_temperature').value),max_completion_tokens:Number($('#proactive_max_completion_tokens').value),reasoning_effort:$('#proactive_reasoning_effort').value.trim(),min_interest:Number($('#proactive_min_interest').value),max_irritation:Number($('#proactive_max_irritation').value),max_fatigue:Number($('#proactive_max_fatigue').value),quiet_hours_enabled:$('#proactive_quiet_hours_enabled').checked,quiet_hours_start:Number($('#proactive_quiet_hours_start').value),quiet_hours_end:Number($('#proactive_quiet_hours_end').value),timezone:$('#proactive_timezone').value.trim(),model:$('#proactive_model').value.trim()},ui:{write_button_text:$('#ui_write_button_text').value,modes_button_text:$('#ui_modes_button_text').value,premium_button_text:$('#ui_premium_button_text').value,input_placeholder:$('#ui_input_placeholder').value,modes_title:$('#ui_modes_title').value,user_not_found_text:$('#ui_user_not_found_text').value,unknown_mode_text:$('#ui_unknown_mode_text').value,mode_locked_text:$('#ui_mode_locked_text').value,mode_saved_toast:$('#ui_mode_saved_toast').value,mode_saved_template:$('#ui_mode_saved_template').value,welcome_user_text:$('#ui_welcome_user_text').value,welcome_admin_text:$('#ui_welcome_admin_text').value}}}
    function safetyPayload(){
      const defaults={},effects={};
      document.querySelectorAll('[data-state-default]').forEach(i=>defaults[i.dataset.stateDefault]=Number(i.value));
      document.querySelectorAll('[data-state-effect]').forEach(i=>effects[i.dataset.stateEffect]=Number(i.value));
      return {safety:{throttle_rate_limit_seconds:Number($('#safety_throttle_rate_limit_seconds').value),throttle_warning_interval_seconds:Number($('#safety_throttle_warning_interval_seconds').value),max_message_length:Number($('#safety_max_message_length').value),reject_suspicious_messages:$('#safety_reject_suspicious_messages').checked,throttle_warning_text:$('#safety_throttle_warning_text').value,message_too_long_text:$('#safety_message_too_long_text').value,suspicious_rejection_text:$('#safety_suspicious_rejection_text').value,suspicious_keywords:$('#safety_suspicious_keywords').value},state_engine:{defaults,positive_keywords:$('#state_positive_keywords').value,negative_keywords:$('#state_negative_keywords').value,attraction_keywords:$('#state_attraction_keywords').value,message_effects:effects},access:{forced_level:$('#access_forced_level').value.trim(),default_level:$('#access_default_level').value.trim(),interest_observation_threshold:Number($('#access_interest_observation_threshold').value),rare_layer_instability_threshold:Number($('#access_rare_layer_instability_threshold').value),rare_layer_attraction_threshold:Number($('#access_rare_layer_attraction_threshold').value),personal_focus_attraction_threshold:Number($('#access_personal_focus_attraction_threshold').value),personal_focus_interest_threshold:Number($('#access_personal_focus_interest_threshold').value),tension_attraction_threshold:Number($('#access_tension_attraction_threshold').value),tension_control_threshold:Number($('#access_tension_control_threshold').value),analysis_interest_threshold:Number($('#access_analysis_interest_threshold').value),analysis_control_threshold:Number($('#access_analysis_control_threshold').value)},limits:{free_daily_messages_enabled:$('#limits_free_daily_messages_enabled').checked,premium_daily_messages_enabled:$('#limits_premium_daily_messages_enabled').checked,admins_bypass_daily_limits:$('#limits_admins_bypass_daily_limits').checked,free_daily_messages_limit:Number($('#limits_free_daily_messages_limit').value),premium_daily_messages_limit:Number($('#limits_premium_daily_messages_limit').value),free_daily_limit_message:$('#limits_free_daily_limit_message').value,premium_daily_limit_message:$('#limits_premium_daily_limit_message').value,mode_preview_enabled:$('#limits_mode_preview_enabled').checked,mode_daily_limits:parseModeLimitsMap($('#limits_mode_daily_limits').value),mode_preview_exhausted_message:$('#limits_mode_preview_exhausted_message').value},engagement:{adaptive_mode_enabled:$('#engagement_adaptive_mode_enabled').checked,reengagement_enabled:$('#engagement_reengagement_enabled').checked,reengagement_idle_hours:Number($('#engagement_reengagement_idle_hours').value),reengagement_min_hours_between:Number($('#engagement_reengagement_min_hours_between').value),reengagement_recent_window_days:Number($('#engagement_reengagement_recent_window_days').value),reengagement_poll_seconds:Number($('#engagement_reengagement_poll_seconds').value),reengagement_batch_size:Number($('#engagement_reengagement_batch_size').value)}}}
    function promptsPayload(){return {personality_core:$('#prompt_personality_core').value,safety_block:$('#prompt_safety_block').value,response_style:$('#prompt_response_style').value,engagement_rules:$('#prompt_engagement_rules').value,memory_intro:$('#prompt_memory_intro').value,state_intro:$('#prompt_state_intro').value,mode_intro:$('#prompt_mode_intro').value,access_intro:$('#prompt_access_intro').value,final_instruction:$('#prompt_final_instruction').value,access_rules:{observation:$('#access_observation').value,analysis:$('#access_analysis').value,tension:$('#access_tension').value,personal_focus:$('#access_personal_focus').value,rare_layer:$('#access_rare_layer').value}}}
    function modesPayload(){const modes={},catalog={};document.querySelectorAll('[data-mode-scale]').forEach(i=>{const [m,k]=i.dataset.modeScale.split('.');modes[m]??={};modes[m][k]=i.type==='checkbox'?i.checked:Number(i.value)});document.querySelectorAll('[data-catalog]').forEach(i=>{const [m,k]=i.dataset.catalog.split('.');catalog[m]??={};catalog[m][k]=i.type==='checkbox'?i.checked:(k==='sort_order'?Number(i.value):i.value)});return {modes,catalog}}
    function paymentsPayload(){return {payment:{provider_token:$('#payment_provider_token').value,currency:$('#payment_currency').value,price_minor_units:Number($('#payment_price_minor_units').value),product_title:$('#payment_product_title').value,product_description:$('#payment_product_description').value,premium_benefits_text:$('#payment_premium_benefits_text').value,buy_cta_text:$('#payment_buy_cta_text').value,unavailable_message:$('#payment_unavailable_message').value,invoice_error_message:$('#payment_invoice_error_message').value,success_message:$('#payment_success_message').value},referral:{enabled:$('#referral_enabled').checked,start_parameter_prefix:$('#referral_start_parameter_prefix').value,program_title:$('#referral_program_title').value,allow_self_referral:$('#referral_allow_self_referral').checked,require_first_paid_invoice:$('#referral_require_first_paid_invoice').checked,award_referrer_premium:$('#referral_award_referrer_premium').checked,award_referred_user_premium:$('#referral_award_referred_user_premium').checked,program_description:$('#referral_program_description').value,share_text_template:$('#referral_share_text_template').value,referred_welcome_message:$('#referral_referred_welcome_message').value,referrer_reward_message:$('#referral_referrer_reward_message').value}}}
    function testPayload(){return {active_mode:$('#test_active_mode').value.trim(),access_level:$('#test_access_level').value.trim(),user_message:$('#test_user_message').value,history:$('#test_history').value,state:$('#test_state').value}}
    function currentUserPayload(){return {active_mode:$('#user_active_mode').value.trim()||'base',is_admin:$('#user_is_admin').checked,is_premium:$('#user_is_premium').checked}}
    async function refreshUsers(query){const search=query??$('#user-search').value.trim();state.users=await api(`/api/users?query=${encodeURIComponent(search)}&limit=100`);renderUsers()}
    async function loadUser(){const rawId=$('#user_user_id').value.trim();if(!rawId)throw new Error('Укажи user_id');const user=await api(`/api/users/${encodeURIComponent(rawId)}`);fillUserForm(user);renderUsers()}
    async function loadConversation(userId){const rawId=String(userId||$('#conversation_user_id').value.trim()||$('#user_user_id').value.trim()||'').trim();if(!rawId)throw new Error('Укажи user_id');const limit=Math.max(10,Math.min(200,Number($('#conversation_limit').value||80)));state.currentConversation=await api(`/api/users/${encodeURIComponent(rawId)}/conversation?limit=${limit}`);renderConversation();return state.currentConversation}
    async function toggleMemoryPin(memoryId,pinned){await api(`/api/memories/${encodeURIComponent(memoryId)}/pin`,{method:'POST',body:JSON.stringify({pinned:!!Number(pinned)})});await loadConversation();notice('Статус памяти обновлен.')}
    function memoryEditorPayload(){return {user_id:Number($('#conversation_user_id').value||0),category:$('#memory_editor_category').value.trim(),value:$('#memory_editor_value').value.trim(),weight:Number($('#memory_editor_weight').value||0),pinned:$('#memory_editor_pinned').checked}}
    async function saveMemoryEditor(){const rawUserId=String($('#conversation_user_id').value||'').trim();if(!rawUserId)throw new Error('Сначала выбери пользователя');const payload=memoryEditorPayload();if(!payload.category)throw new Error('Выбери категорию memory');if(!payload.value)throw new Error('Заполни текст memory');const memoryId=String($('#memory_editor_id').value||'').trim();const result=memoryId?await api(`/api/memories/${encodeURIComponent(memoryId)}`,{method:'PUT',body:JSON.stringify(payload)}):await api(`/api/users/${encodeURIComponent(rawUserId)}/memories`,{method:'POST',body:JSON.stringify(payload)});state.currentMemoryId=result.memory?.id||null;await loadConversation(rawUserId);notice(memoryId?'Memory обновлена.':'Memory создана.')}
    async function deleteMemoryEditor(){const memoryId=String($('#memory_editor_id').value||'').trim();if(!memoryId)throw new Error('Выбери memory для удаления');const rawUserId=String($('#conversation_user_id').value||'').trim();await api(`/api/memories/${encodeURIComponent(memoryId)}`,{method:'DELETE'});state.currentMemoryId=null;await loadConversation(rawUserId);notice('Memory удалена.')}
    async function pruneMemoryEditor(){const rawUserId=String($('#conversation_user_id').value||'').trim();if(!rawUserId)throw new Error('Сначала выбери пользователя');const result=await api(`/api/users/${encodeURIComponent(rawUserId)}/memories/prune`,{method:'POST'});state.currentMemoryId=null;await loadConversation(rawUserId);notice(`Память очищена: удалено ${result.deleted_count||0}.`)}
    async function saveCurrentUser(){const rawId=$('#user_user_id').value.trim();if(!rawId)throw new Error('Укажи user_id');const user=await api(`/api/users/${encodeURIComponent(rawId)}`,{method:'PUT',body:JSON.stringify(currentUserPayload())});fillUserForm(user);await refreshAll();notice('Пользователь сохранен.')}
    function renderAll(){const renderers=[['overview',renderOverview],['health',renderHealth],['users',renderUsers],['conversations',renderConversation],['runtime',renderRuntime],['safety',renderSafety],['prompts',renderPrompts],['modes',renderModes],['payments',renderPayments],['logs',renderLogs]];const errors=[];renderers.forEach(([name,fn])=>{try{fn()}catch(error){console.error(`Render failed: ${name}`,error);errors.push(name)}});if(errors.length)notice(`Часть блоков не отрисована: ${errors.join(', ')}`,'error')}
    async function refreshAll(){const requests=[['overview','/api/overview','overview'],['health','/api/health','health'],['settings','/api/settings','settings'],['users',`/api/users?query=${encodeURIComponent($('#user-search')?.value||'')}&limit=100`,'users'],['logs',`/api/logs?lines=${$('#log-lines')?.value||200}`,'logs']];const conversationUserId=$('#conversation_user_id')?.value?.trim()||String(state.currentConversation?.user?.id||'');if(conversationUserId){const limit=Math.max(10,Math.min(200,Number($('#conversation_limit')?.value||80)));requests.push(['currentConversation',`/api/users/${encodeURIComponent(conversationUserId)}/conversation?limit=${limit}`,'currentConversation'])}const failed=[];for(const [label,path,stateKey] of requests){try{state[stateKey]=await api(path)}catch(error){console.error(`Load failed: ${label}`,error);failed.push(label)}}renderAll();if(failed.length)notice(`Не все данные загрузились: ${failed.join(', ')}`,'error')}
    async function save(path,payload,msg){await api(path,{method:'PUT',body:JSON.stringify(payload)});await refreshAll();notice(msg)}
    async function runTest(path){const data=await api(path,{method:'POST',body:JSON.stringify(testPayload())});$('#test-result').textContent=JSON.stringify(data,null,2)}
    onAll('.nav button','click',event=>openView(event.currentTarget.dataset.view));
    on('#refresh-all','click',()=>refreshAll().then(()=>notice('Данные обновлены.')).catch(e=>notice(e.message,'error')));
    on('#load-user','click',()=>loadUser().then(()=>notice('Пользователь загружен.')).catch(e=>notice(e.message,'error')));
    on('#open-user-conversation','click',()=>{setValue('#conversation_user_id',$('#user_user_id')?.value?.trim()||'');openView('conversations');loadConversation().then(()=>notice('Диалог загружен.')).catch(e=>notice(e.message,'error'))});
    on('#load-conversation','click',()=>loadConversation().then(()=>notice('Диалог загружен.')).catch(e=>notice(e.message,'error')));
    on('#memory-editor-new','click',()=>resetMemoryEditor());
    on('#memory-editor-save','click',()=>saveMemoryEditor().catch(e=>notice(e.message,'error')));
    on('#memory-editor-delete','click',()=>deleteMemoryEditor().catch(e=>notice(e.message,'error')));
    on('#memory-editor-prune','click',()=>pruneMemoryEditor().catch(e=>notice(e.message,'error')));
    on('#save-user','click',()=>saveCurrentUser().catch(e=>notice(e.message,'error')));
    on('#conversation-long-term-memories','click',event=>{const editButton=event.target.closest('[data-memory-edit]');if(editButton){const memory=(state.currentConversation?.long_term_memories||[]).find(item=>String(item.id)===String(editButton.dataset.memoryEdit));if(memory)fillMemoryEditor(memory);return}const pinButton=event.target.closest('[data-memory-pin]');if(!pinButton)return;toggleMemoryPin(pinButton.dataset.memoryPin,pinButton.dataset.pinned).catch(e=>notice(e.message,'error'))});
    on('#search-users','click',()=>refreshUsers().then(()=>notice('Список пользователей обновлен.')).catch(e=>notice(e.message,'error')));
    on('#reset-users','click',()=>{$('#user-search').value='';refreshUsers('').then(()=>notice('Фильтр сброшен.')).catch(e=>notice(e.message,'error'))});
    on('#users-table','click',event=>{const button=event.target.closest('[data-user-pick]');if(!button)return;$('#user_user_id').value=button.dataset.userPick;loadUser().then(()=>notice('Пользователь загружен.')).catch(e=>notice(e.message,'error'))});
    on('#reload-logs','click',()=>api(`/api/logs?lines=${$('#log-lines')?.value||200}`).then(d=>{state.logs=d;renderLogs();notice('Логи обновлены.')}).catch(e=>notice(e.message,'error')));
    on('#invalidate-cache','click',()=>api('/api/actions/cache/invalidate',{method:'POST'}).then(()=>refreshAll()).then(()=>notice('Кеш сброшен.')).catch(e=>notice(e.message,'error')));
    on('#export-json','click',()=>api('/api/export').then(d=>{const blob=new Blob([JSON.stringify(d,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='bot-admin-export.json';a.click();URL.revokeObjectURL(url);notice('Экспорт подготовлен.')}).catch(e=>notice(e.message,'error')));
    on('#save-runtime','click',()=>save('/api/settings/runtime',runtimePayload(),'Настройки AI и UI сохранены.').catch(e=>notice(e.message,'error')));
    on('#save-safety','click',()=>save('/api/settings/runtime',safetyPayload(),'Настройки безопасности сохранены.').catch(e=>notice(e.message,'error')));
    on('#save-prompts','click',()=>save('/api/settings/prompts',promptsPayload(),'Промпты сохранены.').catch(e=>notice(e.message,'error')));
    on('#save-modes','click',async()=>{try{const p=modesPayload();await api('/api/settings/modes',{method:'PUT',body:JSON.stringify(p.modes)});await api('/api/settings/mode-catalog',{method:'PUT',body:JSON.stringify(p.catalog)});await refreshAll();notice('Режимы сохранены.')}catch(e){notice(e.message,'error')}})
    on('#save-payments','click',()=>save('/api/settings/runtime',paymentsPayload(),'Платежные настройки сохранены.').catch(e=>notice(e.message,'error')));
    on('#test-prompt','click',()=>runTest('/api/test/prompt').then(()=>notice('Промпт готов.')).catch(e=>notice(e.message,'error')));
    on('#test-state-btn','click',()=>runTest('/api/test/state').then(()=>notice('State пересчитан.')).catch(e=>notice(e.message,'error')));
    on('#test-live-reply','click',()=>{$('#test-result').textContent='Жду ответ модели...';runTest('/api/test/reply').then(()=>notice('Live-тест завершен.')).catch(e=>notice(e.message,'error'))});
    window.addEventListener('error',e=>{console.error('Admin dashboard error',e.error||e.message);notice(`Ошибка интерфейса: ${e.message||'см. консоль браузера'}`,'error')});
    window.addEventListener('unhandledrejection',e=>{console.error('Admin dashboard rejection',e.reason);notice(`Ошибка загрузки: ${e.reason?.message||e.reason||'неизвестно'}`,'error')});
    refreshAll().catch(e=>notice(e.message,'error'));
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def dashboard(_: str = Depends(require_auth)):
    return _dashboard_html()

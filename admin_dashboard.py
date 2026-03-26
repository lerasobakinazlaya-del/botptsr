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
    await container.ai_service.start()

    container.admin_metrics = AdminMetricsService(
        user_service=container.user_service,
        message_repository=container.message_repository,
        payment_repository=container.payment_repository,
        referral_service=container.referral_service,
        state_repository=container.state_repository,
        ai_service=container.ai_service,
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


def _prepare_test_context(payload: dict[str, Any]) -> dict[str, Any]:
    user_message = str(payload.get("user_message") or "").strip()
    state = _parse_json_field(payload.get("state"), default={})
    if not isinstance(state, dict):
        raise HTTPException(status_code=400, detail="Поле state должно быть объектом JSON")

    active_mode = str(payload.get("active_mode") or state.get("active_mode") or "base").strip()
    state.setdefault("active_mode", active_mode)

    memory_enriched_state = container.keyword_memory_service.apply(state.copy(), user_message)
    updated_state = (
        container.state_engine.update_state(memory_enriched_state, user_message)
        if user_message
        else memory_enriched_state
    )
    updated_state["active_mode"] = active_mode

    access_level = str(
        payload.get("access_level")
        or container.access_engine.update_access_level(updated_state)
    ).strip()
    memory_context = container.keyword_memory_service.build_prompt_context(updated_state)
    grounding_kind = container.keyword_memory_service.detect_grounding_need(user_message)

    return {
        "user_message": user_message,
        "active_mode": active_mode,
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


@app.post("/api/actions/cache/invalidate")
async def api_invalidate_cache(_: str = Depends(require_auth)):
    await _invalidate_metrics_cache()
    return {"ok": True}


@app.post("/api/test/prompt")
async def api_test_prompt(request: Request, _: str = Depends(require_auth)):
    payload = await request.json()
    context = _prepare_test_context(payload)
    system_prompt = container.prompt_builder.build_system_prompt(
        state=context["updated_state"],
        access_level=context["access_level"],
        active_mode=context["active_mode"],
        memory_context=context["memory_context"],
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
    context = _prepare_test_context(payload)
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
    context = _prepare_test_context(payload)
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
    system_prompt = container.prompt_builder.build_system_prompt(
        state=context["updated_state"],
        access_level=context["access_level"],
        active_mode=context["active_mode"],
        memory_context=context["memory_context"],
    )
    messages = [{"role": "system", "content": system_prompt}] + history + [
        {"role": "user", "content": context["user_message"]},
    ]
    response_text, tokens_used = await container.openai_client.generate(
        messages=messages,
        model=ai_settings["openai_model"],
        temperature=ai_settings["temperature"],
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
    table{width:100%;border-collapse:collapse;font-size:14px}th,td{padding:9px 8px;border-bottom:1px solid rgba(255,255,255,.08);text-align:left;vertical-align:top}th{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--warn)}
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
          <div class="panel"><h3>Пользователи</h3><div id="recent-users"></div></div>
          <div class="panel"><h3>Платежи</h3><div id="recent-payments"></div></div>
        </div>
        <div class="cols">
          <div class="panel"><h3>Сервисы</h3><div id="health-summary"></div></div>
          <div class="panel"><h3>Поддержка</h3><div id="support-summary"></div></div>
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
              <label>Таймаут<input id="ai_timeout_seconds" type="number"></label>
              <label>Повторы<input id="ai_max_retries" type="number"></label>
              <label>Память, токены<input id="ai_memory_max_tokens" type="number"></label>
              <label>История сообщений<input id="ai_history_message_limit" type="number"></label>
              <label>Debug user ID<input id="ai_debug_prompt_user_id" type="number"></label>
            </div>
            <label class="checkbox"><input id="ai_log_full_prompt" type="checkbox">Логировать системный промпт</label>
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
          <h3>Уровни доступа и free-лимиты</h3>
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
          <div class="two">
            <label>Лимит сообщений в день<input id="limits_free_daily_messages_limit" type="number" min="1"></label>
          </div>
          <label>Текст при исчерпании лимита<textarea id="limits_free_daily_limit_message"></textarea></label>
          <div class="actions"><button class="primary" id="save-safety">Сохранить раздел</button></div>
        </div>
      </section>

      <section class="page" data-view="prompts">
        <div><h2>Промпты</h2><p class="muted">Редактор характера, рамок и правил доступа.</p></div>
        <div class="panel">
          <label>Личность<textarea id="prompt_personality_core"></textarea></label>
          <label>Безопасность<textarea id="prompt_safety_block"></textarea></label>
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
          <div class="panel"><h3>Health</h3><pre id="full-health"></pre></div>
          <div class="panel"><h3>Файлы</h3><pre id="config-files"></pre></div>
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
    const state={settings:null,overview:null,health:null,logs:null};
    const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
    const esc=v=>String(v??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
    async function api(path,options={}){const r=await fetch(path,{headers:{'Content-Type':'application/json',...(options.headers||{})},...options});const d=await r.json().catch(()=>({}));if(!r.ok)throw new Error(d.detail||'Ошибка запроса');return d}
    function notice(text,kind='ok'){const n=$('#notice');n.textContent=text;n.className='notice '+kind}
    function table(cols,rows){if(!rows||!rows.length)return '<div class="muted">Пока нет данных.</div>';return `<table><thead><tr>${cols.map(c=>`<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${cols.map(c=>`<td>${esc(r[c])}</td>`).join('')}</tr>`).join('')}</tbody></table>`}
    function openView(name){$$('.nav button').forEach(b=>b.classList.toggle('active',b.dataset.view===name));$$('.page').forEach(p=>p.classList.toggle('active',p.dataset.view===name))}
    function renderOverview(){if(!state.overview)return;const o=state.overview;const cards=[['Пользователи',o.users.total,`+7д: ${o.users.new_7d}`],['Premium',o.users.premium_total,`Активных: ${o.users.active_with_messages}`],['Сообщения',o.content.messages_total,`+30д: ${o.users.new_30d}`],['Платежи',o.payments.successful_payments,`Выручка: ${o.payments.revenue}`],['AI',`${o.runtime.queue_size}/${o.runtime.queue_capacity}`,`Workers: ${o.runtime.workers}`],['Support',o.support.users_with_support_profile,`panic: ${o.support.episode_counts.panic}`],['Рефералы',o.referrals.total,`Конверсий: ${o.referrals.converted}`]];$('#overview-cards').innerHTML=cards.map(x=>`<div class="card"><div class="stat-label">${x[0]}</div><div class="stat-value">${x[1]}</div><div class="muted">${x[2]}</div></div>`).join('');$('#recent-users').innerHTML=table(['id','username','active_mode','is_premium','created_at'],o.recent.users);$('#recent-payments').innerHTML=table(['user_id','amount','currency','status','event_time'],o.recent.payments);$('#support-summary').innerHTML=`<pre>${esc(JSON.stringify({support:o.support,referrals:o.referrals},null,2))}</pre>`}
    function renderHealth(){if(!state.health)return;$('#sidebar-health').textContent=`DB: ${state.health.db.ok?'ok':'err'} | Redis: ${state.health.redis.detail}`;$('#health-summary').innerHTML=`<pre>${esc(JSON.stringify({db:state.health.db,redis:state.health.redis,ai:state.health.ai_runtime},null,2))}</pre>`;$('#full-health').textContent=JSON.stringify(state.health,null,2);$('#config-files').textContent=JSON.stringify(state.health.config_files,null,2)}
    function renderRuntime(){const r=state.settings.runtime,a=r.ai,c=r.chat,u=r.ui;$('#ai_openai_model').value=a.openai_model;$('#ai_response_language').value=a.response_language;$('#ai_temperature').value=a.temperature;$('#ai_timeout_seconds').value=a.timeout_seconds;$('#ai_max_retries').value=a.max_retries;$('#ai_memory_max_tokens').value=a.memory_max_tokens;$('#ai_history_message_limit').value=a.history_message_limit;$('#ai_debug_prompt_user_id').value=a.debug_prompt_user_id||'';$('#ai_log_full_prompt').checked=!!a.log_full_prompt;$('#chat_typing_action_enabled').checked=!!c.typing_action_enabled;$('#chat_non_text_message').value=c.non_text_message;$('#chat_busy_message').value=c.busy_message;$('#chat_ai_error_message').value=c.ai_error_message;$('#chat_write_prompt_message').value=c.write_prompt_message;$('#ui_write_button_text').value=u.write_button_text;$('#ui_modes_button_text').value=u.modes_button_text;$('#ui_premium_button_text').value=u.premium_button_text;$('#ui_input_placeholder').value=u.input_placeholder;$('#ui_modes_title').value=u.modes_title;$('#ui_user_not_found_text').value=u.user_not_found_text;$('#ui_unknown_mode_text').value=u.unknown_mode_text;$('#ui_mode_locked_text').value=u.mode_locked_text;$('#ui_mode_saved_toast').value=u.mode_saved_toast;$('#ui_mode_saved_template').value=u.mode_saved_template;$('#ui_welcome_user_text').value=u.welcome_user_text;$('#ui_welcome_admin_text').value=u.welcome_admin_text}
    function renderSafety(){const r=state.settings.runtime,s=r.safety,se=r.state_engine,a=r.access,l=r.limits;$('#safety_throttle_rate_limit_seconds').value=s.throttle_rate_limit_seconds;$('#safety_throttle_warning_interval_seconds').value=s.throttle_warning_interval_seconds;$('#safety_max_message_length').value=s.max_message_length;$('#safety_reject_suspicious_messages').checked=!!s.reject_suspicious_messages;$('#safety_throttle_warning_text').value=s.throttle_warning_text;$('#safety_message_too_long_text').value=s.message_too_long_text;$('#safety_suspicious_rejection_text').value=s.suspicious_rejection_text;$('#safety_suspicious_keywords').value=(s.suspicious_keywords||[]).join('\\n');$('#state-defaults-grid').innerHTML=Object.entries(se.defaults).map(([k,v])=>`<label>${k}<input data-state-default="${k}" type="number" step="0.01" value="${v}"></label>`).join('');$('#state_positive_keywords').value=(se.positive_keywords||[]).join('\\n');$('#state_negative_keywords').value=(se.negative_keywords||[]).join('\\n');$('#state_attraction_keywords').value=(se.attraction_keywords||[]).join('\\n');$('#state-effects-grid').innerHTML=Object.entries(se.message_effects).map(([k,v])=>`<label>${k}<input data-state-effect="${k}" type="number" step="0.01" value="${v}"></label>`).join('');$('#access_forced_level').value=a.forced_level||'';$('#access_default_level').value=a.default_level;$('#access_interest_observation_threshold').value=a.interest_observation_threshold;$('#access_rare_layer_instability_threshold').value=a.rare_layer_instability_threshold;$('#access_rare_layer_attraction_threshold').value=a.rare_layer_attraction_threshold;$('#access_personal_focus_attraction_threshold').value=a.personal_focus_attraction_threshold;$('#access_personal_focus_interest_threshold').value=a.personal_focus_interest_threshold;$('#access_tension_attraction_threshold').value=a.tension_attraction_threshold;$('#access_tension_control_threshold').value=a.tension_control_threshold;$('#access_analysis_interest_threshold').value=a.analysis_interest_threshold;$('#access_analysis_control_threshold').value=a.analysis_control_threshold;$('#limits_free_daily_messages_enabled').checked=!!l.free_daily_messages_enabled;$('#limits_free_daily_messages_limit').value=l.free_daily_messages_limit;$('#limits_free_daily_limit_message').value=l.free_daily_limit_message}
    function renderPrompts(){const p=state.settings.prompts;$('#prompt_personality_core').value=p.personality_core;$('#prompt_safety_block').value=p.safety_block;$('#prompt_memory_intro').value=p.memory_intro;$('#prompt_state_intro').value=p.state_intro;$('#prompt_mode_intro').value=p.mode_intro;$('#prompt_access_intro').value=p.access_intro;$('#prompt_final_instruction').value=p.final_instruction;$('#access_observation').value=p.access_rules.observation;$('#access_analysis').value=p.access_rules.analysis;$('#access_tension').value=p.access_rules.tension;$('#access_personal_focus').value=p.access_rules.personal_focus;$('#access_rare_layer').value=p.access_rules.rare_layer}
    function renderModes(){const m=state.settings.modes,c=state.settings.mode_catalog;const keys=Object.keys(c).sort((a,b)=>(c[a].sort_order||0)-(c[b].sort_order||0));$('#modes-container').innerHTML=keys.map(k=>{const meta=c[k],scale=m[k];return `<div class="mode-card"><div class="mode-head"><div><strong>${esc(meta.icon)} ${esc(meta.name)}</strong><div class="muted">${esc(k)}</div></div><span class="badge">${meta.is_premium?'Premium':'Free'}</span></div><div class="three"><label>Название<input data-catalog="${k}.name" value="${esc(meta.name)}"></label><label>Иконка<input data-catalog="${k}.icon" value="${esc(meta.icon)}"></label><label>Порядок<input data-catalog="${k}.sort_order" type="number" value="${meta.sort_order}"></label></div><label class="checkbox"><input data-catalog="${k}.is_premium" type="checkbox" ${meta.is_premium?'checked':''}>Premium</label><label>Описание<textarea data-catalog="${k}.description">${esc(meta.description)}</textarea></label><label>Тон<input data-catalog="${k}.tone" value="${esc(meta.tone)}"></label><label>Эмоциональное состояние<input data-catalog="${k}.emotional_state" value="${esc(meta.emotional_state)}"></label><label>Правила<textarea data-catalog="${k}.behavior_rules">${esc(meta.behavior_rules)}</textarea></label><label>Фраза активации<textarea data-catalog="${k}.activation_phrase">${esc(meta.activation_phrase)}</textarea></label><div class="three">${Object.entries(scale).map(([mk,mv])=>`<label>${mk}<input data-mode-scale="${k}.${mk}" type="number" min="0" max="10" value="${mv}"></label>`).join('')}</div></div>`}).join('')}
    function renderPayments(){const p=state.settings.runtime.payment,ref=state.settings.runtime.referral;$('#payment_provider_token').value=p.provider_token;$('#payment_currency').value=p.currency;$('#payment_price_minor_units').value=p.price_minor_units;$('#payment_product_title').value=p.product_title;$('#payment_product_description').value=p.product_description;$('#payment_premium_benefits_text').value=p.premium_benefits_text;$('#payment_buy_cta_text').value=p.buy_cta_text;$('#payment_unavailable_message').value=p.unavailable_message;$('#payment_invoice_error_message').value=p.invoice_error_message;$('#payment_success_message').value=p.success_message;$('#referral_enabled').checked=!!ref.enabled;$('#referral_start_parameter_prefix').value=ref.start_parameter_prefix;$('#referral_program_title').value=ref.program_title;$('#referral_allow_self_referral').checked=!!ref.allow_self_referral;$('#referral_require_first_paid_invoice').checked=!!ref.require_first_paid_invoice;$('#referral_award_referrer_premium').checked=!!ref.award_referrer_premium;$('#referral_award_referred_user_premium').checked=!!ref.award_referred_user_premium;$('#referral_program_description').value=ref.program_description;$('#referral_share_text_template').value=ref.share_text_template;$('#referral_referred_welcome_message').value=ref.referred_welcome_message;$('#referral_referrer_reward_message').value=ref.referrer_reward_message;$('#recent-referrals').textContent=JSON.stringify((state.overview&&state.overview.recent&&state.overview.recent.referrals)||[],null,2)}
    function renderLogs(){if(state.logs)$('#logs-output').textContent=(state.logs.lines||[]).join('\\n')||'Лог пуст.'}
    function runtimePayload(){return {ai:{openai_model:$('#ai_openai_model').value.trim(),response_language:$('#ai_response_language').value.trim(),temperature:Number($('#ai_temperature').value),timeout_seconds:Number($('#ai_timeout_seconds').value),max_retries:Number($('#ai_max_retries').value),memory_max_tokens:Number($('#ai_memory_max_tokens').value),history_message_limit:Number($('#ai_history_message_limit').value),debug_prompt_user_id:$('#ai_debug_prompt_user_id').value.trim()||null,log_full_prompt:$('#ai_log_full_prompt').checked},chat:{typing_action_enabled:$('#chat_typing_action_enabled').checked,non_text_message:$('#chat_non_text_message').value,busy_message:$('#chat_busy_message').value,ai_error_message:$('#chat_ai_error_message').value,write_prompt_message:$('#chat_write_prompt_message').value},ui:{write_button_text:$('#ui_write_button_text').value,modes_button_text:$('#ui_modes_button_text').value,premium_button_text:$('#ui_premium_button_text').value,input_placeholder:$('#ui_input_placeholder').value,modes_title:$('#ui_modes_title').value,user_not_found_text:$('#ui_user_not_found_text').value,unknown_mode_text:$('#ui_unknown_mode_text').value,mode_locked_text:$('#ui_mode_locked_text').value,mode_saved_toast:$('#ui_mode_saved_toast').value,mode_saved_template:$('#ui_mode_saved_template').value,welcome_user_text:$('#ui_welcome_user_text').value,welcome_admin_text:$('#ui_welcome_admin_text').value}}}
    function safetyPayload(){const defaults={},effects={};document.querySelectorAll('[data-state-default]').forEach(i=>defaults[i.dataset.stateDefault]=Number(i.value));document.querySelectorAll('[data-state-effect]').forEach(i=>effects[i.dataset.stateEffect]=Number(i.value));return {safety:{throttle_rate_limit_seconds:Number($('#safety_throttle_rate_limit_seconds').value),throttle_warning_interval_seconds:Number($('#safety_throttle_warning_interval_seconds').value),max_message_length:Number($('#safety_max_message_length').value),reject_suspicious_messages:$('#safety_reject_suspicious_messages').checked,throttle_warning_text:$('#safety_throttle_warning_text').value,message_too_long_text:$('#safety_message_too_long_text').value,suspicious_rejection_text:$('#safety_suspicious_rejection_text').value,suspicious_keywords:$('#safety_suspicious_keywords').value},state_engine:{defaults,positive_keywords:$('#state_positive_keywords').value,negative_keywords:$('#state_negative_keywords').value,attraction_keywords:$('#state_attraction_keywords').value,message_effects:effects},access:{forced_level:$('#access_forced_level').value.trim(),default_level:$('#access_default_level').value.trim(),interest_observation_threshold:Number($('#access_interest_observation_threshold').value),rare_layer_instability_threshold:Number($('#access_rare_layer_instability_threshold').value),rare_layer_attraction_threshold:Number($('#access_rare_layer_attraction_threshold').value),personal_focus_attraction_threshold:Number($('#access_personal_focus_attraction_threshold').value),personal_focus_interest_threshold:Number($('#access_personal_focus_interest_threshold').value),tension_attraction_threshold:Number($('#access_tension_attraction_threshold').value),tension_control_threshold:Number($('#access_tension_control_threshold').value),analysis_interest_threshold:Number($('#access_analysis_interest_threshold').value),analysis_control_threshold:Number($('#access_analysis_control_threshold').value)},limits:{free_daily_messages_enabled:$('#limits_free_daily_messages_enabled').checked,free_daily_messages_limit:Number($('#limits_free_daily_messages_limit').value),free_daily_limit_message:$('#limits_free_daily_limit_message').value}}}
    function promptsPayload(){return {personality_core:$('#prompt_personality_core').value,safety_block:$('#prompt_safety_block').value,memory_intro:$('#prompt_memory_intro').value,state_intro:$('#prompt_state_intro').value,mode_intro:$('#prompt_mode_intro').value,access_intro:$('#prompt_access_intro').value,final_instruction:$('#prompt_final_instruction').value,access_rules:{observation:$('#access_observation').value,analysis:$('#access_analysis').value,tension:$('#access_tension').value,personal_focus:$('#access_personal_focus').value,rare_layer:$('#access_rare_layer').value}}}
    function modesPayload(){const modes={},catalog={};document.querySelectorAll('[data-mode-scale]').forEach(i=>{const [m,k]=i.dataset.modeScale.split('.');modes[m]??={};modes[m][k]=Number(i.value)});document.querySelectorAll('[data-catalog]').forEach(i=>{const [m,k]=i.dataset.catalog.split('.');catalog[m]??={};catalog[m][k]=i.type==='checkbox'?i.checked:(k==='sort_order'?Number(i.value):i.value)});return {modes,catalog}}
    function paymentsPayload(){return {payment:{provider_token:$('#payment_provider_token').value,currency:$('#payment_currency').value,price_minor_units:Number($('#payment_price_minor_units').value),product_title:$('#payment_product_title').value,product_description:$('#payment_product_description').value,premium_benefits_text:$('#payment_premium_benefits_text').value,buy_cta_text:$('#payment_buy_cta_text').value,unavailable_message:$('#payment_unavailable_message').value,invoice_error_message:$('#payment_invoice_error_message').value,success_message:$('#payment_success_message').value},referral:{enabled:$('#referral_enabled').checked,start_parameter_prefix:$('#referral_start_parameter_prefix').value,program_title:$('#referral_program_title').value,allow_self_referral:$('#referral_allow_self_referral').checked,require_first_paid_invoice:$('#referral_require_first_paid_invoice').checked,award_referrer_premium:$('#referral_award_referrer_premium').checked,award_referred_user_premium:$('#referral_award_referred_user_premium').checked,program_description:$('#referral_program_description').value,share_text_template:$('#referral_share_text_template').value,referred_welcome_message:$('#referral_referred_welcome_message').value,referrer_reward_message:$('#referral_referrer_reward_message').value}}}
    function testPayload(){return {active_mode:$('#test_active_mode').value.trim(),access_level:$('#test_access_level').value.trim(),user_message:$('#test_user_message').value,history:$('#test_history').value,state:$('#test_state').value}}
    async function refreshAll(){const [overview,health,settingsData,logs]=await Promise.all([api('/api/overview'),api('/api/health'),api('/api/settings'),api(`/api/logs?lines=${$('#log-lines').value||200}`)]);state.overview=overview;state.health=health;state.settings=settingsData;state.logs=logs;renderOverview();renderHealth();renderRuntime();renderSafety();renderPrompts();renderModes();renderPayments();renderLogs()}
    async function save(path,payload,msg){await api(path,{method:'PUT',body:JSON.stringify(payload)});await refreshAll();notice(msg)}
    async function runTest(path){const data=await api(path,{method:'POST',body:JSON.stringify(testPayload())});$('#test-result').textContent=JSON.stringify(data,null,2)}
    $$('.nav button').forEach(b=>b.addEventListener('click',()=>openView(b.dataset.view)));
    $('#refresh-all').addEventListener('click',()=>refreshAll().then(()=>notice('Данные обновлены.')).catch(e=>notice(e.message,'error')));
    $('#reload-logs').addEventListener('click',()=>api(`/api/logs?lines=${$('#log-lines').value}`).then(d=>{state.logs=d;renderLogs();notice('Логи обновлены.')}).catch(e=>notice(e.message,'error')));
    $('#invalidate-cache').addEventListener('click',()=>api('/api/actions/cache/invalidate',{method:'POST'}).then(()=>refreshAll()).then(()=>notice('Кеш сброшен.')).catch(e=>notice(e.message,'error')));
    $('#export-json').addEventListener('click',()=>api('/api/export').then(d=>{const blob=new Blob([JSON.stringify(d,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='bot-admin-export.json';a.click();URL.revokeObjectURL(url);notice('Экспорт подготовлен.')}).catch(e=>notice(e.message,'error')));
    $('#save-runtime').addEventListener('click',()=>save('/api/settings/runtime',runtimePayload(),'Настройки AI и UI сохранены.').catch(e=>notice(e.message,'error')));
    $('#save-safety').addEventListener('click',()=>save('/api/settings/runtime',safetyPayload(),'Настройки безопасности сохранены.').catch(e=>notice(e.message,'error')));
    $('#save-prompts').addEventListener('click',()=>save('/api/settings/prompts',promptsPayload(),'Промпты сохранены.').catch(e=>notice(e.message,'error')));
    $('#save-modes').addEventListener('click',async()=>{try{const p=modesPayload();await api('/api/settings/modes',{method:'PUT',body:JSON.stringify(p.modes)});await api('/api/settings/mode-catalog',{method:'PUT',body:JSON.stringify(p.catalog)});await refreshAll();notice('Режимы сохранены.')}catch(e){notice(e.message,'error')}})
    $('#save-payments').addEventListener('click',()=>save('/api/settings/runtime',paymentsPayload(),'Платежные настройки сохранены.').catch(e=>notice(e.message,'error')));
    $('#test-prompt').addEventListener('click',()=>runTest('/api/test/prompt').then(()=>notice('Промпт готов.')).catch(e=>notice(e.message,'error')));
    $('#test-state-btn').addEventListener('click',()=>runTest('/api/test/state').then(()=>notice('State пересчитан.')).catch(e=>notice(e.message,'error')));
    $('#test-live-reply').addEventListener('click',()=>{$('#test-result').textContent='Жду ответ модели...';runTest('/api/test/reply').then(()=>notice('Live-тест завершен.')).catch(e=>notice(e.message,'error'))});
    refreshAll().catch(e=>notice(e.message,'error'));
  </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def dashboard(_: str = Depends(require_auth)):
    return _dashboard_html()

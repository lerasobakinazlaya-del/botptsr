import secrets
from contextlib import asynccontextmanager

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

    container.admin_metrics = AdminMetricsService(
        user_service=container.user_service,
        message_repository=container.message_repository,
        payment_repository=container.payment_repository,
        state_repository=container.state_repository,
        ai_service=container.ai_service,
        redis=container.redis,
        cache_ttl=settings.admin_dashboard_cache_ttl,
    )

    yield

    await container.db.close()
    if container.redis is not None:
        await container.redis.aclose()


app = FastAPI(title="Админка бота", lifespan=lifespan)


@app.get("/api/overview")
async def api_overview(_: str = Depends(require_auth)):
    return await container.admin_metrics.get_overview()


@app.get("/api/settings")
async def api_settings(_: str = Depends(require_auth)):
    return {
        "runtime": container.admin_settings_service.get_runtime_settings(),
        "prompts": container.admin_settings_service.get_prompt_templates(),
        "modes": container.admin_settings_service.get_modes(),
    }


@app.put("/api/settings/runtime")
async def api_runtime_settings(request: Request, _: str = Depends(require_auth)):
    payload = await request.json()
    try:
        return container.admin_settings_service.update_runtime_settings(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/settings/prompts")
async def api_prompt_settings(request: Request, _: str = Depends(require_auth)):
    payload = await request.json()
    try:
        return container.admin_settings_service.update_prompt_templates(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put("/api/settings/modes")
async def api_mode_settings(request: Request, _: str = Depends(require_auth)):
    payload = await request.json()
    try:
        return container.admin_settings_service.update_modes(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/logs")
async def api_logs(lines: int = 200, _: str = Depends(require_auth)):
    return container.admin_settings_service.get_logs(lines=lines)


@app.get("/", response_class=HTMLResponse)
async def dashboard(_: str = Depends(require_auth)):
    return """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Админка бота</title>
  <style>
    :root {
      --bg: #07111f;
      --bg2: #0c1c30;
      --panel: rgba(11, 27, 46, 0.88);
      --text: #eef4ff;
      --muted: #99aec8;
      --accent: #7ee787;
      --accent-2: #ffd166;
      --danger: #ff7b72;
      --border: rgba(126, 231, 135, 0.18);
      --shadow: 0 18px 50px rgba(0, 0, 0, 0.28);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: var(--text);
      font-family: "Segoe UI", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(126, 231, 135, 0.14), transparent 28%),
        radial-gradient(circle at top right, rgba(255, 209, 102, 0.14), transparent 26%),
        linear-gradient(145deg, var(--bg), var(--bg2));
    }
    .wrap {
      max-width: 1440px;
      margin: 0 auto;
      padding: 28px 18px 48px;
    }
    h1, h2, h3, p { margin-top: 0; }
    h1 { font-size: 38px; margin-bottom: 8px; }
    h2 { font-size: 24px; margin-bottom: 16px; }
    h3 { font-size: 18px; margin-bottom: 10px; }
    .subtitle { color: var(--muted); margin-bottom: 24px; max-width: 780px; }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }
    .stack {
      display: grid;
      gap: 18px;
    }
    .cols {
      display: grid;
      grid-template-columns: 1.2fr 1fr;
      gap: 18px;
      align-items: start;
    }
    .triple {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 18px;
    }
    .panel, .card {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 22px;
      padding: 18px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(8px);
    }
    .label {
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .08em;
      margin-bottom: 8px;
    }
    .value {
      font-size: 30px;
      font-weight: 700;
      margin-bottom: 8px;
    }
    .hint, .status {
      color: var(--muted);
      font-size: 14px;
    }
    .status.ok { color: var(--accent); }
    .status.error { color: var(--danger); }
    .toolbar {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-bottom: 14px;
    }
    button {
      border: 0;
      border-radius: 12px;
      padding: 11px 16px;
      font-weight: 600;
      cursor: pointer;
      background: linear-gradient(135deg, var(--accent), #55d8a0);
      color: #062312;
    }
    button.secondary {
      background: rgba(255,255,255,0.07);
      color: var(--text);
      border: 1px solid rgba(255,255,255,0.08);
    }
    button.warn {
      background: linear-gradient(135deg, var(--accent-2), #ffb347);
      color: #241400;
    }
    table {
      width: 100%;
      border-collapse: collapse;
    }
    th, td {
      padding: 10px 12px;
      text-align: left;
      border-bottom: 1px solid rgba(255,255,255,.08);
      vertical-align: top;
    }
    th {
      color: var(--accent-2);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .08em;
    }
    input, textarea, select {
      width: 100%;
      margin-top: 6px;
      margin-bottom: 12px;
      border-radius: 12px;
      border: 1px solid rgba(255,255,255,0.12);
      background: rgba(7, 17, 31, 0.75);
      color: var(--text);
      padding: 11px 12px;
      font: inherit;
    }
    textarea {
      min-height: 140px;
      resize: vertical;
      line-height: 1.45;
    }
    .mono {
      font-family: Consolas, "Courier New", monospace;
      font-size: 13px;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .log-box {
      min-height: 460px;
      max-height: 720px;
      overflow: auto;
      padding: 14px;
      border-radius: 16px;
      background: rgba(2, 9, 18, 0.8);
      border: 1px solid rgba(255,255,255,0.08);
      white-space: pre-wrap;
    }
    .mode-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 16px;
    }
    .range-row {
      display: grid;
      grid-template-columns: 1fr 70px;
      gap: 10px;
      align-items: center;
      margin-bottom: 10px;
    }
    .range-row input[type=number] {
      margin: 0;
    }
    .small {
      font-size: 13px;
      color: var(--muted);
    }
    @media (max-width: 1100px) {
      .cols, .triple { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Админка бота</h1>
    <p class="subtitle">
      Здесь можно смотреть метрики и логи, а также менять модель, параметры генерации,
      системные промпты и шкалы режимов без правок кода.
    </p>

    <section class="panel">
      <div class="toolbar">
        <button onclick="loadOverview()">Обновить обзор</button>
        <button class="secondary" onclick="loadLogs()">Обновить логи</button>
        <button class="secondary" onclick="loadSettings()">Перечитать настройки</button>
      </div>
      <div class="grid" id="cards"></div>
    </section>

    <div class="cols" style="margin-top:18px;">
      <section class="panel">
        <h2>Обзор за дни</h2>
        <table>
          <thead>
            <tr>
              <th>День</th>
              <th>Новые пользователи</th>
              <th>Успешные оплаты</th>
              <th>Первые оплаты</th>
              <th>Выручка</th>
            </tr>
          </thead>
          <tbody id="series-body"></tbody>
        </table>
      </section>

      <section class="stack">
        <div class="panel">
          <h2>Состояние рантайма</h2>
          <table><tbody id="runtime-body"></tbody></table>
        </div>
        <div class="panel">
          <h2>Сигналы поддержки</h2>
          <table><tbody id="support-body"></tbody></table>
        </div>
      </section>
    </div>

    <div class="cols" style="margin-top:18px;">
      <section class="panel">
        <h2>Последние пользователи</h2>
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Username</th>
              <th>Имя</th>
              <th>Premium</th>
              <th>Создан</th>
            </tr>
          </thead>
          <tbody id="recent-users-body"></tbody>
        </table>
      </section>

      <section class="panel">
        <h2>Последние оплаты</h2>
        <table>
          <thead>
            <tr>
              <th>ID пользователя</th>
              <th>Сумма</th>
              <th>Статус</th>
              <th>Первая</th>
              <th>Время</th>
            </tr>
          </thead>
          <tbody id="recent-payments-body"></tbody>
        </table>
      </section>
    </div>

    <div class="cols" style="margin-top:18px;">
      <section class="panel">
        <h2>Логи бота</h2>
        <div class="toolbar">
          <select id="log-lines" onchange="loadLogs()">
            <option value="100">100 строк</option>
            <option value="200" selected>200 строк</option>
            <option value="500">500 строк</option>
          </select>
          <span class="status" id="log-meta"></span>
        </div>
        <div class="log-box mono" id="log-box">Загрузка логов...</div>
      </section>

      <section class="stack">
        <div class="panel">
          <h2>Настройки ИИ</h2>
          <label>Модель
            <input id="openai_model" placeholder="gpt-4o-mini">
          </label>
          <label>Temperature
            <input id="temperature" type="number" step="0.1" min="0" max="2">
          </label>
          <label>Таймаут запроса, сек
            <input id="timeout_seconds" type="number" min="1">
          </label>
          <label>Повторные попытки
            <input id="max_retries" type="number" min="0">
          </label>
          <label>Лимит памяти, условные токены
            <input id="memory_max_tokens" type="number" min="100">
          </label>
          <label>ID пользователя для логирования полного промпта
            <input id="debug_prompt_user_id" type="number" min="1" placeholder="пусто = для всех">
          </label>
          <label>
            <input id="log_full_prompt" type="checkbox" style="width:auto; margin-right:8px;">
            Логировать полный системный промпт
          </label>
          <button onclick="saveRuntimeSettings()">Сохранить настройки ИИ</button>
          <p class="small">Изменения применяются без редактирования кода. Размер очереди и число воркеров по-прежнему задаются при старте приложения.</p>
          <div class="status" id="runtime-save-status"></div>
        </div>
      </section>
    </div>

    <div class="triple" style="margin-top:18px;">
      <section class="panel">
        <h2>Базовые промпты</h2>
        <label>Ядро личности
          <textarea id="personality_core"></textarea>
        </label>
        <label>Блок безопасности
          <textarea id="safety_block"></textarea>
        </label>
        <button onclick="savePrompts()">Сохранить промпты</button>
      </section>

      <section class="panel">
        <h2>Структура промпта</h2>
        <label>Заголовок памяти
          <input id="memory_intro">
        </label>
        <label>Заголовок состояния
          <input id="state_intro">
        </label>
        <label>Заголовок режима
          <input id="mode_intro">
        </label>
        <label>Заголовок доступа
          <input id="access_intro">
        </label>
        <label>Финальная инструкция
          <textarea id="final_instruction"></textarea>
        </label>
      </section>

      <section class="panel">
        <h2>Правила доступа</h2>
        <label>Observation
          <textarea id="access_observation"></textarea>
        </label>
        <label>Analysis
          <textarea id="access_analysis"></textarea>
        </label>
        <label>Tension
          <textarea id="access_tension"></textarea>
        </label>
        <label>Personal focus
          <textarea id="access_personal_focus"></textarea>
        </label>
        <label>Rare layer
          <textarea id="access_rare_layer"></textarea>
        </label>
        <div class="status" id="prompts-save-status"></div>
      </section>
    </div>

    <section class="panel" style="margin-top:18px;">
      <h2>Точные настройки режимов</h2>
      <p class="hint">Каждое значение от 1 до 10. После сохранения новые шкалы начнут использоваться в системном промпте.</p>
      <div class="mode-grid" id="mode-grid"></div>
      <div class="toolbar" style="margin-top:16px;">
        <button class="warn" onclick="saveModes()">Сохранить шкалы режимов</button>
        <div class="status" id="modes-save-status"></div>
      </div>
    </section>
  </div>

  <script>
    const cards = document.getElementById('cards');
    const seriesBody = document.getElementById('series-body');
    const runtimeBody = document.getElementById('runtime-body');
    const supportBody = document.getElementById('support-body');
    const recentUsersBody = document.getElementById('recent-users-body');
    const recentPaymentsBody = document.getElementById('recent-payments-body');
    const logBox = document.getElementById('log-box');
    const logMeta = document.getElementById('log-meta');
    const modeGrid = document.getElementById('mode-grid');

    function safe(value) {
      if (value === null || value === undefined || value === '') return '—';
      return String(value);
    }

    function setStatus(id, text, isError = false) {
      const el = document.getElementById(id);
      el.textContent = text;
      el.className = isError ? 'status error' : 'status ok';
    }

    function addCard(label, value, extra = '') {
      const el = document.createElement('div');
      el.className = 'card';
      el.innerHTML = `<div class="label">${label}</div><div class="value">${value}</div><div class="hint">${extra}</div>`;
      cards.appendChild(el);
    }

    function appendKeyValueRow(target, label, value) {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${label}</td><td class="mono">${safe(value)}</td>`;
      target.appendChild(tr);
    }

    async function fetchJson(url, options = {}) {
      const response = await fetch(url, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
      });
      if (!response.ok) {
        let detail = 'Ошибка запроса';
        try {
          const payload = await response.json();
          detail = payload.detail || detail;
        } catch (_) {}
        throw new Error(detail);
      }
      return response.json();
    }

    async function loadOverview() {
      const data = await fetchJson('/api/overview');
      cards.innerHTML = '';
      seriesBody.innerHTML = '';
      runtimeBody.innerHTML = '';
      supportBody.innerHTML = '';
      recentUsersBody.innerHTML = '';
      recentPaymentsBody.innerHTML = '';

      addCard('Всего пользователей', data.users.total, `+1 день: ${data.users.new_1d} • +7 дней: ${data.users.new_7d} • +30 дней: ${data.users.new_30d}`);
      addCard('Premium-пользователи', data.users.premium_total, `Активны в сообщениях: ${data.users.active_with_messages}`);
      addCard('Успешные оплаты', data.payments.successful_payments, `+1 день: ${data.payments.successful_1d} • +7 дней: ${data.payments.successful_7d}`);
      addCard('Первые оплаты', data.payments.first_payments, `+1 день: ${data.payments.first_1d} • +7 дней: ${data.payments.first_7d}`);
      addCard('Выручка', data.payments.revenue, `Платящих пользователей: ${data.payments.paid_users}`);
      addCard('Сообщений в базе', data.content.messages_total, `Очередь ИИ: ${data.runtime.queue_size}/${data.runtime.queue_capacity}`);
      addCard('Профили поддержки', data.support.users_with_support_profile, `Паника: ${data.support.episode_counts.panic} • Флэшбек: ${data.support.episode_counts.flashback} • Бессонница: ${data.support.episode_counts.insomnia}`);

      const usersMap = Object.fromEntries((data.series.users || []).map(item => [item.day, item.users_count]));
      const paymentsMap = Object.fromEntries((data.series.payments || []).map(item => [item.day, item]));
      const days = [...new Set([...Object.keys(usersMap), ...Object.keys(paymentsMap)])].sort();

      days.forEach(day => {
        const payment = paymentsMap[day] || { successful_payments: 0, first_payments: 0, revenue: 0 };
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${day}</td>
          <td>${usersMap[day] || 0}</td>
          <td>${payment.successful_payments || 0}</td>
          <td>${payment.first_payments || 0}</td>
          <td>${payment.revenue || 0}</td>
        `;
        seriesBody.appendChild(tr);
      });

      appendKeyValueRow(runtimeBody, 'Воркеры запущены', data.runtime.started);
      appendKeyValueRow(runtimeBody, 'Количество воркеров', data.runtime.workers);
      appendKeyValueRow(runtimeBody, 'Параллельных запросов', data.runtime.max_parallel_requests);
      appendKeyValueRow(runtimeBody, 'Очередь', `${data.runtime.queue_size}/${data.runtime.queue_capacity}`);

      appendKeyValueRow(supportBody, 'Пользователей с профилем поддержки', data.support.users_with_support_profile);
      appendKeyValueRow(supportBody, 'Эпизоды паники', data.support.episode_counts.panic);
      appendKeyValueRow(supportBody, 'Флэшбеки', data.support.episode_counts.flashback);
      appendKeyValueRow(supportBody, 'Бессонница', data.support.episode_counts.insomnia);

      (data.recent.users || []).forEach(user => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td class="mono">${safe(user.id)}</td>
          <td>${safe(user.username)}</td>
          <td>${safe(user.first_name)}</td>
          <td>${user.is_premium ? 'да' : 'нет'}</td>
          <td>${safe(user.created_at)}</td>
        `;
        recentUsersBody.appendChild(tr);
      });

      (data.recent.payments || []).forEach(payment => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td class="mono">${safe(payment.user_id)}</td>
          <td>${safe(payment.amount)} ${safe(payment.currency)}</td>
          <td>${safe(payment.status)}</td>
          <td>${payment.is_first_payment ? 'да' : 'нет'}</td>
          <td>${safe(payment.event_time)}</td>
        `;
        recentPaymentsBody.appendChild(tr);
      });
    }

    async function loadLogs() {
      const lines = document.getElementById('log-lines').value;
      const data = await fetchJson(`/api/logs?lines=${lines}`);
      if (!data.exists) {
        logBox.textContent = 'Лог-файл пока не найден.';
        logMeta.textContent = data.path;
        return;
      }
      const updated = data.updated_at ? new Date(data.updated_at * 1000).toLocaleString('ru-RU') : '—';
      logMeta.textContent = `${data.path} • ${data.size_bytes} байт • обновлен: ${updated}`;
      logBox.textContent = (data.lines || []).join('\\n') || 'Лог пока пуст.';
      logBox.scrollTop = logBox.scrollHeight;
    }

    function fillRuntime(runtime) {
      document.getElementById('openai_model').value = runtime.openai_model || '';
      document.getElementById('temperature').value = runtime.temperature;
      document.getElementById('timeout_seconds').value = runtime.timeout_seconds;
      document.getElementById('max_retries').value = runtime.max_retries;
      document.getElementById('memory_max_tokens').value = runtime.memory_max_tokens;
      document.getElementById('debug_prompt_user_id').value = runtime.debug_prompt_user_id || '';
      document.getElementById('log_full_prompt').checked = Boolean(runtime.log_full_prompt);
    }

    function fillPrompts(prompts) {
      document.getElementById('personality_core').value = prompts.personality_core || '';
      document.getElementById('safety_block').value = prompts.safety_block || '';
      document.getElementById('memory_intro').value = prompts.memory_intro || '';
      document.getElementById('state_intro').value = prompts.state_intro || '';
      document.getElementById('mode_intro').value = prompts.mode_intro || '';
      document.getElementById('access_intro').value = prompts.access_intro || '';
      document.getElementById('final_instruction').value = prompts.final_instruction || '';
      document.getElementById('access_observation').value = prompts.access_rules?.observation || '';
      document.getElementById('access_analysis').value = prompts.access_rules?.analysis || '';
      document.getElementById('access_tension').value = prompts.access_rules?.tension || '';
      document.getElementById('access_personal_focus').value = prompts.access_rules?.personal_focus || '';
      document.getElementById('access_rare_layer').value = prompts.access_rules?.rare_layer || '';
    }

    function renderModes(modes) {
      modeGrid.innerHTML = '';
      Object.entries(modes || {}).forEach(([modeName, values]) => {
        const metrics = Object.entries(values || {}).map(([key, value]) => `
          <label class="range-row">
            <span>${key}</span>
            <input type="number" min="1" max="10" value="${value}" data-mode="${modeName}" data-metric="${key}">
          </label>
        `).join('');
        const section = document.createElement('div');
        section.className = 'card';
        section.innerHTML = `<h3>${modeName}</h3>${metrics}`;
        modeGrid.appendChild(section);
      });
    }

    async function loadSettings() {
      const data = await fetchJson('/api/settings');
      fillRuntime(data.runtime);
      fillPrompts(data.prompts);
      renderModes(data.modes);
    }

    async function saveRuntimeSettings() {
      try {
        const payload = {
          openai_model: document.getElementById('openai_model').value.trim(),
          temperature: Number(document.getElementById('temperature').value),
          timeout_seconds: Number(document.getElementById('timeout_seconds').value),
          max_retries: Number(document.getElementById('max_retries').value),
          memory_max_tokens: Number(document.getElementById('memory_max_tokens').value),
          debug_prompt_user_id: document.getElementById('debug_prompt_user_id').value.trim() || null,
          log_full_prompt: document.getElementById('log_full_prompt').checked,
        };
        await fetchJson('/api/settings/runtime', {
          method: 'PUT',
          body: JSON.stringify(payload),
        });
        setStatus('runtime-save-status', 'Настройки ИИ сохранены.');
      } catch (error) {
        setStatus('runtime-save-status', error.message, true);
      }
    }

    async function savePrompts() {
      try {
        const payload = {
          personality_core: document.getElementById('personality_core').value,
          safety_block: document.getElementById('safety_block').value,
          memory_intro: document.getElementById('memory_intro').value,
          state_intro: document.getElementById('state_intro').value,
          mode_intro: document.getElementById('mode_intro').value,
          access_intro: document.getElementById('access_intro').value,
          final_instruction: document.getElementById('final_instruction').value,
          access_rules: {
            observation: document.getElementById('access_observation').value,
            analysis: document.getElementById('access_analysis').value,
            tension: document.getElementById('access_tension').value,
            personal_focus: document.getElementById('access_personal_focus').value,
            rare_layer: document.getElementById('access_rare_layer').value,
          }
        };
        await fetchJson('/api/settings/prompts', {
          method: 'PUT',
          body: JSON.stringify(payload),
        });
        setStatus('prompts-save-status', 'Промпты сохранены.');
      } catch (error) {
        setStatus('prompts-save-status', error.message, true);
      }
    }

    async function saveModes() {
      try {
        const payload = {};
        document.querySelectorAll('[data-mode][data-metric]').forEach(input => {
          const mode = input.dataset.mode;
          const metric = input.dataset.metric;
          payload[mode] = payload[mode] || {};
          payload[mode][metric] = Number(input.value);
        });
        await fetchJson('/api/settings/modes', {
          method: 'PUT',
          body: JSON.stringify(payload),
        });
        setStatus('modes-save-status', 'Шкалы режимов сохранены.');
      } catch (error) {
        setStatus('modes-save-status', error.message, true);
      }
    }

    Promise.all([loadOverview(), loadLogs(), loadSettings()]).catch(error => {
      console.error(error);
    });
  </script>
</body>
</html>
"""

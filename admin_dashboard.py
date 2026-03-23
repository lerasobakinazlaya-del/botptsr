import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, status
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
            detail="Invalid credentials",
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
    await container.redis.aclose()


app = FastAPI(title="Bot Admin Dashboard", lifespan=lifespan)


@app.get("/api/overview")
async def api_overview(_: str = Depends(require_auth)):
    return await container.admin_metrics.get_overview()


@app.get("/", response_class=HTMLResponse)
async def dashboard(_: str = Depends(require_auth)):
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bot Admin</title>
  <style>
    :root {
      --bg: #0d1321;
      --panel: rgba(20, 32, 51, 0.92);
      --text: #f0ebd8;
      --muted: #b9c3d6;
      --accent: #f4b942;
      --border: rgba(244, 185, 66, 0.18);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", sans-serif;
      background: linear-gradient(135deg, #0d1321, #1d2d44 60%, #3e5c76);
      color: var(--text);
    }
    .wrap {
      max-width: 1280px;
      margin: 0 auto;
      padding: 32px 20px 48px;
    }
    h1 {
      margin: 0 0 8px;
      font-size: 36px;
    }
    .subtitle {
      color: var(--muted);
      margin-bottom: 24px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }
    .card, .panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 18px;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.18);
    }
    .label {
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 8px;
      text-transform: uppercase;
      letter-spacing: .08em;
    }
    .value {
      font-size: 30px;
      font-weight: 700;
    }
    .section {
      margin-top: 18px;
    }
    .split {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 18px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      overflow: hidden;
      background: transparent;
      border-radius: 16px;
    }
    th, td {
      text-align: left;
      padding: 12px 14px;
      border-bottom: 1px solid rgba(255,255,255,.08);
      vertical-align: top;
    }
    th {
      color: var(--accent);
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: .08em;
    }
    .mono {
      font-family: Consolas, monospace;
      font-size: 13px;
      word-break: break-word;
    }
    @media (max-width: 900px) {
      .split {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Bot Admin</h1>
    <div class="subtitle">Separate server dashboard for users, payments, revenue, and operational visibility.</div>

    <div class="grid" id="cards"></div>

    <div class="section panel">
      <h2>Daily overview</h2>
      <table>
        <thead>
          <tr>
            <th>Day</th>
            <th>New users</th>
            <th>Successful payments</th>
            <th>First payments</th>
            <th>Revenue</th>
          </tr>
        </thead>
        <tbody id="series-body"></tbody>
      </table>
    </div>

    <div class="section panel">
      <h2>Runtime</h2>
      <table>
        <tbody id="runtime-body"></tbody>
      </table>
    </div>

    <div class="section panel">
      <h2>Support signals</h2>
      <table>
        <tbody id="support-body"></tbody>
      </table>
    </div>

    <div class="section split">
      <div class="panel">
        <h2>Recent users</h2>
        <table>
          <thead>
            <tr>
              <th>User ID</th>
              <th>Username</th>
              <th>Name</th>
              <th>Premium</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody id="recent-users-body"></tbody>
        </table>
      </div>

      <div class="panel">
        <h2>Recent payments</h2>
        <table>
          <thead>
            <tr>
              <th>User ID</th>
              <th>Amount</th>
              <th>Status</th>
              <th>First</th>
              <th>Time</th>
            </tr>
          </thead>
          <tbody id="recent-payments-body"></tbody>
        </table>
      </div>
    </div>
  </div>

  <script>
    const cards = document.getElementById('cards');
    const seriesBody = document.getElementById('series-body');
    const runtimeBody = document.getElementById('runtime-body');
    const supportBody = document.getElementById('support-body');
    const recentUsersBody = document.getElementById('recent-users-body');
    const recentPaymentsBody = document.getElementById('recent-payments-body');

    function addCard(label, value, extra = '') {
      const el = document.createElement('div');
      el.className = 'card';
      el.innerHTML = `<div class="label">${label}</div><div class="value">${value}</div><div>${extra}</div>`;
      cards.appendChild(el);
    }

    function runtimeRow(label, value) {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${label}</td><td class="mono">${value}</td>`;
      runtimeBody.appendChild(tr);
    }

    function supportRow(label, value) {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td>${label}</td><td class="mono">${value}</td>`;
      supportBody.appendChild(tr);
    }

    function safe(value) {
      if (value === null || value === undefined || value === '') {
        return '-';
      }
      return String(value);
    }

    async function load() {
      const res = await fetch('/api/overview');
      const data = await res.json();

      addCard('Total users', data.users.total, `+1d: ${data.users.new_1d} | +7d: ${data.users.new_7d} | +30d: ${data.users.new_30d}`);
      addCard('Premium users', data.users.premium_total, `With messages: ${data.users.active_with_messages}`);
      addCard('Successful payments', data.payments.successful_payments, `+1d: ${data.payments.successful_1d} | +7d: ${data.payments.successful_7d}`);
      addCard('First payments', data.payments.first_payments, `+1d: ${data.payments.first_1d} | +7d: ${data.payments.first_7d}`);
      addCard('Revenue', data.payments.revenue, `Paying users: ${data.payments.paid_users}`);
      addCard('Messages stored', data.content.messages_total, `AI queue: ${data.runtime.queue_size}/${data.runtime.queue_capacity}`);
      addCard('Support profiles', data.support.users_with_support_profile, `Panic: ${data.support.episode_counts.panic} | Flashback: ${data.support.episode_counts.flashback} | Insomnia: ${data.support.episode_counts.insomnia}`);

      const usersMap = Object.fromEntries(data.series.users.map(item => [item.day, item.users_count]));
      const paymentsMap = Object.fromEntries(data.series.payments.map(item => [item.day, item]));
      const days = new Set([...Object.keys(usersMap), ...Object.keys(paymentsMap)]);

      [...days].sort().forEach(day => {
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

      runtimeRow('Workers started', data.runtime.started);
      runtimeRow('Workers count', data.runtime.workers);
      runtimeRow('Max parallel requests', data.runtime.max_parallel_requests);
      runtimeRow('Queue size', `${data.runtime.queue_size}/${data.runtime.queue_capacity}`);

      supportRow('Users with support profile', data.support.users_with_support_profile);
      supportRow('Panic episodes', data.support.episode_counts.panic);
      supportRow('Flashback episodes', data.support.episode_counts.flashback);
      supportRow('Insomnia episodes', data.support.episode_counts.insomnia);

      (data.recent.users || []).forEach(user => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td class="mono">${safe(user.id)}</td>
          <td>${safe(user.username)}</td>
          <td>${safe(user.first_name)}</td>
          <td>${user.is_premium ? 'yes' : 'no'}</td>
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
          <td>${payment.is_first_payment ? 'yes' : 'no'}</td>
          <td>${safe(payment.event_time)}</td>
        `;
        recentPaymentsBody.appendChild(tr);
      });
    }

    load();
  </script>
</body>
</html>
"""

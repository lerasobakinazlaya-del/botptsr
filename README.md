# Bot

Telegram-бот на `aiogram` с OpenAI, Redis, SQLite и отдельной админкой на FastAPI.

## Что умеет проект

- несколько режимов общения с настраиваемыми шкалами поведения
- отдельные AI-профили по режимам: модель, температура, память, таймауты и дополнительные инструкции
- "человечная" память: профиль пользователя, темы, динамика отношений и контекст последних диалогов
- фоновые re-engagement сообщения после долгой паузы с опорой на накопленную память
- Premium-режимы и Telegram Payments
- preview-доступ к premium-режимам с лимитами для бесплатных пользователей
- веб-админка для runtime-настроек, промптов, режимов и UI
- реферальная программа
- базовые health-метрики, просмотр логов и тестирование промптов из админки

## Что изменено в этой версии

- добавлены per-mode AI-профили и runtime-настройка AI отдельно для каждого режима
- добавлена humanized memory: профиль пользователя, relationship state и сбор живого memory context для промпта
- добавлен фоновый re-engagement worker для инициативных сообщений после периода тишины
- добавлен adaptive mode switch: бот может мягко менять effective mode по контексту общения
- добавлен preview-доступ к premium-режимам с дневными лимитами
- админка в `docker-compose` по умолчанию публикуется только на `127.0.0.1`
- Redis больше не публикуется наружу через `docker-compose`
- успешный чат теперь сохраняется в БД одним `COMMIT`, а не несколькими подряд
- runtime-конфиги кешируются в памяти и не читаются с диска на каждый запрос
- полные промпты логируются только в `DEBUG=true`
- входящие сообщения больше не пишутся в лог с текстовым preview
- рассылка из Telegram-админки отправляется батчами, а не одним длинным последовательным циклом
- платеж подтверждается только при корректном `invoice_payload`
- при старте бот больше не сбрасывает pending updates

## Стек

- Python 3.12+
- aiogram 3
- OpenAI Python SDK
- Redis
- SQLite
- FastAPI + Uvicorn

## Структура

- `main.py` — запуск Telegram-бота
- `admin_dashboard.py` — веб-админка
- `handlers/` — Telegram-хендлеры
- `services/` — AI, платежи, память, метрики, настройки
- `database/` — SQLite и репозитории
- `config/` — редактируемые JSON-конфиги
- `core/` — контейнер, middleware, логирование
- `deploy/systemd/` — systemd-юниты и update-скрипт
- `.github/workflows/deploy.yml` — деплой через GitHub Actions

## Память и AI по режимам

- `services/ai_profile_service.py` собирает effective AI-профиль для конкретного режима
- `services/human_memory_service.py` поддерживает пользовательский профиль, recurring topics и relationship state
- `services/ai_service.py` объединяет short-term историю, старую память и human memory context перед генерацией ответа
- `services/reengagement_service.py` фоном ищет пользователей с паузой в диалоге и отправляет инициативные сообщения
- `services/mode_access_service.py` управляет preview-доступом к premium-режимам

Через админку можно отдельно настраивать:

- AI-параметры по режимам
- preview-лимиты для premium-режимов
- re-engagement и adaptive mode switching

## Быстрый старт

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
.\venv\Scripts\pip.exe install -r requirements.txt
```

## Настройка `.env`

Минимальный набор:

```env
BOT_TOKEN=your_telegram_bot_token
OPENAI_API_KEY=your_openai_api_key
OWNER_ID=123456789
ADMIN_ID=123456789,987654321
REDIS_URL=redis://localhost:6379/0
```

Рекомендуемый production-вариант:

```env
BOT_TOKEN=your_telegram_bot_token
OPENAI_API_KEY=your_openai_api_key
OWNER_ID=123456789
ADMIN_ID=123456789,987654321

REDIS_URL=redis://localhost:6379/0
DEBUG=false
AI_LOG_FULL_PROMPT=false
AI_DEBUG_PROMPT_USER_ID=
OPENAI_MAX_PARALLEL_REQUESTS=8
OPENAI_QUEUE_SIZE=500

ADMIN_DASHBOARD_HOST=127.0.0.1
ADMIN_DASHBOARD_PORT=8080
ADMIN_DASHBOARD_BIND=127.0.0.1
ADMIN_DASHBOARD_USERNAME=admin
ADMIN_DASHBOARD_PASSWORD=change-this-strong-password
ADMIN_DASHBOARD_CACHE_TTL=15

PAYMENT_PROVIDER_TOKEN=your_telegram_payment_provider_token
PAYMENT_CURRENCY=RUB
PREMIUM_PRICE_MINOR_UNITS=49900
PREMIUM_PRODUCT_TITLE=Premium access
PREMIUM_PRODUCT_DESCRIPTION=Unlock premium chat modes and paid features.
```

## Локальный запуск

Бот:

```powershell
.\venv\Scripts\python.exe main.py
```

Админка:

```powershell
.\venv\Scripts\uvicorn.exe admin_dashboard:app --host 127.0.0.1 --port 8080
```

После запуска откройте:

- `http://127.0.0.1:8080`

## Docker

Запуск:

```powershell
docker compose up --build -d
```

Новые безопасные дефолты:

- Redis не публикуется наружу
- админка пробрасывается только на `127.0.0.1`

Если нужен доступ к админке с другого интерфейса, задайте переменную:

```env
ADMIN_DASHBOARD_BIND=0.0.0.0
```

Делайте это только за reverse proxy и с HTTPS.

## systemd

Шаблоны:

- `deploy/systemd/bot.service`
- `deploy/systemd/admin-dashboard.service`
- `deploy/systemd/update_bot.sh`

Скрипт `deploy/systemd/update_bot.sh`:

- обновляет зависимости
- проверяет Python-файлы через `py_compile`
- обновляет systemd-юниты
- перезапускает `bot.service` и `admin-dashboard.service`

## GitHub Actions деплой

В репозитории есть workflow `Deploy Bot`.

Нужны secrets:

- `DEPLOY_HOST`
- `DEPLOY_PORT`
- `DEPLOY_USER`
- `DEPLOY_SSH_KEY`

После этого можно запустить workflow вручную через GitHub Actions.

## Безопасность

- не публикуйте Redis в интернет
- не оставляйте `ADMIN_DASHBOARD_PASSWORD=change-me`
- держите админку за reverse proxy и HTTPS
- не включайте `DEBUG=true` на проде
- не включайте `AI_LOG_FULL_PROMPT` на проде

## Ограничения текущей архитектуры

- основная БД по-прежнему SQLite; для высокой конкурентной нагрузки лучше перейти на PostgreSQL
- throughput по AI ограничен вашим OpenAI rate limit и значениями `OPENAI_MAX_PARALLEL_REQUESTS` / `OPENAI_QUEUE_SIZE`
- fallback без Redis удобен для отказоустойчивости, но не подходит для горизонтального масштабирования

## Проверка после деплоя

```bash
redis-cli ping
sudo systemctl status bot.service
sudo systemctl status admin-dashboard.service
sudo journalctl -u bot.service -n 100 --no-pager
sudo journalctl -u admin-dashboard.service -n 100 --no-pager
```

Ожидаемо:

- `redis-cli ping` отвечает `PONG`
- оба сервиса в состоянии `active (running)`

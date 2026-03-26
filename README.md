# Bot

Telegram-бот на `aiogram` с OpenAI, Redis, SQLite и отдельной админкой на FastAPI.

## Что умеет проект

- несколько режимов общения с настраиваемыми параметрами поведения
- Premium-режимы и Telegram Payments
- веб-админка для runtime-настроек, промптов, режимов и UI
- безопасное форматирование AI-ответов для Telegram с конвертацией Markdown-подобного текста в HTML
- отдельные флаги `allow_bold` и `allow_italic` для каждого режима
- реферальная программа
- health-метрики, просмотр логов и тестирование промптов из админки

## Что изменено в этой версии

- админка в `docker-compose` по умолчанию публикуется только на `127.0.0.1`
- Redis больше не публикуется наружу через `docker-compose`
- успешный чат теперь сохраняется в БД одним `COMMIT`, а не несколькими подряд
- runtime-конфиги кешируются в памяти и не читаются с диска на каждый запрос
- `/api/logs` использует in-memory кеш с автоматической инвалидацией при изменении файла
- полные промпты логируются только при `DEBUG=true`
- входящие сообщения больше не пишутся в лог с текстовым preview
- рассылка из Telegram-админки отправляется батчами
- платеж подтверждается только при корректном `invoice_payload`
- при старте бот больше не сбрасывает pending updates
- AI-ответы с `**жирным**`, `*курсивом*`, кодом, списками и ссылками теперь безопасно конвертируются для Telegram
- для каждого режима появились отдельные переключатели `allow_bold` и `allow_italic` в админке
- если форматирование для режима выключено, сырые Markdown-маркеры не показываются пользователю

## Стек

- Python 3.10+ для локального запуска и systemd
- Python 3.12 в Docker-образе
- aiogram 3
- OpenAI Python SDK
- Redis
- SQLite
- FastAPI + Uvicorn

## Структура

- `main.py` - запуск Telegram-бота
- `admin_dashboard.py` - веб-админка
- `handlers/` - Telegram-хендлеры
- `services/` - AI, платежи, память, метрики, настройки
- `database/` - SQLite и репозитории
- `config/` - редактируемые JSON-конфиги
- `core/` - контейнер, middleware, логирование
- `deploy/systemd/` - systemd-юниты и update-скрипт
- `.github/workflows/deploy.yml` - деплой через GitHub Actions

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

Замечания по переменным админки:

- `ADMIN_DASHBOARD_BIND` используется только в Docker через `docker-compose`
- `deploy/systemd/admin-dashboard.service` сейчас жестко запускает админку на `127.0.0.1:8080`
- `ADMIN_DASHBOARD_HOST` и `ADMIN_DASHBOARD_PORT` уже есть в настройках приложения, но текущие systemd-юниты на них не завязаны

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

Безопасные дефолты:

- Redis не публикуется наружу
- админка пробрасывается только на `127.0.0.1`

Если нужен доступ к админке с другого интерфейса, задайте:

```env
ADMIN_DASHBOARD_BIND=0.0.0.0
```

Делайте это только за reverse proxy и с HTTPS.

## Форматирование ответов и эмодзи

Ответы модели проходят через Telegram-форматтер:

- поддерживаются `**bold**`, `*italic*`, inline-code, fenced code blocks, списки, заголовки и ссылки
- при ошибке Telegram бот отправляет безопасный plain text fallback
- в БД сохраняется исходный ответ модели, а не HTML-разметка

Флаги форматирования задаются отдельно для каждого режима в разделе `Modes` админки:

- `allow_bold`
- `allow_italic`

Поведение эмодзи тоже регулируется профилем режима через `emoji_level`:

- `0` — без эмодзи
- `1` — редкий легкий эмодзи
- `2` — один уместный эмодзи в дружелюбных и поддерживающих ответах
- `3` — один-два эмодзи в теплых, игривых или более близких режимах

Важно:

- если `allow_bold=false`, жирный текст не будет показан, даже если модель вернет `**...**`
- если `allow_italic=false`, курсив не будет показан, даже если модель вернет `*...*`
- по умолчанию новые флаги выключены для всех режимов

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

Важно:

- `deploy/systemd/admin-dashboard.service` по умолчанию слушает только `127.0.0.1:8080`
- скрипт использует `sudo cp`, `sudo systemctl daemon-reload` и `sudo systemctl restart`
- для автоматического деплоя нужен либо `root`, либо пользователь с passwordless `sudo` на эти команды

## GitHub Actions деплой

В репозитории есть workflow `Deploy Bot`.

Нужные secrets:

- `DEPLOY_HOST`
- `DEPLOY_PORT`
- `DEPLOY_USER`
- `DEPLOY_SSH_KEY`

Дополнительно:

- `DEPLOY_USER` должен иметь доступ к каталогу приложения
- если `DEPLOY_USER` не `root`, ему нужен passwordless `sudo`, иначе шаг `update_bot.sh` завершится ошибкой

После этого workflow можно запустить вручную через GitHub Actions.

Что важно понимать про текущую схему:

- workflow запускается вручную через `workflow_dispatch`, а не на каждый `push`
- workflow деплоит содержимое ветки из GitHub, а не локальные незакоммиченные изменения
- если вы правили проект локально, перед деплоем нужно как минимум закоммитить и отправить изменения в нужную ветку
- альтернативный путь — прямой SSH-деплой на сервер с запуском `deploy/systemd/update_bot.sh`

Пример ручного запуска workflow:

1. Отправьте изменения в нужную ветку.
2. Откройте GitHub Actions.
3. Выберите workflow `Deploy Bot`.
4. При необходимости укажите `branch` и `app_dir`.
5. Запустите workflow вручную.

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

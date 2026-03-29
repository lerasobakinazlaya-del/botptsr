# Bot

Telegram-бот на `aiogram` с OpenAI, Redis, SQLite и отдельной админкой на FastAPI.

## Что умеет проект

- живые режимы общения с разной интонацией, глубиной, инициативой и степенью близости
- per-mode AI-профили: отдельные temperature, длина ответа и prompt suffix для каждого режима
- humanized memory: профиль пользователя, recurring topics, relationship state и живой memory context
- proactive и re-engagement сообщения с учетом quiet hours, opt-out и состояния пользователя
- Premium-режимы и Telegram Payments
- preview-доступ к premium-режимам с лимитами для бесплатных пользователей
- веб-админка для runtime-настроек, промптов, режимов и UI
- ручная отправка сообщений пользователю из админки
- массовая рассылка из админки с server-side preview и подтверждением
- сохраняемые шаблоны сообщений в админке
- безопасное форматирование AI-ответов для Telegram с конвертацией Markdown-подобного текста в HTML
- отдельные флаги `allow_bold` и `allow_italic` для каждого режима
- реферальная программа
- health-метрики, release metadata, предупреждения, просмотр логов и тестирование промптов из админки

## Что изменено в этой версии

- добавлены per-mode AI-профили и runtime-настройка AI отдельно для каждого режима
- режимы реально разведены по prompt-архитектуре, mode scales и runtime overrides, а не только по названиям
- добавлена humanized memory: профиль пользователя, relationship state и сбор живого memory context для промпта
- добавлен фоновый re-engagement worker для инициативных сообщений после периода тишины
- добавлен adaptive mode switch: бот может мягко менять effective mode по контексту общения
- добавлен preview-доступ к premium-режимам с дневными лимитами
- админка в `docker-compose` по умолчанию публикуется только на `127.0.0.1`
- Redis больше не публикуется наружу через `docker-compose`
- успешный чат теперь сохраняется в БД одним `COMMIT`, а не несколькими подряд
- runtime-конфиги кешируются в памяти и не читаются с диска на каждый запрос
- `/api/logs` использует in-memory кеш с автоматической инвалидацией при изменении файла
- полные промпты логируются только при `DEBUG=true`
- входящие сообщения больше не пишутся в лог с текстовым preview
- рассылка из Telegram-админки отправляется батчами
- рассылка из веб-админки теперь проходит через preview и `confirmation_token`, чтобы избежать случайной массовой отправки
- в health добавлены `release.json`, предупреждения по окружению и отображение текущего релиза в админке
- платеж подтверждается только при корректном `invoice_payload`
- при старте бот больше не сбрасывает pending updates
- AI-ответы с `**жирным**`, `*курсивом*`, кодом, списками и ссылками теперь безопасно конвертируются для Telegram
- для каждого режима появились отдельные переключатели `allow_bold` и `allow_italic` в админке
- если форматирование для режима выключено, сырые Markdown-маркеры не показываются пользователю
- добавлены PTSD response guardrails и regression-тесты на различимость режимов

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

## Память и AI по режимам

- `services/ai_profile_service.py` собирает effective AI-профиль для конкретного режима
- AI-профиль режима может включать `model`, `temperature`, `max_completion_tokens`, `memory_max_tokens`, `history_message_limit`, `timeout_seconds`, `max_retries` и `prompt_suffix`
- `services/human_memory_service.py` поддерживает пользовательский профиль, recurring topics и relationship state
- `services/ai_service.py` объединяет short-term историю, старую память и human memory context перед генерацией ответа
- `services/prompt_builder.py` собирает system prompt из personality, response style, engagement rules, mode signature, access rules и runtime-состояния
- `services/reengagement_service.py` фоном ищет пользователей с паузой в диалоге и отправляет инициативные сообщения
- `services/mode_access_service.py` управляет preview-доступом к premium-режимам

Через админку можно отдельно настраивать:

- AI-параметры по режимам, включая `mode_overrides`
- preview-лимиты для premium-режимов
- re-engagement и adaptive mode switching
- шаблоны сообщений, ручную отправку и массовую рассылку

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

## Автоматическая проверка перед запуском

Единая проверка запускается так:

```powershell
.\venv\Scripts\python.exe scripts\prelaunch_check.py --strict-env
```

Что она делает автоматически:

- проверяет обязательные `.env`-переменные
- валидирует `config/*.json`
- компилирует Python-файлы через `compileall`
- запускает `pytest`
- поднимает smoke-проверку админки через `TestClient`

JSON-отчёт сохраняется в `logs/prelaunch_report.json`.

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

- проверяет, что `redis-server` и `redis-cli` установлены на сервере, и при необходимости ставит их через `apt-get`
- включает и перезапускает `redis-server.service`
- проверяет Redis через `redis-cli ping` и прерывает деплой, если Redis не отвечает
- обновляет зависимости
- проверяет Python-файлы через `compileall`
- валидирует `config/*.json`
- запускает тесты через `pytest -q` если `RUN_TESTS != 0`
- записывает `config/release.json` с branch, commit и временем деплоя
- обновляет systemd-юниты
- перезапускает `bot.service` и `admin-dashboard.service`

Важно:

- `bot.service` и `admin-dashboard.service` теперь стартуют после `redis-server.service`
- `deploy/systemd/admin-dashboard.service` по умолчанию слушает только `127.0.0.1:8080`
- скрипт использует `sudo cp`, `sudo systemctl daemon-reload` и `sudo systemctl restart`
- для автоматического деплоя нужен либо `root`, либо пользователь с passwordless `sudo` на эти команды

## Redis На Сервере

Для systemd-развертывания Redis теперь считается обязательной частью сервера:

- `deploy/oracle/bootstrap.sh` и `deploy/beget/bootstrap.sh` ставят `redis-server`, включают сервис и сразу проверяют `redis-cli ping`
- `deploy/systemd/update_bot.sh` повторно поднимает Redis на каждом выкатывании и останавливает деплой, если Redis не отвечает
- для systemd-режима используйте `REDIS_URL=redis://localhost:6379/0`

Это нужно, чтобы бот не уходил в in-memory fallback после рестарта сервера или после выкладки.

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
- на практике сервер может быть развернут не как полноценный git checkout; в таком случае возможен ручной SSH-выкат файлов с последующим `systemctl restart`

Пример ручного запуска workflow:

1. Отправьте изменения в нужную ветку.
2. Откройте GitHub Actions.
3. Выберите workflow `Deploy Bot`.
4. При необходимости укажите `branch` и `app_dir`.
5. Запустите workflow вручную.

CLI-запуск из PowerShell:

```powershell
.\deploy\run_github_deploy.ps1 -Branch master -AppDir /opt/bot -Wait
```

Что важно про авторизацию:

- скрипт сначала пробует `GH_TOKEN` или `GITHUB_TOKEN`
- если `gh` установлен и авторизован, скрипт использует `gh auth token`
- если `gh` нет в `PATH`, скрипт умеет брать GitHub credential из Git Credential Manager
- на этой машине это рабочий сценарий, потому что Git настроен с `credential.helper=manager`

То есть информацию о том, что GitHub-доступ у нас уже есть, фиксируем именно в этом разделе `README`, рядом с workflow `Deploy Bot`, а не в `.env`

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
- `http://127.0.0.1:8080/api/health` отдает `200` и показывает актуальный `release.json`

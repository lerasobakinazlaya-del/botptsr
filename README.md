# AI Companion SaaS Bot

Single-tenant SaaS-платформа для запуска, настройки и монетизации Telegram AI-компаньона.

Технически это Telegram-бот на `aiogram` с OpenAI, Redis, SQLite и FastAPI control center. Продуктово это не просто consumer-бот, а основа SaaS для оператора: владелец бота настраивает личность, режимы, paywall, платежи, пользователей, рассылки, качество ответов и health-метрики из одной панели.

SaaS-MVP направление зафиксировано в [`docs/saas-mvp.md`](docs/saas-mvp.md).

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
- короткий SaaS-friendly reply loop для первых 3-5 сообщений: hook turn, fast lane и anti-lecture guardrails

## Что изменено в этой версии

- добавлены per-mode AI-профили и runtime-настройка AI отдельно для каждого режима
- основной reply path переведен на компактный `ConversationEngineV2`: короткий character core, intent routing и меньше роботической meta-обвязки
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
- AI-очередь теперь ограничивает время ожидания через `OPENAI_QUEUE_WAIT_TIMEOUT_SECONDS`, а админка показывает queue wait, reject/timeout и глобальный OpenAI pool
- обработка сообщений одного пользователя сериализована, чтобы под нагрузкой не было гонок состояния и перемешивания ответов
- рассылка из Telegram-админки отправляется батчами
- рассылка из веб-админки теперь проходит через preview и `confirmation_token`, чтобы избежать случайной массовой отправки
- в health добавлены `release.json`, предупреждения по окружению и отображение текущего релиза в админке
- платеж подтверждается только при корректном `invoice_payload`
- при старте бот больше не сбрасывает pending updates
- AI-ответы с `**жирным**`, `*курсивом*`, кодом, списками и ссылками теперь безопасно конвертируются для Telegram
- для каждого режима появились отдельные переключатели `allow_bold` и `allow_italic` в админке
- если форматирование для режима выключено, сырые Markdown-маркеры не показываются пользователю
- добавлены PTSD response guardrails и regression-тесты на различимость режимов
- добавлен жёсткий crisis bypass: при явных сигналах риска самоповреждения или вреда другим бот не идёт в обычную генерацию, а сразу возвращает безопасную кризисную инструкцию
- добавлен safety clamp для близости: уровни `tension`, `personal_focus` и `rare_layer` больше не включаются без явного сигнала пользователя и не используются в тяжёлом эмоциональном состоянии
- PTSD-support is now conditional in `comfort` for heavy emotional states or PTSD-like signals.
- adaptive mode больше не может тихо откатить явно выбранный пользователем `comfort` обратно в `base`
- исправлены битые user-facing fallback и runtime default строки, чтобы на свежем окружении не было mojibake в лимитах и оплате
- память для модели теперь проходит двухступенчатую защиту: instruction-like фрагменты отсекаются при сохранении и повторно санитизируются перед отправкой в OpenAI
- model-facing memory, proactive prompt и episodic summary выровнены под русский язык вместо смешанного RU/EN контура
- proactive и re-engagement используют только безопасный недоверенный preview памяти; инструкции из памяти не должны исполняться как промт
- debug-логирование системного промпта теперь редактирует чувствительные блоки памяти и state summary, даже если флаг включён в админке
- добавлен product eval-набор на короткие первые сообщения, чтобы проверять живость, длину ответа и вариативность follow-up вопросов до выкладки
- добавлен отдельный emotional hooks layer: библиотека хуков, выбор по стадии диалога, anti-repeat через `state["last_hook"]` и `ensure_open_loop` в reply path
- reply-кнопки главного меню больше не попадают под throttle-защиту и не считаются flood при быстром нажатии

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
- `docs/product-copy.md` - готовые тексты для Telegram, лендинга, paywall и рекламы
- `handlers/` - Telegram-хендлеры
- `services/` - AI, платежи, память, метрики, настройки
- `database/` - SQLite и репозитории
- `config/` - редактируемые JSON-конфиги
- `core/` - контейнер, middleware, логирование
- `deploy/systemd/` - systemd-юниты и update-скрипт
- `.github/workflows/deploy.yml` - деплой через GitHub Actions

Ключевые конфиги в `config/`:

- `config/runtime_settings.json` - живые runtime-настройки AI, инициативы, лимитов, UI и монетизации
- `config/prompt_templates.json` - редактируемые шаблоны prompt/template-слоя для админки и совместимости
- `config/mode_catalog.json` - каталог режимов, который использует админка для mode engine
- `config/modes.json` - значения и ограничения по режимам, которые влияют на поведение бота

## Память и AI по режимам

- `services/ai_profile_service.py` собирает effective AI-профиль для конкретного режима
- AI-профиль режима может включать `model`, `temperature`, `max_completion_tokens`, `memory_max_tokens`, `history_message_limit`, `timeout_seconds`, `max_retries` и `prompt_suffix`
- `services/human_memory_service.py` поддерживает пользовательский профиль, recurring topics и relationship state
- `services/human_memory_service.py` использует adaptive mode только как мягкое повышение `base -> comfort`; явный `comfort` не понижается автоматически
- `services/ai_service.py` объединяет short-term историю, старую память и human memory context перед генерацией ответа
- `services/ai_service.py` теперь сначала проверяет crisis signals и только потом идёт в обычную модельную генерацию
- `services/ai_service.py` после guardrails может мягко встраивать emotional hook в короткий разговорный ответ и сохраняет последний использованный хук в `state["last_hook"]`
- `services/emotional_hooks.py` хранит библиотеку curiosity / tension / partial reveal / escalation / personalization хуков, выбирает подходящий вариант по состоянию диалога и удерживает ответ в open-loop формате
- `services/prompt_safety.py` санитизирует память, режет instruction-like payload и редактирует чувствительные части debug prompt-логов
- `services/conversation_engine_v2.py` собирает основной system prompt для reply/reengagement: короткий character core, intent contract и условный PTSD-layer
- `services/prompt_builder.py` остается как legacy/template слой для админского prompt-редактора и совместимости со старыми настройками
- `services/access_engine.py` теперь дополнительно зажимает интимную эскалацию без явного пользовательского сигнала и для proactive/re-engagement сообщений
- `services/reengagement_service.py` фоном ищет пользователей с паузой в диалоге и отправляет инициативные сообщения
- `services/mode_access_service.py` управляет preview-доступом к premium-режимам

Через админку можно отдельно настраивать:

- AI-параметры по режимам, включая `mode_overrides`
- PTSD/anti-canned response guardrails и список фраз, которые надо переписывать в уязвимых состояниях
- preview-лимиты для premium-режимов
- re-engagement и adaptive mode switching
- conversation lab для `hook turn`: лимит фраз, лимит символов, follow-up policy и compact redirect без правок кода
- fast lane control center: отдельные токены, память, история, timeout и retry для `hook / continuation / scene / generic`
- стиль первой инициативы: семьи opener'ов, длина, allow-question и callback bias прямо из админки
- шаблоны сообщений, ручную отправку и массовую рассылку

## SaaS-ядро диалога

Для первых 3-5 сообщений проект теперь опирается не только на mode packs, но и на отдельный короткий reply loop:

- `hook turn`: короткая реплика пользователя считается не запросом на эссе, а ходом в диалоге
- `fast lane`: для таких реплик снижаются токены, история, timeout и retry, чтобы ответ приходил быстрее
- `anti-lecture guardrails`: длинные безопасные простыни сжимаются до 1 мысли + 1 хука на продолжение
- `emotional hooks`: после базового ответа может добавляться короткий curiosity / tension / partial reveal / escalation / personalization-хук без раздувания длины ответа
- `open loop ending`: короткий ответ должен либо оставить мягкую недосказанность, либо закончиться вопросом, чтобы разговор естественно тянулся дальше
- follow-up вопрос подбирается по типу интента: цена, найм, лендинг, тон, timing, диагностика, go/no-go

Это лежит в:

- `services/conversation_engine_v2.py`
- `services/ai_service.py`
- `services/emotional_hooks.py`
- `services/response_guardrails.py`
- `services/human_memory_service.py`

Веб-админка теперь даёт отдельный control center для этого слоя:

- `Conversation lab` — как короткие ответы тянут разговор дальше
- `Fast lane` — насколько быстро и компактно отвечать на короткие реплики
- `Re-engagement style` — как именно бот пишет первым после паузы
- `Testing -> Re-engagement` — preview первого сообщения без ручного вызова воркера

## Product Eval Перед Выкладкой

Отдельный regression-набор для SaaS-ядра:

```powershell
.\venv\Scripts\python.exe -m pytest -q tests\test_conversation_product_eval.py tests\test_conversation_engine_v2.py tests\test_response_guardrails.py tests\test_ai_service.py tests\test_emotional_hooks.py tests\test_middlewares.py
```

Что он проверяет:

- короткие реплики не превращаются в мини-лекции
- ответ остаётся компактным и заканчивается либо одним follow-up вопросом, либо open-loop формулировкой
- в ответах не остаются низкосигнальные фразы вроде “это зависит от контекста”
- follow-up вопросы и заходы не схлопываются в 1-2 одинаковые формулы
- emotional hooks не повторяются подряд и сохраняют open-loop ending без раздувания ответа
- нажатия на reply-кнопки UI не триггерят throttle-предупреждение и не ломают первый сценарий входа

Проверка того же набора на сервере:

```bash
cd /opt/bot && /opt/bot/venv/bin/python -m pytest -q tests/test_conversation_product_eval.py tests/test_conversation_engine_v2.py tests/test_response_guardrails.py tests/test_ai_service.py tests/test_emotional_hooks.py tests/test_middlewares.py
```

Что важно по админке сейчас:

- основная инициатива первого сообщения идёт через `services/reengagement_service.py`, а не через отдельный proactive worker
- массовая рассылка из веб-админки сначала проходит server-side preview через `/api/users/broadcast/preview`, и только потом подтверждается отправка
- быстрые изменения в UI и рантайме пишутся в `config/runtime_settings.json`, поэтому их удобно проверять вместе с админкой, а не только через код
- prompt-редактор и runtime-настройки стоит проверять вместе: часть поведения уже идёт через `ConversationEngineV2`, а часть совместимости всё ещё опирается на `config/prompt_templates.json`

В карточке пользователя админка теперь показывает именно безопасный preview памяти для промпта:

- role-like строки, ссылки и instruction-like фрагменты туда не попадают
- preview памяти больше не равен “сырому” вводу пользователя, а показывает уже отфильтрованный контекст для модели
- ручные записи памяти можно редактировать как раньше, но вредные инструкции всё равно будут отброшены перед использованием в ИИ

В разделе `Health` сейчас дополнительно видно:

- статус Redis с `mode`, `endpoint`, `DB`, `URL` и `latency`
- давление на AI-очередь: `queue_size`, `busy_workers`, queue wait, reject и timeout
- глобальный OpenAI-пул: `in_flight`, `waiting_requests`, wait и latency
- сериализацию пользовательских чатов: `active_sessions`, `tracked_users`, `wait_events`

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
OPENAI_QUEUE_WAIT_TIMEOUT_SECONDS=25

ADMIN_DASHBOARD_HOST=127.0.0.1
ADMIN_DASHBOARD_PORT=8080
ADMIN_DASHBOARD_BIND=127.0.0.1
ADMIN_DASHBOARD_USERNAME=admin
ADMIN_DASHBOARD_PASSWORD=change-this-strong-password
ADMIN_DASHBOARD_CACHE_TTL=15

PAYMENT_PROVIDER_TOKEN=your_telegram_payment_provider_token
PAYMENT_CURRENCY=RUB
PREMIUM_PRICE_MINOR_UNITS=49900
PREMIUM_PRODUCT_TITLE=Подписка Premium
PREMIUM_PRODUCT_DESCRIPTION=Открой премиум-режимы и платные функции.
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
- ловит битые HTML/JS-селекторы в `tests/test_admin_dashboard.py`, чтобы в панели не оставались нерабочие кнопки и поля

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
- после выкладки workflow дополнительно проверяет `redis-cli ping` и делает авторизованный запрос к `http://127.0.0.1:8080/api/health`
- post-deploy шаг валидирует `db.ok`, `redis.ok` и совпадение `release.commit` с выкачанным коммитом
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
- если временно включаете `AI_LOG_FULL_PROMPT` для отладки, помните: лог теперь безопаснее, но всё равно содержит служебный prompt-контекст и не предназначен для постоянного прод-режима
- crisis-сообщения о немедленном вреде себе или другим теперь обрабатываются deterministic bypass без обычной генерации модели
- PTSD-support is now conditional in `comfort` for heavy emotional states or PTSD-like signals.
- proactive и re-engagement сообщения теперь принудительно остаются в безопасном уровне близости и не должны первыми эскалировать intimacy
- In `dominant`, closer delivery is still clamped without an explicit user signal; safe fallback stays `analysis`.
- память для модели считается недоверенным источником: даже если в ней окажутся команды или псевдо-system инструкции, они должны отфильтровываться и не исполняться как промт

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
- `http://127.0.0.1:8080/api/health` отдает `200`, показывает актуальный `release.json` и `redis.mode=connected`
- в `Health` админки видны актуальные метрики `AI queue`, `OpenAI pool` и `Chat sessions`
- в веб-админке работают `Обновить все`, `Экспорт JSON`, `Сбросить кеш`, карточка пользователя, просмотр диалога и preview массовой рассылки без битых селекторов
## Модель монетизации

- Бесплатные пользователи получают дневной лимит и предупреждения до его исчерпания.
- Premium продаётся на фиксированный срок, а не как пожизненный доступ.
- По умолчанию подписка выдаётся на `30 дней`.
- У Premium тоже есть дневной лимит, чтобы нагрузка оставалась экономически предсказуемой.
- Платные режимы поддерживают ограниченный бесплатный preview для роста конверсии в оплату.
- Перед окончанием Premium пользователь получает напоминания о продлении.
- Для Telegram Stars (`XTR`) можно использовать рекуррентную оплату для плана на 30 дней.
- Реферальные награды выдаются в premium-днях, а не в виде пожизненного Premium.

Текущие значения по умолчанию в репозитории:

- Бесплатный лимит: `12` сообщений в день
- Предупреждения по бесплатному лимиту: `5`, `3`, `1`, `0`
- Лимит Premium: `120` сообщений в день
- Напоминания о продлении: за `7`, `3`, `1` день до окончания
- Реферальная награда: `7 premium-дней`

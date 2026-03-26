# Bot

Telegram-бот на `aiogram` с SQLite, Redis, OpenAI и отдельной веб-админкой на FastAPI.

## Что умеет проект

- несколько режимов общения с настраиваемыми шкалами поведения
- Premium-режимы и Telegram Payments
- русская веб-админка с несколькими разделами
- редактирование runtime-настроек, промптов, режимов и UI без правки кода
- тестирование системного промпта, state engine и live-ответа модели из админки
- просмотр логов, health-статуса и базовой аналитики

## Структура

- `main.py` - запуск Telegram-бота
- `admin_dashboard.py` - веб-админка
- `handlers/` - Telegram-хендлеры
- `services/` - AI, платежи, память, метрики и настройки
- `database/` - SQLite и репозитории
- `config/` - редактируемые JSON-конфиги
- `core/` - контейнер, middleware, логирование
- `deploy/systemd/` - systemd-юниты и update-скрипт
- `.github/workflows/deploy.yml` - one-click deploy через GitHub Actions

## Требования

- Python 3.12+
- Redis
- Telegram Bot Token
- OpenAI API key

## Установка

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
.\venv\Scripts\pip.exe install -r requirements.txt
```

## Настройка `.env`

```env
BOT_TOKEN=your_telegram_bot_token
OPENAI_API_KEY=your_openai_api_key
OWNER_ID=123456789
ADMIN_ID=123456789,987654321

REDIS_URL=redis://localhost:6379/0
DEBUG=false
AI_LOG_FULL_PROMPT=false
AI_DEBUG_PROMPT_USER_ID=
OPENAI_MAX_PARALLEL_REQUESTS=4
OPENAI_QUEUE_SIZE=100

ADMIN_DASHBOARD_HOST=127.0.0.1
ADMIN_DASHBOARD_PORT=8080
ADMIN_DASHBOARD_USERNAME=admin
ADMIN_DASHBOARD_PASSWORD=change-me
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

После запуска открой:

- `http://127.0.0.1:8080`

Логин и пароль берутся из:

- `ADMIN_DASHBOARD_USERNAME`
- `ADMIN_DASHBOARD_PASSWORD`

## Что настраивается через админку

### 1. Обзор

- пользователи, Premium, сообщения, выручка
- недавние пользователи и платежи
- состояние DB, Redis и AI-воркеров

### 2. AI и интерфейс

- модель OpenAI
- `temperature`
- таймаут и ретраи
- размер памяти и длина истории
- логирование полного промпта
- тексты ошибок чата
- кнопки и приветствия Telegram-интерфейса

### 3. Безопасность и state engine

- rate limit и предупреждения
- максимальная длина сообщения
- фильтр подозрительных ссылок
- списки ключевых слов
- стартовые значения состояния
- коэффициенты изменения `interest`, `attraction`, `control` и других метрик

### 4. Промпты

- ядро личности
- safety-блок
- префиксы памяти, состояния, режима и доступа
- финальная инструкция
- правила доступа: `observation`, `analysis`, `tension`, `personal_focus`, `rare_layer`

### 5. Режимы

- название, иконка и описание режима
- Premium / Free
- порядок отображения
- тон, эмоциональное состояние, правила поведения
- фраза активации
- числовые шкалы режима в `config/modes.json`

### 6. Оплата

- provider token
- валюта
- цена
- название и описание Premium
- пользовательские сообщения оплаты

### 7. Тестирование

- превью системного промпта
- dry-run обновления state
- live-тест ответа модели из текущих настроек

### 8. Логи

- просмотр `logs/bot.log`
- health-данные
- проверка конфигурационных файлов

## Редактируемые конфиги

- `config/runtime_settings.json` - runtime-настройки, UI, безопасность, state engine, платежи
- `config/prompt_templates.json` - шаблоны системных промптов
- `config/modes.json` - числовые шкалы режимов
- `config/mode_catalog.json` - тексты, названия, иконки и Premium-статусы режимов

Если каких-то файлов нет, сервис настроек создаст их автоматически.

## Режимы общения

Доступны:

- `base`
- `comfort`
- `passion`
- `mentor`
- `night`
- `dominant`

По умолчанию Premium:

- `passion`
- `mentor`
- `night`
- `dominant`

## Telegram-админка

Команда `/admin` доступна администраторам и владельцу.

Она позволяет:

- смотреть статистику
- смотреть runtime/debug
- проверять состояние зависимостей
- выдавать и снимать Premium
- запускать рассылку с подтверждением

## Redis

Redis используется для:

- FSM storage
- rate limit middleware
- кеша метрик админки

Если Redis временно недоступен, проект не падает:

- FSM переходит на `MemoryStorage`
- middleware используют локальный fallback
- админка строит overview без Redis-кеша

## Логи

Основной лог:

- `logs/bot.log`

## Docker

Для серверного запуска можно использовать:

- `Dockerfile`
- `docker-compose.yml`

Запуск:

```powershell
docker compose up --build -d
```

## systemd

Шаблоны:

- `deploy/systemd/bot.service`
- `deploy/systemd/admin-dashboard.service`
- `deploy/systemd/update_bot.sh`

Скрипт `update_bot.sh` выполняет:

- обновление кода
- установку зависимостей
- проверку Python-компиляции
- перезапуск `bot.service`
- перезапуск `admin-dashboard.service`

## GitHub Actions деплой

В репозитории есть workflow `Deploy Bot`.

Нужно добавить secrets:

- `DEPLOY_HOST`
- `DEPLOY_PORT`
- `DEPLOY_USER`
- `DEPLOY_SSH_KEY`

После этого можно запускать деплой кнопкой `Run workflow` в GitHub Actions.

## Быстрая проверка после деплоя

```bash
redis-cli ping
sudo systemctl status bot.service
sudo systemctl status admin-dashboard.service
sudo journalctl -u bot.service -n 100 --no-pager
sudo journalctl -u admin-dashboard.service -n 100 --no-pager
```

Ожидаемо:

- `redis-cli ping` -> `PONG`
- оба сервиса в состоянии `active (running)`

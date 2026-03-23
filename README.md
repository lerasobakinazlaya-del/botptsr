# Bot

Telegram-бот на `aiogram` с SQLite, Redis, OpenAI и отдельной web-админкой.

## Что есть в проекте

- `main.py` - точка входа бота
- `admin_dashboard.py` - отдельная web-админка на FastAPI
- `handlers/` - Telegram-хендлеры
- `services/` - бизнес-логика, AI, платежи, метрики
- `database/` - SQLite-репозитории и инициализация БД
- `config/` - настройки и конфиги режимов
- `core/` - контейнер зависимостей, middleware, логирование
- `deploy/systemd/` - шаблоны unit-файлов

## Требования

- Python 3.12+
- Redis
- Telegram bot token
- OpenAI API key

## Установка

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
.\venv\Scripts\pip.exe install -r requirements.txt
```

## .env

Создай `.env` в корне проекта:

```env
BOT_TOKEN=your_telegram_bot_token
OPENAI_API_KEY=your_openai_api_key
OWNER_ID=123456789
ADMIN_ID=123456789,987654321

REDIS_URL=redis://localhost:6379/0
DEBUG=false
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

## Запуск

Бот:

```powershell
.\venv\Scripts\python.exe main.py
```

Web-админка:

```powershell
.\venv\Scripts\uvicorn.exe admin_dashboard:app --host 127.0.0.1 --port 8080
```

## Режимы общения

Поддерживаются режимы:

- `base`
- `comfort`
- `passion`
- `mentor`
- `night`
- `dominant`

Premium-режимы:

- `passion`
- `mentor`
- `night`
- `dominant`

Метаданные режимов лежат в `config/modes.py`, а AI-профили для prompt builder - в `config/modes.json`.

## Админка

Telegram-админка по `/admin` умеет:

- смотреть статистику
- смотреть debug/runtime
- проверять health
- выдавать и снимать Premium
- делать рассылку с подтверждением

Web-админка показывает:

- общее число пользователей
- новых пользователей за 1 / 7 / 30 дней
- premium-пользователей
- успешные оплаты
- первые оплаты
- выручку
- динамику по дням
- последние регистрации
- последние оплаты
- runtime AI-очереди

## Платежи

В проекте есть базовый Telegram Payments flow:

- кнопка `💎 Premium`
- команда `/buy`
- `pre_checkout` обработчик
- запись успешной оплаты в таблицу `payments`
- автоматическая выдача Premium после успешной оплаты

`PREMIUM_PRICE_MINOR_UNITS` задается в минимальных единицах валюты.
Для `RUB` значение `49900` означает `499.00 RUB`.

## База данных

Основные таблицы:

- `users`
- `messages`
- `user_state`
- `payments`

SQLite настроен с:

- `WAL`
- `busy_timeout`
- индексами на историю сообщений и оплаты

## Кеширование

Для web-админки используется Redis-кеш:

- тяжелая аналитика кешируется
- runtime-метрики остаются живыми
- TTL задается через `ADMIN_DASHBOARD_CACHE_TTL`

## Docker Compose

Для серверного запуска есть:

- `Dockerfile`
- `docker-compose.yml`

Запуск:

```powershell
docker compose up --build -d
```

## systemd

Шаблоны unit-файлов:

- `deploy/systemd/bot.service`
- `deploy/systemd/admin-dashboard.service`

Они рассчитаны на установку проекта в `/opt/bot`.

## GitHub publish

Локальный репозиторий уже инициализирован. Для публикации:

```powershell
git remote add origin https://github.com/<your-name>/<repo>.git
git push -u origin master
```

Если репозиторий на GitHub уже создан с README или `.gitignore`, сначала лучше сделать пустой репозиторий без дополнительных файлов.

## Oracle Cloud Free

Для always-on запуска бота и Redis бесплатная VM обычно практичнее, чем free web platforms.

Подготовлены файлы:

- `deploy/oracle/bootstrap.sh`
- `deploy/oracle/nginx-admin.conf`

Базовый сценарий на сервере:

```bash
git clone <your-repo-url> /opt/bot
cd /opt/bot
chmod +x deploy/oracle/bootstrap.sh
./deploy/oracle/bootstrap.sh
```

После этого:

1. заполнить `/opt/bot/.env`
2. при необходимости настроить `nginx` через `deploy/oracle/nginx-admin.conf`
3. перезапустить сервисы:

```bash
sudo systemctl restart bot.service admin-dashboard.service
sudo systemctl status bot.service
sudo systemctl status admin-dashboard.service
```

# Bot

Telegram-бот на `aiogram` с SQLite, Redis, OpenAI и отдельной веб-админкой на FastAPI.

## Что есть в проекте

- `main.py` - точка входа бота
- `admin_dashboard.py` - отдельная веб-админка
- `handlers/` - Telegram-хендлеры
- `services/` - AI, платежи, метрики, память, настройки админки
- `database/` - SQLite-репозитории и инициализация БД
- `config/` - конфиги режимов и runtime-настроек
- `core/` - контейнер зависимостей, middleware, логирование
- `deploy/systemd/` - шаблоны unit-файлов

## Возможности

- Telegram-бот с несколькими режимами общения
- Premium-режимы и Telegram Payments
- отдельная русскоязычная веб-админка
- просмотр метрик, логов и состояния рантайма
- редактирование системных промптов без изменения кода
- настройка модели, `temperature`, таймаута и памяти из админки
- редактирование шкал режимов через админку

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

Создай `.env` в корне проекта:

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

## Быстрый запуск

Бот:

```powershell
.\venv\Scripts\python.exe main.py
```

Веб-админка:

```powershell
.\venv\Scripts\uvicorn.exe admin_dashboard:app --host 127.0.0.1 --port 8080
```

После запуска открой:

- `http://127.0.0.1:8080`

Логин и пароль для входа берутся из:

- `ADMIN_DASHBOARD_USERNAME`
- `ADMIN_DASHBOARD_PASSWORD`

## Что настраивается через админку

В веб-админке можно:

- смотреть обзор по пользователям, оплатам и выручке
- смотреть последние логи бота
- видеть состояние AI-очереди и воркеров
- менять модель OpenAI
- менять `temperature`
- менять таймаут запросов к модели
- менять количество повторных попыток
- менять лимит памяти для истории
- включать логирование полного промпта
- задавать `user_id` для точечного логирования промпта
- редактировать базовые системные промпты
- редактировать правила доступа
- менять шкалы режимов в `config/modes.json`

## Файлы настраиваемых конфигов

Часть настроек теперь хранится отдельно от кода:

- `config/runtime_settings.json` - runtime-настройки модели
- `config/prompt_templates.json` - редактируемые шаблоны системного промпта
- `config/modes.json` - числовые шкалы режимов
- `config/modes.py` - названия, описания и фразы активации режимов

Если файлов `runtime_settings.json` и `prompt_templates.json` еще нет, они создаются автоматически при первом обращении к админке или сервису настроек.

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

## Telegram-админка

Команда `/admin` доступна администраторам и позволяет:

- смотреть статистику
- смотреть debug/runtime
- проверять состояние зависимостей
- выдавать и снимать Premium
- запускать рассылку с подтверждением

## Веб-админка

Веб-админка показывает:

- общее число пользователей
- новых пользователей за 1 / 7 / 30 дней
- premium-пользователей
- успешные оплаты
- первые оплаты
- выручку
- динамику по дням
- последних пользователей
- последние оплаты
- runtime AI-очереди
- хвост лог-файла `logs/bot.log`

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
- индексами на сообщения и оплаты

## Redis и кеш

Redis используется для:

- FSM storage
- rate limit / middleware
- кеша обзорной аналитики админки

Если Redis временно недоступен, веб-админка не падает: обзор строится без кеша.

## Логи

Логи пишутся в:

- `logs/bot.log`

Используется ротация логов:

- до `5 MB` на файл
- до `5` файлов истории

## Docker Compose

Для серверного запуска есть:

- `Dockerfile`
- `docker-compose.yml`

Запуск:

```powershell
docker compose up --build -d
```

Сервисы:

- `redis`
- `bot`
- `admin-dashboard`

## systemd

Шаблоны unit-файлов:

- `deploy/systemd/bot.service`
- `deploy/systemd/admin-dashboard.service`
- `deploy/systemd/update_bot.sh`

Они рассчитаны на установку проекта в `/opt/bot`.

Пример обновления на сервере:

```bash
cd /opt/bot
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart bot.service admin-dashboard.service
sudo systemctl status bot.service
sudo systemctl status admin-dashboard.service
```

Скрипт `deploy/systemd/update_bot.sh` делает:

- `git fetch` и `git pull`
- установку зависимостей
- быструю проверку Python-файлов
- обновление `systemd` unit-файлов
- перезапуск `bot.service` и `admin-dashboard.service`

Ручной запуск на сервере:

```bash
cd /opt/bot
chmod +x deploy/systemd/update_bot.sh
./deploy/systemd/update_bot.sh main
```

## Обновление одной кнопкой через GitHub

В репозиторий добавлен workflow:

- `.github/workflows/deploy.yml`

После настройки GitHub Secrets можно запускать деплой из вкладки `Actions` кнопкой `Run workflow`.

Нужные Secrets в GitHub:

- `DEPLOY_HOST` - IP или домен сервера
- `DEPLOY_PORT` - SSH-порт, обычно `22`
- `DEPLOY_USER` - SSH-пользователь
- `DEPLOY_SSH_KEY` - приватный SSH-ключ для входа на сервер

Что делает workflow:

- подключается по SSH к серверу
- переходит в директорию проекта
- запускает `deploy/systemd/update_bot.sh`
- обновляет код
- ставит зависимости
- перезапускает бот и веб-админку

Если у тебя основная ветка не `main`, при запуске workflow просто укажи нужную ветку в поле `branch`, например `master`.

## Oracle Cloud Free

Подготовлены файлы:

- `deploy/oracle/bootstrap.sh`
- `deploy/oracle/nginx-admin.conf`

Базовый сценарий:

```bash
git clone <your-repo-url> /opt/bot
cd /opt/bot
chmod +x deploy/oracle/bootstrap.sh
./deploy/oracle/bootstrap.sh
```

После этого:

1. заполнить `/opt/bot/.env`
2. при необходимости настроить `nginx`
3. перезапустить сервисы

```bash
sudo systemctl restart bot.service admin-dashboard.service
sudo systemctl status bot.service
sudo systemctl status admin-dashboard.service
```

## Beget VPS

Для этого проекта на Beget лучше использовать VPS, а не обычный виртуальный хостинг, потому что боту нужны постоянный polling-процесс, Redis и отдельная web-admin.

Подготовлены файлы:

- `deploy/beget/bootstrap.sh`
- `deploy/beget/nginx-admin.conf`

Базовый сценарий:

```bash
git clone https://github.com/lerasobakinazlaya-del/botptsr.git /opt/bot
cd /opt/bot
chmod +x deploy/beget/bootstrap.sh
./deploy/beget/bootstrap.sh
```

После этого:

1. заполнить `/opt/bot/.env`
2. при необходимости настроить `nginx`
3. запустить или перезапустить сервисы

```bash
sudo systemctl restart bot.service admin-dashboard.service
sudo systemctl status bot.service
sudo systemctl status admin-dashboard.service
```

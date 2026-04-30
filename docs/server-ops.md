# Server Ops

Эта заметка нужна, чтобы не повторять одни и те же детали по серверу в чате.

## Основное

- Приложение по умолчанию разворачивается в `/opt/bot`.
- `systemd`-юниты:
- `bot.service`
- `admin-dashboard.service`
- Redis обязателен для production.

## SSH

Текущая команда подключения:

- `ssh -i $HOME\.ssh\id_ed25519 root@89.125.91.152`

Параметры:

- Host: `89.125.91.152`
- Port: `22`
- User: `root`

Если данные не должны храниться в git, держать их только локально или в менеджере паролей.

## Быстрая диагностика места

```bash
cd /opt/bot
du -sh ./* ./.git ./.pytest_cache ./.mypy_cache ./.ruff_cache ./venv ./logs ./backups 2>/dev/null | sort -h
find /opt/bot -type f -size +10M -printf "%s %p\n" 2>/dev/null | sort -n
find /opt/bot -mindepth 1 -maxdepth 2 \( -type f -o -type d \) -exec du -sh {} + 2>/dev/null | sort -h | tail -30
```

## Безопасная очистка

Подготовленный скрипт:

```bash
cd /opt/bot
chmod +x deploy/systemd/cleanup_disk.sh
APP_DIR=/opt/bot KEEP_BACKUPS=7 KEEP_LOG_DAYS=7 ./deploy/systemd/cleanup_disk.sh
```

Если нужно сильнее освободить место и пересобрать окружение:

```bash
cd /opt/bot
chmod +x deploy/systemd/cleanup_disk.sh
APP_DIR=/opt/bot REBUILD_VENV=1 KEEP_BACKUPS=5 KEEP_LOG_DAYS=3 ./deploy/systemd/cleanup_disk.sh
```

Что делает скрипт:

- удаляет `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`
- удаляет старые `*.log`
- оставляет только последние backup-файлы БД
- чистит pip cache
- делает `VACUUM` для SQLite
- опционально пересобирает `venv` только с production-зависимостями

## Journald

На сервере выставлен лимит для systemd journal через:

- `/etc/systemd/journald.conf.d/99-size-limits.conf`

Текущие лимиты:

- `SystemMaxUse=200M`
- `SystemKeepFree=1G`
- `SystemMaxFileSize=50M`
- `RuntimeMaxUse=50M`
- `MaxRetentionSec=14day`

Проверка:

```bash
journalctl --disk-usage
cat /etc/systemd/journald.conf.d/99-size-limits.conf
systemctl is-active systemd-journald
```

## Production dependencies

- Production-зависимости: `requirements-prod.txt`
- Development/test-зависимости: `requirements.txt`
- Docker и server bootstrap должны ставить только `requirements-prod.txt`

## Деплой

Основные файлы:

- `deploy/systemd/update_bot.sh`
- `deploy/systemd/cleanup_disk.sh`
- `deploy/systemd/bot.service`
- `deploy/systemd/admin-dashboard.service`
- `deploy/oracle/bootstrap.sh`
- `deploy/beget/bootstrap.sh`

GitHub Actions:

- `.github/workflows/deploy.yml`
- `.github/workflows/diagnose-bot.yml`

## Что обычно можно удалять

- старые файлы в `logs/`
- старые файлы в `backups/`
- `__pycache__/`
- `.pytest_cache/`
- `.mypy_cache/`
- `.ruff_cache/`
- pip cache
- старый `venv` перед пересборкой

## Что удалять с осторожностью

- `.env`
- `bot.db`
- `config/*.json`
- `config/release.json`
- `deploy/systemd/*.service`

## Заметки для следующей сессии

Если снова понадобится помощь с сервером, сначала открыть этот файл и свериться с:

- SSH-данными
- текущим путём приложения
- командами диагностики места
- сценарием очистки и пересборки `venv`

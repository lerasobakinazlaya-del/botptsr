#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/bot}"
KEEP_BACKUPS="${KEEP_BACKUPS:-7}"
KEEP_LOG_DAYS="${KEEP_LOG_DAYS:-7}"
REBUILD_VENV="${REBUILD_VENV:-0}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
BOT_SERVICE="${BOT_SERVICE:-bot.service}"
ADMIN_SERVICE="${ADMIN_SERVICE:-admin-dashboard.service}"

echo "==> Disk usage before cleanup"
du -sh \
  "${APP_DIR}" \
  "${APP_DIR}/venv" \
  "${APP_DIR}/logs" \
  "${APP_DIR}/backups" \
  "${APP_DIR}/.git" \
  "${APP_DIR}/bot.db" \
  "${APP_DIR}/bot.db-wal" \
  "${APP_DIR}/bot.db-shm" 2>/dev/null || true

echo "==> Removing Python caches"
find "${APP_DIR}" -type d \( -name "__pycache__" -o -name ".pytest_cache" -o -name ".mypy_cache" -o -name ".ruff_cache" \) -prune -exec rm -rf {} +
find "${APP_DIR}" -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete

echo "==> Removing old logs"
find "${APP_DIR}" -type f -name "*.log" -mtime +"${KEEP_LOG_DAYS}" -delete

echo "==> Trimming backup retention"
if [ -d "${APP_DIR}/backups" ]; then
  mapfile -t OLD_BACKUPS < <(find "${APP_DIR}/backups" -maxdepth 1 -type f -name "bot-*.db.gz" | sort -r | tail -n +"$((KEEP_BACKUPS + 1))")
  if [ "${#OLD_BACKUPS[@]}" -gt 0 ]; then
    rm -f "${OLD_BACKUPS[@]}"
  fi
fi

echo "==> Vacuuming SQLite database when present"
if [ -f "${APP_DIR}/bot.db" ]; then
  "${PYTHON_BIN}" - "${APP_DIR}/bot.db" <<'PY'
import sqlite3
import sys
from pathlib import Path

db_path = Path(sys.argv[1])
conn = sqlite3.connect(db_path)
try:
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    conn.execute("VACUUM;")
finally:
    conn.close()
PY
fi

echo "==> Removing pip cache"
rm -rf "${HOME}/.cache/pip"
sudo rm -rf /root/.cache/pip 2>/dev/null || true

if [ "${REBUILD_VENV}" = "1" ]; then
  echo "==> Rebuilding production virtual environment"
  sudo systemctl stop "${BOT_SERVICE}" "${ADMIN_SERVICE}" || true
  rm -rf "${APP_DIR}/venv"
  "${PYTHON_BIN}" -m venv "${APP_DIR}/venv"
  "${APP_DIR}/venv/bin/pip" install --upgrade pip
  "${APP_DIR}/venv/bin/pip" install --no-cache-dir -r "${APP_DIR}/requirements-prod.txt"
  sudo systemctl start "${BOT_SERVICE}" "${ADMIN_SERVICE}"
fi

echo "==> Disk usage after cleanup"
du -sh \
  "${APP_DIR}" \
  "${APP_DIR}/venv" \
  "${APP_DIR}/logs" \
  "${APP_DIR}/backups" \
  "${APP_DIR}/.git" \
  "${APP_DIR}/bot.db" \
  "${APP_DIR}/bot.db-wal" \
  "${APP_DIR}/bot.db-shm" 2>/dev/null || true

echo "==> Cleanup completed"

#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/bot}"
BRANCH="${1:-${DEPLOY_BRANCH:-main}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
BOT_SERVICE="${BOT_SERVICE:-bot.service}"
ADMIN_SERVICE="${ADMIN_SERVICE:-admin-dashboard.service}"

echo "==> Updating project in ${APP_DIR}"
cd "${APP_DIR}"

if [ ! -d .git ]; then
  echo "Git repository not found in ${APP_DIR}"
  exit 1
fi

echo "==> Fetching branch ${BRANCH}"
git fetch --all --prune
git checkout "${BRANCH}"
git pull --ff-only origin "${BRANCH}"

echo "==> Preparing virtual environment"
if [ ! -x "./venv/bin/python" ]; then
  "${PYTHON_BIN}" -m venv venv
fi

./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

echo "==> Verifying Python files"
./venv/bin/python -m py_compile main.py admin_dashboard.py

echo "==> Updating systemd unit files"
sudo cp deploy/systemd/bot.service /etc/systemd/system/bot.service
sudo cp deploy/systemd/admin-dashboard.service /etc/systemd/system/admin-dashboard.service
sudo systemctl daemon-reload

echo "==> Restarting services"
sudo systemctl restart "${BOT_SERVICE}" "${ADMIN_SERVICE}"

echo "==> Service status"
sudo systemctl --no-pager --full status "${BOT_SERVICE}" "${ADMIN_SERVICE}" || true

echo "==> Deployment completed"

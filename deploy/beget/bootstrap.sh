#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/bot"
PYTHON_BIN="python3"

sudo apt-get update
sudo apt-get install -y git redis-server python3 python3-venv python3-pip nginx

sudo mkdir -p "$APP_DIR"
sudo chown -R "$USER":"$USER" "$APP_DIR"

if [ ! -d "$APP_DIR/.git" ]; then
  echo "Clone your repository into $APP_DIR before rerunning this script."
  exit 1
fi

cd "$APP_DIR"

$PYTHON_BIN -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install --no-cache-dir -r requirements-prod.txt

sudo systemctl enable redis-server
sudo systemctl restart redis-server

if ! redis-cli ping >/dev/null 2>&1; then
  echo "Redis did not respond to ping after bootstrap."
  sudo systemctl --no-pager --full status redis-server || true
  exit 1
fi

sudo cp deploy/systemd/bot.service /etc/systemd/system/bot.service
sudo cp deploy/systemd/admin-dashboard.service /etc/systemd/system/admin-dashboard.service
sudo systemctl daemon-reload
sudo systemctl enable bot.service
sudo systemctl enable admin-dashboard.service

echo "Bootstrap complete. Fill /opt/bot/.env, then run:"
echo "sudo systemctl restart bot.service admin-dashboard.service"

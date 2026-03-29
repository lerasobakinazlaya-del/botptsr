#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/bot}"
BRANCH="${1:-${DEPLOY_BRANCH:-main}}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
BOT_SERVICE="${BOT_SERVICE:-bot.service}"
ADMIN_SERVICE="${ADMIN_SERVICE:-admin-dashboard.service}"
REDIS_SERVICE="${REDIS_SERVICE:-redis-server.service}"
SKIP_GIT="${SKIP_GIT:-0}"

ensure_redis() {
  echo "==> Ensuring Redis is installed and running"

  if ! command -v redis-server >/dev/null 2>&1 || ! command -v redis-cli >/dev/null 2>&1; then
    if command -v apt-get >/dev/null 2>&1; then
      sudo apt-get update
      sudo apt-get install -y redis-server
    else
      echo "Redis is not installed and apt-get is unavailable."
      echo "Install Redis manually or set a working REDIS_URL before deployment."
      exit 1
    fi
  fi

  sudo systemctl enable "${REDIS_SERVICE}"
  sudo systemctl restart "${REDIS_SERVICE}"

  if ! redis-cli ping >/dev/null 2>&1; then
    echo "Redis ping failed after restart."
    sudo systemctl --no-pager --full status "${REDIS_SERVICE}" || true
    exit 1
  fi
}

echo "==> Updating project in ${APP_DIR}"
cd "${APP_DIR}"

if [ "${SKIP_GIT}" != "1" ]; then
  if [ ! -d .git ]; then
    echo "Git repository not found in ${APP_DIR}"
    exit 1
  fi

  echo "==> Fetching branch ${BRANCH}"
  git fetch --all --prune
  git checkout "${BRANCH}"
  git pull --ff-only origin "${BRANCH}"
else
  echo "==> SKIP_GIT=1, using already synced sources"
fi

echo "==> Preparing virtual environment"
if [ ! -x "./venv/bin/python" ]; then
  "${PYTHON_BIN}" -m venv venv
fi

ensure_redis

./venv/bin/pip install --upgrade pip
./venv/bin/pip install -r requirements.txt

echo "==> Verifying Python files"
./venv/bin/python -m compileall -q main.py admin_dashboard.py core handlers services scripts tests

echo "==> Validating JSON config files"
./venv/bin/python - <<'PY'
import json
from pathlib import Path

validated = []
for path in sorted(Path("config").glob("*.json")):
    json.loads(path.read_text(encoding="utf-8"))
    validated.append(path.name)

print("Validated:", ", ".join(validated))
PY

if [ "${RUN_TESTS:-1}" = "1" ]; then
  echo "==> Running automated prelaunch checks"
  ./venv/bin/python scripts/prelaunch_check.py --strict-env
else
  echo "==> RUN_TESTS=0, skipping tests"
fi

echo "==> Writing release metadata"
mkdir -p config
if [ -d .git ]; then
  CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
  CURRENT_COMMIT="$(git rev-parse HEAD)"
else
  CURRENT_BRANCH="${DEPLOY_BRANCH:-${BRANCH}}"
  CURRENT_COMMIT="${DEPLOY_COMMIT:-unknown}"
fi
DEPLOYED_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
cat > config/release.json <<EOF
{
  "branch": "${CURRENT_BRANCH}",
  "commit": "${CURRENT_COMMIT}",
  "deployed_at": "${DEPLOYED_AT}"
}
EOF

echo "==> Updating systemd unit files"
sudo cp deploy/systemd/bot.service /etc/systemd/system/bot.service
sudo cp deploy/systemd/admin-dashboard.service /etc/systemd/system/admin-dashboard.service
sudo systemctl daemon-reload

echo "==> Restarting services"
sudo systemctl restart "${BOT_SERVICE}" "${ADMIN_SERVICE}"

echo "==> Service status"
sudo systemctl --no-pager --full status "${REDIS_SERVICE}" "${BOT_SERVICE}" "${ADMIN_SERVICE}" || true

echo "==> Deployment completed"

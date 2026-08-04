#!/usr/bin/env bash
# 在香港 ECS 上执行：从 git 仓库同步 API 文件到 ~/workflow-api 并重启服务
set -euo pipefail

REPO_DIR="${REPO_DIR:-/root/pybroker_trade-vue}"
APP_DIR="${APP_DIR:-/root/workflow-api}"
SRC="$REPO_DIR/A_stocks/ma_strategy_project/pybroker_integration"
BRANCH="${DEPLOY_BRANCH:-main}"

if [[ ! -d "$REPO_DIR/.git" ]]; then
  echo "ERROR: $REPO_DIR 不是 git 仓库。请先在服务器执行一次性初始化（见部署文档 §1.3）。"
  exit 1
fi

cd "$REPO_DIR"
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git reset --hard "origin/$BRANCH"

mkdir -p "$APP_DIR/config"
FILES=(
  workflow_server.py
  db.py
  auth_api.py
  admin_api.py
  membership_api.py
  membership_service.py
  payment_api.py
  onboarding_api.py
  events_api.py
  events_service.py
  rate_limit.py
  requirements.txt
)
for f in "${FILES[@]}"; do
  cp -f "$SRC/$f" "$APP_DIR/$f"
done
if [[ -f "$SRC/config/workflow_runner.yaml" ]]; then
  cp -f "$SRC/config/workflow_runner.yaml" "$APP_DIR/config/workflow_runner.yaml"
fi

cd "$APP_DIR"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r requirements.txt

sudo systemctl restart workflow-api
sudo systemctl is-active workflow-api
echo "deploy ok: $(date -Is)"

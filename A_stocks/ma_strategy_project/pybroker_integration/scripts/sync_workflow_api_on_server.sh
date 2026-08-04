#!/usr/bin/env bash
# 香港 ECS：git pull 全量 pybroker_integration，安装依赖，systemd 在该目录跑 uvicorn
set -euo pipefail

REPO_DIR="${REPO_DIR:-/root/pybroker_trade-vue}"
SRC="$REPO_DIR/A_stocks/ma_strategy_project/pybroker_integration"
BRANCH="${DEPLOY_BRANCH:-main}"
SERVICE_NAME="${SERVICE_NAME:-workflow-api}"
OLD_APP_DIR="${OLD_APP_DIR:-/root/workflow-api}"

if [[ ! -d "$REPO_DIR/.git" ]]; then
  echo "ERROR: $REPO_DIR 不是 git 仓库。请先按部署文档初始化 clone。"
  exit 1
fi

cd "$REPO_DIR"
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git reset --hard "origin/$BRANCH"

if [[ ! -d "$SRC" ]]; then
  echo "ERROR: 缺少目录 $SRC"
  exit 1
fi

# 迁移旧精简部署的 SQLite（仅首次）
if [[ -d "$OLD_APP_DIR/.pybrokercache" && ! -d "$SRC/.pybrokercache" ]]; then
  echo "migrate sqlite cache from $OLD_APP_DIR"
  cp -a "$OLD_APP_DIR/.pybrokercache" "$SRC/.pybrokercache"
fi

cd "$SRC"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -U pip
echo "pip install requirements.txt + requirements-server.txt (含 lib-pybroker)..."
pip install -q -r requirements.txt
if [[ -f requirements-server.txt ]]; then
  pip install -r requirements-server.txt
fi

PYTHON_BIN="$SRC/.venv/bin/python"
PARENT_DIR="$(dirname "$SRC")"

# 冒烟：与本地一致的核心策略依赖必须可 import
echo "smoke import: pybroker / sklearn / numba / matplotlib / akshare..."
"$PYTHON_BIN" - <<'PY'
import importlib
need = ["pybroker", "sklearn", "numba", "matplotlib", "akshare", "pandas", "numpy"]
missing = []
for name in need:
    try:
        importlib.import_module(name)
        print(f"OK {name}")
    except Exception as e:
        missing.append(f"{name}: {e}")
        print(f"FAIL {name}: {e}")
if missing:
    raise SystemExit("strategy deps missing:\n" + "\n".join(missing))
print("strategy deps ok")
PY

# 保留已有 systemd 环境变量（避免每次 deploy 冲掉 JWT / Token）
if [[ -f "/etc/systemd/system/${SERVICE_NAME}.service" ]]; then
  if [[ -z "${MVP_JWT_SECRET:-}" ]]; then
    MVP_JWT_SECRET="$(grep -E '^Environment=MVP_JWT_SECRET=' "/etc/systemd/system/${SERVICE_NAME}.service" | head -1 | sed 's/^Environment=MVP_JWT_SECRET=//' || true)"
  fi
  if [[ -z "${TUSHARE_TOKEN:-}" ]]; then
    TUSHARE_TOKEN="$(grep -E '^Environment=TUSHARE_TOKEN=' "/etc/systemd/system/${SERVICE_NAME}.service" | head -1 | sed 's/^Environment=TUSHARE_TOKEN=//' || true)"
  fi
fi
MVP_JWT_SECRET="${MVP_JWT_SECRET:-change-me-to-a-long-random-string}"
TUSHARE_TOKEN="${TUSHARE_TOKEN:-}"

# systemd：工作目录 = 全量 integration；PYTHONPATH 含上级以便 data.* / pybroker_integration.*
sudo tee "/etc/systemd/system/${SERVICE_NAME}.service" >/dev/null <<EOF
[Unit]
Description=workflow_server FastAPI (full scripts)
After=network.target

[Service]
WorkingDirectory=$SRC
Environment=CORS_ORIGINS=https://freealpha.lol,https://www.freealpha.lol
Environment=MVP_JWT_SECRET=$MVP_JWT_SECRET
Environment=TUSHARE_TOKEN=$TUSHARE_TOKEN
Environment=PYTHONPATH=$PARENT_DIR
Environment=PYTHONUTF8=1
ExecStart=$PYTHON_BIN -m uvicorn workflow_server:app --host 127.0.0.1 --port 8765
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"
sudo systemctl is-active "$SERVICE_NAME"

# 冒烟：关键脚本应在工作目录可见
if [[ -f "$SRC/fetch_dc_concept_ma5.py" ]]; then
  echo "script ok: fetch_dc_concept_ma5.py"
else
  echo "WARN: fetch_dc_concept_ma5.py missing after pull"
fi

echo "deploy full ok: $(date -Is) root=$SRC"

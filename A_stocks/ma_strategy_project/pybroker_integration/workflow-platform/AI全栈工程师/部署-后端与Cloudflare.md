# 线上部署：前端（Cloudflare）+ 后端最小步骤

Cloudflare Pages/Workers **只能托管静态前端**，不能跑 FastAPI / SQLite / 策略子进程。  
线上要登录、配额、支付、跑工作流，必须另起一台能访问的后端，并让前端指向它。

## 架构

```
浏览器 → https://freealpha.lol（静态 SPA）
       → https://你的后端（香港轻量 IP/域名 → FastAPI）
```

本地仍可用桌面快捷方式：前端 5173 + 本机 8765（相对路径 `/api`，无需 `VITE_API_BASE_URL`）。

---

## 0. 测试阶段平台选型（已确认 · 2026-08-04 修订）

目标用户：**国内访问**。测试阶段优先打通 **API + 前端 `VITE_API_BASE_URL`**（登录 / 会员 / Admin）；完整策略跑通可后置。

| 阶段 | 平台 | 说明 |
|------|------|------|
| **现在（测试）** | **香港 2 核轻量 VPS**（阿里云 / 腾讯云） | **支付宝可买**；免备案；国内访问优于海外 PaaS |
| **有国际卡时可选** | Railway | 部署快，但仅 Stripe 国际卡；试用过期且无卡则跳过 |
| **正式 / 完整工作流** | 大陆或香港轻量（建议 ≥2 核 2G） | SQLite、本地脚本、长跑策略最稳 |
| **暂不上** | **阿里云 SAE** | 镜像 / 挂载成本高，不适合当前测试 |
| **不适合后端** | Cloudflare Workers / 纯 Serverless | 无法承载本仓库 FastAPI 工作流 |

**实操路径（冻结）：**

1. 购买 **香港地区** 轻量（建议 **2 核 2G**，Ubuntu 22.04）  
2. 按 §1.1 安装依赖、启动 `workflow_server`、开防火墙  
3. （推荐）Caddy/Nginx 上 HTTPS；测试也可先用 `http://公网IP:8765`  
4. Cloudflare 构建变量设 `VITE_API_BASE_URL=<后端根地址>`，重新 Deploy  
5. 验登录 / 配额 / Admin（`demo@workflow.local` / `demo1234`）  
6. **SAE 先别上**；Railway 无国际卡则不跟

**支付说明：** Railway Hobby 仅国际信用卡，**无支付宝/微信** → 国内测试默认走香港轻量。

能力对照（测试期）：

| 能力 | 香港轻量 VPS | Railway / Render / Fly | SAE |
|------|--------------|------------------------|-----|
| 国内支付购机 | ✅ 支付宝等 | ❌ 需国际卡 | ✅ |
| 登录 / 会员 / Admin | ✅ | ✅ | ✅（配置重） |
| 真正跑工作流脚本 | ✅（装全项目后） | ⚠️ | ⚠️ |
| 国内打开速度 | 较好 | 偏慢 | 大陆最好（以后） |

---

## 1. 后端最小启动

在装有本仓库 `pybroker_integration` 的机器上：

```bash
# 依赖（最小 API）
pip install -r requirements.txt
# 或: pip install fastapi "uvicorn[standard]" pyyaml pydantic

export CORS_ORIGINS=https://freealpha.lol,https://www.freealpha.lol
export MVP_JWT_SECRET='请换成足够长的随机串'

# 测试期可直接暴露 8765；生产用反代后只监听 127.0.0.1
python -m uvicorn workflow_server:app --host 0.0.0.0 --port 8765
```

验证：`curl http://公网IP:8765/api/config`（或 HTTPS 域名）应返回 JSON，不是 HTML。

### 1.1 香港 2 核轻量（当前测试首选）

#### A. 购机（控制台）

1. 打开 **阿里云轻量** 或 **腾讯云轻量** → 地域选 **香港**  
2. 镜像：**Ubuntu 22.04**  
3. 套餐：**≥ 2 核 2G**（1 核仅够极简验通，跑策略偏紧）  
4. 防火墙 / 安全组放行：**22**（SSH）、**8765**（先测 API）；上 HTTPS 后再放 **80/443**  
5. 记下 **公网 IP**，用 SSH 登录（密钥或控制台密码）

#### B. 机器上首次安装

```bash
sudo apt update
sudo apt install -y python3 python3-pip python3-venv git

# 代码：任选 git clone 或 scp/rsync 上传 pybroker_integration
# 示例（按你的仓库地址改）：
# git clone <你的仓库URL> repo && cd repo/A_stocks/ma_strategy_project/pybroker_integration

cd /path/to/pybroker_integration
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export CORS_ORIGINS=https://freealpha.lol,https://www.freealpha.lol
export MVP_JWT_SECRET='请换成足够长的随机串'

# 前台试跑（确认 /api/config 通了再改成 systemd 常驻）
python -m uvicorn workflow_server:app --host 0.0.0.0 --port 8765
```

本机浏览器访问：`http://公网IP:8765/api/config` → JSON 即后端通。

#### C. 常驻（systemd 示例）

```bash
sudo tee /etc/systemd/system/workflow-api.service >/dev/null <<'EOF'
[Unit]
Description=workflow_server FastAPI
After=network.target

[Service]
WorkingDirectory=/path/to/pybroker_integration
Environment=CORS_ORIGINS=https://freealpha.lol,https://www.freealpha.lol
Environment=MVP_JWT_SECRET=请换成足够长的随机串
ExecStart=/path/to/pybroker_integration/.venv/bin/python -m uvicorn workflow_server:app --host 0.0.0.0 --port 8765
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now workflow-api
sudo systemctl status workflow-api
```

把两处 `/path/to/pybroker_integration` 换成真实路径。

#### D. HTTPS（推荐，可用子域名）

- 在 Cloudflare（或域名 DNS）把 `api.freealpha.lol`（或任意子域）**A 记录**指到香港机公网 IP  
- 安装 Caddy 或 Nginx，反代到 `127.0.0.1:8765`，并申请证书  
- 之后前端 `VITE_API_BASE_URL=https://api.freealpha.lol`（无尾斜杠）  

测试若赶时间：可暂时用 `http://公网IP:8765`（注意浏览器混合内容：前端是 **https://freealpha.lol** 时，**不能**调 http API，须上 HTTPS 或临时用同协议方案）。

> **重要：** 线上前端是 HTTPS 时，`VITE_API_BASE_URL` 必须也是 **https://...**，否则浏览器会拦混合内容。

#### E. 打通 Cloudflare 前端

1. 后端根地址确定（如 `https://api.freealpha.lol`）  
2. Cloudflare 构建变量：`VITE_API_BASE_URL=https://api.freealpha.lol`  
3. 重新 Deploy  
4. 站点登录：`demo@workflow.local` / `demo1234`；管理：`admin@workflow.local` / `admin1234`

### 1.2 Railway（有国际卡时可选）

本目录已备：`Dockerfile` / `railway.toml` / `requirements.txt` / `.dockerignore`。

```bash
cd A_stocks/ma_strategy_project/pybroker_integration
railway login
railway init --name workflow-api-test
railway variables set CORS_ORIGINS=https://freealpha.lol,https://www.freealpha.lol
railway variables set MVP_JWT_SECRET=请换成足够长的随机串
railway up
railway domain
```

**本机进度（2026-08-04）：** CLI 已登录；因 **trial expired** + **仅国际卡支付**，测试路径改香港轻量。套餐开通后仍可按上表部署。

**香港 ECS 实测进度（2026-08-04）：**

| 项 | 状态 |
|----|------|
| 机器 | 阿里云香港 `47.76.54.42`，Ubuntu 22.04，2核2G |
| API 目录 | `~/workflow-api`（zip 部署） |
| DNS | `api.freealpha.lol` → 该 IP |
| Caddy | 反代 `127.0.0.1:8765`，HTTPS 已通 |
| 前端 | Cloudflare `VITE_API_BASE_URL=https://api.freealpha.lol`，登录已通 |
| 注意 | `uvicorn` 须 **systemd 常驻**，否则关 SSH 后易 502 / Failed to fetch |
| DNS 代理 | `api` 可用橙云；**手机登录**建议前端走同源 `/api`（Worker 反代），构建时 **清空** `VITE_API_BASE_URL` |
| SSL | Cloudflare 对源站用 **Full / Full strict**（Caddy 已签证书） |

### 1.4 手机登录验收：同源 `/api` 反代（推荐）

现象：电脑能登、手机蜂窝「无法连接」——页面在 Cloudflare，登录却直连 `api.`，部分运营商不稳定。

做法：

1. 仓库已含 `workflow-platform/worker.js`：把 `https://freealpha.lol/api/*` 反代到 `API_ORIGIN`（默认 `https://api.freealpha.lol`）  
2. Cloudflare 构建变量：**删除或清空** `VITE_API_BASE_URL`（必须为空，前端才用相对路径 `/api`）  
3. 重新 Deploy 前端（`npm run build` + `wrangler deploy`）  
4. 手机流量打开站点登录；可在手机访问 `https://freealpha.lol/api/config` 应返回 JSON  

电脑 WiFi / 手机流量都应只请求 `freealpha.lol`，不再依赖单独打通 `api.` 子域。

### 1.5 全量策略脚本部署（已确认）

此前 `/root/workflow-api` 只有登录 API，不含 `fetch_dc_concept_ma5.py` 等。  
现改为 systemd 工作目录：

`/root/pybroker_trade-vue/A_stocks/ma_strategy_project/pybroker_integration`

同步脚本会 `git pull`、安装 `requirements.txt` + `requirements-server.txt`、重启服务，并在首次迁移旧 SQLite。  
东财等脚本如需 Token：GitHub Secret `TUSHARE_TOKEN`，或写入 systemd 环境变量后 restart。

冒烟：不应再出现 `脚本不存在: /root/workflow-api/fetch_...`。

限制：SQLite 在容器内，重部署可能丢库；完整策略数据未进镜像。

### 1.3 GitHub → 香港 ECS 自动部署（已确认要做）

推送到 `main` 且变更后端相关文件时，Actions 会 SSH 到服务器：`git pull` → 同步到 `~/workflow-api` → `systemctl restart workflow-api`。

前端仍由 Cloudflare 构建；**本流水线只更新 API**。

#### A. 服务器一次性初始化（SSH 执行）

```bash
# 1) 允许 GitHub Actions 用密钥登录（在你本机生成密钥后，把公钥写入服务器）
mkdir -p ~/.ssh && chmod 700 ~/.ssh
# 将本机生成的 deploy key 公钥内容追加到：
#   ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys

# 2) clone 仓库（路径须与下方默认一致，或改 GitHub Secret）
cd /root
# 若仓库为私有，需配置 deploy key / PAT；公有可直接：
git clone https://github.com/taobb123/pybroker_trade-vue.git
# 若你的 GitHub 用户名/仓库不同，改成实际地址

# 3) 确认 API 目录与 systemd 仍指向 /root/workflow-api（已有则可跳过）
ls /root/workflow-api
sudo systemctl status workflow-api --no-pager | head -15
```

本机生成专用部署密钥（不要用你日常登录密钥上传到 GitHub）：

```powershell
ssh-keygen -t ed25519 -f $env:USERPROFILE\.ssh\workflow_ecs_deploy -N '""'
# 公钥发给服务器 authorized_keys：
# Get-Content $env:USERPROFILE\.ssh\workflow_ecs_deploy.pub
# 私钥整段（含 BEGIN/END）粘到 GitHub Secret ECS_SSH_KEY
```

#### B. GitHub 仓库 Secrets

路径：仓库 → **Settings → Secrets and variables → Actions → New repository secret**

| Secret | 必填 | 示例 |
|--------|------|------|
| `ECS_HOST` | 是 | `47.76.54.42` |
| `ECS_USER` | 是 | `root` |
| `ECS_SSH_KEY` | 是 | 上面私钥全文 |
| `ECS_REPO_DIR` | 否 | 默认 `/root/pybroker_trade-vue` |
| `ECS_APP_DIR` | 否 | 默认 `/root/workflow-api` |

工作流文件：`.github/workflows/deploy-workflow-api.yml`  
服务器同步脚本：`.../pybroker_integration/scripts/sync_workflow_api_on_server.sh`

#### C. 验证

1. 合并/推送上述文件到 `main`  
2. GitHub → **Actions** → 看 **Deploy workflow-api (HK ECS)** 是否绿  
3. 也可手动 **Run workflow**  
4. 打开 `https://api.freealpha.lol/api/config` 确认仍 200  

**注意：** 私有仓库时，服务器上 `git fetch` 需要额外凭证（deploy key 只读挂到该仓库，或 HTTPS PAT）。公有仓库一般无需。

---

## 2. 前端构建变量

仓库已支持 `VITE_API_BASE_URL`（见 `src/config/apiBase.ts`、`.env.example`）。

| 环境 | 取值 |
|------|------|
| 本地 `npm run dev` | 留空 |
| Cloudflare（香港轻量） | `https://api.你的域名` 或带证书的后端根地址 |
| Cloudflare（Railway） | `https://xxxx.up.railway.app` |

```
VITE_API_BASE_URL=https://你的后端根地址
```

须重新 `npm run build` / Deploy 后生效。

---

## 3. 常见故障

| 现象 | 原因 | 处理 |
|------|------|------|
| 登录 405 / 响应是 HTML | 请求打到静态站 | 配置并重建 `VITE_API_BASE_URL` |
| CORS 报错 | 后端未允许前端 Origin | 设 `CORS_ORIGINS` 后重启 |
| `Unexpected token '<'` | API base 指错或后端未开 | 先 curl `/api/config` |
| 混合内容被拦 | HTTPS 页请求了 http API | 给后端上 HTTPS |
| 连不上 8765 | 安全组未放行 | 香港轻量防火墙放行 8765/443 |
| 工作流跑失败但登录正常 | 机器缺数据/脚本 | 装全项目后再跑步骤 |

---

## 4. 演示账号（后端 DB 种子）

- 用户：`demo@workflow.local` / `demo1234`
- 管理：`admin@workflow.local` / `admin1234`

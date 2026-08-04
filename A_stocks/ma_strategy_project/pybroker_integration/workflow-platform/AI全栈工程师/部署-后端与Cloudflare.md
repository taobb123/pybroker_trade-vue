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

限制：SQLite 在容器内，重部署可能丢库；完整策略数据未进镜像。

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

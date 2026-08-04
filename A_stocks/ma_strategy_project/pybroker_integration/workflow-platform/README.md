# workflow-platform

新工作流平台（与旧版 `docs/stock_pool_workflow.html` **并存**）。

## 选定模板

- **壳**：官方 shadcn-vue Dashboard 形态（Sidebar + Header + Content）
- **执行台**：Workflow **列表** + 右侧 **Output Sheet**（非固定三栏）
- **数据层**：Tremor 风格 KPI / BarList / StatusPill + 后续 ECharts

## 技术栈

```
Vue 3 · Vite · TypeScript
Tailwind CSS 4
shadcn-vue（reka-nova）+ reka-ui + @lucide/vue
Tremor 风格数据组件（src/components/tremor）
vue-router · pinia
vue-echarts · echarts（已依赖，报告页下一期接入）
```

## 目录

```
src/
  layouts/AppShell.vue          # SidebarProvider + SidebarInset
  pages/
    DashboardPage.vue           # KPI + BarList + Table
    WorkflowsPage.vue           # 列表 + Sheet 执行
    RunsPage.vue                # Skeleton 占位
    ReportsPage.vue             # Tabs 占位
  components/
    ui/                         # shadcn-vue 正式组件（见下）
    tremor/                     # KpiCard / BarList / StatusPill
    workflow/                   # WorkflowRow / OutputSheet
  api/workflow.ts
  stores/workflow.ts
components.json                 # shadcn-vue 配置
```

## 已接入 shadcn-vue 组件

`button` `badge` `card` `input` `separator` `scroll-area` `tabs` `select`  
`table` `dialog` `sheet` `dropdown-menu` `tooltip` `sidebar` `skeleton`

补充组件：

```bash
npx shadcn-vue@latest add <component> -y
```

## 页面状态

| 页面 | 状态 |
|---|---|
| 登录 `/login` | **样板**：Mock 登录（邮箱/手机可选 + 一键演示）；不接真 Auth |
| 用户中心 `/account` | **样板**：头像缩写 / 昵称 / 邮箱 / 手机 / 会员等级 / 邀请码 |
| 会员套餐 `/billing/plans` | **样板**：Free / Pro / Team；Pro Mock 升档；Team 联系客服 |
| 订单 `/billing/orders` | **样板**：Mock 订单列表（本地） |
| 用量 `/usage` | **样板**：访问 KPI + 30 日趋势 + Top（访问 Mock；运行次数读本地历史） |
| 总览 Dashboard | KPI + 最近结果 BarList / 预览表（工作流结果向，与用量分离） |
| 工作流 Workflows | 按 YAML 动态输入（粘贴/形态ID/模式/池/编辑）+ 查看产物链接 |
| 运行记录 Runs | 历史表 + 筛选 + 日志 Sheet + 跳转报告 |
| 报告 Reports | 工作区表（CSV）+ 文档（Markdown）+ 文本（TXT）+ 图形（PNG）+ 预测 K 线（JSON/ECharts）+ 次要日志 |

侧栏底部为账户菜单；未登录不阻断工作流主路径。

运行历史保存在 `localStorage`（`workflow-platform:run-history:v1`）。

## 启动

**桌面快捷方式（推荐）**

- 双击桌面「流控制台 Vue 平台」→ 运行 `start-dev.bat`（自动 `npm run dev` 并打开浏览器）
- 若快捷方式丢失，可重新生成：

```powershell
cd workflow-platform
powershell -ExecutionPolicy Bypass -File .\create-desktop-shortcut.ps1
```

**命令行**

1. 可选：先启动旧后端 `python -m uvicorn workflow_server:app --host 127.0.0.1 --port 8765`
2. 前端：

```bash
cd workflow-platform
npm install
npm run dev
# 或
start-dev.bat
```

浏览器打开 Vite 地址（默认 `http://127.0.0.1:5173`）。  
`/api` 已代理到 `8765`；后端未启动时，Workflows 使用内置 mock 数据与模拟输出。

## 线上 API 地址

Cloudflare 只托管静态前端。构建时设置：

```
VITE_API_BASE_URL=https://你的后端域名
```

见 `.env.example` 与 `AI全栈工程师/部署-后端与Cloudflare.md`。

测试阶段平台路径（已确认）：**香港 2 核轻量打通 API + `VITE_API_BASE_URL`（支付宝可购）；Railway 无国际卡则跳过；SAE 暂不上**。

## 与旧台关系

- 旧台：`docs/stock_pool_workflow.html` 继续可用
- 新台：本目录 SPA，共用同一 FastAPI API
- 不强制迁移；按页面逐步增强报告与图表

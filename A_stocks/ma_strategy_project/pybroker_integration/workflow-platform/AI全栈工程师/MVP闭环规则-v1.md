# MVP 闭环规则 v1

> **依据**：`产品经理/商业项目计划1.2.md`（**忽略 Sprint/工期**）  
> **协作**：`产品经理/协作纪要/005-MVP闭环规则-基于1.2.md`  
> **继承**：`业务闭环-产品规则设计-v1.md` 中套餐/配额/门控数字（Free10 / Pro100 / ¥99 · 006 决议）  
> **主导沟通**：产品定优先级与验收；工程定模型与落地切片  

---

## 0. MVP 目标一句话

让**可识别的用户**完成：注册 → 首次跑通 → 触达付费点 → 支付生效 → 导出价值，并且**全程可审计、可纠偏**。

---

## 1. 闭环定义（必须全部可走通）

```
注册/登录（users）
  → Onboarding（身份 + 推荐 + 体验次数）
  → 运行工作流（runs 归属 user_id，扣配额）
  → 限额/高级门控 → 升级 CTA
  → 支付（orders）→ membership 自动生效
  → 报告导出（report.export）
  → events 漏斗可查
  → admin 可查人/单并手工改会员与额度
```

**非目标**：更多策略、更多图表、完整 BI、自动退款、多租户 Team 席位。

---

## 2. 优先级与 MVP 范围

| 优先级 | 模块 | MVP 规则要点 |
|--------|------|----------------|
| **P0** | 用户身份 | 必须有持久化 `users`；业务表全挂 `user_id` |
| **P1** | 权益自动化 | 支付 `paid` ⇒ 写 membership + 配额窗口归属该用户；与前端规则一致 |
| **P2** | Onboarding | 首登强制/可跳过一次；赠送体验次数；推荐 1 条基础工作流 |
| **P3** | 行为事件 | 最小 5 事件入库存；支撑漏斗计数 |
| **P4** | Admin | 列表用户/订单/运行；手工改 plan、加 bonus、禁用用户 |
| **P5** | 安全薄做 | run 速率限制；订单态含 pending/paid/failed/cancelled |

---

## 3. 逻辑数据模型（最小）

### 3.1 users

| 字段 | 说明 |
|------|------|
| id | PK |
| email | 唯一 |
| password_hash | MVP 邮箱密码 |
| nickname / avatar_text | 资料上限字段 |
| phone | 可选 |
| role | `user` \| `admin` |
| status | `active` \| `disabled` |
| onboarding_done | bool |
| persona | 可选：investor / researcher / explorer |
| created_at / last_login_at | |

### 3.2 memberships

| 字段 | 说明 |
|------|------|
| id / user_id | |
| plan | free \| pro \| team |
| start_at / expire_at | Pro 支付成功 +30 天；free 的 expire 空 |
| updated_at | |

> 有效 plan = memberships 当前行；到期回落 free（与既有规则一致）。

### 3.3 quota_ledger（日配额）

| 字段 | 说明 |
|------|------|
| user_id + date | 联合唯一 |
| used_runs | 发起即 +1（含失败） |
| bonus_runs | Onboarding/Admin 赠送，当日有效 |
| | 可用 = daily_limit(plan) + bonus - used；Team daily_limit=-1 |

### 3.4 payments / orders

| 字段 | 说明 |
|------|------|
| id / user_id / plan / amount_yuan / channel | |
| status | pending \| paid \| failed \| cancelled |
| provider_ref / paid_at / created_at | |
| period_days | 默认 30 |

**自动化规则**：`status` 变为 `paid` 时事务内：更新 membership +（可选）写入 bonus=0 的新日窗。

### 3.5 workflow_runs

| 字段 | 说明 |
|------|------|
| id / user_id / step_id / status / started_at / finished_at | |
| plan_snapshot | 发起时档位 |
| exit_code / log_ref | 日志可仍文件；库存元数据 |

### 3.6 events

| 字段 | 说明 |
|------|------|
| id / user_id(nullable) / event_name / props_json / created_at | |

**MVP 事件名（仅此 5 个）**：

| event_name | 触发 |
|------------|------|
| `page_view` | 关键页进入（工作流/套餐/报告） |
| `run_strategy` | 发起 run |
| `export_report` | 复制/下载报告成功 |
| `click_upgrade` | 点击升级/打开支付 Sheet |
| `payment_success` | 订单 paid |

### 3.7 admin_actions（可选薄表）

记录人工改会员/加额度：admin_id, target_user_id, action, payload, created_at。

---

## 4. 产品规则（相对 v1 的增量）

### 4.1 身份

| 规则 | MVP |
|------|-----|
| 注册 | 邮箱+密码；字段仍遵守资料上限 |
| 登录后 | 所有 run/支付/导出必须登录 |
| guest | **仅只读浏览**；`ENFORCE_AUTH_FOR_RUN=true` |
| 禁用 | status=disabled 禁止登录与 run |

### 4.2 Onboarding

| 步骤 | 规则 |
|------|------|
| 1 | 选身份三选一（可跳过则 persona=null） |
| 2 | 推荐 **1 条 basic** 工作流（固定配置 ID，如 `roc_20`） |
| 3 | 写入 `bonus_runs=+3`（当日）；标记可进入工作台 |
| 完成 | `onboarding_done=true`；其后不再强弹（Admin 可重置） |

### 4.3 套餐 / 门控（沿用已确认数字）

| 档位 | 日配额 | 高级 | 导出 |
|------|--------|------|------|
| Free | 10 + 当日 bonus | ❌ | ❌ |
| Pro | 100 | ✅ | ✅ |
| Team | 不限 | ✅ | ✅ |

支付成功自动化：与 v1 相同（plan、expire_at、订单 paid），但**必须落库挂 user_id**。

### 4.4 漏斗（产品看的数）

```
page_view(unique users)
  → 注册用户数
  → run_strategy 用户数
  → click_upgrade 用户数
  → payment_success 用户数
```

Admin 或简单 `/admin/funnel` 聚合即可，不做可视化大盘。

### 4.5 Admin 最小能力

- 用户列表：邮箱、plan、status、今日 used  
- 订单列表：状态筛选  
- 操作：设 plan/expire、加当日 bonus、禁用/启用  
- 不写：退款打款、营销活动引擎  

### 4.6 安全薄规则

| 规则 | MVP |
|------|-----|
| run rate limit | 每用户每分钟 ≤ 10 次发起（可配置） |
| 支付异常 | 允许 pending 滞留；Admin 可手工 paid 纠偏或 cancelled |
| 退款 | 不做自动；纠偏靠 Admin 降档 |

---

## 5. 与现有代码的衔接

| 现有 | MVP 动作 |
|------|----------|
| `businessRules.ts` | 保留为权益数字源；服务端镜像同数字 |
| `payment_api.py` | 订单写入 DB；回调更新 membership |
| `stores/auth|quota|billing` | 改为调后端 API，逐步去掉「仅本地真相」 |
| `/usage` Mock 访问 | 保留展示；真漏斗以 `events` 为准 |

---

## 6. 实现切片（只排序，不写工期）

| 刀 | 内容 | 完成定义 |
|----|------|----------|
| **M1** | SQLite + users 注册/登录/JWT + 强制登录 run | 有库、能登录、run 带 user_id | ✅ |
| **M2** | memberships + quota_ledger 服务端化；支付回调写库 | 换浏览器仍保留会员与配额 | ✅ |
| **M3** | Onboarding 三步 + bonus+3 | 新用户 5 分钟内可完成首次 basic run | ✅ |
| **M4** | events 五类埋点 + 简单漏斗查询 | 能算出访问→付费漏斗人数 | ✅ |
| **M5** | Admin 薄后台 | 能改会员/加额度/禁用 | ✅ |
| **M6** | rate limit + 订单 failed 态 | 刷跑与异常单可处理 | ✅ |

---

## 7. MVP 上线检查表（规则验收）

### 用户侧

| 项 | 验收 |
|----|------|
| 注册登录 | 有持久用户 |
| 个人中心 | 展示 plan / 配额 / 导出权益 |
| 历史运行 | 按 user_id 隔离 |
| Onboarding | 首登可完成并获 bonus |

### 商业侧

| 项 | 验收 |
|----|------|
| 套餐+支付 | 成功后库内 membership=pro |
| 订单 | pending→paid 可查 |
| 自动开通 | 无需手工改库（Admin 仅纠偏） |

### 增长侧

| 项 | 验收 |
|----|------|
| 五类事件 | 有数据 |
| 漏斗 | 能输出四个转化人数 |
| 反馈入口 | **MVP 可不做**（1.2 标 ❌，本规则剔除） |

---

## 8. 产品确认后执行

确认纪要 005「决议」五条默认假设后，从 **M1 用户库 + 登录服务端化** 开工。

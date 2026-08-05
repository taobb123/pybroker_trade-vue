# 实现记录 · 价值 MVP S1 机会雷达

> 依据：`产品经理/协作纪要/007-价值MVP-巴菲特理念无AI.md`  
> 日期：2026-08-05 · 假设 Q1–Q4 已确认

## 交付（S1）

| 项 | 说明 |
|----|------|
| 路由 | `/` → `RadarPage`（机会雷达）；原总览迁至 `/overview` |
| 侧栏 | 「机会雷达」置顶；「运行总览」保留 |
| 规则 | `config/opportunityRules.ts`：阈值 80、分项平均、无 AI 文案 |
| 领域 | `domain/opportunity.ts`：`scoreOpportunity` |
| Mock | `data/mockOpportunities.ts`；`?empty=1` 验收「今日无好球」 |
| 卡片 | `components/radar/OpportunityCard.vue`：分项 + 是/等待 + 研究深链 |
| Onboarding 落地 | 默认回 `/` 雷达（不再强制推荐策略页） |

## 验收对照

| # | 状态 |
|---|------|
| V1 首屏「今天有没有好球？」 | ✅ |
| V2 mock 好球卡片结构 | ✅ |
| V3 空态「今日无好球」 | ✅（`/?empty=1`） |
| V4 观察池 | ⏳ S2（按钮占位禁用） |
| V5 好球→工作流 | ✅（S1 深链；报告链路 S3 可再补） |
| V6 无 AI 暗示 | ✅ |
| V7 旧路径保留 | ✅ `/overview` + 工作流等 |

## 下一刀

S2：观察池 CRUD（localStorage）+ 目标买入区状态；启用「加入观察池」。

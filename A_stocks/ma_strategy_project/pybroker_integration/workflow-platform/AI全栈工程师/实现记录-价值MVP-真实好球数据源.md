# 实现记录 · 价值 MVP 真实好球数据源（形态优先）

> 日期：2026-08-05  
> 依据：[摸底好球数据源](3350c1dc-fd03-438b-a0f4-5050f6f23051) 结论纠偏

## 优先级（已落地）

```
pattern_entry_scan.csv（+ valuation_rank 可选）
  → roc_20 运行日志 JSON
  → factor_investing_ranking_latest.csv
  → MOCK 演示
市场环境：market_temperature_latest.csv（否则演示）
```

| 项 | 说明 |
|----|------|
| 主文件 | `data/loadOpportunities.ts` |
| 趋势分 | pattern `score` 归一；`entry`/`待选`/`建仓` 加权 |
| 估值分 | `undervalued` / `upside` → `scores.valuation` |
| 理想区 | `fair_price` 或 `platform_level`–`breakout_high` |
| stepId | 形态源为 `fetch_pattern_entry` |

## 注意

- 无专用「今日机会」API；一律 `GET /api/workspace/table`
- pattern 原始分远低于 80，**必须归一**，否则永远「等待」
- 后端未启动时回退演示；有工作区产物且 API 可达时显示真实列表

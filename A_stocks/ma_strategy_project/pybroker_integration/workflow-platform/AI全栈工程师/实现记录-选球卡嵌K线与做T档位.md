# 实现记录 · 选球卡嵌 K 线 + 做 T 档位

> 日期：2026-08-05 · 用户确认需求

## 需求

1. **选股**：市场中性多头净值 Top2 因子 × 各因子排名 Top2 股  
2. **选球卡**：卡片内嵌预测 K 线；**K 线右侧**标注做 T 的买一/买二/…（非把卡嵌进 K 线页）

## 落地

| 文件 | 职责 |
|------|------|
| `data/selectPitches.ts` | `metrics.csv` → Top2 因子；对应 rank CSV → Top2 股 |
| `data/tLevels.ts` | `today_high_low_result.csv` → 按股票名称索引档位 |
| `components/radar/EmbeddedPitchKline.vue` | 迷你 K 线 + 右侧做 T 档位条 |
| `components/radar/PitchSelectCard.vue` | 选球卡（评分 + K线档位 + 操作） |
| `pages/RadarPage.vue` | 优先选球模式；无中性产物则回退旧雷达 |

## 数据依赖

- `market_neutral/output/latest/metrics.csv`（`long_total_return` / `*_L`）
- 排名表：`pattern_entry_*_rank.csv` / scan
- `prediction_kline_compare.json`、`today_high_low_result.csv`（做 T）

## 注意

- 做 T 结果 CSV **无 symbol 列**，档位按 **股票名称** 匹配  
- 预测 K 线 JSON 仅含做 T 列表内标的；未跑入列表则卡内显示占位提示  

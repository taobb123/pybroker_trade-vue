# 实现记录 · 回测对比 combo2+3 vs 4+6（仅多头年化）

## 产品确认

- 步骤形态 **A**：单步骤对比  
- 主指标：**仅多头 `*_L` 年化**  
- **不动**原「量价六组合」默认 watch 4+6  

## 交付

| 项 | 说明 |
|----|------|
| 步骤 id | `vp_combo_23_long_compare` |
| 脚本 | `run_vp_combo_23_long_compare.py` |
| 中性扩展 | `--combo-ids` / `--latest-dir`（2+3 写入 `combo23_latest`，不覆盖 4+6 `latest`） |
| 归档播种 | `seed_from_current_watch` 按 combo 补缺（4+6 有档时仍可种 2+3） |
| 产物 | `vp_combo_23_vs_46_long_annual.md` / `.csv` |
| 自选推送 | 固定 M-：`combo23` 最新 `factor_snapshot` 按 `mud_minus` Top2 → 东财「23M减」；排名表 `vp_combo_23_mminus_top.csv` |

## 运行顺序建议

1. `fetch_vp_six_combo`（生成 scan）  
2. `market_neutral`（生成 4+6 基线 `output/latest`）  
3. `vp_combo_23_long_compare`（导出 2+3 → 回测 → 对比）  

## 注意

2+3 历史归档初期偏少时，长区间回测更依赖近期池；摘要已写明。

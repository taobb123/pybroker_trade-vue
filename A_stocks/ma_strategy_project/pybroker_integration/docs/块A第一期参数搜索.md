# 块 A 第一期参数搜索

脚本：`param_block_a_search.py`。

得分：观察池（combo 4 或 combo 6）入池日收盘，到其后第 10 个交易日收盘的收益。同一代码 10 个交易日内只计第一次。

搜索网格只含会改变观察池成员的 Phase1 常数：放量阈值、底部位置、高位位置。各折在训练段取收益前四分位，再取中位；折与折之间再取中位。最后一段交易日只评价一次，不参与选参。

缩量阈值、形态回踩与再突破常数、共振分、`match_exact` 保持 `docs/系统参数初始状态.md`。缩量和形态常数不决定谁进入观察池，这份得分移动不了它们。

运行：

```text
python pybroker_integration/param_block_a_search.py
```

产物在 `output/param_block_a/report.md`。脚本不修改 `VP_SIX_CONFIG` 和 `config/workflow_runner.yaml`。

\(H_0\)（2+3 对 4+6 的仅多头年化）不在本期使用。

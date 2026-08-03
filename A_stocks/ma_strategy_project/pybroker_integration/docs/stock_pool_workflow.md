# 选股票池 · 工作流一页集成

个人自用：与 topic 图示一致的线性流程。命令均在 **`pybroker_integration` 项目根目录**执行。

### 交互控制台（推荐）

在项目根目录执行：

```bash
pip install -r requirements-workflow.txt
python -m uvicorn workflow_server:app --host 127.0.0.1 --port 8765
```

浏览器打开 **http://127.0.0.1:8765/** ：可编辑 `config/workflow_runner.yaml`、单步运行、一键全部（失败即停、合并日志）；步骤上可 **编辑输入文件**（如 `stocks_pool.txt`、`config/backtest_sy_threshold.yaml`）、**预览表格输出**（仅配置为 `workspace_outputs` 的 csv/tsv）。勿用 `file://` 打开该 HTML。

回测起止日期与初始资金见 **`config/backtest_sy_threshold.yaml`**（`backtest_sy_002028_threshold` / `backtest_sy_base_cost_search` 共用）。

纯静态只读时仍可打开 **`stock_pool_workflow.html`**（无运行能力）。

---

## 0. 市场温度计 - 每日仓位报告（建议最先运行）

```bash
python market_temperature_model.py
```

综合指数趋势、成交额、上涨家数、热点持续性，输出 0~100 分与阶梯建议仓位（20/40/70/100%）。结果见 `market_temperature_latest.csv`。

控制台 **market_temperature** 步骤可用 **运行模式** 下拉切换：

| 模式 | 说明 |
|------|------|
| 每日报告（默认） | `market_temperature_model.py`；日常请看这个，输出仓位建议 |
| 快速回测 | `market_temperature_backtest.py --fast --forward 5,10,20 --brief`；结束日默认截至最近交易日 |
| 回测并校准 | 同上 + `--calibrate --apply --brief`，写入 `config/market_temperature_calibration.json`，日志精简并追加每日仓位报告 |

回测起始日见 `config/workflow_runner.yaml` 中 `run_modes` 的 `--start`；未写 `--end` 时自动取最近有数据的交易日。日常使用优先点 **查看 · 每日仓位报告**，不必盯回测过程日志。

---

## 1. 运行 OpenBB

参考本地 OpenBB 流程（图示：OpenBB P）。无统一命令行入口。

## 2. 20 日 ROC 排序（沪深300、中证A500、中证1000）

控制台 **roc_20** 步骤用下拉选择股票池 txt（预设路径见 `config/workflow_runner.yaml` 的 `pool_presets`，可选手动自定义路径）；运行成功后点 **复制 Top20** 可将最近一次排名前 20 写入剪贴板（制表符分隔）。其它步骤仍用项目内 `stocks_pool.txt`。

```bash
python factor_investing_20ROC.py --pool "C:\Users\111\Desktop\股票池\沪深300.txt"
```

## 3. 发现异动

```bash
python morning_limit_up_news.py
```

### 3.1 按题材分类（AI 算力、有色金属、新能源、化工）

```bash
python classify_morning_limit_up.py
```

#### 3.1.1 按成长因子排序（保留资产安全、现金流质量为正）

```bash
python factor_growthT_indicator.py
```

##### 加入自选

###### 观察是否「回踩支撑结构」（结合 20 日线，可问 OpenAI 辅助判断）

```bash
python backtest_sy_base_cost_search.py
```

```bash
python fetch_a_share_spot_delayed_1m.py --compare-table
```

- **做 T、调仓、止盈止损、优化股票池**

  ```bash
  python compute_today_prices.py
  ```

- **验证支撑反弹结构**（按当日自选修改 `--symbols`）

  ```bash
  python fetch_a_low.py --symbols 002821,002378,601872
  ```

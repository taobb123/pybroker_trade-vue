# 轮动策略文档

本文档说明两个轮动交易策略的实现和使用方法。

## 策略概述

### 策略1：趋势行情轮动策略

**适用场景**: 趋势行情（单边上涨或下跌）

**排名依据**: 过去20天的收益率（ROC）

**使用指标**（用于买卖点判断）:
- **MACD**: 趋势跟踪指标，判断趋势方向和强度
- **RSI**: 相对强弱指标，判断超买超卖状态
- **成交量**: 成交量比率，判断市场参与度

**策略逻辑**:
1. **排名阶段**: 根据过去20天的收益率（ROC）对所有股票进行排名
2. **持仓管理**: 
   - 将资金的50%分配给前2名股票（各50%）
   - 如果持有的股票不在前5名中，则卖出
3. **买卖点判断**:
   - **买入条件**: 股票在前2名中 + 指标显示买入信号
     - MACD线在信号线上方 或 MACD柱状图为正
     - RSI在合理区间（30-80）
     - 成交量比率大于0.8
   - **卖出条件**: 股票不在前5名中 或 指标显示卖出信号
     - MACD线在信号线下方且柱状图为负
     - 或 RSI严重超买（>80）或严重超卖（<30）

### 策略2：均值回归轮动策略

**适用场景**: 震荡行情（价格围绕均值波动）

**排名依据**: 过去20天的收益率（ROC）

**使用指标**（用于买卖点判断）:
- **Z分数**: 价格偏离均值的标准差倍数
- **布林带**: 价格波动区间，判断价格位置

**策略逻辑**:
1. **排名阶段**: 根据过去20天的收益率（ROC）对所有股票进行排名
2. **持仓管理**: 
   - 将资金的50%分配给前2名股票（各50%）
   - 如果持有的股票不在前5名中，则卖出
3. **买卖点判断**:
   - **买入条件**: 股票在前2名中 + 指标显示买入信号
     - Z分数为负（价格低于均值）
     - 价格接近或低于布林带下轨（位置<0.3）
   - **卖出条件**: 股票不在前5名中 或 指标显示卖出信号
     - Z分数为正且较大（>1.0，价格高于均值，回归完成）
     - 或 价格接近或高于布林带上轨（位置>0.7）

## 目录结构

```
src/
├── modules/
│   ├── indicators.py          # 技术指标定义
│   └── signals.py             # 信号生成逻辑
├── strategies/
│   ├── trend_rotation_strategy.py          # 趋势轮动策略
│   └── mean_reversion_rotation_strategy.py # 均值回归轮动策略
└── ...

run_rotation_strategies.py     # 主执行文件
```

## 使用方法

### 方法1：使用主执行文件（推荐）

```bash
cd ma_strategy_project/pybroker_integration
python run_rotation_strategies.py
```

这将同时运行两个策略并进行对比。

### 方法2：单独运行策略

#### 运行趋势轮动策略

```python
from src.strategies import TrendRotationStrategy

# 创建策略实例
strategy = TrendRotationStrategy(
    max_positions=2,        # 最大持仓数量
    rank_threshold=5,        # 排名阈值（从前5名中选择）
    initial_cash=50000      # 初始资金
)

# 运行回测
symbols = ['600570', '600690', '000738', ...]
result = strategy.run_backtest(
    symbols=symbols,
    start_date='20240501',
    end_date='20251128',
    warmup=26
)
```

#### 运行均值回归轮动策略

```python
from src.strategies import MeanReversionRotationStrategy

# 创建策略实例
strategy = MeanReversionRotationStrategy(
    max_positions=2,         # 最大持仓数量
    rank_threshold=5,        # 排名阈值（从前5名中选择）
    initial_cash=50000,      # 初始资金
    zscore_weight=0.6,      # Z分数权重
    bollinger_weight=0.4     # 布林带权重
)

# 运行回测
symbols = ['600570', '600690', '000738', ...]
result = strategy.run_backtest(
    symbols=symbols,
    start_date='20240501',
    end_date='20251128',
    warmup=20
)
```

## 参数说明

### 趋势轮动策略参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `max_positions` | 最大持仓数量 | 2 |
| `rank_threshold` | 排名阈值（从前N名中选择） | 5 |
| `initial_cash` | 初始资金 | 50000 |

### 均值回归轮动策略参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `max_positions` | 最大持仓数量 | 2 |
| `rank_threshold` | 排名阈值（从前N名中选择） | 5 |
| `initial_cash` | 初始资金 | 50000 |
| `zscore_weight` | Z分数权重 | 0.6 |
| `bollinger_weight` | 布林带权重 | 0.4 |

## 输出结果

回测结果会保存到 `data/processed/` 目录：

- `trend_rotation_result.csv`: 趋势轮动策略的交易记录
- `mean_reversion_rotation_result.csv`: 均值回归轮动策略的交易记录

每个CSV文件包含以下列：
- `symbol`: 股票代码
- `entry_date`: 买入日期
- `exit_date`: 卖出日期
- `shares`: 交易股数
- `entry_price`: 买入价格
- `exit_price`: 卖出价格
- `pnl`: 盈亏
- 等等

## 策略优化说明

### 核心优化点

1. **排名与买卖点分离**:
   - **排名**: 使用过去20天的收益率（ROC）进行排名，选择表现最好的股票
   - **买卖点**: 使用技术指标判断具体的买入和卖出时机

2. **资金分配**:
   - 前2名股票各分配50%资金
   - 确保资金集中投资于表现最好的股票

3. **风险控制**:
   - 如果股票退出前5名，立即卖出
   - 即使在前5名中，如果指标显示卖出信号，也会卖出

## 策略选择建议

### 何时使用趋势轮动策略

- 市场处于明显的趋势行情（单边上涨或下跌）
- 成交量放大，市场参与度高
- 技术指标显示明确的趋势信号

### 何时使用均值回归轮动策略

- 市场处于震荡行情（价格围绕均值波动）
- 成交量相对稳定
- 价格偏离均值较多，有回归潜力

## 注意事项

1. **预热期**: 
   - 趋势策略需要26个Bar的预热期（确保MACD等指标有足够数据）
   - 均值回归策略需要20个Bar的预热期

2. **数据质量**: 确保股票数据完整，避免因数据缺失导致指标计算失败

3. **参数调优**: 根据实际市场情况调整权重参数，可以通过回测优化找到最佳参数

4. **风险管理**: 建议设置止损和止盈，控制单笔交易的风险

## 扩展建议

1. **动态权重**: 根据市场状态动态调整指标权重
2. **止损止盈**: 添加止损和止盈逻辑
3. **仓位管理**: 根据市场波动性动态调整仓位
4. **多策略组合**: 结合两个策略，根据市场状态自动切换

## 参考资源

- [MACD指标说明](https://www.investopedia.com/terms/m/macd.asp)
- [RSI指标说明](https://www.investopedia.com/terms/r/rsi.asp)
- [布林带指标说明](https://www.investopedia.com/terms/b/bollingerbands.asp)
- [均值回归策略](https://www.investopedia.com/terms/m/meanreversion.asp)


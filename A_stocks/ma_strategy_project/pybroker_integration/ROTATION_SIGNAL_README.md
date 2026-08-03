# 轮动策略实时信号生成器使用说明

## 功能概述

`rotation_signal_generator.py` 是一个基于轮动策略的实时买入信号生成工具。它基于 `rotation_trade.py` 的策略逻辑，使用 **tushare** 数据源获取最新市场数据，计算 ROC 20 指标，并对股票进行排名，输出买入信号用于人工建仓。

## 核心功能

1. **数据获取**：使用 tushare 获取最新的股票数据（最近60天）
2. **指标计算**：计算每只股票的 ROC 20（20日价格变化率）指标
3. **股票排名**：根据 ROC 指标对所有股票进行降序排名
4. **信号生成**：输出前2名股票的买入信号（与轮动策略的最大持仓数一致）
5. **结果输出**：在控制台打印信号，并保存到 CSV 文件

## 策略参数

- **ROC 周期**：20天
- **最大持仓数**：2只股票
- **排名阈值**：前5名（如果持仓股票跌出前5名，建议卖出）
- **资金分配**：每只股票分配 50% 的资金

## 使用方法

### 1. 配置 tushare token

确保在 `config/settings.py` 中配置了 tushare token：

```python
DATA_CONFIG = {
    'tushare_token': 'your_token_here',  # 替换为您的 token
}
```

### 2. 运行脚本

```bash
cd ma_strategy_project/pybroker_integration
python rotation_signal_generator.py
```

### 3. 查看输出

脚本会在控制台输出：
- 数据获取进度
- 每只股票的 ROC 指标值
- **买入信号**（前2名）
- **参考排名**（前5名）
- 建仓建议

同时会生成一个 CSV 文件，包含详细的买入信号信息。

## 输出示例

```
================================================================================
轮动策略买入信号
================================================================================
生成时间: 2024-12-02 15:30:00
策略参数: ROC周期=20, 最大持仓=2, 排名阈值=5
--------------------------------------------------------------------------------

【买入信号】前 2 名（建议建仓）:
--------------------------------------------------------------------------------
1. 股票代码: 603194
   ROC 20: 15.23%
   当前价格: 45.60 元
   数据日期: 2024-12-02
   排名: 第 1 名

2. 股票代码: 301626
   ROC 20: 12.45%
   当前价格: 38.90 元
   数据日期: 2024-12-02
   排名: 第 2 名

【参考信息】前 5 名排名:
--------------------------------------------------------------------------------
✓  1. 603194   - ROC:   15.23% - 价格:    45.60 元
✓  2. 301626   - ROC:   12.45% - 价格:    38.90 元
   3. 603596   - ROC:   10.12% - 价格:    52.30 元
   4. 300308   - ROC:    8.56% - 价格:    28.70 元
   5. 300502   - ROC:    7.89% - 价格:    35.20 元

================================================================================
建仓建议:
1. 建议买入前 2 只股票
2. 每只股票分配 50% 的资金
3. 如果持仓股票跌出前 5 名，建议卖出
================================================================================
```

## 代码使用示例

### 基本使用

```python
from pybroker_integration.rotation_signal_generator import RotationSignalGenerator

# 创建信号生成器（默认使用 tushare）
generator = RotationSignalGenerator(use_tushare_only=True)

# 定义股票列表
symbols = ['603194', '301626', '603596', ...]

# 生成买入信号
result = generator.generate_buy_signals(symbols)

# 打印信号
generator.print_signals(result)

# 保存到 CSV
generator.save_signals_to_csv(result, 'my_signals.csv')
```

### 自定义参数

```python
# 创建生成器
generator = RotationSignalGenerator(use_tushare_only=True)

# 修改策略参数
generator.roc_period = 20
generator.max_positions = 2
generator.rank_threshold = 5
generator.lookback_days = 60

# 生成信号
result = generator.generate_buy_signals(symbols)
```

### 仅获取排名（不生成信号）

```python
generator = RotationSignalGenerator()
ranked_stocks = generator.rank_stocks(symbols)

# ranked_stocks 是一个列表，包含所有股票的排名信息
for stock in ranked_stocks:
    print(f"{stock['rank']}. {stock['symbol']}: ROC={stock['roc']:.2f}%")
```

## 注意事项

1. **数据源**：脚本默认使用 tushare，如果 token 未配置，会自动回退到其他数据源
2. **数据要求**：需要至少 20 天的历史数据才能计算 ROC 20 指标
3. **网络连接**：需要网络连接以获取最新数据
4. **API 限制**：tushare 根据积分有不同的调用频率限制，请注意控制调用频率
5. **交易日**：建议在交易日运行，获取最新的市场数据

## 与 rotation_trade.py 的关系

- **相同点**：
  - 使用相同的策略逻辑（ROC 20 排名）
  - 相同的参数设置（最大持仓2只，排名阈值5）
  - 相同的股票池

- **不同点**：
  - `rotation_trade.py`：用于历史回测
  - `rotation_signal_generator.py`：用于实时信号生成

## 故障排除

### 问题1：tushare token 未配置

**解决方案**：在 `config/settings.py` 中配置 token，或设置 `use_tushare_only=False` 使用其他数据源

### 问题2：数据获取失败

**可能原因**：
- 网络连接问题
- API 调用频率限制
- 股票代码格式错误

**解决方案**：
- 检查网络连接
- 等待一段时间后重试
- 确认股票代码格式正确

### 问题3：ROC 计算失败

**可能原因**：历史数据不足（少于20天）

**解决方案**：增加 `lookback_days` 参数值

## 文件输出

脚本会在 `pybroker_integration` 目录下生成 CSV 文件，文件名格式：
- `rotation_signals_YYYYMMDD_HHMMSS.csv`

CSV 文件包含以下列：
- `symbol`: 股票代码
- `roc`: ROC 20 指标值
- `price`: 当前价格
- `date`: 数据日期
- `rank`: 排名
- `data_points`: 数据点数量

## 更新日志

- **v1.0** (2024-12-02): 初始版本
  - 基于 rotation_trade.py 的策略逻辑
  - 支持 tushare 数据源
  - 生成买入信号并保存到 CSV


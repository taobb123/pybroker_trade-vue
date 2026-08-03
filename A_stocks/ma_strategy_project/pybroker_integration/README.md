# PyBroker 集成说明

本项目已集成 **PyBroker** 框架，支持快速回测和机器学习策略开发。

## 什么是 PyBroker？

PyBroker 是一个专为量化交易和机器学习策略开发设计的 Python 框架，具有以下特点：

- ⚡ **快速回测引擎**：基于 NumPy 和 Numba 加速
- 📊 **数据源支持**：支持 AKShare、Yahoo Finance、Alpaca 等
- 🔄 **Walkforward 分析**：模拟真实交易环境
- 📈 **可靠指标**：使用随机化自举法提供更准确的交易指标
- 💾 **数据缓存**：缓存下载的数据、指标和模型，加速开发
- 🚀 **并行计算**：提升计算性能

## 安装

```bash
pip install -U lib-pybroker
```

或使用项目的 requirements.txt：

```bash
pip install -r requirements.txt
```

## 快速开始

### 方法1: 转换现有策略（推荐）

将项目中已有的策略（如 `MovingAverageStrategy`）转换为 PyBroker 格式：

```python
from strategies.moving_average import MovingAverageStrategy
from pybroker_integration.adapter import convert_strategy_to_pybroker
from data.fetcher import DataFetcher

# 创建现有策略
strategy = MovingAverageStrategy(short_window=5, long_window=20)

# 转换为 PyBroker 适配器
adapter = convert_strategy_to_pybroker(
    strategy=strategy,
    initial_cash=100000,
    commission=0.001
)

# 获取数据
with DataFetcher() as fetcher:
    data = fetcher.fetch_stock_data(
        code='600111',
        start_date='2023-01-01',
        end_date='2023-12-31'
    )

# 运行 PyBroker 回测
result = adapter.run_backtest(
    data=data,
    start_date='2023-01-01',
    end_date='2023-12-31',
    symbol='600111'
)
```

### 方法2: 使用 PyBroker 原生方式

直接使用 PyBroker 的 API 创建策略：

```python
import pybroker as pb

# 定义策略
def my_strategy(ctx: pb.Context):
    # 计算均线
    try:
        ma5 = ctx.sma('close', 5)
        ma20 = ctx.sma('close', 20)
    except AttributeError:
        # 如果不可用，使用数据计算
        data = ctx.data
        ma5 = data['close'].rolling(window=5, min_periods=1).mean().iloc[-1]
        ma20 = data['close'].rolling(window=20, min_periods=1).mean().iloc[-1]
    
    # 买入信号：短期均线上穿长期均线
    if ma5 > ma20 and ctx.long_positions() == 0:
        shares = int(ctx.cash / ctx.close)
        if shares > 0:
            ctx.buy_shares = shares
    
    # 卖出信号：短期均线下穿长期均线
    elif ma5 < ma20 and ctx.long_positions() > 0:
        ctx.sell_all_shares()

# 配置策略
config = pb.StrategyConfig(
    strategy=my_strategy,
    symbols=['000001'],
    start_date='2023-01-01',
    end_date='2023-12-31',
    initial_cash=100000,
    commission=0.001,
)

# 运行回测
result = pb.run_backtest(config)
```

## 模块结构

```
pybroker_integration/
├── __init__.py              # 模块初始化
├── adapter.py               # 策略适配器（将现有策略转换为 PyBroker 格式）
├── data_provider.py         # 数据提供者（集成现有数据获取模块）
├── example_pybroker.py      # 使用示例
└── README.md               # 本文件
```

## 主要功能

### 1. 策略适配器 (adapter.py)

`PyBrokerAdapter` 类可以将现有的策略对象转换为 PyBroker 格式：

- 支持 `MovingAverageStrategy`（移动平均策略）
- 支持 `MeanReversionStrategy`（均值回归策略）
- 自动处理策略参数和信号生成

### 2. 数据提供者 (data_provider.py)

`PyBrokerDataProvider` 类集成现有的数据获取模块：

- 使用 `DataFetcher` 获取数据
- 自动转换为 PyBroker 格式
- 支持注册自定义数据源

### 3. 示例代码 (example_pybroker.py)

包含多个使用示例：

- 示例1: PyBroker 原生策略
- 示例2: 转换现有策略到 PyBroker
- 示例3: 使用数据提供者
- 示例4: Walkforward 分析

运行示例：

```bash
python pybroker_integration/example_pybroker.py
```

## PyBroker 核心概念

### Context 对象

在策略函数中，`ctx: pb.Context` 提供了访问市场数据和执行交易的接口：

- `ctx.close` - 当前收盘价
- `ctx.data` - 历史数据 DataFrame
- `ctx.cash` - 当前现金
- `ctx.long_positions()` - 当前持仓数量
- `ctx.buy_shares` - 设置买入股数
- `ctx.sell_all_shares()` - 卖出所有持仓

### 策略配置

使用 `pb.StrategyConfig` 配置回测参数：

```python
config = pb.StrategyConfig(
    strategy=my_strategy,      # 策略函数
    symbols=['000001'],        # 股票代码列表
    start_date='2023-01-01',  # 开始日期
    end_date='2023-12-31',    # 结束日期
    initial_cash=100000,      # 初始资金
    commission=0.001,         # 手续费率
)
```

### 数据源

使用 `@pb.data_source` 装饰器注册自定义数据源：

```python
@pb.data_source(symbols=['000001'])
def my_data_source(symbol: str, start_date: str, end_date: str):
    # 返回包含 open, high, low, close, volume 列的 DataFrame
    # 日期作为索引
    return data
```

## 与现有系统的集成

### 使用现有数据获取模块

```python
from pybroker_integration.data_provider import PyBrokerDataProvider

provider = PyBrokerDataProvider()
data = provider.fetch_for_pybroker(
    code='600111',
    start_date='2023-01-01',
    end_date='2023-12-31'
)
```

### 使用现有策略

```python
from strategies.moving_average import MovingAverageStrategy
from pybroker_integration.adapter import convert_strategy_to_pybroker

strategy = MovingAverageStrategy(short_window=5, long_window=20)
adapter = convert_strategy_to_pybroker(strategy)
```

## 高级功能

### Walkforward 分析

PyBroker 支持 Walkforward 分析，用于模拟真实交易环境：

```python
config = pb.WalkforwardConfig(
    strategy=my_strategy,
    symbols=['000001'],
    train_start_date='2022-01-01',
    train_end_date='2022-12-31',
    test_start_date='2023-01-01',
    test_end_date='2023-12-31',
    initial_cash=100000,
    commission=0.001,
)

result = pb.run_walkforward(config)
```

### 机器学习策略

PyBroker 支持集成机器学习模型，可以使用 scikit-learn 等库：

```python
from sklearn.ensemble import RandomForestClassifier

# 定义特征工程
def create_features(data):
    # 创建特征
    return features

# 训练模型
model = RandomForestClassifier()
# ... 训练代码 ...

# 在策略中使用模型
def ml_strategy(ctx: pb.Context):
    features = create_features(ctx.data)
    prediction = model.predict(features)
    if prediction == 1:
        ctx.buy_shares = 100
```

## 注意事项

1. **数据格式**：PyBroker 需要数据以日期为索引，包含 `open`, `high`, `low`, `close`, `volume` 列
2. **API 兼容性**：不同版本的 PyBroker 可能有 API 差异，请参考官方文档
3. **性能**：PyBroker 使用 NumPy 和 Numba 加速，适合大规模回测
4. **数据源**：确保数据源可用，建议使用 AKShare 或配置好的数据源

## 参考资源

- [PyBroker 官方文档](https://www.pybroker.com/)
- [PyBroker GitHub](https://github.com/edtechre/pybroker)
- [项目主 README](../README.md)

## 示例输出

运行示例代码后，您将看到：

```
======================================================================
PyBroker 集成示例
======================================================================

======================================================================
示例2: 转换现有策略到 PyBroker
======================================================================
获取数据: 600111 (2023-11-01 至 2024-11-01)
数据获取成功，共 245 条记录
PyBroker 回测完成
结果: {...}

======================================================================
示例3: 使用数据提供者
======================================================================
数据获取成功: 245 条记录
数据列: ['open', 'high', 'low', 'close', 'volume']
日期范围: 2023-11-01 至 2024-11-01

======================================================================
示例完成
======================================================================
```

## 故障排除

### 问题1: 导入错误

如果遇到 `ModuleNotFoundError: No module named 'pybroker'`：

```bash
pip install -U lib-pybroker
```

### 问题2: 数据格式错误

确保数据包含必需的列：`open`, `high`, `low`, `close`, `volume`，并且日期作为索引。

### 问题3: API 不兼容

如果遇到 API 错误，请检查 PyBroker 版本：

```bash
pip show lib-pybroker
```

并参考对应版本的文档。

## 贡献

欢迎提交问题和改进建议！


# 均线策略量化交易系统

## 项目概述

这是一个基于双均线策略的量化交易系统，采用模块化、可复用的设计，便于扩展和维护。

**当前状态**：✅ Phase 1核心功能已完成，包括数据获取、策略实现、回测引擎和性能分析。

## 核心特性

- ✅ **混合数据源**：优先从数据库获取，失败则尝试API，最后使用模拟数据
- ✅ **策略基类设计**：易于扩展新策略
- ✅ **完整回测系统**：支持历史回测和性能分析
- ✅ **可配置参数**：策略参数和回测参数均可配置
- ✅ **详细日志**：完整的日志记录系统

## 项目结构

```
ma_strategy_project/
├── README.md                 # 项目说明文档
├── requirements.txt          # 依赖包列表
├── main.py                   # 主程序入口
├── config/                   # 配置文件目录
│   ├── __init__.py
│   ├── settings.py           # 全局配置
│   └── db_config.py          # 数据库配置（引用父级配置）
├── data/                     # 数据模块
│   ├── __init__.py
│   ├── fetcher.py            # 数据获取类
│   └── storage.py            # 数据存储类
├── strategies/               # 策略模块
│   ├── __init__.py
│   ├── base.py               # 策略基类
│   └── moving_average.py     # 双均线策略实现
├── backtest/                 # 回测模块
│   ├── __init__.py
│   ├── engine.py             # 回测引擎
│   └── analyzer.py           # 回测结果分析
├── execution/                # 执行模块
│   ├── __init__.py
│   ├── executor.py           # 策略执行器
│   └── order_manager.py      # 订单管理
├── risk/                     # 风险管理模块
│   ├── __init__.py
│   └── manager.py            # 风险管理器
├── utils/                    # 工具模块
│   ├── __init__.py
│   ├── logger.py             # 日志工具
│   └── visualization.py      # 可视化工具
└── tests/                    # 测试文件
    ├── __init__.py
    └── test_strategy.py      # 策略测试
```

## 核心功能

### 1. 数据获取（DataFetcher）✅ 已实现
- **混合方案**：优先从数据库获取，失败则尝试API（akshare/tushare），最后使用模拟数据
- 自动检测数据库中的历史数据表
- 数据格式标准化：date, open, high, low, close, volume
- 支持上下文管理器，自动管理数据库连接

### 2. 策略模块（Strategy）✅ 已实现
- **基类设计**：`BaseStrategy`抽象基类，定义了`generate_signals()`接口
- **双均线策略**：`MovingAverageStrategy`
  - 短期均线上穿长期均线 → 买入信号(1)
  - 短期均线下穿长期均线 → 卖出信号(-1)
  - 其他情况 → 持有信号(0)
- **参数可配置**：短期和长期均线周期可通过构造函数传入
- **数据验证**：自动验证数据格式和完整性
- **信号查询**：支持获取最新交易信号

### 3. 回测引擎（BacktestEngine）✅ 已实现
- **回测引擎**：`BacktestEngine`类
  - 模拟交易执行（买入、卖出、持仓管理）
  - 考虑手续费影响
  - 记录每笔交易明细
  - 计算持仓价值、总资产变化
- **性能分析**：`PerformanceAnalyzer`类
  - 总收益率、年化收益率
  - 夏普比率（风险调整后收益）
  - 最大回撤（金额、百分比、持续时间）
  - 交易统计（交易次数、胜率、平均盈亏）
- **报告输出**：详细的文本回测报告

### 4. 执行模块（Executor）⏳ Phase 2
- 实时信号生成
- 订单执行管理
- 与交易系统对接

### 5. 风险管理（RiskManager）⏳ Phase 2
- 仓位控制
- 止损止盈
- 最大回撤限制

### 6. 配置和工具 ✅ 已实现
- **配置管理**：`config/settings.py`集中管理所有配置参数
- **数据库配置**：自动引用父级`db_config.py`
- **日志系统**：统一的日志格式和输出

## 使用流程

### 基本流程

1. **数据准备**：配置数据库连接（可选），或使用API/模拟数据
2. **策略回测**：使用历史数据验证策略效果
3. **参数优化**：调整均线周期等参数，对比回测结果
4. **性能分析**：查看收益率、夏普比率、最大回撤等指标
5. **实盘执行**：Phase 2将实现实时信号生成和订单执行（待开发）

### 配置说明

编辑 `config/settings.py` 可以修改：
- 回测参数：初始资金、手续费率
- 策略默认参数：均线周期
- 数据配置：数据源优先级
- 日志配置：日志级别、文件路径

### 数据源配置

**数据获取优先级**：数据库 → API → 模拟数据

#### 1. 数据库（优先）
- 自动检测常见的历史数据表名：`stock_daily`, `daily_quotes`, `historical_data`等
- 数据库配置在父级`db_config.py`中

#### 2. API数据源（推荐）✅ 已完善

**akshare（推荐，免费）**：
```bash
pip install akshare
```
- 无需配置，安装即可使用
- 免费，数据全面

**tushare（可选）**：
```bash
pip install tushare
```
- 需要在`config/settings.py`中配置token
- 编辑`DATA_CONFIG['tushare_token']`设置您的token

**配置API偏好**：
在`config/settings.py`中设置：
```python
DATA_CONFIG = {
    'api_preference': 'akshare',  # 或 'tushare'
    'tushare_token': '',           # 仅使用tushare时需要
}
```

**测试API连接**：
```bash
python test_api.py
```

#### 3. 模拟数据（开发测试）
- 如果前两者都失败，可以使用模拟数据
- 设置`use_mock_if_fail=True`即可

详细API配置说明请查看：`API配置说明.md`

## 安装依赖

```bash
pip install -r requirements.txt
```

**注意**：
- `talib`和`plotly`为可选依赖，如需要高级技术指标或可视化功能可安装
- 如使用`akshare`获取数据，需要：`pip install akshare`
- 如使用`tushare`获取数据，需要：`pip install tushare`并配置token

## 快速开始

### 方法1：使用主程序（推荐）

```bash
python main.py
```

### 方法2：使用简单示例

```bash
python example_simple.py
```

### 方法3：在代码中使用

```python
from data.fetcher import DataFetcher
from strategies.moving_average import MovingAverageStrategy
from backtest.engine import BacktestEngine
from backtest.analyzer import PerformanceAnalyzer

# 1. 获取数据（混合方案：数据库 → API → 模拟数据）
fetcher = DataFetcher()
data = fetcher.fetch_stock_data(
    code='000001',
    start_date='2023-01-01',
    end_date='2023-12-31',
    use_mock_if_fail=True  # 如果真实数据获取失败，使用模拟数据
)

# 2. 创建策略（参数可配置）
strategy = MovingAverageStrategy(short_window=5, long_window=20)

# 3. 运行回测
engine = BacktestEngine(strategy, initial_capital=100000, commission=0.001)
results = engine.run(data)

# 4. 性能分析
analyzer = PerformanceAnalyzer()
analysis = analyzer.analyze(results)
analyzer.print_report(analysis)

# 5. 查看最新信号
latest_signal = strategy.get_latest_signal(data)
print(f"最新信号: {latest_signal['action']} @ {latest_signal['price']:.2f}")
```

## 设计原则

1. **模块化**：各模块独立，职责清晰
2. **可复用**：基类和接口设计，便于扩展新策略
3. **可测试**：每个模块都有对应的测试
4. **可配置**：参数通过配置文件管理
5. **可扩展**：易于添加新的策略、数据源、分析工具

## PyBroker 集成 ✅ 已实现

项目已集成 **PyBroker** 框架，支持快速回测和机器学习策略开发。

### PyBroker 特性

- ✅ **快速回测引擎**：基于 NumPy 和 Numba 加速
- ✅ **策略转换**：将现有策略自动转换为 PyBroker 格式
- ✅ **数据源支持**：支持 AKShare、Yahoo Finance 等数据源
- ✅ **Walkforward 分析**：模拟真实交易环境
- ✅ **可靠指标**：使用随机化自举法提供更准确的交易指标
- ✅ **数据缓存**：缓存下载的数据、指标和模型，加速开发
- ✅ **并行计算**：提升计算性能

### 使用 PyBroker

#### 方法1: 转换现有策略（推荐）

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

#### 方法2: 使用 PyBroker 原生方式

```python
import pybroker as pb

# 定义策略
def my_strategy(ctx: pb.Context):
    ma5 = ctx.indicators['sma_5']
    ma20 = ctx.indicators['sma_20']
    
    if ma5 > ma20 and ctx.long_positions() == 0:
        ctx.buy_shares = ctx.calc_target_shares(1.0)
    elif ma5 < ma20 and ctx.long_positions() > 0:
        ctx.sell_all_shares()

# 注册指标
@pb.indicator(name='sma_5')
def sma_5(data: pd.DataFrame):
    return data['close'].rolling(window=5).mean()

@pb.indicator(name='sma_20')
def sma_20(data: pd.DataFrame):
    return data['close'].rolling(window=20).mean()

# 配置并运行
config = pb.StrategyConfig(
    strategy=my_strategy,
    symbols=['000001'],
    start_date='2023-01-01',
    end_date='2023-12-31',
    initial_cash=100000,
    commission=0.001,
)

result = pb.run_backtest(config)
```

#### 运行示例

```bash
# 运行 PyBroker 集成示例
python pybroker_integration/example_pybroker.py
```

### PyBroker 模块结构

```
pybroker_integration/
├── __init__.py              # 模块初始化
├── adapter.py               # 策略适配器（将现有策略转换为 PyBroker 格式）
├── data_provider.py         # 数据提供者（集成现有数据获取模块）
└── example_pybroker.py      # 使用示例
```

### 安装 PyBroker

```bash
pip install -r requirements.txt
# 或单独安装
pip install -U lib-pybroker
```

更多 PyBroker 文档请参考：[PyBroker 官方文档](https://www.pybroker.com/)

## 待开发功能（Phase 2+）

### Phase 2: 完善功能
- [ ] 风险管理模块（仓位控制、止损止盈）
- [ ] 执行模块（实时信号生成、订单管理）
- [ ] 可视化工具（资金曲线、持仓变化图表）
- [ ] 参数优化（网格搜索最佳参数）

### Phase 3: 扩展功能
- [ ] 更多策略类型（MACD、布林带、RSI等）
- [ ] 实时数据更新
- [ ] 多股票组合回测
- [x] 机器学习策略集成（✅ 已通过 PyBroker 实现）
- [ ] Web界面（可选）

## 常见问题

**Q: 如何获取真实数据？**  
A: 配置数据库连接，或安装`akshare`库（推荐，免费且无需token）。

**Q: 如何修改策略参数？**  
A: 在创建策略时传入参数：`MovingAverageStrategy(short_window=10, long_window=30)`

**Q: 如何查看详细的交易记录？**  
A: 回测结果中的`results['trades']`包含所有交易明细。

**Q: 可以同时回测多只股票吗？**  
A: 当前版本仅支持单股票回测，多股票组合功能在Phase 3规划中。

## 项目文件说明

- `main.py` - 主程序入口，完整的回测流程示例
- `example_simple.py` - 简单的使用示例
- `TODO清单.md` - 详细的任务清单
- `项目设计文档.md` - 架构设计文档
- `设计决策讨论.md` - 设计决策记录

## 许可证

本项目为学习和研究用途，请勿用于实盘交易决策。


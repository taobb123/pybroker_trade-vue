# PyBroker 数据格式转换指南

## 概述

`PyBrokerDataFormatter` 提供了统一的数据格式转换接口，用于处理 PyBroker 策略回测中不同场景的数据格式需求。

## 支持的数据格式

### 1. INDEXED_BY_DATE（date 作为索引）
- **用途**: `PyBrokerDataProvider.fetch_for_pybroker()` 返回格式
- **格式**: 
  - 索引: `DatetimeIndex` (date)
  - 列: `open`, `high`, `low`, `close`, `volume`
- **示例**:
```python
df = PyBrokerDataFormatter.to_indexed_by_date(df, symbol='600000')
```

### 2. COLUMNS_WITH_SYMBOL（date 和 symbol 作为列）
- **用途**: `IndicatorSet` 和 `Strategy` 使用
- **格式**:
  - 列: `date`, `symbol`, `open`, `high`, `low`, `close`, `volume`
  - `date` 为 datetime 类型
- **示例**:
```python
df = PyBrokerDataFormatter.to_columns_with_symbol(df, symbol='600000')
```

### 3. COLUMNS_WITHOUT_SYMBOL（date 作为列，无 symbol）
- **用途**: 单股票 `IndicatorSet` 使用
- **格式**:
  - 列: `date`, `open`, `high`, `low`, `close`, `volume`
  - `date` 为 datetime 类型
- **示例**:
```python
df = PyBrokerDataFormatter.to_columns_without_symbol(df, symbol='600000')
```

## 使用方法

### 基本用法

```python
from pybroker_integration.data_formatter import PyBrokerDataFormatter, DataFormat

# 获取数据（date 作为索引）
df = data_provider.fetch_for_pybroker('600000', '2022-01-01', '2024-01-01')

# 转换为 IndicatorSet 需要的格式
df_for_indicators = PyBrokerDataFormatter.convert(
    df=df,
    target_format=DataFormat.COLUMNS_WITH_SYMBOL,
    symbol='600000'
)

# 使用 IndicatorSet
from pybroker import IndicatorSet
indicator_set = IndicatorSet()
indicator_set.add(my_indicator)
results = indicator_set(df_for_indicators)
```

### 创建 BarData 对象

```python
# 自动创建 BarData 对象（用于单个指标计算）
bar_data = PyBrokerDataFormatter.create_bar_data(df)
result = my_indicator(bar_data)
```

### 验证数据格式

```python
# 验证数据是否符合指定格式
is_valid, error_msg = PyBrokerDataFormatter.validate_format(
    df=df,
    required_format=DataFormat.COLUMNS_WITH_SYMBOL,
    symbol='600000'
)

if not is_valid:
    print(f"格式验证失败: {error_msg}")
```

## 完整示例

```python
from pybroker_integration.data_provider import PyBrokerDataProvider
from pybroker_integration.data_formatter import PyBrokerDataFormatter, DataFormat
from pybroker import IndicatorSet

# 1. 获取数据
data_provider = PyBrokerDataProvider()
df = data_provider.fetch_for_pybroker('600000', '2022-01-01', '2024-01-01')

# 2. 转换为 IndicatorSet 格式
df_for_indicators = PyBrokerDataFormatter.convert(
    df=df,
    target_format=DataFormat.COLUMNS_WITH_SYMBOL,
    symbol='600000'
)

# 3. 使用 IndicatorSet 计算指标
indicator_set = IndicatorSet()
indicator_set.add(indicator1)
indicator_set.add(indicator2)
results = indicator_set(df_for_indicators)

# 4. 验证格式（可选）
is_valid, error = PyBrokerDataFormatter.validate_format(
    df=df_for_indicators,
    required_format=DataFormat.COLUMNS_WITH_SYMBOL
)
```

## 优势

1. **统一接口**: 所有格式转换使用统一的接口，代码更清晰
2. **类型安全**: 使用枚举类型确保格式正确
3. **自动验证**: 自动检查必需列和数据类型
4. **易于维护**: 格式转换逻辑集中管理，易于修改和扩展
5. **错误处理**: 提供详细的错误信息，便于调试

## 注意事项

1. 确保输入 DataFrame 包含必需的 OHLCV 列
2. 如果 DataFrame 包含多股票数据，需要提供 `symbol` 参数
3. `date` 列会自动转换为 datetime 类型
4. 转换后的 DataFrame 会自动按日期排序


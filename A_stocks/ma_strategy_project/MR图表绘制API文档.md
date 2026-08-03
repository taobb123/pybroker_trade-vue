# MR图表绘制API文档

## 📋 目录
- [主要接口](#主要接口)
- [函数签名](#函数签名)
- [参数说明](#参数说明)
- [数据要求](#数据要求)
- [返回值说明](#返回值说明)
- [使用示例](#使用示例)
- [辅助函数](#辅助函数)
- [常见问题](#常见问题)

---

## 主要接口

### 1. `plot_mean_reversion_signals()` - 主接口函数

**功能**: 绘制均值回归策略的可视化图表，支持交互式悬浮提示和十字线联动

**位置**: `ma_strategy_project/utils/visualization.py`

---

## 函数签名

```python
def plot_mean_reversion_signals(
    data: pd.DataFrame, 
    outfile: str = "price_mr.png",
    entry_z: float = 2.0, 
    exit_z: float = 0.0,
    interactive: bool | None = None
) -> str
```

---

## 参数说明

### `data: pd.DataFrame` (必需)
包含MR策略数据的DataFrame，必须包含以下列：

**必需列**:
- `close`: 收盘价 (float)
- `mr_mean`: 移动均值 (float)
- `mr_std`: 移动标准差 (float)
- `z`: Z分数 (float)

**可选列**:
- `date`: 日期 (datetime或字符串，推荐)
- `positions`: 持仓变化标记 (int: 1=买入, -1=卖出, 0=无变化)
- `signal`: 交易信号 (int: 1=买入, -1=卖出, 0=无操作)

### `outfile: str` (可选，默认="price_mr.png")
- **非交互模式**: 输出PNG文件的路径
- **交互模式**: 此参数被忽略

### `entry_z: float` (可选，默认=2.0)
进场Z阈值，用于绘制布林带上下轨
- 上轨 = `mr_mean + entry_z * mr_std`
- 下轨 = `mr_mean - entry_z * mr_std`

### `exit_z: float` (可选，默认=0.0)
出场Z阈值，用于绘制出场线
- 出场线 = `mr_mean + exit_z * mr_std`
- 如果为0，则不绘制出场线

### `interactive: bool | None` (可选，默认=None)
- `None`: 自动检测环境（Streamlit环境自动使用交互模式）
- `True`: 强制使用交互模式（返回HTML字符串）
- `False`: 使用非交互模式（返回PNG文件路径）

---

## 数据要求

### 数据格式示例

```python
import pandas as pd
import numpy as np

# 示例数据
data = pd.DataFrame({
    'date': pd.date_range('2024-01-01', periods=100, freq='D'),
    'close': np.random.randn(100).cumsum() + 100,
    'mr_mean': np.random.randn(100).cumsum() + 100,
    'mr_std': np.abs(np.random.randn(100)) + 1,
    'z': np.random.randn(100),
    'positions': np.random.choice([-1, 0, 1], size=100),
    'signal': np.random.choice([-1, 0, 1], size=100)
})
```

### 数据验证

函数会自动验证：
- ✅ 数据不为空
- ✅ 包含必需列
- ✅ 关键列有有效数据（非全NaN）
- ✅ x和y维度一致
- ✅ 日期格式正确

---

## 返回值说明

### 交互模式 (`interactive=True`)
- **返回类型**: `str`
- **内容**: 完整的HTML字符串，包含Plotly图表
- **用途**: 可直接在Streamlit中使用 `st.components.html()` 显示

### 非交互模式 (`interactive=False`)
- **返回类型**: `str`
- **内容**: PNG文件路径
- **用途**: 可直接使用 `st.image()` 或保存到文件

### 错误情况
- **返回**: 空字符串 `""`
- **原因**: 数据无效、缺少必需列、生成失败等

---

## 使用示例

### 示例1: 基础使用（自动检测模式）

```python
from utils.visualization import plot_mean_reversion_signals
from strategies.mean_reversion import MeanReversionStrategy
from data.fetcher import load_data

# 1. 加载数据
data = load_data('000001', '2024-01-01', '2024-12-31')

# 2. 生成策略信号
strategy = MeanReversionStrategy(window=20, entry_z=2.0, exit_z=0.0)
sig_df = strategy.generate_signals(data)

# 3. 绘制图表（自动检测环境）
chart_result = plot_mean_reversion_signals(
    data=sig_df,
    entry_z=2.0,
    exit_z=0.0
)

# 4. 显示图表（Streamlit）
if chart_result:
    st.components.html(chart_result, height=1200)
```

### 示例2: 交互模式（Streamlit）

```python
import streamlit as st
from utils.visualization import plot_mean_reversion_signals

# 在Streamlit中使用
mr_fig = plot_mean_reversion_signals(
    chart_data_mr, 
    entry_z=2.0, 
    exit_z=0.0,
    interactive=True  # 强制交互模式
)

if mr_fig:
    st.markdown("**均值回归策略 - 布林带与Z分数指标**")
    st.components.html(mr_fig, height=1200)
```

### 示例3: 非交互模式（保存PNG）

```python
from utils.visualization import plot_mean_reversion_signals

# 生成PNG文件
png_path = plot_mean_reversion_signals(
    data=sig_df,
    outfile="mr_chart.png",
    entry_z=2.0,
    exit_z=0.0,
    interactive=False  # 非交互模式
)

if png_path:
    print(f"图表已保存到: {png_path}")
    # 在Streamlit中显示
    st.image(png_path)
```

### 示例4: 完整工作流

```python
import pandas as pd
import numpy as np
from strategies.mean_reversion import MeanReversionStrategy
from utils.visualization import plot_mean_reversion_signals
from utils.data_validator import validate_data_for_plot

# 1. 准备数据
data = load_data('000001', '2024-01-01', '2024-12-31')

# 2. 生成策略信号
strategy = MeanReversionStrategy(
    window=20,
    entry_z=2.0,
    exit_z=0.0
)
sig_df = strategy.generate_signals(data)

# 3. 数据验证（推荐）
if validate_data_for_plot(sig_df, plot_type="mr", verbose=True):
    # 4. 绘制图表
    chart_result = plot_mean_reversion_signals(
        data=sig_df,
        entry_z=2.0,
        exit_z=0.0,
        interactive=True
    )
    
    # 5. 显示结果
    if chart_result:
        display_chart(chart_result, height=1200)
    else:
        print("图表生成失败")
else:
    print("数据验证失败")
```

---

## 辅助函数

### 1. `_plot_mr_with_plotly()` - Plotly绘图引擎

**功能**: 使用Plotly绘制MR策略图表（内部函数）

**签名**:
```python
def _plot_mr_with_plotly(
    data: pd.DataFrame, 
    entry_z: float, 
    exit_z: float, 
    window_val: str, 
    outfile: str
) -> str
```

**说明**: 
- 这是内部函数，通常不需要直接调用
- 如果Plotly可用，`plot_mean_reversion_signals()` 会自动使用此函数
- 如果Plotly不可用或失败，会自动回退到matplotlib/mpld3

### 2. `_get_tooltip_text()` - 工具提示生成

**功能**: 生成买卖信号点的悬浮提示文本

**签名**:
```python
def _get_tooltip_text(
    row_idx: int, 
    data: pd.DataFrame, 
    signal_type: str = "", 
    html_format: bool = False
) -> str
```

**参数**:
- `row_idx`: 数据行索引
- `data`: 数据DataFrame
- `signal_type`: 信号类型（"买入"/"卖出"/""）
- `html_format`: 是否使用HTML格式

**返回**: 格式化的提示文本

### 3. `_is_streamlit_env()` - 环境检测

**功能**: 检测是否在Streamlit环境中运行

**签名**:
```python
def _is_streamlit_env() -> bool
```

**返回**: `True` 如果在Streamlit环境，否则 `False`

---

## 图表内容说明

### 主图（上部分）
- **收盘价线**: 黑色实线
- **均值线**: 蓝色虚线 (`mr_mean`)
- **布林带上轨**: 橙色点线 (`mr_mean + entry_z * mr_std`)
- **布林带下轨**: 橙色点线 (`mr_mean - entry_z * mr_std`)
- **布林带填充**: 灰色半透明区域
- **出场线**: 绿色点划线（如果 `exit_z != 0`）
- **买入信号点**: 绿色向上三角形
- **卖出信号点**: 红色向下三角形

### 副图（下部分）
- **Z分数线**: 紫色实线
- **进场线**: 橙色点线 (`Z = -entry_z`)
- **超涨线**: 橙色点线 (`Z = +entry_z`)
- **出场线**: 绿色点划线 (`Z = exit_z`)
- **均值线**: 蓝色虚线 (`Z = 0`)
- **买入信号点**: 绿色向上三角形（对应Z分数位置）
- **卖出信号点**: 红色向下三角形（对应Z分数位置）

---

## 常见问题

### Q1: 图表显示为空怎么办？

**排查步骤**:
1. 检查数据是否包含必需列：`close`, `mr_mean`, `mr_std`, `z`
2. 检查数据是否全为NaN：`data['close'].isna().all()`
3. 检查数据长度：`len(data) > 0`
4. 使用数据验证：`validate_data_for_plot(data, plot_type="mr")`

### Q2: 如何自定义图表样式？

目前不支持直接自定义样式，但可以通过修改源码中的颜色和样式参数：
- 位置: `ma_strategy_project/utils/visualization.py`
- 函数: `_plot_mr_with_plotly()` 或 matplotlib部分

### Q3: 交互模式和非交互模式的区别？

- **交互模式**: 
  - 使用Plotly或mpld3
  - 支持缩放、平移、悬浮提示
  - 返回HTML字符串
  - 适合Web应用（Streamlit）

- **非交互模式**:
  - 使用matplotlib
  - 生成静态PNG图片
  - 返回文件路径
  - 适合保存和分享

### Q4: 如何获取策略数据？

```python
from strategies.mean_reversion import MeanReversionStrategy

strategy = MeanReversionStrategy(window=20, entry_z=2.0, exit_z=0.0)
sig_df = strategy.generate_signals(data)  # 包含所有必需列
```

### Q5: 图表在Streamlit中不显示？

**检查**:
1. 确保返回的不是空字符串：`if chart_result:`
2. 使用正确的显示方法：`st.components.html(chart_result, height=1200)`
3. 检查浏览器控制台是否有JavaScript错误

---

## 相关文件

- **主函数**: `ma_strategy_project/utils/visualization.py`
- **策略类**: `ma_strategy_project/strategies/mean_reversion.py`
- **数据验证**: `ma_strategy_project/utils/data_validator.py`
- **使用示例**: `ma_strategy_project/test_plotly_mr.py`
- **Streamlit集成**: `ma_strategy_project/app/streamlit_app.py`

---

## 更新日志

- **2024-11**: 添加Plotly支持，增强数据验证，修复索引对齐问题
- **2024-10**: 初始版本，支持matplotlib和mpld3

---

## 技术支持

如有问题，请检查：
1. 数据验证结果
2. 日志输出（`utils/logger.py`）
3. 浏览器控制台错误（交互模式）


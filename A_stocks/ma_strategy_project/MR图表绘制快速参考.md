# MR图表绘制快速参考

## 🚀 快速开始

### 最简单的使用方式

```python
from utils.visualization import plot_mean_reversion_signals
from strategies.mean_reversion import MeanReversionStrategy

# 1. 生成策略数据
strategy = MeanReversionStrategy(window=20, entry_z=2.0, exit_z=0.0)
sig_df = strategy.generate_signals(data)

# 2. 绘制图表
chart = plot_mean_reversion_signals(sig_df, entry_z=2.0, exit_z=0.0)

# 3. 显示（Streamlit）
if chart:
    st.components.html(chart, height=1200)
```

---

## 📝 函数签名

```python
plot_mean_reversion_signals(
    data: pd.DataFrame,           # 必需：包含MR数据的DataFrame
    outfile: str = "price_mr.png", # 可选：输出文件名
    entry_z: float = 2.0,         # 可选：进场Z阈值
    exit_z: float = 0.0,          # 可选：出场Z阈值
    interactive: bool | None = None # 可选：交互模式（None=自动检测）
) -> str                          # 返回：HTML字符串或文件路径
```

---

## 📊 数据要求

### 必需列
```python
data = pd.DataFrame({
    'close': [...],      # 收盘价
    'mr_mean': [...],    # 移动均值
    'mr_std': [...],     # 移动标准差
    'z': [...]          # Z分数
})
```

### 可选列
```python
data['date'] = [...]        # 日期（推荐）
data['positions'] = [...]   # 持仓变化（1=买入, -1=卖出, 0=无变化）
data['signal'] = [...]      # 交易信号
```

---

## 💡 使用场景

### 场景1: Streamlit Web应用
```python
# 自动检测，使用交互模式
chart = plot_mean_reversion_signals(sig_df)
st.components.html(chart, height=1200)
```

### 场景2: 保存PNG图片
```python
# 非交互模式
png_path = plot_mean_reversion_signals(
    sig_df, 
    outfile="mr_chart.png",
    interactive=False
)
st.image(png_path)
```

### 场景3: 自定义参数
```python
chart = plot_mean_reversion_signals(
    sig_df,
    entry_z=2.5,    # 更宽的布林带
    exit_z=0.5,    # 添加出场线
    interactive=True
)
```

---

## 🔍 数据验证

```python
from utils.data_validator import validate_data_for_plot

# 验证数据
if validate_data_for_plot(sig_df, plot_type="mr"):
    chart = plot_mean_reversion_signals(sig_df)
else:
    st.warning("数据验证失败")
```

---

## ⚠️ 常见错误

### 错误1: 图表为空
```python
# 检查数据
print(f"数据形状: {data.shape}")
print(f"必需列: {['close', 'mr_mean', 'mr_std', 'z']}")
print(f"缺失列: {[c for c in ['close', 'mr_mean', 'mr_std', 'z'] if c not in data.columns]}")
```

### 错误2: 数据全为NaN
```python
# 检查有效数据
print(f"close有效值: {data['close'].notna().sum()}/{len(data)}")
print(f"mr_mean有效值: {data['mr_mean'].notna().sum()}/{len(data)}")
```

### 错误3: 维度不一致
```python
# 检查长度
print(f"数据长度: {len(data)}")
print(f"close长度: {len(data['close'])}")
print(f"date长度: {len(data['date']) if 'date' in data.columns else 'N/A'}")
```

---

## 📚 相关函数

| 函数 | 说明 | 位置 |
|------|------|------|
| `plot_mean_reversion_signals()` | 主接口函数 | `utils/visualization.py` |
| `_plot_mr_with_plotly()` | Plotly绘图引擎 | `utils/visualization.py` |
| `_get_tooltip_text()` | 工具提示生成 | `utils/visualization.py` |
| `validate_data_for_plot()` | 数据验证 | `utils/data_validator.py` |
| `MeanReversionStrategy.generate_signals()` | 生成策略信号 | `strategies/mean_reversion.py` |

---

## 📖 完整文档

详细文档请参考: `MR图表绘制API文档.md`


# plot_mean_reversion_signals() 接口验证报告

## 验证时间
2025-11-11

## 验证结果总览
✅ **接口功能正常** - 所有核心功能测试通过

## 详细验证结果

### 1. 数据准备 ✅
- ✅ 测试数据创建成功 (100行, 6列)
- ✅ 包含必要列: date, open, high, low, close, volume

### 2. 策略信号生成 ✅
- ✅ MeanReversionStrategy 实例化成功
- ✅ 信号生成成功 (100行, 12列)
- ✅ 包含所有必要列: close, mr_mean, mr_std, z, date, signal, positions
- ✅ 数据有效性检查通过
- ✅ 买入信号: 2个
- ✅ 卖出信号: 7个

### 3. 非交互模式测试 ✅
- ✅ 图表文件生成成功: `test_mr_chart.png`
- ✅ 文件大小: 275,365 字节 (正常)
- ✅ 文件可正常打开和查看

### 4. 交互模式测试 ✅
- ✅ HTML生成成功
- ✅ HTML长度: 161,211 字符
- ✅ 包含mpld3库引用
- ✅ 包含JavaScript代码
- ✅ 包含工具提示插件
- ⚠️ SVG标签: mpld3通过JavaScript动态生成，HTML中不直接包含（这是正常的）

**说明**: mpld3使用JavaScript在浏览器中动态创建SVG，因此HTML源码中不会直接包含`<svg>`标签。这是mpld3的正常工作方式。

### 5. 边界情况处理 ✅
- ✅ 空数据处理: 正确返回空字符串
- ✅ 缺少列处理: 正确返回空字符串

### 6. 数据属性传递 ⚠️
- ⚠️ window属性传递: 需要进一步验证在图表标题中的显示

## 接口功能验证

### 函数签名
```python
plot_mean_reversion_signals(
    data: pd.DataFrame,
    outfile: str = "price_mr.png",
    entry_z: float = 2.0,
    exit_z: float = 0.0,
    interactive: bool | None = None
) -> str
```

### 输入要求
**必需列**:
- `close`: 收盘价
- `mr_mean`: 移动均值
- `mr_std`: 移动标准差
- `z`: Z分数
- `date`: 日期（可选，但推荐）

**可选列**:
- `positions`: 持仓变化标记（用于显示买卖信号点）

### 输出格式

#### 非交互模式 (`interactive=False`)
- **返回**: 文件路径字符串 (PNG格式)
- **示例**: `"price_mr.png"`
- **文件内容**: 静态图表图像

#### 交互模式 (`interactive=True`)
- **返回**: HTML字符串
- **格式**: `<div class="mpld3-wrapper">...</div>`
- **内容**: 
  - mpld3 JavaScript库引用
  - 图表数据（JSON格式）
  - 交互插件（工具提示、垂直联动线等）
  - CSS样式

### 交互功能
1. **工具提示**: 鼠标悬停在买卖点上显示详细信息
   - 日期
   - 价格
   - Z分数
   - 信号类型
   
2. **垂直联动线**: 鼠标移动时在两个子图之间显示同步的垂直参考线

3. **工具栏**: 提供缩放、平移等交互功能

## 在Streamlit中的使用

### 显示方式
```python
from utils.visualization import plot_mean_reversion_signals
import streamlit.components.v1 as components

# 生成图表
html_result = plot_mean_reversion_signals(
    chart_data,
    entry_z=2.0,
    exit_z=0.0,
    interactive=True
)

# 在Streamlit中显示
if html_result:
    components.html(html_result, height=1200, scrolling=False)
```

### 注意事项
1. **高度设置**: 建议设置足够的高度（如1200px）以确保图表完整显示
2. **滚动**: 建议禁用滚动 (`scrolling=False`) 以获得更好的用户体验
3. **数据完整性**: 确保传入的数据包含所有必需列
4. **mpld3依赖**: 交互模式需要mpld3库，如果未安装会自动回退到非交互模式

## 已知问题和解决方案

### 1. 图表空白问题
**可能原因**:
- 数据缺少必要列
- 数据全为NaN
- 数据为空

**解决方案**:
- 检查数据是否包含所有必需列
- 验证数据有效性
- 确保数据不为空

### 2. HTML不显示
**可能原因**:
- Streamlit的components.html高度设置不足
- HTML格式不正确

**解决方案**:
- 增加height参数
- 检查HTML字符串是否以`<div`开头

### 3. 交互功能不工作
**可能原因**:
- mpld3库未正确加载
- JavaScript执行错误

**解决方案**:
- 检查浏览器控制台错误
- 确保mpld3已安装

## 测试文件
- `test_mr_chart.png`: 非交互模式生成的PNG文件
- `test_mr_chart.html`: 交互模式生成的HTML文件

## 结论

✅ **plot_mean_reversion_signals() 接口功能正常**

所有核心功能测试通过：
- 数据验证 ✅
- 信号生成 ✅
- 非交互模式 ✅
- 交互模式 ✅
- 边界情况处理 ✅

接口可以在Streamlit应用中正常使用。如果遇到图表空白问题，请检查：
1. 数据是否包含所有必需列
2. 数据是否有效（非空、非全NaN）
3. Streamlit显示设置是否正确


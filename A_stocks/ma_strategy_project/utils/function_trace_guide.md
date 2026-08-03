# 图表渲染函数调用跟踪指南

## 概述

已在关键位置添加日志记录，用于跟踪图表渲染函数的调用和执行流程。

## 日志位置

### 1. Streamlit应用层 (`app/streamlit_app.py`)

#### MA策略图表生成
- **准备阶段**: `[streamlit_app] 准备生成MA策略图表`
- **验证失败**: `[streamlit_app] MA策略数据验证失败`
- **函数调用**: `[streamlit_app] 调用 plot_price_ma_signals`
- **函数返回**: `[streamlit_app] plot_price_ma_signals 返回`

#### MR策略图表生成
- **准备阶段**: `[streamlit_app] 准备生成MR策略图表`
- **验证失败**: `[streamlit_app] MR策略数据验证失败`
- **函数调用**: `[streamlit_app] 调用 plot_mean_reversion_signals`
- **函数返回**: `[streamlit_app] plot_mean_reversion_signals 返回`

#### 图表显示
- **函数调用**: `[display_chart] 函数被调用`
- **空结果**: `[display_chart] chart_result为空，不显示图表`
- **HTML检测**: `[display_chart] 检测到HTML字符串，使用components.html显示`
- **文件检测**: `[display_chart] 检测到文件路径`
- **文件不存在**: `[display_chart] 文件不存在`

### 2. 图表渲染函数 (`utils/visualization.py`)

#### plot_price_ma_signals()
- **函数调用**: `[plot_price_ma_signals] 函数被调用`
- **数据检查**: `[plot_price_ma_signals] 数据为空或None，返回空字符串`
- **交互模式**: `[plot_price_ma_signals] 交互模式`
- **matplotlib导入**: `[plot_price_ma_signals] matplotlib导入成功/失败`
- **HTML生成**: `[plot_price_ma_signals] HTML生成成功，长度: X`
- **PNG生成**: `[plot_price_ma_signals] PNG文件生成成功`

#### plot_mean_reversion_signals()
- **函数调用**: `[plot_mean_reversion_signals] 函数被调用`
- **数据检查**: `[plot_mean_reversion_signals] 数据为空或None，返回空字符串`
- **交互模式**: `[plot_mean_reversion_signals] 交互模式`
- **matplotlib导入**: `[plot_mean_reversion_signals] matplotlib导入成功/失败`
- **HTML生成**: `[plot_mean_reversion_signals] HTML生成成功，长度: X`
- **PNG生成**: `[plot_mean_reversion_signals] PNG文件生成成功`

## 如何查看日志

### 方法1: Streamlit控制台
运行Streamlit应用时，日志会输出到控制台：
```bash
streamlit run app/streamlit_app.py
```

### 方法2: 日志文件
如果配置了日志文件，可以在日志文件中查看：
- 默认位置：项目根目录下的日志文件
- 格式：`YYYY-MM-DD.log`

### 方法3: 浏览器开发者工具
对于前端渲染问题，可以查看浏览器控制台：
- F12 打开开发者工具
- Console 标签查看JavaScript错误
- Network 标签查看资源加载

## 调试流程

### 步骤1: 检查函数是否被调用
查找日志中的 `[streamlit_app] 准备生成XX策略图表`

**如果没有此日志**:
- 检查回测是否成功执行
- 检查策略选择是否正确
- 检查条件判断逻辑

### 步骤2: 检查数据验证
查找日志中的 `[streamlit_app] XX策略数据验证失败`

**如果验证失败**:
- 查看Streamlit界面中的验证详情
- 检查数据是否包含必需列
- 检查数据是否为空或全为NaN

### 步骤3: 检查函数调用
查找日志中的 `[streamlit_app] 调用 plot_XX_signals`

**如果没有此日志**:
- 数据验证可能失败
- 检查验证逻辑

### 步骤4: 检查函数执行
查找日志中的 `[plot_XX_signals] 函数被调用`

**如果没有此日志**:
- 函数可能未被正确调用
- 检查导入和函数名

### 步骤5: 检查函数返回
查找日志中的 `[plot_XX_signals] HTML生成成功` 或 `[plot_XX_signals] PNG文件生成成功`

**如果没有此日志**:
- 函数可能在中间步骤失败
- 检查matplotlib导入
- 检查数据列完整性

### 步骤6: 检查图表显示
查找日志中的 `[display_chart] 函数被调用`

**如果没有此日志**:
- 函数可能返回空结果
- 检查函数返回值

## 常见问题排查

### 问题1: 函数未被调用
**症状**: 没有 `[streamlit_app] 准备生成XX策略图表` 日志

**可能原因**:
- 回测未执行
- 策略选择错误
- 条件判断逻辑错误

**解决方法**:
- 检查 `run_backtest` 变量
- 检查 `strat_choice` 变量
- 检查条件分支逻辑

### 问题2: 数据验证失败
**症状**: 有 `[streamlit_app] XX策略数据验证失败` 日志

**可能原因**:
- 数据缺少必需列
- 数据为空或全为NaN

**解决方法**:
- 查看验证详情
- 检查数据合并逻辑
- 确保策略正确生成信号

### 问题3: 函数返回空结果
**症状**: 有函数调用日志，但没有HTML/PNG生成日志

**可能原因**:
- matplotlib导入失败
- 数据检查失败
- 中间步骤出错

**解决方法**:
- 检查matplotlib是否安装
- 检查数据完整性
- 查看错误日志

### 问题4: 图表不显示
**症状**: 有HTML生成日志，但图表空白

**可能原因**:
- HTML格式问题
- Streamlit渲染问题
- JavaScript执行错误

**解决方法**:
- 检查HTML长度（应该>1000字符）
- 检查浏览器控制台错误
- 检查components.html参数

## 日志级别

- **INFO**: 正常执行流程
- **WARNING**: 警告信息（如数据验证失败）
- **ERROR**: 错误信息（如导入失败）

## 注意事项

1. 日志记录使用try-except包裹，不会影响主流程
2. 如果logger不可用，日志记录会静默失败
3. 日志可能包含敏感数据，注意保护隐私


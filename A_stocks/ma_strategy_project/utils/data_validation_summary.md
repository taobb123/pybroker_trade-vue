# 数据验证工具使用说明

## 概述

已添加数据验证工具 `data_validator.py`，用于在图表生成前检查传入数据的完整性和有效性。

## 功能

### 1. 数据完整性检查
- 检查数据是否为None
- 检查数据类型是否为DataFrame
- 检查数据是否为空
- 检查必需列是否存在
- 检查可选列是否存在

### 2. 数据有效性检查
- 检查关键列是否有有效数据（非NaN）
- 检查数据范围是否合理
- 检查日期格式是否正确
- 检查信号列是否存在

### 3. 数据一致性检查
- 检查索引是否重复
- 检查数据长度
- 检查列的数据类型

## 使用方法

### 在代码中使用

```python
from utils.data_validator import validate_data_for_plot, validate_plot_data

# 简单验证（返回True/False）
is_valid = validate_data_for_plot(data, plot_type="mr", verbose=False)

# 详细验证（返回详细结果）
results = validate_plot_data(data, plot_type="mr")
for key, (status, message) in results.items():
    print(f"{'✓' if status else '✗'} {key}: {message}")
```

### 在Streamlit中使用

已在 `streamlit_app.py` 中集成数据验证：

1. **MA策略**: 在调用 `plot_price_ma_signals()` 前验证数据
2. **MR策略**: 在调用 `plot_mean_reversion_signals()` 前验证数据

如果验证失败，会显示：
- 警告信息
- 可展开的详细验证结果

## 验证项说明

### MR策略必需列
- `close`: 收盘价
- `mr_mean`: 移动均值
- `mr_std`: 移动标准差
- `z`: Z分数

### MR策略可选列
- `date`: 日期（推荐）
- `positions`: 持仓变化标记
- `signal`: 交易信号

### MA策略必需列
- `close`: 收盘价

### MA策略可选列
- `date`: 日期（推荐）
- `ma_short`: 短期均线
- `ma_long`: 长期均线
- `positions`: 持仓变化标记
- `signal`: 交易信号

## 验证结果示例

```
======================================================================
MR策略数据验证
======================================================================
✓ data_not_none: 数据不为None
✓ data_type: 数据类型正确: DataFrame
✓ data_empty: 数据不为空: 50 行
✓ plot_type: 图表类型: mr
✓ required_columns: 包含所有必需列: ['close', 'mr_mean', 'mr_std', 'z']
✓ optional_columns: 包含所有可选列: ['date', 'positions', 'signal']
✓ close_validity: close列有效数据: 50/50
✓ close_range: close范围: [10.13, 19.65]
✓ mr_mean_validity: mr_mean列有效数据: 50/50
✓ mr_std_validity: mr_std列有效数据: 49/50
✓ z_validity: z列有效数据: 50/50
✓ date_validity: date列有效数据: 50/50
✓ date_format: date格式正确
✓ signals: 买入信号: 1, 卖出信号: 14
✓ data_length: 数据长度: 50 行
✓ index_duplicates: 索引无重复
✓ summary: 数据形状: (50, 12), 列数: 12, 列名: [...]
----------------------------------------------------------------------
总计: 17 项检查
通过: 17 项
失败: 0 项
通过率: 100.0%
======================================================================
```

## 常见问题排查

### 1. 图表空白
**可能原因**:
- 数据缺少必需列
- 数据全为NaN
- 数据为空

**解决方法**:
- 检查验证结果中的错误项
- 确保策略已正确生成信号
- 检查数据合并逻辑

### 2. 验证失败
**检查项**:
1. `required_columns`: 是否缺少必需列
2. `close_validity`: close列是否有有效数据
3. `data_empty`: 数据是否为空

### 3. 数据合并问题
**常见情况**:
- 回测数据中缺少策略生成的列（如 `mr_mean`, `mr_std`, `z`）
- 数据长度不一致

**解决方法**:
- 使用 `date` 列进行合并
- 检查数据对齐逻辑

## 集成位置

数据验证已集成到以下位置：

1. **MA策略图表生成** (`streamlit_app.py:1230-1254`)
   - 验证 `chart_data` 的完整性
   - 显示详细验证结果（如果失败）

2. **MR策略图表生成** (`streamlit_app.py:1313-1337`)
   - 验证 `chart_data_mr` 的完整性
   - 显示详细验证结果（如果失败）

## 测试

运行测试：
```bash
python -m utils.data_validator
```

这将：
1. 创建测试数据
2. 生成策略信号
3. 验证数据完整性
4. 显示验证结果

## 注意事项

1. 验证是**非阻塞**的：即使验证失败，也会尝试生成图表（但可能失败）
2. 验证结果会显示在Streamlit界面中，方便调试
3. 建议在开发时启用 `verbose=True` 查看详细日志


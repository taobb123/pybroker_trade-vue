# 图表生成依赖健康检查报告

## 检查时间
2025-11-11

## 检查结果总览
✅ **所有检查通过！** (30/30)

## 详细检查结果

### 1. 基础库导入检查 ✅
- ✅ pandas: 导入成功
- ✅ numpy: 导入成功
- ✅ matplotlib: 导入成功
- ✅ matplotlib.pyplot: 导入成功
- ✅ streamlit: 导入成功
- ✅ streamlit.components.v1: 导入成功
- ✅ mpld3: 导入成功 (版本: 0.5.11)
- ✅ mpld3.plugins: 导入成功

### 2. 项目模块检查 ✅
- ✅ data.fetcher: 模块导入成功
- ✅ strategies.mean_reversion: 模块导入成功
- ✅ strategies.moving_average: 模块导入成功
- ✅ strategies.base: 模块导入成功
- ✅ backtest.engine: 模块导入成功
- ✅ backtest.analyzer: 模块导入成功
- ✅ utils.visualization: 模块导入成功
- ✅ utils.logger: 模块导入成功

### 3. 类和函数可用性检查 ✅
- ✅ MeanReversionStrategy: 类可用
- ✅ MeanReversionStrategy.__init__: 实例化成功
- ✅ BacktestEngine: 类可用
- ✅ plot_mean_reversion_signals: 函数可用
- ✅ plot_equity_curve: 函数可用
- ✅ plot_price_ma_signals: 函数可用
- ✅ _get_tooltip_text: 函数可用
- ✅ _is_streamlit_env: 函数可用
- ✅ VLinePlugin: 插件可用

### 4. 函数签名检查 ✅
- ✅ plot_mean_reversion_signals_signature: 签名完整
  - 参数: ['data', 'outfile', 'entry_z', 'exit_z', 'interactive']

### 5. 数据流检查 ✅
- ✅ strategy_generate_signals: 信号生成成功
  - 数据形状: (50, 12)
  - 包含必要列: close, mr_mean, mr_std, z, signal, positions
- ✅ plot_function_execution: 图表生成成功
  - 输出文件: price_mr.png

### 6. mpld3 交互功能检查 ✅
- ✅ mpld3_import: mpld3版本 0.5.11
- ✅ mpld3_html_generation: HTML生成成功
  - HTML长度: 5359 字符

## 依赖关系图

```
图表生成流程
├── 数据输入
│   └── DataFrame (包含: date, close, volume等)
├── 策略信号生成
│   └── MeanReversionStrategy.generate_signals()
│       └── 生成: mr_mean, mr_std, z, signal, positions
├── 回测引擎
│   └── BacktestEngine.run()
│       └── 合并回测结果到数据
└── 图表生成
    └── plot_mean_reversion_signals()
        ├── matplotlib (基础绘图)
        ├── mpld3 (交互功能)
        │   ├── plugins.PointHTMLTooltip (工具提示)
        │   └── VLinePlugin (垂直联动线)
        └── _get_tooltip_text() (提示文本生成)
```

## 关键接口说明

### plot_mean_reversion_signals()
**功能**: 绘制均值回归策略的可视化图表

**参数**:
- `data`: DataFrame，必须包含列: close, mr_mean, mr_std, z, date, positions
- `outfile`: 输出文件名（非交互模式）
- `entry_z`: 进场Z阈值（默认2.0）
- `exit_z`: 出场Z阈值（默认0.0）
- `interactive`: 是否使用交互模式（None时自动检测）

**返回值**:
- 交互模式: HTML字符串
- 非交互模式: 文件路径（PNG）

**依赖**:
- matplotlib: 基础绘图
- mpld3: 交互功能（可选，但推荐）
- pandas: 数据处理

### MeanReversionStrategy.generate_signals()
**功能**: 生成均值回归交易信号

**输入**: DataFrame with columns: date, open, high, low, close, volume

**输出**: DataFrame with additional columns:
- mr_mean: 移动均值
- mr_std: 移动标准差
- z: Z分数
- signal: 交易信号 (1=买入, -1=卖出, 0=无操作)
- positions: 持仓变化 (1=买入, -1=卖出, 0=无变化)

## 已知问题和修复

### 1. pandas FutureWarning (已修复)
**问题**: `df['mr_std'].replace(0, np.nan, inplace=True)` 触发警告

**修复**: 改为 `df['mr_std'] = df['mr_std'].replace(0, np.nan)`

**位置**: `strategies/mean_reversion.py:80`

## 建议

1. ✅ 所有依赖正常，图表生成功能完整
2. ✅ mpld3 交互功能可用，支持工具提示和垂直联动线
3. ✅ 数据流验证通过，从策略生成到图表显示链路完整
4. ⚠️ 建议定期运行健康检查，确保依赖库更新后兼容性

## 运行健康检查

```bash
cd ma_strategy_project
python -m utils.health_check
```

## 结论

所有图表生成依赖的类和接口健康状况良好，可以正常使用。


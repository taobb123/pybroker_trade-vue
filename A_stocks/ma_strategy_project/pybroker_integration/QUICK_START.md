# 快速开始指南

本文档帮助您快速了解和使用标准化的项目结构。

## 目录结构概览

```
pybroker_integration/
├── config/          # 配置文件
├── data/            # 数据管理（raw/interim/processed）
├── docs/            # 项目文档
├── notebooks/       # Jupyter Notebooks
├── src/             # 核心源代码
│   ├── modules/     # 功能模块
│   ├── strategies/  # 交易策略
│   └── utils/       # 工具函数
└── tests/           # 测试代码
```

## 使用指南

### 1. 配置文件

**开发环境**:
```python
from config import dev_config

# 使用开发配置
data_source = dev_config.DATA_SOURCE
backtest_config = dev_config.BACKTEST_CONFIG
```

**生产环境**:
```python
from config import prod_config

# 使用生产配置（从环境变量读取敏感信息）
data_source = prod_config.DATA_SOURCE
```

### 2. 数据管理

**原始数据** (`data/raw/`):
- 存放从数据源直接下载的原始数据
- 不应被修改

**中间数据** (`data/interim/`):
- 存放数据清洗、转换的中间结果
- 可以随时重新生成

**最终数据** (`data/processed/`):
- 存放可直接用于回测的最终数据
- 应记录处理版本和日期

### 3. 源代码组织

**功能模块** (`src/modules/`):
```python
# 示例：数据处理模块
from src.modules import data_processor
processed_data = data_processor.clean_data(raw_data)
```

**交易策略** (`src/strategies/`):
```python
# 示例：轮动策略
from src.strategies import rotation_strategy
strategy = rotation_strategy.RotationStrategy()
```

**工具函数** (`src/utils/`):
```python
# 示例：可视化工具
from src.utils import visualization
visualization.plot_equity_curve(result)
```

### 4. 测试

运行测试：
```bash
# 运行所有测试
pytest tests/

# 运行特定测试
pytest tests/test_indicators.py
```

### 5. Notebooks

在 `notebooks/` 目录中创建探索性分析：
- 数据探索
- 策略原型
- 概念验证

**注意**: Notebooks 不用于生产部署，重要代码应提取到 `src/` 目录。

## 最佳实践

1. **配置管理**: 使用环境变量管理敏感信息
2. **数据版本**: 处理后的数据应记录版本信息
3. **代码模块化**: 保持代码模块化，职责清晰
4. **文档同步**: 保持文档与代码同步更新
5. **测试覆盖**: 保持测试覆盖率在 80% 以上

## 下一步

1. 阅读 `PROJECT_STRUCTURE.md` 了解详细结构说明
2. 查看各目录的 `README.md` 了解具体用法
3. 根据项目需求调整配置和结构

## 参考资源

- [项目结构文档](PROJECT_STRUCTURE.md)
- [PyBroker 集成文档](README.md)
- [数据格式指南](DATA_FORMAT_GUIDE.md)


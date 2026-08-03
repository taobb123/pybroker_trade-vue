# 项目目录结构说明

本文档说明量化实践项目的标准化目录结构。

## 目录结构

```
pybroker_integration/
├── config/                 # 配置文件目录
│   ├── __init__.py
│   ├── dev_config.py       # 开发环境配置
│   ├── prod_config.py      # 生产环境配置
│   └── README.md
│
├── data/                   # 数据目录
│   ├── raw/                # 原始数据（不可更改）
│   ├── interim/            # 中间处理数据
│   ├── processed/          # 最终处理数据
│   └── README.md
│
├── docs/                   # 文档目录
│   └── README.md
│
├── notebooks/              # Jupyter Notebooks
│   └── README.md
│
├── src/                    # 核心源代码
│   ├── __init__.py
│   ├── modules/            # 功能模块
│   │   └── __init__.py
│   ├── strategies/         # 交易策略
│   │   └── __init__.py
│   ├── utils/              # 工具函数
│   │   └── __init__.py
│   └── README.md
│
├── tests/                  # 测试代码
│   ├── __init__.py
│   └── README.md
│
└── PROJECT_STRUCTURE.md     # 本文件
```

## 目录说明

### config/ - 配置文件
存放所有的配置文件（如数据库连接、模型参数、系统设置等）。生产环境和开发环境的配置应分离管理。

**原则**:
- 环境分离：开发、测试、生产环境配置分开
- 敏感信息：使用环境变量或密钥管理服务
- 版本控制：配置文件纳入版本控制，敏感信息使用占位符

### data/ - 数据管理
管理项目所需的所有数据，按照数据处理的阶段分为三个子目录：

- **raw/**: 存放原始的、不可更改的初始数据转储
- **interim/**: 存放中间处理过程生成的数据
- **processed/**: 存放可直接用于模型训练或回测的最终、规范化数据集

**原则**:
- 原始数据保护：raw/ 目录中的数据不应被修改
- 版本控制：处理后的数据应记录处理版本和日期
- 数据文档：每个数据集应有对应的说明文档

### docs/ - 文档
存放项目文档、研究报告、API 文档、设计规范等。

**文档类型**:
- 项目文档（README、安装指南等）
- 研究报告（策略研究、回测分析等）
- API 文档（接口说明、使用示例等）
- 设计规范（架构设计、代码规范等）

### notebooks/ - Jupyter Notebooks
存放探索性数据分析（EDA）、原型设计、临时性分析或概念验证的 Jupyter Notebooks。

**注意**: 这些 Notebooks 通常不用于生产部署。

**使用场景**:
- 探索性数据分析（EDA）
- 原型设计
- 临时性分析
- 概念验证

### src/ - 核心源代码
存放核心源代码。代码应按模块或功能划分。

**子目录**:
- **modules/**: 具体的功能模块（数据处理、特征工程、模型训练、回测引擎、交易执行、风险管理等）
- **strategies/**: 存放不同的交易策略实现
- **utils/**: 存放通用的辅助函数和工具

**原则**:
- 模块化：每个模块应有明确的职责
- 可复用：代码应设计为可复用的组件
- 文档化：重要的函数和类应有文档字符串
- 测试：每个模块应有对应的单元测试

### tests/ - 测试
存放单元测试和集成测试代码，确保代码质量和功能正确性。

**测试类型**:
- 单元测试：测试单个函数或类的功能
- 集成测试：测试多个模块协同工作的功能

**测试框架**: 推荐使用 `pytest` 或 `unittest`

## 最佳实践

1. **代码组织**: 保持代码模块化，职责清晰
2. **文档维护**: 保持文档与代码同步更新
3. **测试覆盖**: 保持测试覆盖率在 80% 以上
4. **版本控制**: 重要数据和处理结果应记录版本
5. **环境分离**: 开发、测试、生产环境配置分离

## 文件命名规范

- **Python 文件**: 使用小写字母和下划线，如 `data_processor.py`
- **测试文件**: 以 `test_` 开头，如 `test_indicators.py`
- **配置文件**: 使用描述性名称，如 `dev_config.py`
- **数据文件**: 包含版本信息，如 `data_20241129_v1.csv`
- **Notebooks**: 包含日期和主题，如 `20241129_macd_analysis.ipynb`

## 参考资源

- [Python 项目结构最佳实践](https://docs.python-guide.org/writing/structure/)
- [数据科学项目结构](https://drivendata.github.io/cookiecutter-data-science/)
- [量化交易项目组织](https://www.quantstart.com/articles/How-to-Organize-a-Quantitative-Trading-Project/)


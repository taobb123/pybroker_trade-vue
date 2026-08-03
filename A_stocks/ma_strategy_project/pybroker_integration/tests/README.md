# 测试目录

本目录存放单元测试和集成测试代码，确保代码质量和功能正确性。

## 测试类型

### 单元测试
测试单个函数或类的功能，例如：
- 指标计算函数
- 数据处理函数
- 工具函数

### 集成测试
测试多个模块协同工作的功能，例如：
- 数据获取和处理流程
- 策略回测流程
- 完整的交易流程

## 测试框架

推荐使用以下测试框架：
- `pytest` - Python 测试框架
- `unittest` - Python 标准库测试框架

## 测试文件命名规范

- 测试文件应以 `test_` 开头
- 测试类应以 `Test` 开头
- 测试函数应以 `test_` 开头

示例：
- `test_indicators.py`
- `test_strategy.py`
- `test_data_processing.py`

## 运行测试

```bash
# 运行所有测试
pytest

# 运行特定测试文件
pytest tests/test_indicators.py

# 运行特定测试函数
pytest tests/test_indicators.py::test_macd_calculation
```

## 测试覆盖率

建议保持测试覆盖率在 80% 以上。


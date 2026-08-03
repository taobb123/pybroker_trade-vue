# PE和PB计算优化说明

## 问题诊断

### 原始问题
- PE和PB计算结果为 `None`
- 原因：缺少必要的计算数据（总股本、净资产）

### 解决方案

已实现**多重回退机制**，确保在数据不完整时仍能计算PE和PB：

## 计算方法

### 1. 总市值计算（多种方法）

```python
# 方法1: 总股本 × 当前价格（优先）
if total_shares and current_price:
    total_market_value = current_price * total_shares * 10000

# 方法2: 通过EPS反推总股本
elif eps and net_profit and current_price:
    total_shares = net_profit / eps  # 总股本 = 净利润 / 每股收益
    total_market_value = current_price * total_shares

# 方法3: 通过BPS和净资产反推总股本
elif bps and net_assets and current_price:
    total_shares = net_assets / bps  # 总股本 = 净资产 / 每股净资产
    total_market_value = current_price * total_shares
```

### 2. 市盈率(PE)计算

```python
# PE = 总市值 / 净利润
if total_market_value and net_profit > 0:
    pe_ratio = total_market_value / net_profit
```

### 3. 市净率(PB)计算（两种方法）

```python
# 方法1: 使用总市值和净资产（优先）
if total_market_value and net_assets > 0:
    pb_ratio = total_market_value / net_assets

# 方法2: 使用当前价格和每股净资产（备选）
elif current_price and bps > 0:
    pb_ratio = current_price / bps  # PB = 价格 / 每股净资产
```

## 数据映射优化

### 新增指标名称映射

在 `financial_fetcher.py` 中新增了：
- `股东权益合计(净资产)` → `net_assets`（净资产）
- 确保能正确识别API返回的净资产数据

## 综合得分计算优化

### 归一化算法改进

**PE得分（60%权重）**：
- PE ≤ 5: 得分 = 1.0（满分）
- 5 < PE < 50: 线性插值，得分从 1.0 到 0.1
- PE ≥ 50: 得分 = 0.1（最低分）

**PB得分（40%权重）**：
- PB ≤ 0.5: 得分 = 1.0（满分）
- 0.5 < PB < 5: 线性插值，得分从 1.0 到 0.1
- PB ≥ 5: 得分 = 0.1（最低分）

**盈利加分**：
- 有净利润: +0.2
- ROE > 10%: +0.2

## 测试结果

测试股票：000001（平安银行），价格：10.0

```
净利润: 383.39 亿元
ROE: 8.28%
净利润率: 38.08%
市盈率(PE): 5.35
市净率(PB): 0.40
综合得分: 1.196
```

**结果分析**：
- ✅ PE计算成功：通过方法3（BPS+净资产反推总股本）
- ✅ PB计算成功：通过方法2（价格/每股净资产）
- ✅ 综合得分合理：PE和PB都很低，得分较高

## 改进要点

1. **多重回退机制**：即使缺少某些数据，仍能通过其他途径计算
2. **数据映射完善**：支持更多API返回的指标名称格式
3. **计算逻辑优化**：优先使用最准确的方法，回退到次优方法
4. **归一化算法**：更合理的得分计算，避免异常值影响

## 使用示例

```python
from utils.financial_metrics import get_financial_display_data

# 获取财务数据（会自动计算PE和PB）
info = get_financial_display_data('000001', current_price=10.0)

if info.get('pe_ratio'):
    print(f"市盈率: {info['pe_ratio']:.2f}")

if info.get('pb_ratio'):
    print(f"市净率: {info['pb_ratio']:.2f}")

if info.get('comprehensive_score'):
    print(f"综合得分: {info['comprehensive_score']:.4f}")
```

## 注意事项

1. **价格准确性**：`current_price` 需要使用最新收盘价，确保PE/PB计算准确
2. **数据时效性**：财务数据来自最新报告期，可能存在1-3个月延迟
3. **异常值过滤**：自动过滤PE>1000或PB>20的异常值
4. **计算优先级**：优先使用最准确的方法，确保结果可靠性


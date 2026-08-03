# PyBroker 故障排除指南

## 常见问题

### 1. 代理连接错误 (ProxyError)

**错误信息：**
```
ProxyError: HTTPSConnectionPool(host='push2his.eastmoney.com', port=443)
Max retries exceeded with url: ...
Caused by ProxyError('Unable to connect to proxy', ...)
```

**原因：**
- 系统配置了代理，但代理服务器无法连接
- 代理配置不正确
- 代理服务器已关闭或不可用

**解决方案：**

#### 方案1: 禁用代理（推荐）

在代码开头添加以下代码：

```python
import os

# 禁用代理
os.environ.pop('HTTP_PROXY', None)
os.environ.pop('HTTPS_PROXY', None)
os.environ.pop('http_proxy', None)
os.environ.pop('https_proxy', None)
```

#### 方案2: 配置正确的代理

如果必须使用代理，请配置正确的代理地址：

```python
import os

os.environ['HTTP_PROXY'] = 'http://your-proxy-server:port'
os.environ['HTTPS_PROXY'] = 'http://your-proxy-server:port'
```

#### 方案3: 禁用 requests 的代理

```python
import requests

session = requests.Session()
session.trust_env = False  # 不信任环境变量中的代理设置
```

#### 方案4: 使用备用数据源

如果 AKShare 数据源无法访问，可以使用项目自带的数据获取模块：

```bash
# 运行备用方案
python pybroker_integration/query_test_alternative.py
```

### 2. AKShare 数据源无法访问

**错误信息：**
- 网络连接超时
- 代理连接错误
- 数据源暂时不可用

**解决方案：**

#### 方案1: 使用项目自带的数据获取模块

项目已经集成了多种数据源，包括：
- 数据库（优先）
- akshare（自动重试）
- baostock（推荐作为 akshare 替代）
- tushare（需要 token）
- yfinance（备选）

使用 `DataFetcher` 类：

```python
from data.fetcher import DataFetcher

fetcher = DataFetcher()
data = fetcher.fetch_stock_data(
    code='600000',
    start_date='2020-01-31',
    end_date='2023-02-28',
    use_mock_if_fail=False
)
```

#### 方案2: 使用 baostock（推荐）

baostock 是免费的 A 股数据源，数据质量可靠：

```bash
pip install baostock
```

在 `config/settings.py` 中配置：

```python
DATA_CONFIG = {
    'api_preference': 'baostock',  # 使用 baostock
}
```

### 3. PyBroker Context 类型错误

**错误信息：**
```
AttributeError: module 'pybroker' has no attribute 'Context'
```

**解决方案：**

不要使用类型注解 `ctx: pb.Context`，直接使用：

```python
def my_strategy(ctx):  # 不使用类型注解
    # 策略代码
    pass
```

或者使用 `ExecContext`：

```python
from pybroker import ExecContext

def my_strategy(ctx: ExecContext):
    # 策略代码
    pass
```

### 4. 数据格式错误

**错误信息：**
- 缺少必需的列
- 日期格式不正确

**解决方案：**

确保数据包含以下列：
- `open` - 开盘价
- `high` - 最高价
- `low` - 最低价
- `close` - 收盘价
- `volume` - 成交量

日期应作为索引（DatetimeIndex）：

```python
# 转换日期格式
if 'date' in data.columns:
    data['date'] = pd.to_datetime(data['date'])
    data = data.set_index('date')
```

### 5. 网络连接问题

**错误信息：**
- 连接超时
- DNS 解析失败
- SSL 证书错误

**解决方案：**

1. **检查网络连接**
   ```bash
   ping push2his.eastmoney.com
   ```

2. **检查防火墙设置**
   - 确保防火墙允许 Python 访问网络
   - 检查公司网络是否限制访问

3. **使用 VPN 或更换网络**
   - 如果在公司网络，可能需要 VPN
   - 尝试使用移动热点测试

4. **增加重试次数**
   - 项目已内置重试机制
   - 可以手动增加重试次数

### 6. 数据源限流

**错误信息：**
- 请求过于频繁
- 429 Too Many Requests

**解决方案：**

1. **降低请求频率**
   - 增加请求间隔
   - 批量获取数据

2. **使用缓存**
   - 将数据保存到数据库
   - 使用本地缓存

3. **使用多个数据源**
   - 在多个数据源之间切换
   - 项目已自动实现数据源切换

## 快速诊断

运行以下代码诊断问题：

```python
import os
import sys

print("="*70)
print("环境诊断")
print("="*70)

# 检查代理设置
print("\n代理设置:")
print(f"  HTTP_PROXY: {os.environ.get('HTTP_PROXY', '未设置')}")
print(f"  HTTPS_PROXY: {os.environ.get('HTTPS_PROXY', '未设置')}")

# 检查 PyBroker
print("\nPyBroker:")
try:
    import pybroker as pb
    print(f"  ✓ PyBroker 已安装，版本: {pb.__version__ if hasattr(pb, '__version__') else '未知'}")
except ImportError:
    print("  ✗ PyBroker 未安装")

# 检查数据源
print("\n数据源:")
try:
    import akshare as ak
    print("  ✓ akshare 已安装")
except ImportError:
    print("  ✗ akshare 未安装")

try:
    import baostock as bs
    print("  ✓ baostock 已安装")
except ImportError:
    print("  ✗ baostock 未安装")

try:
    import tushare as ts
    print("  ✓ tushare 已安装")
except ImportError:
    print("  ✗ tushare 未安装")

# 测试网络连接
print("\n网络连接:")
try:
    import requests
    response = requests.get('https://www.baidu.com', timeout=5)
    print(f"  ✓ 网络连接正常 (状态码: {response.status_code})")
except Exception as e:
    print(f"  ✗ 网络连接失败: {e}")

print("\n" + "="*70)
```

## 推荐配置

### 最佳实践配置

1. **禁用代理**（如果不需要）
2. **使用 baostock 作为主要数据源**（免费、稳定）
3. **配置数据库缓存**（减少 API 调用）
4. **使用项目自带的数据获取模块**（自动切换数据源）

### 配置文件示例

`config/settings.py`:

```python
DATA_CONFIG = {
    'api_preference': 'baostock',  # 推荐使用 baostock
    'provider_override': ['baostock', 'akshare', 'tushare'],  # 数据源优先级
}
```

## 获取帮助

如果以上方案都无法解决问题，请：

1. 检查 PyBroker 官方文档：https://www.pybroker.com/
2. 检查项目日志：`logs/strategy.log`
3. 提交 Issue 到项目仓库


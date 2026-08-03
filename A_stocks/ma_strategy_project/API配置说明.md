# API数据源配置说明

## 支持的API

本项目支持四种API数据源：

1. **akshare**（推荐用于A股）⭐
   - 免费使用
   - 无需token
   - A股数据全面

2. **baostock**（强烈推荐作为akshare替代）⭐
   - 免费使用
   - 无需token
   - 数据质量可靠
   - 专门为A股设计，接口稳定
   - 如果 akshare 安装失败，**强烈推荐使用 baostock**

3. **tushare**
   - 需要注册获取token
   - 部分功能需要积分
   - A股数据质量高

4. **yfinance**（备选方案）
   - 免费使用
   - 无需token
   - **注意：主要用于国际股票（美股、港股），对A股支持有限**

## 安装API库

### 方法1：使用 conda 环境（推荐）⭐

**akshare 会安装到当前激活的 conda 环境中，无需指定文件夹。**

#### 步骤1：创建并激活 conda 环境

在项目根目录（`ma_strategy_project`）下执行：

```bash
# 方式A：使用项目提供的 environment.yml（推荐）
conda env create -f environment.yml
conda activate ma_strategy

# 方式B：手动创建环境
conda create -n ma_strategy python=3.9
conda activate ma_strategy
```

#### 步骤2：安装 akshare

在激活的环境中安装：

```bash
conda install -c conda-forge akshare
```

#### 步骤3：安装其他依赖（如需要）

```bash
pip install -r requirements.txt
```

**注意**：
- conda 会自动管理包安装位置，无需手动指定文件夹
- 确保环境已激活（命令行前会显示 `(ma_strategy)`）
- 每次使用项目前，记得激活环境：`conda activate ma_strategy`

### 方法2：使用 pip 直接安装

```bash
pip install akshare
```

### 方法3：安装tushare

```bash
pip install tushare
```

然后在 `config/settings.py` 中配置token。

### 方法4：安装baostock（强烈推荐作为akshare替代）⭐

```bash
pip install baostock
```

如果遇到网络问题，可以使用国内镜像：
```bash
pip install baostock -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**推荐**：baostock 是 akshare 的最佳替代方案，专门为A股设计，数据质量可靠且稳定。

### 方法5：安装yfinance（备选）

```bash
pip install yfinance
```

**注意**：yfinance 主要用于国际股票数据，对A股支持有限。

## 配置说明

### 配置文件位置

编辑 `config/settings.py` 文件：

```python
DATA_CONFIG = {
    'data_source_priority': ['database', 'api'],  # 数据源优先级
    'min_data_points': 60,
    'api_preference': 'akshare',   # API偏好：'akshare', 'baostock', 'tushare' 或 'yfinance'
    'tushare_token': '',           # tushare token（如使用需配置）
}
```

### akshare配置（推荐用于A股）

**无需任何配置**，安装后即可使用：

```python
# 自动使用akshare，无需额外配置
DATA_CONFIG = {
    'api_preference': 'akshare',  # 默认值
}
```

### baostock配置（强烈推荐作为akshare替代）⭐

如果 akshare 安装失败，**强烈推荐使用 baostock**：

```python
DATA_CONFIG = {
    'api_preference': 'baostock',  # 使用baostock作为优先API
}
```

**baostock 优势**：
- 专门为A股设计，数据质量可靠
- 免费且无需token
- 接口稳定，文档清晰
- **是 akshare 的最佳替代方案**

### yfinance配置（如果akshare和baostock都失败）

如果 akshare 和 baostock 都安装失败，可以使用 yfinance 作为最后备选：

```python
DATA_CONFIG = {
    'api_preference': 'yfinance',  # 使用yfinance作为优先API
}
```

**重要提示**：
- yfinance 对A股数据的支持有限，可能无法获取所有A股数据
- 系统会自动在 akshare/baostock/tushare/yfinance 之间切换尝试
- 如果都不成功，可以设置 `use_mock_if_fail=True` 使用模拟数据

### tushare配置

1. **注册tushare账号**
   - 访问：https://tushare.pro/
   - 注册并获取token

2. **配置token**

编辑 `config/settings.py`：

```python
DATA_CONFIG = {
    'api_preference': 'tushare',
    'tushare_token': 'your_token_here',  # 替换为您的token
}
```

## 数据获取优先级

系统按以下优先级尝试获取数据：

1. **数据库** - 如果数据库中有历史数据表
2. **API** - 根据`api_preference`配置选择akshare或tushare
3. **模拟数据** - 如果以上都失败，可使用模拟数据（开发测试用）

## 使用示例

### 自动使用API

```python
from data.fetcher import DataFetcher

fetcher = DataFetcher()

# 自动尝试：数据库 → API → 模拟数据
data = fetcher.fetch_stock_data(
    code='000001',
    start_date='2023-01-01',
    end_date='2023-12-31',
    use_mock_if_fail=False  # 如果API失败，不使用模拟数据
)
```

### 优先使用API

如果数据库没有数据，系统会自动使用配置的API：

```python
# akshare会自动尝试
data = fetcher.fetch_stock_data('000001', '2023-01-01', '2023-12-31')
```

## 常见问题

### Q: akshare安装失败？

**A:** akshare依赖较多，可能需要安装额外依赖：
```bash
pip install akshare --upgrade
```

或者使用conda安装（在激活的conda环境中）：
```bash
# 确保已激活conda环境
conda activate ma_strategy  # 或您的环境名称
conda install -c conda-forge akshare
```

**重要提示**：`conda install` 会将包安装到**当前激活的conda环境**中，不需要也不应该指定文件夹路径。conda会自动管理所有包的安装位置。

### Q: conda/pip 安装时卡住或下载很慢？

**A:** 如果安装过程中卡住（特别是下载大包时），可以使用以下方法：

#### 方法1：使用 pip 代替 conda（推荐）
```bash
# 在激活的conda环境中使用pip
conda activate ma_strategy
pip install yfinance  # 或其他包名
```
pip 通常比 conda 下载更快，特别是对于纯 Python 包。

#### 方法2：使用国内镜像源加速
```bash
# 使用清华镜像源（pip）
pip install yfinance -i https://pypi.tuna.tsinghua.edu.cn/simple

# 或使用中科大镜像
pip install yfinance -i https://pypi.mirrors.ustc.edu.cn/simple
```

#### 方法3：取消并重试
```bash
# 如果安装卡住，按 Ctrl+C 取消，然后：
# 1. 检查网络连接
# 2. 使用上面的方法1或2重新安装
```

#### 方法4：设置 conda 镜像源（如果必须用 conda）
```bash
# 配置 conda 使用清华镜像
conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main
conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/free
conda config --set show_channel_urls yes

# 然后重新安装
conda install yfinance
```

### Q: tushare提示token无效？

**A:** 
1. 检查token是否正确配置
2. 确认token是否过期
3. 检查账户是否有足够积分

### Q: API获取数据很慢？

**A:** 
- akshare可能需要一些时间
- 可以先用模拟数据测试策略逻辑
- 或者从数据库/其他数据源获取

### Q: 如何切换API？

**A:** 修改 `config/settings.py` 中的 `api_preference`：
```python
'api_preference': 'akshare'   # 或 'baostock', 'tushare', 'yfinance'
```

推荐顺序：akshare > baostock > tushare > yfinance

### Q: akshare安装失败，可以用什么替代？

**A:** **强烈推荐使用 baostock**！baostock 是 akshare 的最佳替代方案：

1. **安装 baostock**（推荐）：
   ```bash
   pip install baostock
   ```

2. **修改配置**：
   在 `config/settings.py` 中设置 `'api_preference': 'baostock'`

3. **baostock 优势**：
   - ✅ 专门为A股设计，数据质量可靠
   - ✅ 免费且无需token
   - ✅ 接口稳定，比 yfinance 更适合A股

**其他备选方案**：
- **yfinance**：也可用，但对A股支持有限
- 系统会自动在 akshare/baostock/tushare/yfinance 之间切换尝试
- 如果都不成功，可以设置 `use_mock_if_fail=True` 使用模拟数据

**推荐顺序**：akshare > baostock > tushare > yfinance

## 注意事项

1. **API限制**：
   - **baostock**：免费使用，无严格频率限制，推荐使用
   - **akshare**：可能有频率限制，但不严格
   - **tushare**：根据积分有不同的调用频率限制
   - **yfinance**：对A股支持有限

2. **数据更新**：
   - API数据通常是实时或接近实时的
   - 建议将获取的数据缓存到数据库

3. **错误处理**：
   - 如果API调用失败，系统会自动尝试另一个API
   - 如果都失败，可以设置`use_mock_if_fail=True`使用模拟数据

4. **网络要求**：
   - API需要网络连接
   - 确保能够访问API服务器

## 测试API连接

可以运行以下代码测试API是否正常工作：

```python
from data.fetcher import DataFetcher

fetcher = DataFetcher()

# 测试akshare
print("测试akshare...")
df = fetcher._fetch_from_akshare('000001', '2023-01-01', '2023-12-31')
if df is not None:
    print(f"✓ akshare正常，获取 {len(df)} 条数据")
else:
    print("✗ akshare获取失败")

# 测试tushare（如果已配置）
print("\n测试tushare...")
df = fetcher._fetch_from_tushare('000001', '2023-01-01', '2023-12-31')
if df is not None:
    print(f"✓ tushare正常，获取 {len(df)} 条数据")
else:
    print("✗ tushare未配置或获取失败")

# 测试baostock（强烈推荐作为akshare替代）
print("\n测试baostock...")
df = fetcher._fetch_from_baostock('000001', '2023-01-01', '2023-12-31')
if df is not None:
    print(f"✓ baostock正常，获取 {len(df)} 条数据")
else:
    print("✗ baostock未安装或获取失败")

# 测试yfinance（备选）
print("\n测试yfinance...")
df = fetcher._fetch_from_yfinance('000001', '2023-01-01', '2023-12-31')
if df is not None:
    print(f"✓ yfinance正常，获取 {len(df)} 条数据")
else:
    print("✗ yfinance未安装或获取失败（对A股支持有限）")
```

---

**推荐配置**：
- **首选**：使用 akshare，无需配置即可开始使用！
- **强烈推荐替代**：如果 akshare 安装失败，使用 **baostock**（专门为A股设计，数据质量可靠）
- **其他备选**：tushare（需token）或 yfinance（A股支持有限）


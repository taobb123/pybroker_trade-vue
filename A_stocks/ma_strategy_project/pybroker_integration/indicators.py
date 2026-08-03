import sys
import os
import numpy as np
import pandas as pd
from numba import njit
import pybroker

# 添加项目根目录到路径，确保可以导入模块
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 导入 PyBroker 数据提供者和格式转换工具
from pybroker_integration.data_provider import PyBrokerDataProvider
from pybroker_integration.data_formatter import PyBrokerDataFormatter, DataFormat

# 编写指标
def cmma(bar_data, lookback):

    @njit  # Enable Numba JIT.
    def vec_cmma(values):
        # Initialize the result array.
        n = len(values)
        out = np.array([np.nan for _ in range(n)])

        # For all bars starting at lookback:
        for i in range(lookback, n):
            # Calculate the moving average for the lookback.
            ma = 0
            for j in range(i - lookback, i):
                ma += values[j]
            ma /= lookback
            # Subtract the moving average from value.
            out[i] = values[i] - ma
        return out

    # Calculate with close prices.
    return vec_cmma(bar_data.close)


cmma_20 = pybroker.indicator('cmma_20', cmma, lookback=20)

# 启用数据源缓存（使用自定义数据源，支持多种数据源）
pybroker.enable_data_source_cache('custom_data_source')

# 使用 PyBrokerDataProvider 获取数据（支持 tushare/baostock/akshare）
# 注意：股票代码应该是6位数字，6000001 改为 600000
stock_code = '600000'
start_date = '2022-04-01'
end_date = '2024-04-01'

print(f"正在获取股票数据: {stock_code} ({start_date} 至 {end_date})...")

# 创建数据提供者实例
data_provider = PyBrokerDataProvider()

# 使用数据格式转换工具创建 BarData 对象（不再需要手动定义类）

# 使用数据提供者获取数据（已转换为 PyBroker 格式）
df = data_provider.fetch_for_pybroker(
    code=stock_code,
    start_date=start_date,
    end_date=end_date
)

if df is None or df.empty:
    print("❌ 未能获取数据")
else:
    print(f"✓ 数据获取成功，共 {len(df)} 条记录")
    print(f"数据格式: date 作为索引，包含列: {list(df.columns)}")


# 在策略中使用指标

def buy_cmma_cross(ctx):
    if ctx.long_pos():
        return
    # Place a buy order if the most recent value of the 20 day CMMA is < 0:
    if ctx.indicator('cmma_20')[-1] < 0:
        ctx.buy_shares = ctx.calc_target_shares(1)
        ctx.hold_bars = 3

# 将 buy_cmma_cross 函数与 cmma_20 指标一起添加到 Strategy 中
from pybroker import Strategy
from pybroker_integration.custom_data_source import create_custom_data_source

# 禁用代理（避免代理连接问题）
os.environ.pop('HTTP_PROXY', None)
os.environ.pop('HTTPS_PROXY', None)
os.environ.pop('http_proxy', None)
os.environ.pop('https_proxy', None)

# 配置 requests 库不使用代理
try:
    import requests
    session = requests.Session()
    session.trust_env = False  # 不信任环境变量中的代理设置
except ImportError:
    pass

# 使用自定义数据源（支持 tushare/baostock/akshare，已处理代理问题）
custom_data_source = create_custom_data_source()

# 使用自定义数据源，日期格式为 YYYYMMDD，股票代码使用 A 股代码
strategy = Strategy(custom_data_source, '20200401', '20220401')
strategy.add_execution(buy_cmma_cross, '600000', indicators=cmma_20)

# 将计算出的指标值缓存到磁盘
pybroker.enable_indicator_cache('my_indicators')

# warmup 参数指定在运行回测执行之前需要经过 20 个 Bar
result = strategy.backtest(warmup=20)
# print(result.metrics_df.round(4))


# 向量化辅助函数
from pybroker import highv

def hhv(bar_data, period):
    return highv(bar_data.high, period)

# hhv_5 = pybroker.indicator('hhv_5', hhv, period=5)
# print(hhv_5(df))


from pybroker import highest

hhv_5 = highest('hhv_5', 'high', period=5)

# # 计算多个指标（需要在数据获取成功后执行）
# if df is not None and not df.empty:
#     # 使用数据格式转换工具转换为 IndicatorSet 需要的格式
#     # IndicatorSet 需要 date 和 symbol 作为列
#     df_for_indicators = PyBrokerDataFormatter.convert(
#         df=df,
#         target_format=DataFormat.COLUMNS_WITH_SYMBOL,
#         symbol=stock_code
#     )
    
#     # 创建指标集合
#     from pybroker import IndicatorSet
    
#     indicator_set = IndicatorSet()
#     indicator_set.add(cmma_20)
#     indicator_set.add(hhv_5)
    
#     # 计算所有指标（传入正确格式的 DataFrame）
#     results = indicator_set(df_for_indicators)
    
#     print("\n多个指标计算结果:")
#     print(f"指标数量: {len(results)}")
#     for name, values in results.items():
#         print(f"{name}: 长度={len(values)}, 前5个值={values[:5]}")
    
#     # 可选：将结果添加到 DataFrame 中查看
#     df_result = df.copy()
#     for name, values in results.items():
#         df_result[name] = values
#     print(f"\n数据预览（最后5行，包含指标）:")
#     print(df_result[['close', 'cmma_20', 'hhv_5']].tail())
# else:
#     print("⚠ 无法计算指标：数据获取失败")


# 将 TA-Lib 与 PyBroker 集成
import talib

rsi_20 = pybroker.indicator('rsi_20', lambda data: talib.RSI(data.close, timeperiod=20))
print(rsi_20(df))
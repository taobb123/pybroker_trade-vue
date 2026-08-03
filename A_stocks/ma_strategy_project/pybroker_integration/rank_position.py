import sys
import os
import pybroker
from pybroker import Strategy, StrategyConfig

# 添加项目根目录到路径，确保可以导入 pybroker_integration 包
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 导入自定义数据源基类
from pybroker_integration.custom_data_source import create_custom_data_source

pybroker.enable_data_source_cache('ranking_and_pos_sizing')

def buy_highest_volume(ctx):
    # 如果所有交易的股票中都没有多头持仓：
    if not tuple(ctx.long_positions()):
        ctx.buy_shares = ctx.calc_target_shares(1)
        ctx.hold_bars = 2
        ctx.score = ctx.volume[-1]

# 初始化数据源
print("="*70)
print("初始化数据源...")
try:
    # 使用便捷函数创建自定义数据源
    custom_data_source = create_custom_data_source()
    print("✓ 自定义数据源创建成功")
except Exception as e:
    print(f"✗ 初始化失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

config = StrategyConfig(max_long_positions=1)
# 使用自定义数据源替代 AKShare()，日期格式为 YYYYMMDD
# 使用 A 股代码（例如：600000-浦发银行, 000001-平安银行, 600519-贵州茅台, 000002-万科A）
strategy = Strategy(custom_data_source, '20210601', '20220601', config)
strategy.add_execution(buy_highest_volume, ['600000', '000001', '600519', '000002'])

# try:
#     # result = strategy.backtest()
    
    # 打印交易记录
#     print("\n" + "="*70)
#     print("交易记录:")
#     print("="*70)
#     print(result.trades)
#     print("="*70)
    
# except Exception as e:
#     print(f"✗ 回测执行失败: {e}")
#     import traceback
#     print("\n详细错误信息:")
#     traceback.print_exc()
#     sys.exit(1)


def buy_and_hold(ctx):
    if not ctx.long_pos() and ctx.bars >= 100:
        ctx.buy_shares = 100
        ctx.hold_bars = 30

strategy = Strategy(custom_data_source, '20220601', '20240601')
strategy.add_execution(buy_and_hold,  ['600000', '000001', '600519', '000002'])


import numpy as np

def pos_size_handler(ctx):
    # Fetch all buy signals.
    signals = tuple(ctx.signals("buy"))
    # Return if there are no buy signals (i.e. there are only sell signals).
    if not signals:
        return
    # Calculates the inverse volatility, where volatility is defined as the
    # standard deviation of close prices for the last 100 days.
    get_inverse_volatility = lambda signal: 1 / np.std(signal.bar_data.close[-100:])
    # Sums the inverse volatilities for all of the buy signals.
    total_inverse_volatility = sum(map(get_inverse_volatility, signals))
    for signal in signals:
        size = get_inverse_volatility(signal) / total_inverse_volatility
        # Calculate the number of shares given the latest close price.
        shares = ctx.calc_target_shares(size, signal.bar_data.close[-1], cash=95_000)
        ctx.set_shares(signal, shares)

strategy.set_pos_size_handler(pos_size_handler)

result = strategy.backtest()

print(result.trades)
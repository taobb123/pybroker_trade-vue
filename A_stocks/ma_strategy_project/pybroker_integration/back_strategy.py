import os
import pybroker
from pybroker import Strategy, StrategyConfig
from pybroker.ext.data import AKShare
import matplotlib.pyplot as plt

# 禁用代理（如果需要使用代理，请注释掉以下代码）
os.environ.pop('HTTP_PROXY', None)
os.environ.pop('HTTPS_PROXY', None)
os.environ.pop('http_proxy', None)
os.environ.pop('https_proxy', None)

pybroker.enable_data_source_cache('my_strategy')
config = StrategyConfig(initial_cash=500_000)

# 使用 AKShare 数据源，日期格式为 YYYYMMDD
strategy = Strategy(AKShare(), '20170301', '20220301', config)

def buy_low(ctx):
    # 如果已经买入并持有股票，则返回
    if ctx.long_pos():
        return
    # 如果最新收盘价低于前一日的低价，
    # 则下买入订单
    if ctx.bars >= 2 and ctx.close[-1] < ctx.low[-2]:
        # 买入相当于投资组合 25% 的股票数量
        ctx.buy_shares = ctx.calc_target_shares(0.25)
        # 设置订单的限价
        ctx.buy_limit_price = ctx.close[-1] - 0.01
        # 在平仓前持有仓位 3 个周期（在这种情况下，3 天）
        ctx.hold_bars = 3


# 使用 A 股代码（例如：600000-浦发银行, 000001-平安银行）
strategy.add_execution(buy_low, ['600000', '000001'])

def short_high(ctx):
    # 如果已经做空，则返回
    if ctx.short_pos():
        return
    # 如果最新收盘价高于前一日的最高价，
    # 则下卖出订单
    if ctx.bars >= 2 and ctx.close[-1] > ctx.high[-2]:
        # 做空 100 股
        ctx.sell_shares = 100
        # 在 2 个周期后平仓（在这种情况下，2 天）
        ctx.hold_bars = 2

# 使用 A 股代码（例如：600519-贵州茅台）
strategy.add_execution(short_high, ['600519'])

result = strategy.backtest()

# 打印回测指标
# print("\n" + "="*70)
# print("回测指标:")
# print("="*70)
# print(result.metrics_df.round(4))
# print("="*70)

# # 打印持仓信息
# print("\n" + "="*70)
# print("持仓信息:")
# print("="*70)
# print(result.positions)
# print("="*70)

# # 打印交易记录
# print("\n" + "="*70)
# print("交易记录:")
# print("="*70)
# print(result.trades)
# print("="*70)




# 创建图表
plt.figure(figsize=(12, 6))
plt.plot(result.portfolio.index, result.portfolio['market_value'], linewidth=2, label='组合市值')
plt.title('回测组合市值变化', fontsize=14, fontweight='bold')
plt.xlabel('日期', fontsize=12)
plt.ylabel('市值 (元)', fontsize=12)
plt.grid(True, alpha=0.3)
plt.legend()
plt.xticks(rotation=45)
plt.tight_layout()

# 显示图表
# plt.show()

# 如果需要保存图表，取消下面的注释
plt.savefig('backtest_portfolio_value.png', dpi=300, bbox_inches='tight')
print("\n图表已保存为: backtest_portfolio_value.png")


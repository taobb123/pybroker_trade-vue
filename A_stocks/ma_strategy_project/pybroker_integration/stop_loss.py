import os
import sys
import pandas as pd
import pybroker
from pybroker import Strategy, StrategyConfig
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from pybroker_integration.custom_data_source import create_custom_data_source


custom_data_source = create_custom_data_source()
pybroker.enable_data_source_cache('stops')
# 设置初始资金（初始持仓）
config = StrategyConfig(initial_cash=50000)  # 初始资金50万元，可根据需要修改
strategy = Strategy(custom_data_source, '20250501', '20251127', config)

# 入场价格下跌 20% 处设置的止损单
def buy_with_stop_loss(ctx):
    if not ctx.long_pos():
        ctx.buy_shares = ctx.calc_target_shares(1)
        ctx.stop_loss_pct = 20

# strategy.add_execution(buy_with_stop_loss, ['600570'])
# result = strategy.backtest()
# print(result.trades)


# 价格上涨 10% 处添加了一个获利单
def buy_with_stop_loss_and_profit(ctx):
    if not ctx.long_pos():
        ctx.buy_shares = ctx.calc_target_shares(1)
        ctx.stop_loss_pct = 20
        ctx.stop_profit_pct = 10

# strategy.clear_executions()
# strategy.add_execution(buy_with_stop_loss_and_profit, ['600690'])
# result = strategy.backtest()
# print(result.trades)


# 移动止损 最高市场价格下跌 20% 处设置移动止损
def buy_with_trailing_stop_loss_and_profit(ctx):
    if not ctx.long_pos():
        # ========================================================================
        # 仓位分配说明:
        # ========================================================================
        # ctx.calc_target_shares(比例) 用于计算目标股数
        # 参数说明:
        #   - 1.0  : 使用 100% 的可用资金（当前设置）
        #   - 0.5  : 使用 50% 的可用资金
        #   - 0.33 : 使用 33% 的可用资金（适合3个股票等权重分配）
        # 
        # ⚠️ 当前问题: 使用 1.0 (100%) 时，如果多个股票同时买入，
        #    每个股票都会尝试使用全部资金，可能导致资金不足！
        # 
        # ✅ 推荐方案:
        #   方案1: 等权重分配 - 如果有N个股票，每个分配 1/N
        #   方案2: 使用 max_long_positions 限制同时持仓数量
        #   方案3: 使用 set_pos_size_handler 自定义仓位分配逻辑
        # ========================================================================
        
        # 当前设置：使用 100% 资金（仅适合单股票或确保不同时买入）
        ctx.buy_shares = ctx.calc_target_shares(1)
        
        # 推荐设置：等权重分配（3个股票，每个33.3%）
        # num_stocks = 3  # 股票数量
        # ctx.buy_shares = ctx.calc_target_shares(1.0 / num_stocks)
        
        ctx.stop_trailing_pct = 20
        ctx.stop_profit_pct = 10

strategy.clear_executions()
# 可以同时测试多个股票，只需在列表中添加多个股票代码
stock_list = ['600570', '600690', '000738']
num_stocks = len(stock_list)

# ============================================================================
# 仓位分配配置选项:
# ============================================================================
# 选项1: 不限制持仓数量（默认）- 所有股票都可以同时持仓
# config = StrategyConfig(initial_cash=50000)

# 选项2: 限制最大持仓数量（推荐用于多股票策略）
# 例如：最多同时持有2个股票，每个分配50%资金
# config = StrategyConfig(initial_cash=50000, max_long_positions=2)
# 然后在策略函数中使用: ctx.calc_target_shares(1.0 / config.max_long_positions)

# 选项3: 等权重分配（当前使用）
# 每个股票分配 1/股票数量 的仓位
# 在策略函数中使用: ctx.calc_target_shares(1.0 / num_stocks)
# ============================================================================

strategy.add_execution(buy_with_trailing_stop_loss_and_profit, stock_list)
result = strategy.backtest()



# ============================================================================
# 显示完整交易表数据的几种方法:
# ============================================================================

# 方法1: 设置 pandas 显示选项，显示所有行和列（推荐）
# pd.set_option('display.max_rows', None)      # 显示所有行
# pd.set_option('display.max_columns', None)   # 显示所有列
# pd.set_option('display.width', None)         # 不限制显示宽度
# pd.set_option('display.max_colwidth', None)  # 不限制列宽度
# print("\n方法1: 完整交易表（所有行和列）:")
try:
    if result.trades is not None:
        print(result.trades)
    else:
        print("交易数据为空 (result.trades 为 None)")
except Exception as e:
    print(f"显示交易数据时出错: {e}")
    print(f"trades 类型: {type(result.trades)}")

# 方法2: 使用 to_string() 强制显示所有内容
print("\n方法2: 使用 to_string() 显示:")
# print(result.trades.to_string())

# 方法3: 保存到 CSV 文件（方便在 Excel 中查看）
try:
    if result.trades is not None and not result.trades.empty:
        # 使用项目根目录保存文件，避免权限问题
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_filename = 'trades_result.csv'
        csv_file = os.path.join(script_dir, base_filename)
        
        # 确保 result.trades 是 DataFrame
        if not isinstance(result.trades, pd.DataFrame):
            trades_df = pd.DataFrame(result.trades)
        else:
            trades_df = result.trades
        
        # 尝试保存文件
        try:
            trades_df.to_csv(csv_file, index=False, encoding='utf-8-sig')
            print(f"\n方法3: 交易数据已保存到文件: {csv_file}")
        except PermissionError:
            # 如果文件被占用，使用带时间戳的文件名
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            csv_file_alt = os.path.join(script_dir, f'trades_result_{timestamp}.csv')
            try:
                trades_df.to_csv(csv_file_alt, index=False, encoding='utf-8-sig')
                print(f"\n方法3: 原文件被占用，已保存到新文件: {csv_file_alt}")
                print(f"       提示: 请关闭 Excel 或其他打开 'trades_result.csv' 的程序")
            except Exception as e2:
                print(f"\n方法3: 保存 CSV 文件失败: {e2}")
                print(f"       可能原因:")
                print(f"       1. 文件被其他程序（如 Excel）打开，请关闭后重试")
                print(f"       2. 文件权限不足，请检查目录写入权限")
                print(f"       3. 磁盘空间不足")
        except Exception as e:
            print(f"\n方法3: 保存 CSV 文件时出错: {e}")
            print(f"       文件路径: {csv_file}")
            print(f"       请检查文件权限和磁盘空间")
    else:
        print(f"\n方法3: 没有交易数据可保存（trades 为空）")
except Exception as e:
    print(f"\n方法3: 处理 CSV 保存时出错: {e}")
    print(f"       trades 类型: {type(result.trades)}")
    if hasattr(result.trades, 'empty'):
        print(f"       trades 是否为空: {result.trades.empty}")

# 方法4: 显示统计信息
print("\n方法4: 交易统计信息:")
try:
    if result.trades is not None and not result.trades.empty:
        print(f"总交易笔数: {len(result.trades)}")
        if 'type' in result.trades.columns:
            buy_trades = result.trades[result.trades['type'] == 'BUY']
            sell_trades = result.trades[result.trades['type'] == 'SELL']
            print(f"买入交易: {len(buy_trades)}")
            print(f"卖出交易: {len(sell_trades)}")
        else:
            print("无法统计买入/卖出交易（缺少 'type' 列）")
        
        if len(result.trades) > 0:
            print(f"\n前5笔交易:")
            # print(result.trades.head())
            if len(result.trades) > 5:
                print(f"\n后5笔交易:")
                # print(result.trades.tail())
    else:
        print("没有交易数据")
except Exception as e:
    print(f"统计交易信息时出错: {e}")

# 恢复 pandas 默认显示设置（可选）
# pd.reset_option('display.max_rows')
# pd.reset_option('display.max_columns')

# ============================================================================
# 回测结果指标说明 (result.trades 各列含义):
# ============================================================================
# type          : 交易类型 ('BUY' 买入 / 'SELL' 卖出)
# symbol        : 股票代码
# entry_date    : 入场日期 (开仓日期)
# exit_date     : 出场日期 (平仓日期，仅卖出交易有值)
# entry_price   : 入场价格 (买入价格)
# exit_price    : 出场价格 (卖出价格，仅卖出交易有值)
# shares        : 交易股数
# pnl           : 盈亏金额 (Profit and Loss，仅卖出交易有值)
# pnl_per_bar   : 每个周期的平均盈亏 (总盈亏 / 持仓周期数)
# return_pct    : 收益率百分比
# bars          : 持仓周期数 (从买入到卖出的天数)
# stop          : 止损类型 ('stop_loss' / 'stop_profit' / 'stop_trailing' / None)
# mae           : Maximum Adverse Excursion (最大不利偏移)
#                - 持仓期间价格相对入场价格的最大不利变动百分比
#                - 反映交易的最大潜在亏损风险
# mfe           : Maximum Favorable Excursion (最大有利偏移)
#                - 持仓期间价格相对入场价格的最大有利变动百分比
#                - 反映交易的最大潜在盈利机会
# ============================================================================
# 示例解读:
# - 如果 mae = -5%，表示持仓期间价格最多下跌了5%
# - 如果 mfe = 8%，表示持仓期间价格最多上涨了8%
# - pnl_per_bar 可以帮助评估持仓效率（单位时间的盈亏）
# ============================================================================


# 设定限价 在止损单设定限价
def buy_with_trailing_stop_loss_and_profit(ctx):
    if not ctx.long_pos():
        ctx.buy_shares = ctx.calc_target_shares(1)
        ctx.stop_trailing_pct = 20
        ctx.stop_trailing_limit = ctx.close[-1] + 1
        ctx.stop_profit_pct = 10
        ctx.stop_profit_limit = ctx.close[-1] - 1

# strategy.clear_executions()
# strategy.add_execution(buy_with_trailing_stop_loss_and_profit, ['600570'])
# result = strategy.backtest()
# print(result.trades.head())


# 取消止损单
def buy_with_stop_trailing_and_cancel(ctx):
    pos = ctx.long_pos()
    if not pos:
        ctx.buy_shares = ctx.calc_target_shares(1)
        ctx.stop_trailing_pct = 20
    elif pos.bars > 60:
        ctx.cancel_stops(ctx.symbol)

# strategy.clear_executions()
# strategy.add_execution(buy_with_stop_trailing_and_cancel, ['600570'])
# result = strategy.backtest()
# print(result.trades)


# 设定限价
from pybroker import PriceType

def buy_with_stop_trailing_and_exit_price(ctx):
    pos = ctx.long_pos()
    if not pos:
        ctx.buy_shares = ctx.calc_target_shares(1)
        ctx.stop_trailing_pct = 20
        ctx.stop_trailing_exit_price = PriceType.OPEN

# strategy.clear_executions()
# strategy.add_execution(buy_with_stop_trailing_and_exit_price, ['600570'])
# result = strategy.backtest()
# print(result.trades.head())















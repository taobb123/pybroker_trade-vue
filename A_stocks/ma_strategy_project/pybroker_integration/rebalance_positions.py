import os
import sys
import pybroker as pyb
from datetime import datetime
from pybroker import Strategy, StrategyConfig, ExecContext

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
from pybroker_integration.custom_data_source import create_custom_data_source

# 模拟重新平衡投资组合
pyb.enable_data_source_cache('rebalancing')


# 等额仓位配置
# 检测当前 K 线的日期是否为新月的开始
def start_of_month(ctxs: dict[str, ExecContext]) -> bool:
    dt = tuple(ctxs.values())[0].dt
    current_month = pyb.param('current_month')
    if current_month is None or dt.month != current_month:
        pyb.param('current_month', dt.month)
        return True
    return False


# 该函数将买入或卖出足够数量的股票，以达到目标配置
def set_target_shares(
    ctxs: dict[str, ExecContext],
    targets: dict[str, float]
):
    for symbol, target in targets.items():
        ctx = ctxs[symbol]
        target_shares = ctx.calc_target_shares(target)
        pos = ctx.long_pos()
        if pos is None:
            ctx.buy_shares = target_shares
        elif pos.shares < target_shares:
            ctx.buy_shares = target_shares - pos.shares
        elif pos.shares > target_shares:
            ctx.sell_shares = pos.shares - target_shares


# 编写一个再平衡函数，使每个月初每种资产的配置比例达到相等
def rebalance(ctxs: dict[str, ExecContext]):
    if start_of_month(ctxs):
        target = 1 / len(ctxs)
        set_target_shares(ctxs, {symbol: target for symbol in ctxs.keys()})


# 投资组合优化
import pandas as pd
import riskfolio as rp

pyb.param('lookback', 252)  # Use past year of returns.

def calculate_returns(ctxs: dict[str, ExecContext], lookback: int):
    """计算历史收益率"""
    prices = {}
    for ctx in ctxs.values():
        # 使用 ctx.data 获取历史数据
        if hasattr(ctx, 'data') and ctx.data is not None and not ctx.data.empty:
            data = ctx.data
            # 优先使用 adj_close，如果没有则使用 close
            if 'adj_close' in data.columns:
                price_series = data['adj_close'].copy()
            elif 'close' in data.columns:
                price_series = data['close'].copy()
            else:
                # 如果都没有，跳过该股票
                continue
        else:
            # 如果没有历史数据，跳过该股票
            continue
        
        # 确保有足够的数据
        if len(price_series) >= lookback:
            prices[ctx.symbol] = price_series[-lookback:]
        elif len(price_series) >= 10:  # 至少需要10个数据点
            # 如果数据不足但至少有10个点，使用所有可用数据
            prices[ctx.symbol] = price_series
        # 如果数据太少，跳过该股票
    
    if not prices or len(prices) < 2:
        # 至少需要2只股票才能计算相关性
        return pd.DataFrame()
    
    # 对齐所有价格序列的索引（日期）
    df = pd.DataFrame(prices)
    if df.empty:
        return df
    
    # 删除所有 NaN 的行
    df = df.dropna()
    
    if len(df) < 10:
        # 至少需要10个数据点
        return pd.DataFrame()
    
    returns = df.pct_change().dropna()
    return returns

def optimization(ctxs: dict[str, ExecContext]):
    """投资组合优化函数"""
    lookback = pyb.param('lookback')
    
    # 检查是否有足够的数据
    min_bars = min(ctx.bars for ctx in ctxs.values())
    if min_bars < lookback:
        # 如果数据不足，使用等权重分配
        if start_of_month(ctxs):
            target = 1 / len(ctxs)
            set_target_shares(ctxs, {symbol: target for symbol in ctxs.keys()})
        return
    
    if start_of_month(ctxs):
        try:
            Y = calculate_returns(ctxs, lookback)
            
            # 检查返回的 DataFrame 是否有效
            if Y.empty or len(Y) < 10:  # 至少需要10个数据点
                # 数据不足，使用等权重
                target = 1 / len(ctxs)
                set_target_shares(ctxs, {symbol: target for symbol in ctxs.keys()})
                return
            
            # 确保所有股票都有数据
            if not all(symbol in Y.columns for symbol in ctxs.keys()):
                # 如果某些股票缺少数据，使用等权重
                target = 1 / len(ctxs)
                set_target_shares(ctxs, {symbol: target for symbol in ctxs.keys()})
                return
            
            # 使用 riskfolio 进行优化
            port = rp.Portfolio(returns=Y)
            port.assets_stats(method_mu='hist', method_cov='hist')
            w = port.optimization(
                model='Classic',
                rm='CVaR',
                obj='MinRisk',
                rf=0,      # Risk free rate.
                l=0,       # Risk aversion factor.
                hist=True  # Use historical scenarios.
            )
            
            # 提取权重
            if w is not None and not w.empty:
                targets = {}
                for symbol in ctxs.keys():
                    if symbol in w.columns:
                        targets[symbol] = w.T[symbol].values[0]
                    else:
                        # 如果某个股票没有权重，使用等权重
                        targets[symbol] = 1 / len(ctxs)
                
                # 确保权重和为1（归一化）
                total_weight = sum(targets.values())
                if total_weight > 0:
                    targets = {k: v / total_weight for k, v in targets.items()}
                else:
                    # 如果权重和为零，使用等权重
                    target = 1 / len(ctxs)
                    targets = {symbol: target for symbol in ctxs.keys()}
                
                set_target_shares(ctxs, targets)
            else:
                # 优化失败，使用等权重
                target = 1 / len(ctxs)
                set_target_shares(ctxs, {symbol: target for symbol in ctxs.keys()})
                
        except Exception as e:
            # 如果优化过程中出现任何错误，使用等权重分配
            print(f"优化过程中出现错误: {e}，使用等权重分配")
            target = 1 / len(ctxs)
            set_target_shares(ctxs, {symbol: target for symbol in ctxs.keys()})

# 对策略进行回测
# 创建新的策略对象用于优化回测
data_source = create_custom_data_source()
strategy = Strategy(data_source, start_date='20240501', end_date='20251128')
strategy.add_execution(None, ['600570', '600690', '000738', '601939', '000738'])
strategy.set_after_exec(optimization)

# 运行回测，warmup 确保有足够的历史数据
lookback = pyb.param('lookback')
result = strategy.backtest(warmup=lookback)

# 输出回测结果
print(f"\n回测完成！")
print(f"订单数量: {len(result.orders)}")
print(f"回测期间: {result.orders['date'].min() if not result.orders.empty else 'N/A'} 到 {result.orders['date'].max() if not result.orders.empty else 'N/A'}")
if not result.orders.empty:
    print("\n前10条订单:")
    print(result.orders.head(10))
    print(f"\n订单统计:")
    print(result.orders.groupby('type').size())
else:
    print("\n警告: 没有生成任何订单！")
    print("可能的原因:")
    print("1. 数据不足（需要至少252个交易日的历史数据）")
    print("2. 回测期间没有遇到月初（策略只在月初执行）")
    print("3. 数据获取失败")

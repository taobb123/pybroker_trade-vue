import os
import sys
import pybroker as pyb
from pybroker import Strategy, StrategyConfig, ExecContext
import numpy as np

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
from pybroker_integration.custom_data_source import create_custom_data_source

# 启用数据源缓存，提高性能
pyb.enable_data_source_cache('rotation_trade_cache')

# 策略将涉及对 价格涨幅（ROC） 最高的股票进行排名和购买。首先，我们将使用 TA-Lib 定义一个 20 天的 ROC 指标：
import talib as ta

# 定义 ROC 指标，处理可能的 NaN 值
def roc_20_func(data):
    """计算 20 日 ROC 指标，处理 NaN 值"""
    roc = ta.ROC(data.close, timeperiod=20)
    # 将 NaN 和 inf 替换为 0
    roc = np.nan_to_num(roc, nan=0.0, posinf=0.0, neginf=0.0)
    return roc

roc_20 = pyb.indicator('roc_20', roc_20_func)

# 购买 20 天涨幅（ROC）最高的两只股票。
# 将我们的资本的 50% 分配给每只股票。
# 如果其中一只股票不再位于前五名的 20 天涨幅（ROC）中，则我们将清盘该股票。
# 每天交易这些规则
config = StrategyConfig(max_long_positions=2, initial_cash=50000)
pyb.param('target_size', 1 / config.max_long_positions)
pyb.param('rank_threshold', 5)


def rank(ctxs: dict[str, ExecContext]):
    """对股票按 ROC 指标进行排名"""
    scores = {}
    for symbol, ctx in ctxs.items():
        try:
            roc_values = ctx.indicator('roc_20')
            if roc_values is not None and len(roc_values) > 0:
                # 获取最后一个有效值（非 NaN）
                last_value = roc_values[-1]
                if not (np.isnan(last_value) or np.isinf(last_value)):
                    scores[symbol] = float(last_value)
        except (IndexError, TypeError, ValueError) as e:
            # 如果指标计算失败，跳过该股票
            continue
    
    if not scores:
        # 如果没有有效的分数，设置空列表
        pyb.param('top_symbols', [])
        return
    
    # 按分数排序（降序）
    sorted_scores = sorted(
        scores.items(),
        key=lambda score: score[1],
        reverse=True
    )
    threshold = pyb.param('rank_threshold')
    top_scores = sorted_scores[:threshold]
    top_symbols = [score[0] for score in top_scores]
    pyb.param('top_symbols', top_symbols)


# 我们已经有了一个根据 ROC 对股票进行排名的方法，我们可以继续实现一个 轮动 函数来管理轮动交易。
def rotate(ctx: ExecContext):
    """轮动交易函数"""
    top_symbols = pyb.param('top_symbols')
    if top_symbols is None or len(top_symbols) == 0:
        # 如果还没有排名或排名为空，不执行任何操作
        return
    
    try:
        if ctx.long_pos():
            # 如果持有股票但不在 top_symbols 中，则卖出
            if ctx.symbol not in top_symbols:
                ctx.sell_all_shares()
        else:
            # 如果股票在 top_symbols 中，则买入
            if ctx.symbol in top_symbols:
                target_size = pyb.param('target_size')
                ctx.buy_shares = ctx.calc_target_shares(target_size)
                # 获取 ROC 分数
                try:
                    roc_values = ctx.indicator('roc_20')
                    if roc_values is not None and len(roc_values) > 0:
                        ctx.score = float(roc_values[-1])
                except (IndexError, TypeError, ValueError):
                    ctx.score = 0.0
    except Exception as e:
        # 捕获任何异常，避免中断回测
        print(f"⚠ 警告: {ctx.symbol} 轮动交易异常: {e}")
        return


# 我们将使用 set_before_exec 方法在运行 轮动 函数之前使用 rank 执行我们的排名
if __name__ == '__main__':
    import time
    
    # 股票列表
    symbols = [
        '000408',
        '600309',
    ]
    
    print("=" * 80)
    print("轮动交易策略回测")
    print("=" * 80)
    print(f"股票池数量: {len(symbols)}")
    print(f"回测日期范围: 2022-01-01 至 2025-12-05")
    print(f"预热期: 20 天")
    print(f"数据源: 优先使用 tushare")
    print("=" * 80)
    print("提示: 数据获取可能需要一些时间，请耐心等待...")
    print("=" * 80)
    
    try:
        # 创建数据源
        data_source = create_custom_data_source()
        
        # 创建策略
        strategy = Strategy(
            data_source,
            start_date='20220101',
            end_date='20251205',
            config=config
        )
        strategy.set_before_exec(rank)
        strategy.add_execution(rotate, symbols, indicators=roc_20)
        
        # 运行回测
        start_time = time.time()
        print("\n开始回测...")
        result = strategy.backtest(warmup=20)
        elapsed_time = time.time() - start_time
        
        print(f"\n✓ 回测完成！耗时: {elapsed_time:.2f} 秒 ({elapsed_time/60:.2f} 分钟)")
        print("=" * 80)
        
        # 保存结果
        script_dir = os.path.dirname(os.path.abspath(__file__))
        base_filename = 'rotation_trade_result.csv'
        csv_file = os.path.join(script_dir, base_filename)
        trades_df = result.trades
        
        if trades_df is not None and not trades_df.empty:
            trades_df.to_csv(csv_file, index=False, encoding='utf-8-sig')
            print(f"✓ 交易记录已保存到: {csv_file}")
            print(f"  总交易数: {len(trades_df)}")
        else:
            print("⚠ 警告: 没有交易记录")
        
        # 显示订单信息
        if hasattr(result, 'orders') and result.orders is not None:
            print(f"\n订单信息:")
            print(result.orders)
        
    except Exception as e:
        elapsed_time = time.time() - start_time if 'start_time' in locals() else 0
        print(f"\n✗ 回测过程中发生错误！耗时: {elapsed_time:.2f} 秒")
        print(f"错误类型: {type(e).__name__}")
        print(f"错误信息: {e}")
        import traceback
        print("\n详细错误堆栈:")
        traceback.print_exc()
        raise




    
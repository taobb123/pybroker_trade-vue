import os
import sys
import pybroker as pyb
from pybroker import Strategy, StrategyConfig, ExecContext
import pandas as pd
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
from pybroker_integration.custom_data_source import create_custom_data_source


# 策略将涉及对 价格涨幅（ROC） 最高的股票进行排名和购买。首先，我们将使用 TA-Lib 定义一个 20 天的 ROC 指标：
import talib as ta

roc_20 = pyb.indicator(
    'roc_20', lambda data: ta.ROC(data.close, timeperiod=20))

# 购买 20 天涨幅（ROC）最高的两只股票。
# 将我们的资本的 50% 分配给每只股票。
# 如果其中一只股票不再位于前五名的 20 天涨幅（ROC）中，则我们将清盘该股票。
# 每天交易这些规则
config = StrategyConfig(max_long_positions=2, initial_cash=50000)
pyb.param('target_size', 1 / config.max_long_positions)
pyb.param('rank_threshold', 5)


def rank(ctxs: dict[str, ExecContext]):
    scores = {
        symbol: ctx.indicator('roc_20')[-1]
        for symbol, ctx in ctxs.items()
    }
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
    top_symbols = pyb.param('top_symbols')
    if top_symbols is None:
        # 如果还没有排名，不执行任何操作
        return
    
    if ctx.long_pos():
        # 如果持有股票但不在 top_symbols 中，则卖出
        if ctx.symbol not in top_symbols:
            ctx.sell_all_shares()
    else:
        # 如果股票在 top_symbols 中，则买入
        if ctx.symbol in top_symbols:
            target_size = pyb.param('target_size')
            ctx.buy_shares = ctx.calc_target_shares(target_size)
            ctx.score = ctx.indicator('roc_20')[-1]


# 我们将使用 set_before_exec 方法在运行 轮动 函数之前使用 rank 执行我们的排名

def load_stocks_pool(file_path):
    """从文件读取股票池列表（支持每行多个股票代码，用空格分隔）"""
    if os.path.exists(file_path):
        try:
            symbols = []
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        # 按空格分割，支持每行多个股票代码
                        line_symbols = line.split()
                        symbols.extend(line_symbols)
            print(f"从文件 {file_path} 读取到 {len(symbols)} 只股票")
            return symbols
        except Exception as e:
            print(f"读取股票池文件失败: {e}")
            return None
    else:
        print(f"股票池文件 {file_path} 不存在，将使用默认股票池")
        return None

def save_stocks_pool(file_path, symbols):
    """将股票池列表保存到文件（每行10个股票代码，用空格分隔）"""
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            # 每行保存10个股票代码
            for i in range(0, len(symbols), 10):
                row_symbols = symbols[i:i+10]
                f.write(' '.join(row_symbols) + '\n')
        print(f"\n已将过滤后的股票池（共 {len(symbols)} 只）保存到 {file_path}")
    except Exception as e:
        print(f"保存股票池文件失败: {e}")

if __name__ == '__main__':
    # 配置参数：要删除的亏损最大的股票数量
    max_loss_stocks_to_remove = 0
    
    # 获取脚本所在目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    stocks_pool_file = os.path.join(script_dir, 'stocks_pool.txt')
    
    # 从文件读取股票池，如果文件不存在则使用默认股票池
    original_symbols = load_stocks_pool(stocks_pool_file)
    
    # 如果文件不存在或读取失败，使用默认股票池
    if original_symbols is None:
        # 定义默认原始股票池
        original_symbols = [
		'600919',
		'601698',
		'600011',
		'601998',
		'300502',
		'601658',
		'300628',
		'601077',
		'600941',
		'601808',
		'601298',
		'600377',
		'688036',
		'688271',
		'600025',
		'600674',
		'600938',
		'003816',
		'300308',
		'300433',
		'605499',
		'001965',
		'600039',
		'600886'
    ]
    
    data_source = create_custom_data_source()
    # 每次运行自动拉取最近日期数据：结束日=今天，开始日=约2年前
    end_date_d = datetime.now()
    start_date_d = end_date_d - timedelta(days=2 * 365)
    start_date = start_date_d.strftime('%Y%m%d')
    end_date = end_date_d.strftime('%Y%m%d')
    strategy = Strategy(
        data_source,
        start_date=start_date,
        end_date=end_date,
        config=config
    )
    strategy.set_before_exec(rank)
    strategy.add_execution(rotate, original_symbols, indicators=roc_20)
    
    result = strategy.backtest(warmup=20)

    print(result.orders)
    base_filename = 'rotation_trade_pln.csv'
    csv_file = os.path.join(script_dir, base_filename)
    trades_df = result.trades
    trades_df.to_csv(csv_file, index=False, encoding='utf-8-sig')
    
    # ============================================================================
    # 分析交易历史，找出亏损最大的前30只股票并删除
    # ============================================================================
    print("\n" + "="*80)
    print("开始分析交易历史，计算每只股票的累计亏损...")
    print("="*80)
    
    if trades_df is not None and not trades_df.empty:
        # 检查必要的列是否存在
        required_columns = ['symbol', 'pnl']
        missing_columns = [col for col in required_columns if col not in trades_df.columns]
        
        if missing_columns:
            print(f"警告: 交易数据中缺少必要的列: {missing_columns}")
            print(f"可用的列: {list(trades_df.columns)}")
        else:
            # 按股票代码分组，计算每只股票的累计亏损
            # 只考虑亏损的交易（pnl < 0）
            loss_trades = trades_df[trades_df['pnl'] < 0].copy()
            
            if not loss_trades.empty:
                # 计算每只股票的累计亏损（负值，所以亏损越大，值越小）
                symbol_losses = loss_trades.groupby('symbol')['pnl'].sum().sort_values()
                
                # 获取亏损最大的前N只股票（pnl 最小的N只）
                top_loss_symbols = symbol_losses.head(max_loss_stocks_to_remove).index.tolist()
                
                print(f"\n找到 {len(symbol_losses)} 只有亏损记录的股票")
                print(f"\n亏损最大的前{max_loss_stocks_to_remove}只股票:")
                print("-" * 80)
                for i, (symbol, total_loss) in enumerate(symbol_losses.head(max_loss_stocks_to_remove).items(), 1):
                    print(f"{i:2d}. {symbol}: 累计亏损 {total_loss:.2f} 元")
                
                # 从原始股票池中删除这些股票
                filtered_symbols = [s for s in original_symbols if s not in top_loss_symbols]
                
                print(f"\n原始股票池数量: {len(original_symbols)}")
                print(f"删除股票数量: {len(top_loss_symbols)}")
                print(f"过滤后股票池数量: {len(filtered_symbols)}")
                
                print(f"\n已删除的股票代码列表:")
                print("-" * 80)
                for i, symbol in enumerate(top_loss_symbols, 1):
                    loss_amount = symbol_losses[symbol]
                    print(f"{i:2d}. {symbol} (累计亏损: {loss_amount:.2f} 元)")
                
                print(f"\n过滤后的股票池（共 {len(filtered_symbols)} 只）:")
                print("-" * 80)
                # 每行显示10只股票
                for i in range(0, len(filtered_symbols), 10):
                    row_symbols = filtered_symbols[i:i+10]
                    print(" ".join(f"{s:>6}" for s in row_symbols))
                
                # 将过滤后的股票池保存到文件
                save_stocks_pool(stocks_pool_file, filtered_symbols)
            else:
                print("未找到亏损交易记录")
                # 即使没有亏损记录，也保存原始股票池（保持不变）
                save_stocks_pool(stocks_pool_file, original_symbols)
    else:
        print("交易数据为空，无法进行分析")
        # 即使没有交易数据，也保存原始股票池（保持不变）
        save_stocks_pool(stocks_pool_file, original_symbols)




    
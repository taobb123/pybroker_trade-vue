#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
均线策略主程序入口
"""

import sys
import os
from datetime import datetime, timedelta

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data.fetcher import DataFetcher
from strategies.moving_average import MovingAverageStrategy
from strategies.mean_reversion import MeanReversionStrategy
from backtest.engine import BacktestEngine
from backtest.analyzer import PerformanceAnalyzer
from utils.logger import logger
from utils.visualization import plot_equity_curve
from optimization.grid_search import grid_search_ma
from risk.manager import RiskManager, RiskParams
from execution.manager import ExecutionManager
from execution.executor import StrategyExecutor
from execution.order_manager import OrderManager
from config.settings import BACKTEST_CONFIG, STRATEGY_DEFAULT_PARAMS
from backtest.portfolio import run_portfolio_backtest


def main():
    """主函数"""
    print("\n" + "="*70)
    print("双均线策略回测系统")
    print("="*70)
    
    # ========== 参数配置 ==========
    # 股票代码（可单只，也可组合）
    stock_code = '600111'
    portfolio_codes = ['600111', '601318', '600519']  # 组合示例，可修改
    
    # 时间范围（默认最近一年）
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    
    # 策略参数
    short_window = STRATEGY_DEFAULT_PARAMS['moving_average']['short_window']
    long_window = STRATEGY_DEFAULT_PARAMS['moving_average']['long_window']
    
    # 回测参数
    initial_capital = BACKTEST_CONFIG['initial_capital']
    commission = BACKTEST_CONFIG['commission']
    
    print(f"\n【策略参数】")
    print(f"  股票代码: {stock_code}")
    print(f"  时间范围: {start_date} 至 {end_date}")
    print(f"  短期均线: {short_window}天")
    print(f"  长期均线: {long_window}天")
    print(f"  初始资金: {initial_capital:,.0f} 元")
    print(f"  手续费率: {commission*100:.2f}%")
    
    # ========== 1. 获取数据 ==========
    print(f"\n【步骤 1/4】获取股票数据...")
    with DataFetcher() as fetcher:
        # 尝试获取真实数据，如果失败则使用模拟数据
        data = fetcher.fetch_stock_data(
                code=stock_code,
                start_date=start_date,
                end_date=end_date,
                use_mock_if_fail=True  # 如果真实数据获取失败，使用模拟数据
            )
        
        if data.empty:
            print("[FAIL] 未能获取数据")
            return
        
        print(f"[OK] 获取数据成功，共 {len(data)} 条记录")
        print(f"  日期范围: {data['date'].min()} 至 {data['date'].max()}")
        
    # ========== 2. 创建策略 ==========
    print(f"\n【步骤 2/4】创建策略...")
    # 最小均值回归示例：设置 use_mean_reversion=True 体验
    use_mean_reversion = False
    if use_mean_reversion:
        strategy = MeanReversionStrategy(window=20, entry_z=2.0, exit_z=0.0)
    else:
        strategy = MovingAverageStrategy(
            short_window=short_window,
            long_window=long_window
        )
    print(f"[OK] 策略创建成功: {strategy.name}")

    # ========== 3. 运行回测 ==========
    print(f"\n【步骤 3/4】运行回测...")
    engine = BacktestEngine(
        strategy=strategy,
        initial_capital=initial_capital,
        commission=commission
    )

    results = engine.run(data)
    print(f"[OK] 回测完成，共执行 {results['num_trades']} 笔交易")

    # ========== 4. 性能分析 ==========
    print(f"\n【步骤 4/4】性能分析...")
    analyzer = PerformanceAnalyzer()
    analysis = analyzer.analyze(results)

    # 打印报告
    analyzer.print_report(analysis)

    # 可视化：保存权益曲线
    try:
        outfile = plot_equity_curve(results['data'])
        if outfile:
            print(f"[OK] 已保存权益曲线: {outfile}")
    except Exception as _:
        pass

    # 执行建议 + 风险管理（演示）
    try:
        # 使用原始行情数据重新计算一次信号，确保包含 ma 与 signal 列
        _sig_df = strategy.generate_signals(data)
        # 打印最新K线的均线数值
        _last = _sig_df.iloc[-1]
        # 额外打印：不含今日的SMA20 以及 EMA20 以便与行情软件对齐排查
        ma20_excl_today = _sig_df['ma_long'].shift(1).iloc[-1]
        # 对齐口径探测：逐日先四舍五入到2位后再做SMA20（上面策略里已使用该口径）
        sma20_round2 = _sig_df['close'].round(2).rolling(long_window, min_periods=1).mean().iloc[-1]
        ma20_ema = _sig_df['close'].ewm(span=long_window, adjust=False).mean().iloc[-1]
        print(
            f"\n【最新K线均线】 日期:{_last['date']}  收盘:{_last['close']:.2f}  "
            f"SMA{short_window}:{_last['ma_short']:.2f}  "
            f"SMA{long_window}(含今日):{_last['ma_long']:.2f}  "
            f"SMA{long_window}(不含今日):{ma20_excl_today:.2f}  "
            f"SMA{long_window}(先四舍五入再均值):{sma20_round2:.2f}  "
            f"EMA{long_window}:{ma20_ema:.2f}"
        )
        latest_info = strategy.get_latest_signal(_sig_df)
        exec_mgr = ExecutionManager()
        advice = exec_mgr.advise(latest_info['signal'])
        print(f"\n【执行建议】 action={advice.action} | reason={advice.reason}")

        risk_mgr = RiskManager(total_capital=initial_capital, params=RiskParams())
        max_shares = risk_mgr.calc_max_buy_amount(price=latest_info['price'])
        print(f"【风险管理】单笔最大仓位可买股数: {max_shares}")

        # 进一步：生成下单建议并记录
        executor = StrategyExecutor(risk_mgr)
        order_suggestion = executor.suggest(latest_info['signal'], latest_info['price'])
        order_book = OrderManager()
        if order_suggestion.action != 'HOLD':
            order_book.add_order(
                action=order_suggestion.action,
                symbol=stock_code,
                quantity=(order_suggestion.quantity or 0),
                price=order_suggestion.price,
                note=order_suggestion.reason,
            )
        print(order_book.summary())
    except Exception as e:
        print(f"[FAIL] 执行建议/风险管理 输出失败: {e}")

    # 额外：小型参数优化示例（快速网格搜索）
    try:
        best, _all = grid_search_ma(
            data,
            short_choices=[5, 10],
            long_choices=[20, 40, 60],
            initial_capital=initial_capital,
            commission=commission,
        )
        print(f"\n参数优化建议 -> 短期:{best.short_window} 长期:{best.long_window} 总收益:{best.total_return:+.2f}%")
    except Exception:
        pass

    # 组合回测（演示：等权）
    try:
        pf = run_portfolio_backtest(
            portfolio_codes,
            start_date,
            end_date,
            initial_capital,
            commission,
            short_window,
            long_window,
        )
        print("\n【组合回测】等权三标的")
        for item in pf['per_code']:
            print(f"  {item['code']} -> 收益:{item['total_return']:+.2f}%  交易:{item['num_trades']}")
        print(f"  组合最终资产: {pf['final_value']:.2f}  组合总收益: {pf['total_return']:+.2f}%")
    except Exception:
        pass
    
    # ========== 5. 显示交易明细（可选）==========
    if results['trades']:
        print("【交易明细】（全部）")
        print("-"*70)
        for i, trade in enumerate(results['trades'], 1):
            trade_type = "买入" if trade['type'] == 'BUY' else "卖出"
            print(f"{i}. {trade['date']} | {trade_type} | "
                  f"{trade.get('shares', 0)}股 @ {trade['price']:.2f}")
            if 'pnl' in trade:
                pnl_sign = "+" if trade['pnl'] >= 0 else ""
                print(f"   盈亏: {pnl_sign}{trade['pnl']:.2f} 元")
        print()

    print("="*70)
    print("[OK] 回测流程完成！")
    print("="*70 + "\n")
    # 注：如需全局异常捕获，可在此处添加 try/except 包裹以上流程


if __name__ == '__main__':
    main()


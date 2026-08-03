#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试财务数据与回测系统的集成
"""

import sys
import os

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from data.fetcher import DataFetcher
from data.financial_fetcher import FinancialDataFetcher
from strategies.moving_average import MovingAverageStrategy
from backtest.engine import BacktestEngine
from backtest.analyzer import PerformanceAnalyzer
from utils.visualization import plot_price_ma_signals
from utils.financial_metrics import get_financial_display_data
from config.settings import BACKTEST_CONFIG


def test_financial_integration():
    """测试财务数据集成到回测系统"""
    print("="*70)
    print("测试：财务数据与回测系统集成")
    print("="*70)
    
    # 测试股票代码
    stock_code = '000001'
    start_date = '2024-01-01'
    end_date = '2024-12-31'
    
    print(f"\n【步骤 1/4】获取股票数据...")
    with DataFetcher() as fetcher:
        data = fetcher.fetch_stock_data(stock_code, start_date, end_date, use_mock_if_fail=True)
        if data.empty:
            print("✗ 无法获取数据")
            return
        print(f"✓ 获取数据成功，共 {len(data)} 条记录")
    
    print(f"\n【步骤 2/4】运行回测...")
    strategy = MovingAverageStrategy(short_window=5, long_window=20)
    engine = BacktestEngine(strategy=strategy, 
                           initial_capital=BACKTEST_CONFIG['initial_capital'],
                           commission=BACKTEST_CONFIG['commission'])
    results = engine.run(data)
    print(f"✓ 回测完成，总收益率: {results['total_return']:.2f}%")
    
    print(f"\n【步骤 3/4】获取财务指标...")
    current_price = data['close'].iloc[-1]
    financial_info = get_financial_display_data(stock_code, current_price=current_price)
    
    if financial_info.get('data_available'):
        print("✓ 财务数据获取成功")
        print(f"  净利润: {financial_info.get('net_profit_yi', 'N/A')} 亿元")
        print(f"  ROE: {financial_info.get('roe', 'N/A')}%")
        print(f"  市盈率: {financial_info.get('pe_ratio', 'N/A')}")
        print(f"  市净率: {financial_info.get('pb_ratio', 'N/A')}")
        print(f"  综合得分: {financial_info.get('comprehensive_score', 'N/A')}")
    else:
        print("⚠ 财务数据获取失败或不可用")
    
    print(f"\n【步骤 4/4】生成带财务指标的图表...")
    try:
        # 生成信号数据
        sig_df = strategy.generate_signals(data)
        
        # 绘制图表（带财务指标）
        fig_path = plot_price_ma_signals(
            sig_df, 
            outfile="test_ma_with_financial.png",
            stock_code=stock_code,
            interactive=False
        )
        
        if fig_path:
            print(f"✓ 图表已保存: {fig_path}")
            print("  请查看图表左侧是否显示了财务指标")
        else:
            print("✗ 图表生成失败")
    
    except Exception as e:
        print(f"✗ 图表生成失败: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"\n{'='*70}")
    print("测试完成")
    print(f"{'='*70}\n")


if __name__ == '__main__':
    test_financial_integration()


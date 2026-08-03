#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PyBroker 集成示例
展示如何使用 PyBroker 回测现有策略
"""

import sys
import os
from datetime import datetime, timedelta

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import pybroker as pb  # type: ignore
except ImportError:
    print("警告: PyBroker 未安装，请运行: pip install -U lib-pybroker")
    pb = None  # type: ignore
import pandas as pd
from data.fetcher import DataFetcher
from strategies.moving_average import MovingAverageStrategy
from strategies.mean_reversion import MeanReversionStrategy
from pybroker_integration.adapter import PyBrokerAdapter, convert_strategy_to_pybroker
from pybroker_integration.data_provider import PyBrokerDataProvider
from config.settings import BACKTEST_CONFIG, STRATEGY_DEFAULT_PARAMS
from utils.logger import logger


def example_basic_pybroker():
    """示例1: 使用 PyBroker 原生方式创建简单策略"""
    if pb is None:
        print("PyBroker 未安装，跳过此示例")
        return
    
    print("\n" + "="*70)
    print("示例1: PyBroker 原生策略")
    print("="*70)
    
    # 定义简单的移动平均策略
    def simple_ma_strategy(ctx):
        """简单的双均线策略"""
        # 使用 PyBroker 的内置函数计算均线
        try:
            ma5 = ctx.sma('close', 5)
            ma20 = ctx.sma('close', 20)
        except AttributeError:
            # 如果不可用，使用数据计算
            data = ctx.data
            if len(data) < 20:
                return
            ma5 = data['close'].rolling(window=5, min_periods=1).mean().iloc[-1]
            ma20 = data['close'].rolling(window=20, min_periods=1).mean().iloc[-1]
        
        if ma5 > ma20 and ctx.long_positions() == 0:
            # 买入（全仓）
            shares = int(ctx.cash / ctx.close)
            if shares > 0:
                ctx.buy_shares = shares
        elif ma5 < ma20 and ctx.long_positions() > 0:
            # 卖出
            ctx.sell_all_shares()
    
    # 配置策略
    config = pb.StrategyConfig(
        strategy=simple_ma_strategy,
        symbols=['000001'],  # 股票代码
        start_date='2023-01-01',
        end_date='2023-12-31',
        initial_cash=100000,
        commission=0.001,
    )
    
    # 注册数据源（使用 AKShare）
    @pb.data_source(symbols=['000001'])
    def akshare_source(symbol: str, start_date: str, end_date: str):
        """使用 AKShare 获取数据"""
        try:
            import akshare as ak
            # AKShare 获取数据
            # 注意：需要根据实际 AKShare API 调整
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date.replace('-', ''),
                end_date=end_date.replace('-', ''),
                adjust=""
            )
            # 转换格式
            df.columns = ['date', 'open', 'close', 'high', 'low', 'volume', 'turnover', 'amplitude', 'change_pct', 'change_amount', 'turnover_rate']
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')
            return df[['open', 'high', 'low', 'close', 'volume']]
        except Exception as e:
            logger.warning(f"AKShare 获取数据失败: {e}")
            return None
    
    try:
        # 运行回测
        result = pb.run_backtest(config)
        print(f"回测完成: {result}")
    except Exception as e:
        print(f"回测失败: {e}")


def example_convert_existing_strategy():
    """示例2: 将现有策略转换为 PyBroker 格式"""
    print("\n" + "="*70)
    print("示例2: 转换现有策略到 PyBroker")
    print("="*70)
    
    # 创建现有策略
    strategy = MovingAverageStrategy(
        short_window=5,
        long_window=20,
        reverse_signals=False
    )
    
    # 转换为 PyBroker 适配器
    adapter = convert_strategy_to_pybroker(
        strategy=strategy,
        initial_cash=BACKTEST_CONFIG['initial_capital'],
        commission=BACKTEST_CONFIG['commission']
    )
    
    # 获取数据
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    stock_code = '600111'
    
    print(f"获取数据: {stock_code} ({start_date} 至 {end_date})")
    with DataFetcher() as fetcher:
        data = fetcher.fetch_stock_data(
            code=stock_code,
            start_date=start_date,
            end_date=end_date,
            use_mock_if_fail=True
        )
    
    if data.empty:
        print("未能获取数据")
        return
    
    print(f"数据获取成功，共 {len(data)} 条记录")
    
    # 运行 PyBroker 回测
    try:
        result = adapter.run_backtest(
            data=data,
            start_date=start_date,
            end_date=end_date,
            symbol=stock_code
        )
        print(f"PyBroker 回测完成")
        print(f"结果: {result}")
    except Exception as e:
        print(f"PyBroker 回测失败: {e}")
        logger.error(f"回测错误: {e}", exc_info=True)


def example_use_data_provider():
    """示例3: 使用数据提供者"""
    print("\n" + "="*70)
    print("示例3: 使用数据提供者")
    print("="*70)
    
    provider = PyBrokerDataProvider()
    
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    stock_code = '600111'
    
    # 获取数据
    data = provider.fetch_for_pybroker(
        code=stock_code,
        start_date=start_date,
        end_date=end_date
    )
    
    if data is not None and not data.empty:
        print(f"数据获取成功: {len(data)} 条记录")
        print(f"数据列: {data.columns.tolist()}")
        print(f"日期范围: {data.index.min()} 至 {data.index.max()}")
    else:
        print("数据获取失败")


def example_walkforward_analysis():
    """示例4: Walkforward 分析（PyBroker 高级功能）"""
    if pb is None:
        print("PyBroker 未安装，跳过此示例")
        return
    
    print("\n" + "="*70)
    print("示例4: Walkforward 分析")
    print("="*70)
    
    # 定义策略
    def ma_strategy(ctx):
        try:
            ma5 = ctx.sma('close', 5)
            ma20 = ctx.sma('close', 20)
        except AttributeError:
            data = ctx.data
            if len(data) < 20:
                return
            ma5 = data['close'].rolling(window=5, min_periods=1).mean().iloc[-1]
            ma20 = data['close'].rolling(window=20, min_periods=1).mean().iloc[-1]
        
        if ma5 > ma20 and ctx.long_positions() == 0:
            shares = int(ctx.cash / ctx.close)
            if shares > 0:
                ctx.buy_shares = shares
        elif ma5 < ma20 and ctx.long_positions() > 0:
            ctx.sell_all_shares()
    
    # Walkforward 配置
    try:
        config = pb.WalkforwardConfig(
            strategy=ma_strategy,
            symbols=['000001'],
            train_start_date='2022-01-01',
            train_end_date='2022-12-31',
            test_start_date='2023-01-01',
            test_end_date='2023-12-31',
            initial_cash=100000,
            commission=0.001,
        )
        
        # 运行 Walkforward 分析
        result = pb.run_walkforward(config)
        print(f"Walkforward 分析完成: {result}")
    except Exception as e:
        print(f"Walkforward 分析失败: {e}")
        logger.warning(f"Walkforward 功能可能不可用: {e}")


def main():
    """主函数"""
    print("\n" + "="*70)
    print("PyBroker 集成示例")
    print("="*70)
    
    # 运行示例
    try:
        # 示例2: 转换现有策略（最实用）
        example_convert_existing_strategy()
        
        # 示例3: 使用数据提供者
        example_use_data_provider()
        
        # 示例1 和 4 需要配置数据源，可能失败
        # example_basic_pybroker()
        # example_walkforward_analysis()
        
    except Exception as e:
        logger.error(f"示例运行失败: {e}", exc_info=True)
        print(f"错误: {e}")
    
    print("\n" + "="*70)
    print("示例完成")
    print("="*70)


if __name__ == '__main__':
    main()


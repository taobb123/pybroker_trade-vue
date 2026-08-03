#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PyBroker 数据源备用方案
当 AKShare 数据源无法访问时，使用项目自带的数据获取模块（支持 tushare/baostock/akshare）
"""

import sys
import os
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pybroker as pb
from pybroker import Strategy, ExecContext
from pybroker.data import DataSource
from data.fetcher import DataFetcher
import pandas as pd

print("="*70)
print("PyBroker 备用数据源方案（使用项目自带数据获取模块）")
print("="*70)

# ========== 禁用代理 ==========
os.environ.pop('HTTP_PROXY', None)
os.environ.pop('HTTPS_PROXY', None)
os.environ.pop('http_proxy', None)
os.environ.pop('https_proxy', None)

# 定义全局参数
pb.param(name='stock_code', value='600000')
pb.param(name='percent', value=1)
pb.param(name='stop_loss_pct', value=10)
pb.param(name='stop_profit_pct', value=10)

# ========== 创建自定义数据源类 ==========
class CustomDataSource(DataSource):
    """自定义数据源类，使用项目自带的数据获取模块，继承自 PyBroker 的 DataSource"""
    
    def __init__(self, fetcher: DataFetcher):
        """
        初始化数据源
        
        Args:
            fetcher: DataFetcher 实例
        """
        super().__init__()  # 调用父类初始化
        self.fetcher = fetcher
        self._cache = {}  # 缓存已获取的数据
    
    def _fetch_data(self, symbols, start_date, end_date, timeframe='', adjust=None):
        """
        获取股票数据（抽象方法实现）
        
        Args:
            symbols: 股票代码集合（frozenset）
            start_date: 开始日期（datetime）
            end_date: 结束日期（datetime）
            timeframe: 时间周期（可选）
            adjust: 复权类型（可选）
        
        Returns:
            DataFrame: 股票数据
        """
        from datetime import datetime as dt
        
        # 转换日期格式
        if isinstance(start_date, dt):
            start_date_str = start_date.strftime('%Y-%m-%d')
        else:
            start_date_str = str(start_date)
            
        if isinstance(end_date, dt):
            end_date_str = end_date.strftime('%Y-%m-%d')
        else:
            end_date_str = str(end_date)
        
        all_data = []
        
        # 处理 symbols（可能是 frozenset 或单个值）
        symbol_list = list(symbols) if hasattr(symbols, '__iter__') and not isinstance(symbols, str) else [symbols]
        
        for symbol in symbol_list:
            # 获取数据
            try:
                data = self.fetcher.fetch_stock_data(
                    code=symbol,
                    start_date=start_date_str,
                    end_date=end_date_str,
                    use_mock_if_fail=False
                )
                
                if data is None or data.empty:
                    continue
                
                # 确保日期列为 datetime 类型（但保持为列，不作为索引）
                if 'date' in data.columns:
                    data['date'] = pd.to_datetime(data['date'])
                elif data.index.name == 'date' or isinstance(data.index, pd.DatetimeIndex):
                    # 如果日期是索引，转换为列
                    data = data.reset_index()
                    if 'index' in data.columns:
                        data = data.rename(columns={'index': 'date'})
                    data['date'] = pd.to_datetime(data['date'])
                
                # 确保列名正确
                required_cols = ['date', 'open', 'high', 'low', 'close', 'volume']
                missing_cols = [col for col in required_cols if col not in data.columns]
                if missing_cols:
                    print(f"⚠ 警告: {symbol} 缺少必需的列: {missing_cols}")
                    continue
                
                # 只保留需要的列
                data = data[required_cols].copy()
                
                # 添加 symbol 列（PyBroker 需要）
                data['symbol'] = symbol
                
                all_data.append(data)
                
            except Exception as e:
                print(f"⚠ 警告: {symbol} 数据获取异常: {e}")
                continue
        
        if not all_data:
            return pd.DataFrame()
        
        # 合并所有股票的数据
        result = pd.concat(all_data, axis=0, ignore_index=True)
        
        # 确保按日期排序
        if 'date' in result.columns:
            result = result.sort_values(by=['symbol', 'date']).reset_index(drop=True)
        
        return result
    

# ========== 使用项目自带的数据获取模块 ==========
print("\n[1/3] 初始化数据获取模块...")
try:
    fetcher = DataFetcher()
    print("✓ 数据获取模块初始化成功")
    
    # 创建自定义数据源
    custom_data_source = CustomDataSource(fetcher)
    print("✓ 自定义数据源创建成功")
    
except Exception as e:
    print(f"✗ 初始化失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# ========== 定义交易策略 ==========
def buy_with_stop_loss(ctx: ExecContext):
    """交易策略：买入并设置止盈止损"""
    pos = ctx.long_pos()
    if not pos:
        # 计算目标股票数量
        ctx.buy_shares = ctx.calc_target_shares(pb.param(name='percent'))
        ctx.hold_bars = 100
    else:
        ctx.sell_shares = pos.shares
        # 设置止盈点位
        ctx.stop_profit_pct = pb.param(name='stop_profit_pct')

# ========== 创建策略并回测 ==========
try:
    print("\n[2/3] 创建策略配置...")
    my_config = pb.StrategyConfig(initial_cash=500000)
    print("✓ 策略配置创建成功")
    
    print("\n[3/3] 创建策略对象并执行回测...")
    stock_code = pb.param(name='stock_code')
    
    # 使用自定义数据源创建策略
    # Strategy 的第一个参数是数据源对象
    strategy = Strategy(custom_data_source, start_date='20200131', end_date='20230228', config=my_config)
    
    # 添加执行策略
    strategy.add_execution(fn=buy_with_stop_loss, symbols=[stock_code])
    
    # 执行回测
    result = strategy.backtest()
    print("✓ 回测完成")
    
    print("\n" + "="*70)
    print("回测结果:")
    print("="*70)
    print(result.metrics_df.round(4))
    print("="*70)
    
except Exception as e:
    print(f"✗ 回测执行失败: {e}")
    import traceback
    print("\n详细错误信息:")
    traceback.print_exc()
    sys.exit(1)


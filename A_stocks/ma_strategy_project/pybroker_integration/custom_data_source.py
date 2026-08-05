#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PyBroker 自定义数据源基类
使用项目自带的数据获取模块（支持 tushare/baostock/akshare），避免代理问题
"""

import os
import sys
from typing import Optional
import pandas as pd
from pybroker.data import DataSource

# 添加 ma_strategy_project 到路径最前（必须先于本包 config/，才能 import config.db_config）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT in sys.path:
    sys.path.remove(_PROJECT_ROOT)
sys.path.insert(0, _PROJECT_ROOT)

# 禁用代理（如果需要使用代理，请注释掉以下代码）
os.environ.pop('HTTP_PROXY', None)
os.environ.pop('HTTPS_PROXY', None)
os.environ.pop('http_proxy', None)
os.environ.pop('https_proxy', None)

# 配置 requests 库不使用代理
try:
    import requests
    session = requests.Session()
    session.trust_env = False  # 不信任环境变量中的代理设置
except ImportError:
    pass

# 导入项目自带的数据获取模块（支持多种数据源，自动切换）
from data.fetcher import DataFetcher


class CustomDataSource(DataSource):
    """
    自定义数据源类，使用项目自带的数据获取模块，继承自 PyBroker 的 DataSource
    
    该类封装了项目自带的 DataFetcher，支持多种数据源自动切换（数据库、baostock、tushare等），
    避免了直接使用 AKShare 时的代理问题。
    
    使用示例:
        from pybroker_integration.custom_data_source import create_custom_data_source
        
        # 创建数据源实例
        data_source = create_custom_data_source()
        
        # 在策略中使用
        strategy = Strategy(data_source, '20200101', '20231231', config)
    """
    
    def __init__(self, fetcher: Optional[DataFetcher] = None):
        """
        初始化数据源
        
        Args:
            fetcher: DataFetcher 实例，如果为 None 则自动创建
        """
        super().__init__()  # 调用父类初始化
        self.fetcher = fetcher if fetcher is not None else DataFetcher()
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
            DataFrame: 股票数据，包含列：date, symbol, open, high, low, close, volume
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
        
        for i, symbol in enumerate(symbol_list, 1):
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


def create_custom_data_source(fetcher: Optional[DataFetcher] = None) -> CustomDataSource:
    """
    便捷函数：创建自定义数据源实例
    
    Args:
        fetcher: DataFetcher 实例，如果为 None 则自动创建
    
    Returns:
        CustomDataSource: 自定义数据源实例
    
    使用示例:
        from pybroker_integration.custom_data_source import create_custom_data_source
        
        data_source = create_custom_data_source()
        strategy = Strategy(data_source, '20200101', '20231231', config)
    """
    return CustomDataSource(fetcher=fetcher)


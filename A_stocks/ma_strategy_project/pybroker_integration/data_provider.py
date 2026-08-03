#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PyBroker 数据提供者
将现有数据获取模块集成到 PyBroker
"""

try:
    import pybroker as pb  # type: ignore
except ImportError:
    pb = None  # type: ignore
import pandas as pd
from typing import Optional
from data.fetcher import DataFetcher
from utils.logger import logger


class PyBrokerDataProvider:
    """PyBroker 数据提供者，使用现有的 DataFetcher"""
    
    def __init__(self):
        """初始化数据提供者"""
        self.fetcher = DataFetcher()
    
    def register_akshare_source(self):
        """
        注册 AKShare 数据源到 PyBroker
        
        注意：PyBroker 原生支持 AKShare，这里提供便捷方法
        """
        try:
            # PyBroker 原生支持 AKShare
            # 使用 pb.data_source 装饰器注册
            logger.info("PyBroker 已支持 AKShare 数据源")
        except Exception as e:
            logger.warning(f"注册 AKShare 数据源失败: {e}")
    
    def fetch_for_pybroker(self, code: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """
        获取数据并转换为 PyBroker 格式
        
        Args:
            code: 股票代码（如 '000001'）
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            DataFrame: PyBroker 格式的数据（date 作为索引，包含 open, high, low, close, volume）
        """
        try:
            # 使用现有的 DataFetcher 获取数据
            data = self.fetcher.fetch_stock_data(
                code=code,
                start_date=start_date,
                end_date=end_date,
                use_mock_if_fail=False
            )
            
            if data.empty:
                logger.warning(f"未能获取数据: {code}")
                return None
            
            # 转换为 PyBroker 格式
            # PyBroker 需要 date 作为索引
            if 'date' in data.columns:
                data['date'] = pd.to_datetime(data['date'])
                data = data.set_index('date')
            
            # 确保列名正确（PyBroker 需要：open, high, low, close, volume）
            required_columns = ['open', 'high', 'low', 'close', 'volume']
            for col in required_columns:
                if col not in data.columns:
                    logger.warning(f"缺少列: {col}")
            
            # 按日期排序
            data = data.sort_index()
            
            logger.info(f"成功获取数据: {code}, 共 {len(data)} 条记录")
            return data
            
        except Exception as e:
            logger.error(f"获取数据失败: {e}")
            return None
    
    def register_custom_source(self, symbol: str):
        """
        注册自定义数据源到 PyBroker
        
        Args:
            symbol: 股票代码
        """
        @pb.data_source(symbols=[symbol])
        def custom_data_source(symbol: str, start_date: str, end_date: str):
            """自定义数据源函数"""
            return self.fetch_for_pybroker(symbol, start_date, end_date)
        
        return custom_data_source


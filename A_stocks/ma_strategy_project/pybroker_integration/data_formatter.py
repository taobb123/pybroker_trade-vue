#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PyBroker 数据格式转换工具
提供通用的数据格式转换功能，支持不同场景的数据格式需求
"""

import pandas as pd
from typing import Optional, Union, List, Tuple
from enum import Enum


class DataFormat(Enum):
    """数据格式枚举"""
    # date 作为索引，OHLCV 作为列（用于 PyBrokerDataProvider）
    INDEXED_BY_DATE = "indexed_by_date"
    
    # date 和 symbol 作为列，OHLCV 作为列（用于 IndicatorSet 和 Strategy）
    COLUMNS_WITH_SYMBOL = "columns_with_symbol"
    
    # date 作为列，OHLCV 作为列（用于单股票 IndicatorSet）
    COLUMNS_WITHOUT_SYMBOL = "columns_without_symbol"


class PyBrokerDataFormatter:
    """
    PyBroker 数据格式转换器
    
    提供统一的数据格式转换接口，支持：
    1. date 作为索引的格式（用于 PyBrokerDataProvider）
    2. date 和 symbol 作为列的格式（用于 IndicatorSet 和 Strategy）
    3. date 作为列的格式（用于单股票 IndicatorSet）
    """
    
    # 必需的 OHLCV 列
    REQUIRED_OHLCV_COLS = ['open', 'high', 'low', 'close', 'volume']
    
    def __init__(self):
        """初始化格式转换器"""
        pass
    
    @staticmethod
    def to_indexed_by_date(
        df: pd.DataFrame,
        symbol: Optional[str] = None
    ) -> pd.DataFrame:
        """
        转换为 date 作为索引的格式
        
        Args:
            df: 输入 DataFrame
            symbol: 股票代码（如果 DataFrame 中没有 symbol 列）
        
        Returns:
            DataFrame: date 作为索引，包含 open, high, low, close, volume 列
        """
        result = df.copy()
        
        # 确保 date 列存在
        if 'date' not in result.columns:
            if isinstance(result.index, pd.DatetimeIndex):
                result = result.reset_index()
                if 'index' in result.columns:
                    result = result.rename(columns={'index': 'date'})
            else:
                raise ValueError("无法确定 date 列")
        
        # 确保 date 是 datetime 类型
        result['date'] = pd.to_datetime(result['date'])
        
        # 如果有多股票数据，过滤单股票
        if 'symbol' in result.columns and symbol:
            result = result[result['symbol'] == symbol].copy()
        
        # 设置 date 为索引
        result = result.set_index('date')
        
        # 确保必需的列存在
        missing_cols = [col for col in PyBrokerDataFormatter.REQUIRED_OHLCV_COLS 
                       if col not in result.columns]
        if missing_cols:
            raise ValueError(f"缺少必需的列: {missing_cols}")
        
        # 只保留需要的列
        result = result[PyBrokerDataFormatter.REQUIRED_OHLCV_COLS].copy()
        
        # 按日期排序
        result = result.sort_index()
        
        return result
    
    @staticmethod
    def to_columns_with_symbol(
        df: pd.DataFrame,
        symbol: Optional[str] = None
    ) -> pd.DataFrame:
        """
        转换为 date 和 symbol 作为列的格式（用于 IndicatorSet 和 Strategy）
        
        Args:
            df: 输入 DataFrame
            symbol: 股票代码（如果 DataFrame 中没有 symbol 列）
        
        Returns:
            DataFrame: 包含 date, symbol, open, high, low, close, volume 列
        """
        result = df.copy()
        
        # 如果 date 是索引，重置为列
        if isinstance(result.index, pd.DatetimeIndex):
            result = result.reset_index()
            if 'index' in result.columns:
                result = result.rename(columns={'index': 'date'})
            elif result.index.name == 'date':
                # 索引名称是 'date'，重置后会自动成为列
                pass
        
        # 确保 date 列存在且为 datetime 类型
        if 'date' not in result.columns:
            raise ValueError("无法确定 date 列")
        result['date'] = pd.to_datetime(result['date'])
        
        # 确保 symbol 列存在
        if 'symbol' not in result.columns:
            if symbol:
                result['symbol'] = symbol
            else:
                raise ValueError("缺少 symbol 列且未提供 symbol 参数")
        
        # 确保必需的列存在
        required_cols = ['date', 'symbol'] + PyBrokerDataFormatter.REQUIRED_OHLCV_COLS
        missing_cols = [col for col in required_cols if col not in result.columns]
        if missing_cols:
            raise ValueError(f"缺少必需的列: {missing_cols}")
        
        # 按 symbol 和 date 排序
        result = result.sort_values(by=['symbol', 'date']).reset_index(drop=True)
        
        return result
    
    @staticmethod
    def to_columns_without_symbol(
        df: pd.DataFrame,
        symbol: Optional[str] = None
    ) -> pd.DataFrame:
        """
        转换为 date 作为列的格式（用于单股票 IndicatorSet）
        
        Args:
            df: 输入 DataFrame
            symbol: 股票代码（如果 DataFrame 中有多股票数据，用于过滤）
        
        Returns:
            DataFrame: 包含 date, open, high, low, close, volume 列
        """
        result = df.copy()
        
        # 如果 date 是索引，重置为列
        if isinstance(result.index, pd.DatetimeIndex):
            result = result.reset_index()
            if 'index' in result.columns:
                result = result.rename(columns={'index': 'date'})
        
        # 确保 date 列存在且为 datetime 类型
        if 'date' not in result.columns:
            raise ValueError("无法确定 date 列")
        result['date'] = pd.to_datetime(result['date'])
        
        # 如果有多股票数据，过滤单股票
        if 'symbol' in result.columns:
            if symbol:
                result = result[result['symbol'] == symbol].copy()
            else:
                # 如果只有一个股票，使用第一个
                symbols = result['symbol'].unique()
                if len(symbols) == 1:
                    result = result[result['symbol'] == symbols[0]].copy()
                else:
                    raise ValueError("DataFrame 包含多股票数据，请提供 symbol 参数")
            # 删除 symbol 列
            result = result.drop(columns=['symbol'])
        
        # 确保必需的列存在
        required_cols = ['date'] + PyBrokerDataFormatter.REQUIRED_OHLCV_COLS
        missing_cols = [col for col in required_cols if col not in result.columns]
        if missing_cols:
            raise ValueError(f"缺少必需的列: {missing_cols}")
        
        # 按 date 排序
        result = result.sort_values(by='date').reset_index(drop=True)
        
        return result
    
    @staticmethod
    def convert(
        df: pd.DataFrame,
        target_format: DataFormat,
        symbol: Optional[str] = None
    ) -> pd.DataFrame:
        """
        通用格式转换方法
        
        Args:
            df: 输入 DataFrame
            target_format: 目标格式
            symbol: 股票代码（可选）
        
        Returns:
            DataFrame: 转换后的 DataFrame
        """
        if target_format == DataFormat.INDEXED_BY_DATE:
            return PyBrokerDataFormatter.to_indexed_by_date(df, symbol)
        elif target_format == DataFormat.COLUMNS_WITH_SYMBOL:
            return PyBrokerDataFormatter.to_columns_with_symbol(df, symbol)
        elif target_format == DataFormat.COLUMNS_WITHOUT_SYMBOL:
            return PyBrokerDataFormatter.to_columns_without_symbol(df, symbol)
        else:
            raise ValueError(f"不支持的目标格式: {target_format}")
    
    @staticmethod
    def create_bar_data(df: pd.DataFrame) -> object:
        """
        创建 BarData 对象（用于单个指标计算）
        
        Args:
            df: DataFrame，date 作为索引或列
        
        Returns:
            BarData: 包含 date, open, high, low, close, volume 属性的对象
        """
        # 确保 date 是索引格式
        if 'date' in df.columns:
            df_for_bar = df.set_index('date')
        else:
            df_for_bar = df.copy()
        
        # 确保索引是 DatetimeIndex
        if not isinstance(df_for_bar.index, pd.DatetimeIndex):
            df_for_bar.index = pd.to_datetime(df_for_bar.index)
        
        class BarData:
            def __init__(self, df):
                # 确保必需的列存在且为 numpy 数组
                required_cols = ['open', 'high', 'low', 'close', 'volume']
                for col in required_cols:
                    if col in df.columns:
                        setattr(self, col, df[col].values)
                    else:
                        raise ValueError(f"数据中缺少 '{col}' 列")
                
                # pybroker indicator 需要 date 属性
                if isinstance(df.index, pd.DatetimeIndex):
                    self.date = df.index
                else:
                    self.date = pd.to_datetime(df.index)
        
        return BarData(df_for_bar)
    
    @staticmethod
    def validate_format(
        df: pd.DataFrame,
        required_format: DataFormat,
        symbol: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        验证 DataFrame 是否符合指定格式
        
        Args:
            df: 要验证的 DataFrame
            required_format: 要求的格式
            symbol: 股票代码（可选）
        
        Returns:
            tuple: (是否有效, 错误信息)
        """
        try:
            if required_format == DataFormat.INDEXED_BY_DATE:
                # 检查索引是否为 DatetimeIndex
                if not isinstance(df.index, pd.DatetimeIndex):
                    return False, "索引必须是 DatetimeIndex"
                # 检查必需的列
                missing = [col for col in PyBrokerDataFormatter.REQUIRED_OHLCV_COLS 
                          if col not in df.columns]
                if missing:
                    return False, f"缺少必需的列: {missing}"
            
            elif required_format == DataFormat.COLUMNS_WITH_SYMBOL:
                # 检查必需的列
                required = ['date', 'symbol'] + PyBrokerDataFormatter.REQUIRED_OHLCV_COLS
                missing = [col for col in required if col not in df.columns]
                if missing:
                    return False, f"缺少必需的列: {missing}"
                # 检查 date 是否为 datetime 类型
                if not pd.api.types.is_datetime64_any_dtype(df['date']):
                    return False, "date 列必须是 datetime 类型"
            
            elif required_format == DataFormat.COLUMNS_WITHOUT_SYMBOL:
                # 检查必需的列
                required = ['date'] + PyBrokerDataFormatter.REQUIRED_OHLCV_COLS
                missing = [col for col in required if col not in df.columns]
                if missing:
                    return False, f"缺少必需的列: {missing}"
                # 检查 date 是否为 datetime 类型
                if not pd.api.types.is_datetime64_any_dtype(df['date']):
                    return False, "date 列必须是 datetime 类型"
            
            return True, None
            
        except Exception as e:
            return False, str(e)


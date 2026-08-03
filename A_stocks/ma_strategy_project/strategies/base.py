#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略基类
所有策略都应继承此类
"""

import pandas as pd
from abc import ABC, abstractmethod
try:
    from ..utils.logger import logger  # type: ignore
except Exception:  # pragma: no cover
    from utils.logger import logger  # type: ignore


class BaseStrategy(ABC):
    """策略基类（抽象类）"""
    
    def __init__(self, name: str = "BaseStrategy"):
        """
        初始化策略
        
        Args:
            name: 策略名称
        """
        self.name = name
        self.logger = logger
    
    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        生成交易信号（抽象方法，必须由子类实现）
        
        Args:
            data: 包含date, open, high, low, close, volume列的DataFrame
        
        Returns:
            DataFrame: 原始数据 + signal列
            signal列值：1=买入信号, -1=卖出信号, 0=无信号/持有
        """
        pass
    
    def validate_data(self, data: pd.DataFrame) -> bool:
        """
        验证数据格式是否正确
        
        Args:
            data: 待验证的DataFrame
        
        Returns:
            bool: 数据格式是否正确
        """
        required_columns = ['date', 'open', 'high', 'low', 'close', 'volume']
        
        if data is None or data.empty:
            self.logger.error("数据为空")
            return False
        
        for col in required_columns:
            if col not in data.columns:
                self.logger.error(f"缺少必需列: {col}")
                return False
        
        # 检查数据是否包含NaN
        if data[required_columns].isnull().any().any():
            self.logger.warning("数据中包含NaN值")
        
        return True
    
    def calculate_returns(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        计算收益率（辅助方法）
        
        Args:
            data: 包含close列的DataFrame
        
        Returns:
            DataFrame: 添加了returns列
        """
        if 'close' not in data.columns:
            return data
        
        data = data.copy()
        data['returns'] = data['close'].pct_change()
        return data




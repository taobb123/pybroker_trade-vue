#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易策略模块
存放不同的交易策略实现
"""

# 延迟导入，避免在模块级别触发路径问题
# 使用 __getattr__ 实现延迟导入
def __getattr__(name):
    if name == 'TrendRotationStrategy':
        from .trend_rotation_strategy import TrendRotationStrategy
        return TrendRotationStrategy
    elif name == 'MeanReversionRotationStrategy':
        from .mean_reversion_rotation_strategy import MeanReversionRotationStrategy
        return MeanReversionRotationStrategy
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

__all__ = [
    'TrendRotationStrategy',
    'MeanReversionRotationStrategy',
]

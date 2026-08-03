#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
技术指标模块
提供MACD、RSI、成交量、均值回归等指标的定义
"""

import pybroker as pyb
import talib as ta
import numpy as np


def create_macd_indicators(fastperiod=12, slowperiod=26, signalperiod=9):
    """
    创建MACD相关指标
    
    Args:
        fastperiod: 快速EMA周期，默认12
        slowperiod: 慢速EMA周期，默认26
        signalperiod: 信号线周期，默认9
    
    Returns:
        tuple: (macd_indicator, macd_signal_indicator, macd_hist_indicator)
    """
    def macd_func(data):
        """计算MACD线"""
        macd, signal, hist = ta.MACD(
            data.close,
            fastperiod=fastperiod,
            slowperiod=slowperiod,
            signalperiod=signalperiod
        )
        return macd
    
    def macd_signal_func(data):
        """计算MACD信号线"""
        macd, signal, hist = ta.MACD(
            data.close,
            fastperiod=fastperiod,
            slowperiod=slowperiod,
            signalperiod=signalperiod
        )
        return signal
    
    def macd_hist_func(data):
        """计算MACD柱状图（MACD - Signal）"""
        macd, signal, hist = ta.MACD(
            data.close,
            fastperiod=fastperiod,
            slowperiod=slowperiod,
            signalperiod=signalperiod
        )
        return hist
    
    macd_indicator = pyb.indicator(
        f'macd_{fastperiod}_{slowperiod}_{signalperiod}',
        macd_func
    )
    
    macd_signal_indicator = pyb.indicator(
        f'macd_signal_{fastperiod}_{slowperiod}_{signalperiod}',
        macd_signal_func
    )
    
    macd_hist_indicator = pyb.indicator(
        f'macd_hist_{fastperiod}_{slowperiod}_{signalperiod}',
        macd_hist_func
    )
    
    return macd_indicator, macd_signal_indicator, macd_hist_indicator


def create_rsi_indicator(timeperiod=14):
    """
    创建RSI指标
    
    Args:
        timeperiod: RSI周期，默认14
    
    Returns:
        pybroker.Indicator: RSI指标
    """
    def rsi_func(data):
        """计算RSI"""
        return ta.RSI(data.close, timeperiod=timeperiod)
    
    rsi_indicator = pyb.indicator(f'rsi_{timeperiod}', rsi_func)
    return rsi_indicator


def create_volume_indicators(period=20):
    """
    创建成交量相关指标
    
    Args:
        period: 成交量均线周期，默认20
    
    Returns:
        tuple: (volume_ma_indicator, volume_ratio_indicator)
            - volume_ma: 成交量移动平均
            - volume_ratio: 当前成交量与均量的比值
    """
    def volume_ma_func(data):
        """计算成交量移动平均"""
        return ta.SMA(data.volume, timeperiod=period)
    
    def volume_ratio_func(data):
        """计算成交量比率（当前成交量 / 成交量均线）"""
        volume_ma = ta.SMA(data.volume, timeperiod=period)
        # 避免除零
        volume_ratio = np.where(
            volume_ma > 0,
            data.volume / volume_ma,
            np.nan
        )
        return volume_ratio
    
    volume_ma_indicator = pyb.indicator(
        f'volume_ma_{period}',
        volume_ma_func
    )
    
    volume_ratio_indicator = pyb.indicator(
        f'volume_ratio_{period}',
        volume_ratio_func
    )
    
    return volume_ma_indicator, volume_ratio_indicator


def create_mean_reversion_indicators(period=20):
    """
    创建均值回归相关指标
    
    Args:
        period: 计算周期，默认20
    
    Returns:
        tuple: (zscore_indicator, bollinger_bands_indicator)
            - zscore: Z分数（价格偏离均值的标准差倍数）
            - bollinger_bands: 布林带指标（上轨、中轨、下轨）
    """
    def zscore_func(data):
        """计算Z分数（价格偏离均值的标准差倍数）"""
        close = data.close
        ma = ta.SMA(close, timeperiod=period)
        std = ta.STDDEV(close, timeperiod=period)
        # 避免除零
        zscore = np.where(
            std > 0,
            (close - ma) / std,
            np.nan
        )
        return zscore
    
    def bollinger_upper_func(data):
        """计算布林带上轨"""
        upper, middle, lower = ta.BBANDS(
            data.close,
            timeperiod=period,
            nbdevup=2,
            nbdevdn=2,
            matype=0
        )
        return upper
    
    def bollinger_middle_func(data):
        """计算布林带中轨"""
        upper, middle, lower = ta.BBANDS(
            data.close,
            timeperiod=period,
            nbdevup=2,
            nbdevdn=2,
            matype=0
        )
        return middle
    
    def bollinger_lower_func(data):
        """计算布林带下轨"""
        upper, middle, lower = ta.BBANDS(
            data.close,
            timeperiod=period,
            nbdevup=2,
            nbdevdn=2,
            matype=0
        )
        return lower
    
    zscore_indicator = pyb.indicator(f'zscore_{period}', zscore_func)
    bollinger_upper_indicator = pyb.indicator(f'bb_upper_{period}', bollinger_upper_func)
    bollinger_middle_indicator = pyb.indicator(f'bb_middle_{period}', bollinger_middle_func)
    bollinger_lower_indicator = pyb.indicator(f'bb_lower_{period}', bollinger_lower_func)
    
    return (
        zscore_indicator,
        bollinger_upper_indicator,
        bollinger_middle_indicator,
        bollinger_lower_indicator
    )


# 默认参数创建指标（用于策略）
# 趋势策略指标
MACD_INDICATOR, MACD_SIGNAL_INDICATOR, MACD_HIST_INDICATOR = create_macd_indicators()
RSI_INDICATOR = create_rsi_indicator(timeperiod=14)
VOLUME_MA_INDICATOR, VOLUME_RATIO_INDICATOR = create_volume_indicators(period=20)

# 均值回归策略指标
ZSCORE_INDICATOR, BB_UPPER_INDICATOR, BB_MIDDLE_INDICATOR, BB_LOWER_INDICATOR = create_mean_reversion_indicators(period=20)

# 所有趋势策略指标的集合
TREND_INDICATORS = [
    MACD_INDICATOR,
    MACD_SIGNAL_INDICATOR,
    MACD_HIST_INDICATOR,
    RSI_INDICATOR,
    VOLUME_MA_INDICATOR,
    VOLUME_RATIO_INDICATOR,
]

# 所有均值回归策略指标的集合
MEAN_REVERSION_INDICATORS = [
    ZSCORE_INDICATOR,
    BB_UPPER_INDICATOR,
    BB_MIDDLE_INDICATOR,
    BB_LOWER_INDICATOR,
]


def create_roc_indicator(timeperiod=20):
    """
    创建ROC（Rate of Change，价格变化率）指标
    用于计算过去N天的收益率
    
    Args:
        timeperiod: ROC周期，默认20
    
    Returns:
        pybroker.Indicator: ROC指标
    """
    def roc_func(data):
        """计算ROC（收益率）"""
        return ta.ROC(data.close, timeperiod=timeperiod)
    
    roc_indicator = pyb.indicator(f'roc_{timeperiod}', roc_func)
    return roc_indicator


def create_cmma_indicator(timeperiod=20):
    """
    创建CMMA（Close Minus Moving Average，收盘价减去移动平均线）指标
    用于判断价格是否低于移动平均线
    
    Args:
        timeperiod: 移动平均线周期，默认20
    
    Returns:
        pybroker.Indicator: CMMA指标
    """
    def cmma_func(data):
        """计算CMMA（收盘价 - 移动平均线）"""
        ma = ta.SMA(data.close, timeperiod=timeperiod)
        return data.close - ma
    
    cmma_indicator = pyb.indicator(f'cmma_{timeperiod}', cmma_func)
    return cmma_indicator


# ROC指标（用于排名）
ROC_20_INDICATOR = create_roc_indicator(timeperiod=20)

# CMMA指标（用于均值回归/趋势策略的价格相对均线过滤）
CMMA_20_INDICATOR = create_cmma_indicator(timeperiod=20)
# 将 CMMA 指标加入均值回归和趋势指标集合
MEAN_REVERSION_INDICATORS.append(CMMA_20_INDICATOR)
TREND_INDICATORS.append(CMMA_20_INDICATOR)


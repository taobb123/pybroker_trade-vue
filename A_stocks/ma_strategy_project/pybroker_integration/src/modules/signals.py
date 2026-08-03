#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
信号生成模块
提供基于技术指标的综合评分信号生成
"""

import numpy as np
from typing import Dict, Optional


def calculate_trend_score(
    macd: float,
    macd_signal: float,
    macd_hist: float,
    rsi: float,
    volume_ratio: float,
    macd_weight: float = 0.3,
    rsi_weight: float = 0.3,
    volume_weight: float = 0.4
) -> float:
    """
    计算趋势策略的综合评分
    
    评分逻辑：
    - MACD: MACD线在信号线上方为正分，柱状图为正为正分
    - RSI: RSI在50-70之间为正分，超过70为负分（超买）
    - 成交量: 成交量比率大于1为正分
    
    Args:
        macd: MACD值
        macd_signal: MACD信号线值
        macd_hist: MACD柱状图值
        rsi: RSI值
        volume_ratio: 成交量比率
        macd_weight: MACD权重，默认0.3
        rsi_weight: RSI权重，默认0.3
        volume_weight: 成交量权重，默认0.4
    
    Returns:
        float: 综合评分（越高越好）
    """
    # 检查是否有NaN值
    if any(np.isnan([macd, macd_signal, macd_hist, rsi, volume_ratio])):
        return 0.0
    
    # MACD评分：MACD > Signal 为正，MACD柱状图为正为正
    macd_score = 0.0
    if macd > macd_signal:
        macd_score += 0.5
    if macd_hist > 0:
        macd_score += 0.5
    
    # RSI评分：50-70为最佳区间
    if 50 <= rsi <= 70:
        rsi_score = 1.0
    elif 30 <= rsi < 50:
        rsi_score = 0.5  # 偏弱但可接受
    elif 70 < rsi <= 80:
        rsi_score = 0.3  # 超买，但仍有上涨空间
    elif rsi > 80:
        rsi_score = -0.5  # 严重超买
    elif rsi < 30:
        rsi_score = 0.2  # 超卖，可能反弹
    else:
        rsi_score = 0.0
    
    # 成交量评分：成交量比率大于1为正
    if volume_ratio > 1.5:
        volume_score = 1.0  # 成交量显著放大
    elif volume_ratio > 1.2:
        volume_score = 0.8  # 成交量适度放大
    elif volume_ratio > 1.0:
        volume_score = 0.5  # 成交量略增
    elif volume_ratio > 0.8:
        volume_score = 0.2  # 成交量略减
    else:
        volume_score = 0.0  # 成交量萎缩
    
    # 加权综合评分
    total_score = (
        macd_score * macd_weight +
        rsi_score * rsi_weight +
        volume_score * volume_weight
    )
    
    return total_score


def calculate_mean_reversion_score(
    zscore: float,
    close: float,
    bb_upper: float,
    bb_middle: float,
    bb_lower: float,
    zscore_weight: float = 0.6,
    bollinger_weight: float = 0.4
) -> float:
    """
    计算均值回归策略的综合评分
    
    评分逻辑：
    - Z分数: 负值越大（价格越低）评分越高（买入机会）
    - 布林带: 价格接近下轨时评分高，接近上轨时评分低
    
    Args:
        zscore: Z分数（价格偏离均值的标准差倍数）
        close: 当前收盘价
        bb_upper: 布林带上轨
        bb_middle: 布林带中轨
        bb_lower: 布林带下轨
        zscore_weight: Z分数权重，默认0.6
        bollinger_weight: 布林带权重，默认0.4
    
    Returns:
        float: 综合评分（越高越好，表示买入机会）
    """
    # 检查是否有NaN值
    if any(np.isnan([zscore, close, bb_upper, bb_middle, bb_lower])):
        return 0.0
    
    # Z分数评分：负值越大（价格越低）评分越高
    # Z分数在-2到0之间为最佳买入区间
    if zscore <= -2.0:
        zscore_normalized = 1.0  # 严重超卖，最佳买入机会
    elif zscore <= -1.5:
        zscore_normalized = 0.8
    elif zscore <= -1.0:
        zscore_normalized = 0.6
    elif zscore <= -0.5:
        zscore_normalized = 0.4
    elif zscore <= 0:
        zscore_normalized = 0.2
    else:
        zscore_normalized = 0.0  # 价格高于均值，不是买入机会
    
    # 布林带评分：价格接近下轨时评分高
    if bb_upper != bb_lower:
        # 计算价格在布林带中的位置（0=下轨，1=上轨）
        bb_position = (close - bb_lower) / (bb_upper - bb_lower)
        # 位置越低（接近下轨）评分越高
        bb_score = 1.0 - bb_position
        # 限制在0-1之间
        bb_score = max(0.0, min(1.0, bb_score))
    else:
        bb_score = 0.0
    
    # 加权综合评分
    total_score = (
        zscore_normalized * zscore_weight +
        bb_score * bollinger_weight
    )
    
    return total_score


def rank_stocks_by_score(
    scores: Dict[str, float],
    top_n: int = 5
) -> list:
    """
    根据评分对股票进行排名，返回前N名
    
    Args:
        scores: 股票代码到评分的字典
        top_n: 返回前N名，默认5
    
    Returns:
        list: 前N名股票代码列表（按评分从高到低）
    """
    # 过滤掉评分为0或NaN的股票
    valid_scores = {
        symbol: score
        for symbol, score in scores.items()
        if score is not None and not np.isnan(score) and score > 0
    }
    
    if not valid_scores:
        return []
    
    # 按评分排序
    sorted_stocks = sorted(
        valid_scores.items(),
        key=lambda x: x[1],
        reverse=True
    )
    
    # 返回前N名
    top_stocks = [symbol for symbol, score in sorted_stocks[:top_n]]
    
    return top_stocks


def check_trend_buy_signal(
    macd: float,
    macd_signal: float,
    macd_hist: float,
    rsi: float,
    volume_ratio: float
) -> bool:
    """
    检查趋势策略的买入信号
    
    买入条件：
    - MACD线在信号线上方 或 MACD柱状图为正
    - RSI在合理区间（30-80）
    - 成交量比率大于0.8（有一定成交量）
    
    Args:
        macd: MACD值
        macd_signal: MACD信号线值
        macd_hist: MACD柱状图值
        rsi: RSI值
        volume_ratio: 成交量比率
    
    Returns:
        bool: 是否产生买入信号
    """
    # 检查是否有NaN值
    if any(np.isnan([macd, macd_signal, macd_hist, rsi, volume_ratio])):
        return False
    
    # MACD条件：MACD > Signal 或 MACD柱状图为正
    macd_condition = (macd > macd_signal) or (macd_hist > 0)
    
    # RSI条件：在合理区间（30-80）
    rsi_condition = 30 <= rsi <= 80
    
    # 成交量条件：成交量比率大于0.8
    volume_condition = volume_ratio > 0.8
    
    # 所有条件都满足才买入
    return macd_condition and rsi_condition and volume_condition


def check_trend_sell_signal(
    macd: float,
    macd_signal: float,
    macd_hist: float,
    rsi: float
) -> bool:
    """
    检查趋势策略的卖出信号
    
    卖出条件：
    - MACD线在信号线下方 且 MACD柱状图为负
    - 或 RSI严重超买（>80）或严重超卖（<30）
    
    Args:
        macd: MACD值
        macd_signal: MACD信号线值
        macd_hist: MACD柱状图值
        rsi: RSI值
    
    Returns:
        bool: 是否产生卖出信号
    """
    # 检查是否有NaN值
    if any(np.isnan([macd, macd_signal, macd_hist, rsi])):
        return False
    
    # MACD条件：MACD < Signal 且 MACD柱状图为负
    macd_condition = (macd < macd_signal) and (macd_hist < 0)
    
    # RSI条件：严重超买或超卖
    rsi_condition = (rsi > 80) or (rsi < 30)
    
    # 任一条件满足就卖出
    return macd_condition or rsi_condition


def check_mean_reversion_buy_signal(
    zscore: float,
    close: float,
    bb_upper: float,
    bb_lower: float,
    cmma: float = None
) -> bool:
    """
    检查均值回归策略的买入信号
    
    买入条件：
    - Z分数为负（价格低于均值）
    - 价格接近或低于布林带下轨
    - CMMA小于0（收盘价低于20日移动平均线）
    
    Args:
        zscore: Z分数（价格偏离均值的标准差倍数）
        close: 当前收盘价
        bb_upper: 布林带上轨
        bb_lower: 布林带下轨
        cmma: CMMA值（收盘价减去移动平均线），可选
    
    Returns:
        bool: 是否产生买入信号
    """
    # 检查是否有NaN值
    check_values = [zscore, close, bb_upper, bb_lower]
    if cmma is not None:
        check_values.append(cmma)
    if any(np.isnan(check_values)):
        return False
    
    # Z分数条件：为负（价格低于均值）
    zscore_condition = zscore < 0
    
    # 布林带条件：价格接近或低于下轨（在布林带下轨附近或以下）
    if bb_upper != bb_lower:
        # 计算价格在布林带中的位置
        bb_position = (close - bb_lower) / (bb_upper - bb_lower)
        # 位置在0.3以下（接近下轨）为买入信号
        bb_condition = bb_position < 0.3
    else:
        bb_condition = False
    
    # CMMA条件：CMMA小于0（收盘价低于20日移动平均线）
    cmma_condition = True  # 如果未提供CMMA，默认满足条件（向后兼容）
    if cmma is not None:
        cmma_condition = cmma < 0
    
    # 所有条件都满足才买入
    return zscore_condition and bb_condition and cmma_condition


def check_mean_reversion_sell_signal(
    zscore: float,
    close: float,
    bb_upper: float,
    bb_lower: float
) -> bool:
    """
    检查均值回归策略的卖出信号
    
    卖出条件：
    - Z分数为正且较大（价格高于均值较多，回归完成）
    - 价格接近或高于布林带上轨
    
    Args:
        zscore: Z分数（价格偏离均值的标准差倍数）
        close: 当前收盘价
        bb_upper: 布林带上轨
        bb_lower: 布林带下轨
    
    Returns:
        bool: 是否产生卖出信号
    """
    # 检查是否有NaN值
    if any(np.isnan([zscore, close, bb_upper, bb_lower])):
        return False
    
    # Z分数条件：为正且较大（价格高于均值，回归完成）
    zscore_condition = zscore > 1.0
    
    # 布林带条件：价格接近或高于上轨
    if bb_upper != bb_lower:
        # 计算价格在布林带中的位置
        bb_position = (close - bb_lower) / (bb_upper - bb_lower)
        # 位置在0.7以上（接近上轨）为卖出信号
        bb_condition = bb_position > 0.7
    else:
        bb_condition = False
    
    # 任一条件满足就卖出
    return zscore_condition or bb_condition


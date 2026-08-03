#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
财务指标计算工具
计算估值指标和综合得分
"""

from typing import Dict, Optional

try:
    from ..data.financial_fetcher import FinancialDataFetcher
except Exception:
    from data.financial_fetcher import FinancialDataFetcher


def calculate_valuation_metrics(financial_data: Dict, current_price: float = None, 
                                 total_market_value: float = None) -> Dict:
    """
    计算估值指标
    
    Args:
        financial_data: 财务数据字典（来自FinancialDataFetcher）
        current_price: 当前股价（可选，用于计算总市值）
        total_market_value: 总市值（可选，如果提供则直接使用）
    
    Returns:
        估值指标字典，包含：
        - pe_ratio: 市盈率
        - pb_ratio: 市净率
        - comprehensive_score: 综合得分
    """
    metrics = {
        'pe_ratio': None,
        'pb_ratio': None,
        'comprehensive_score': None,
    }
    
    if not financial_data:
        return metrics
    
    # 提取财务数据
    net_profit = financial_data.get('net_profit')  # 净利润（元）
    net_assets = financial_data.get('net_assets')  # 净资产（元）
    total_shares = financial_data.get('total_shares')  # 总股本（万股）
    roe = financial_data.get('roe')  # ROE（%）
    eps = financial_data.get('eps')  # 每股收益（元）
    bps = financial_data.get('bps')  # 每股净资产（元）
    
    # 计算总市值（多种方法）
    if total_market_value is None and current_price is not None:
        # 方法1: 如果有总股本和当前价格
        if total_shares is not None:
            # 总市值 = 当前价格 × 总股本（万股转换为股）
            total_market_value = current_price * total_shares * 10000  # 万股转股
        # 方法2: 通过每股收益反推总股本，再计算总市值
        elif eps is not None and net_profit is not None and eps > 0 and net_profit > 0:
            # 总股本（股）= 净利润 / 每股收益
            total_shares_shares = net_profit / eps
            total_market_value = current_price * total_shares_shares
        # 方法3: 通过每股净资产和净资产反推总股本，再计算总市值
        elif bps is not None and net_assets is not None and bps > 0 and net_assets > 0:
            # 总股本（股）= 净资产 / 每股净资产
            total_shares_shares = net_assets / bps
            total_market_value = current_price * total_shares_shares
    
    # 计算市盈率（PE），保留两位小数
    if total_market_value is not None and net_profit is not None and net_profit > 0:
        metrics['pe_ratio'] = round(total_market_value / net_profit, 2)
    
    # 计算市净率（PB），保留两位小数
    if current_price is not None:
        # 方法1: 直接使用净资产计算（如果有总市值）
        if total_market_value is not None and net_assets is not None and net_assets > 0:
            metrics['pb_ratio'] = round(total_market_value / net_assets, 2)
        # 方法2: 通过每股净资产和当前价格计算（最直接的方法）
        elif bps is not None and bps > 0:
            # PB = 当前价格 / 每股净资产
            metrics['pb_ratio'] = round(current_price / bps, 2)
    
    # 计算综合得分
    metrics['comprehensive_score'] = calculate_comprehensive_score(
        pe_ratio=metrics['pe_ratio'],
        pb_ratio=metrics['pb_ratio'],
        net_profit=net_profit,
        roe=roe
    )
    
    return metrics


def calculate_comprehensive_score(pe_ratio: Optional[float] = None,
                                 pb_ratio: Optional[float] = None,
                                 net_profit: Optional[float] = None,
                                 roe: Optional[float] = None) -> Optional[float]:
    """
    计算综合得分
    
    公式：
    综合得分 = (1/PE × 60% + 1/PB × 40%) + 盈利加分
    盈利加分：有净利润 +0.2，ROE>10% 再+0.2
    
    Args:
        pe_ratio: 市盈率
        pb_ratio: 市净率
        net_profit: 净利润（元）
        roe: ROE（%）
    
    Returns:
        综合得分（浮点数），如果数据不足返回None
    """
    score = 0.0
    valid_components = 0
    
    # PE得分（60%权重）
    if pe_ratio is not None and pe_ratio > 0 and pe_ratio < 1000:  # 过滤异常值
        # 归一化：1/PE，PE越小得分越高
        # 假设PE范围在5-50之间，归一化到0-1
        # PE=5时得分最高(0.2)，PE=50时得分最低(0.004)
        # 归一化公式：当PE在[5,50]区间，得分在[1, 0.1]区间
        if pe_ratio <= 5:
            pe_normalized = 1.0  # PE很低，满分
        elif pe_ratio >= 50:
            pe_normalized = 0.1  # PE很高，最低分
        else:
            # 线性插值：PE从5到50，得分从1到0.1
            pe_normalized = 1.0 - (pe_ratio - 5) / 50 * 0.9
        score += pe_normalized * 0.6
        valid_components += 1
    
    # PB得分（40%权重）
    if pb_ratio is not None and pb_ratio > 0 and pb_ratio < 20:  # 过滤异常值
        # 归一化：1/PB，PB越小得分越高
        # 假设PB范围在0.5-5之间，归一化到0-1
        # PB=0.5时得分最高(2.0)，PB=5时得分最低(0.2)
        if pb_ratio <= 0.5:
            pb_normalized = 1.0  # PB很低，满分
        elif pb_ratio >= 5:
            pb_normalized = 0.1  # PB很高，最低分
        else:
            # 线性插值：PB从0.5到5，得分从1到0.1
            pb_normalized = 1.0 - (pb_ratio - 0.5) / 4.5 * 0.9
        score += pb_normalized * 0.4
        valid_components += 1
    
    # 盈利加分
    profit_bonus = 0.0
    if net_profit is not None and net_profit > 0:
        profit_bonus += 0.2
    
    if roe is not None and roe > 10:
        profit_bonus += 0.2
    
    score += profit_bonus
    
    # 如果没有任何有效数据，返回None
    if valid_components == 0 and profit_bonus == 0:
        return None
    
    return round(score, 2)  # 保留两位小数


def get_financial_display_data(stock_code: str, current_price: float = None,
                               total_market_value: float = None) -> Dict:
    """
    获取财务数据并计算所有显示指标
    
    Args:
        stock_code: 股票代码
        current_price: 当前股价（可选）
        total_market_value: 总市值（可选）
    
    Returns:
        包含所有显示指标的字典：
        - net_profit_yi: 净利润（亿元）
        - roe: ROE（%）
        - profit_margin: 净利润率（%）
        - pe_ratio: 市盈率
        - pb_ratio: 市净率
        - comprehensive_score: 综合得分
        - data_available: 数据是否可用
    """
    display_data = {
        'net_profit_yi': None,
        'roe': None,
        'profit_margin': None,
        'pe_ratio': None,
        'pb_ratio': None,
        'comprehensive_score': None,
        'data_available': False,
    }
    
    try:
        # 性能优化：使用上下文管理器，确保快速获取
        # 减少重试次数和延迟，优先使用缓存
        with FinancialDataFetcher() as fetcher:
            # 优化：减少重试次数，加快响应速度
            financial_data = fetcher.get_financial_data(stock_code, retry=1)
            
            if not financial_data:
                return display_data
            
            display_data['data_available'] = True
            
            # 净利润（转换为亿元）
            net_profit = financial_data.get('net_profit')
            if net_profit is not None:
                display_data['net_profit_yi'] = net_profit / 1e8  # 转换为亿元
            
            # ROE
            display_data['roe'] = financial_data.get('roe')
            
            # 净利润率
            display_data['profit_margin'] = financial_data.get('profit_margin')
            
            # 计算估值指标
            valuation = calculate_valuation_metrics(
                financial_data=financial_data,
                current_price=current_price,
                total_market_value=total_market_value
            )
            
            display_data['pe_ratio'] = valuation['pe_ratio']
            display_data['pb_ratio'] = valuation['pb_ratio']
            display_data['comprehensive_score'] = valuation['comprehensive_score']
            
    except Exception as e:
        # 静默处理错误，返回未填充的数据
        pass
    
    return display_data


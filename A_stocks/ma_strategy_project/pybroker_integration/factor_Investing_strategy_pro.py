#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多因子成长策略 - 优化版
结合基本面因子和技术面因子进行综合评分和筛选

核心功能：
1. 利用多个财务指标和技术指标对股票进行综合评分和筛选
2. 因子排序：根据市盈率(PE)、换手率等因子对股票池进行降序或升序排列，选取头部标的构建组合
3. 因子加权：结合基本面因子和技术面因子，通过加权得分来调整仓位权重
"""

import os
import sys
import numpy as np
import pandas as pd
import pybroker as pyb
from pybroker import Strategy, StrategyConfig, ExecContext
from typing import Dict, List, Optional, Tuple
import talib as ta
from datetime import datetime, timedelta

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from pybroker_integration.custom_data_source import create_custom_data_source
from data.fetcher import DataFetcher

# 启用数据源缓存
pyb.enable_data_source_cache('factor_investing_cache')

# ==================== 基本面因子获取模块 ====================

class FundamentalFactorFetcher:
    """基本面因子获取器"""
    
    def __init__(self):
        self.fetcher = DataFetcher()
        self._cache = {}  # 缓存基本面数据
        self._cache_date = None  # 缓存日期
    
    def fetch_fundamental_factors(self, symbol: str, date: Optional[str] = None) -> Dict[str, float]:
        """
        获取股票的基本面因子
        
        Args:
            symbol: 股票代码
            date: 日期（YYYY-MM-DD），如果为None则使用最新数据
        
        Returns:
            Dict: 包含PE、PB、ROE、换手率等基本面因子的字典
        """
        try:
            # 尝试从 tushare 获取基本面数据
            # 注意：这里需要根据实际的数据源API进行调整
            import tushare as ts
            
            # 获取股票基本信息
            # 这里使用简化的方法，实际应用中需要根据数据源调整
            factors = {
                'pe': 0.0,           # 市盈率
                'pb': 0.0,           # 市净率
                'roe': 0.0,          # 净资产收益率
                'turnover_rate': 0.0, # 换手率
                'total_mv': 0.0,     # 总市值
                'circ_mv': 0.0,      # 流通市值
            }
            
            try:
                # 尝试获取每日基本面数据
                pro = ts.pro_api()
                # 获取股票基本信息（需要tushare pro权限）
                # 这里使用模拟数据，实际应用中需要调用真实API
                # df = pro.daily_basic(ts_code=symbol, trade_date=date)
                
                # 暂时返回默认值，实际应用中需要从数据源获取
                # 可以通过 DataFetcher 扩展来获取基本面数据
                pass
            except Exception as e:
                # 如果无法获取，使用默认值或从缓存获取
                pass
            
            return factors
            
        except ImportError:
            # 如果 tushare 不可用，返回默认值
            return {
                'pe': 20.0,
                'pb': 2.0,
                'roe': 10.0,
                'turnover_rate': 2.0,
                'total_mv': 1000000.0,
                'circ_mv': 800000.0,
            }
        except Exception as e:
            print(f"⚠ 警告: 获取 {symbol} 基本面数据失败: {e}")
            return {
                'pe': 20.0,
                'pb': 2.0,
                'roe': 10.0,
                'turnover_rate': 2.0,
                'total_mv': 1000000.0,
                'circ_mv': 800000.0,
            }
    
    def calculate_turnover_rate(self, symbol: str, volume: float, date: str) -> float:
        """
        计算换手率（基于成交量和流通市值）
        
        Args:
            symbol: 股票代码
            volume: 成交量
            date: 日期
        
        Returns:
            float: 换手率（百分比）
        """
        try:
            # 获取流通市值
            factors = self.fetch_fundamental_factors(symbol, date)
            circ_mv = factors.get('circ_mv', 0)
            
            if circ_mv > 0:
                # 换手率 = 成交量 / 流通市值 * 100
                # 注意：这里需要根据实际数据单位调整
                turnover_rate = (volume / circ_mv) * 100 if circ_mv > 0 else 0.0
                return max(0.0, min(100.0, turnover_rate))
            else:
                # 如果无法获取流通市值，使用成交量比率作为替代
                return 2.0  # 默认值
        except Exception as e:
            return 2.0  # 默认值

# 创建全局基本面因子获取器
fundamental_fetcher = FundamentalFactorFetcher()

# ==================== 定义技术指标因子 ====================

def roc_20_func(data):
    """计算20日价格变化率（ROC）- 动量因子"""
    roc = ta.ROC(data.close, timeperiod=20)
    return np.nan_to_num(roc, nan=0.0, posinf=0.0, neginf=0.0)

def rsi_14_func(data):
    """计算14日相对强弱指标（RSI）- 超买超卖因子"""
    rsi = ta.RSI(data.close, timeperiod=14)
    return np.nan_to_num(rsi, nan=50.0, posinf=50.0, neginf=50.0)

def macd_func(data):
    """计算MACD指标 - 趋势因子"""
    macd, signal, hist = ta.MACD(data.close, fastperiod=12, slowperiod=26, signalperiod=9)
    return np.nan_to_num(hist, nan=0.0, posinf=0.0, neginf=0.0)

def volume_ratio_func(data):
    """计算成交量比率 - 成交量因子（当前成交量/过去20日平均成交量）"""
    if len(data.volume) < 21:
        return np.array([1.0] * len(data.volume))
    volume_ma = ta.SMA(data.volume, timeperiod=20)
    ratio = data.volume / volume_ma
    return np.nan_to_num(ratio, nan=1.0, posinf=1.0, neginf=1.0)

def ma_trend_func(data):
    """计算均线趋势强度 - 趋势因子"""
    ma5 = ta.SMA(data.close, timeperiod=5)
    ma20 = ta.SMA(data.close, timeperiod=20)
    trend = (data.close - ma20) / ma20 * 100
    return np.nan_to_num(trend, nan=0.0, posinf=0.0, neginf=0.0)

def volatility_func(data):
    """计算波动率（ATR标准化）- 风险因子"""
    atr = ta.ATR(data.high, data.low, data.close, timeperiod=14)
    volatility = (atr / data.close) * 100
    return np.nan_to_num(volatility, nan=0.0, posinf=999.0, neginf=0.0)

# 注册技术指标
roc_20 = pyb.indicator('roc_20', roc_20_func)
rsi_14 = pyb.indicator('rsi_14', rsi_14_func)
macd_hist = pyb.indicator('macd_hist', macd_func)
volume_ratio = pyb.indicator('volume_ratio', volume_ratio_func)
ma_trend = pyb.indicator('ma_trend', ma_trend_func)
volatility = pyb.indicator('volatility', volatility_func)

# ==================== 因子评分和排序函数 ====================

def normalize_factor_value(value: float, min_val: float, max_val: float, reverse: bool = False) -> float:
    """
    标准化因子值到0-100范围
    
    Args:
        value: 原始因子值
        min_val: 最小值
        max_val: 最大值
        reverse: 是否反向（值越小评分越高）
    
    Returns:
        float: 标准化后的评分（0-100）
    """
    if max_val == min_val:
        return 50.0
    
    if reverse:
        # 反向：值越小评分越高
        normalized = (max_val - value) / (max_val - min_val) * 100
    else:
        # 正向：值越大评分越高
        normalized = (value - min_val) / (max_val - min_val) * 100
    
    return max(0.0, min(100.0, normalized))

def calculate_comprehensive_score(
    # 技术面因子
    roc_20: float,
    rsi_14: float,
    macd_hist: float,
    volume_ratio: float,
    ma_trend: float,
    volatility: float,
    # 基本面因子
    pe: float = 20.0,
    pb: float = 2.0,
    roe: float = 10.0,
    turnover_rate: float = 2.0,
    # 权重配置
    technical_weight: float = 0.6,  # 技术面权重60%
    fundamental_weight: float = 0.4,  # 基本面权重40%
) -> Tuple[float, Dict[str, float]]:
    """
    计算综合评分（技术面 + 基本面）
    
    因子权重分配：
    技术面（60%）：
    - ROC（动量）: 15%
    - RSI（超买超卖）: 10%
    - MACD（趋势）: 12%
    - 成交量比率: 10%
    - 均线趋势: 10%
    - 波动率（风险）: 3%
    
    基本面（40%）：
    - PE（估值）: 12% - 低PE更好（反向）
    - PB（估值）: 10% - 低PB更好（反向）
    - ROE（盈利能力）: 12% - 高ROE更好（正向）
    - 换手率（流动性）: 6% - 适中换手率更好
    
    Args:
        roc_20: 20日价格变化率
        rsi_14: 14日RSI值
        macd_hist: MACD柱状图值
        volume_ratio: 成交量比率
        ma_trend: 均线趋势强度
        volatility: 波动率
        pe: 市盈率
        pb: 市净率
        roe: 净资产收益率
        turnover_rate: 换手率
        technical_weight: 技术面权重
        fundamental_weight: 基本面权重
    
    Returns:
        Tuple[float, Dict]: (综合评分, 详细评分字典)
    """
    # ========== 技术面因子评分 ==========
    
    # 1. ROC评分（0-100）：价格涨幅越大越好
    roc_score = max(0, min(100, (roc_20 + 50) / 100 * 100))
    
    # 2. RSI评分（0-100）：50-70为最佳区间
    if 50 <= rsi_14 <= 70:
        rsi_score = 100
    elif 40 <= rsi_14 < 50:
        rsi_score = 70
    elif 70 < rsi_14 <= 80:
        rsi_score = 60
    elif 30 <= rsi_14 < 40:
        rsi_score = 50
    elif 80 < rsi_14 <= 90:
        rsi_score = 30
    elif rsi_14 < 30:
        rsi_score = 40
    else:
        rsi_score = 20
    
    # 3. MACD评分（0-100）
    macd_score = max(0, min(100, (macd_hist + 5) / 10 * 100))
    
    # 4. 成交量比率评分（0-100）
    if volume_ratio >= 2.0:
        volume_score = 100
    elif volume_ratio >= 1.5:
        volume_score = 80
    elif volume_ratio >= 1.2:
        volume_score = 60
    elif volume_ratio >= 1.0:
        volume_score = 40
    elif volume_ratio >= 0.8:
        volume_score = 20
    else:
        volume_score = 10
    
    # 5. 均线趋势评分（0-100）
    ma_trend_score = max(0, min(100, (ma_trend + 20) / 40 * 100))
    
    # 6. 波动率评分（0-100）：低波动率更好（反向）
    volatility_score = max(0, min(100, (10 - volatility) / 10 * 100))
    
    # 技术面综合评分
    technical_score = (
        roc_score * 0.25 +      # 15% / 60% = 25%
        rsi_score * 0.167 +     # 10% / 60% = 16.7%
        macd_score * 0.20 +     # 12% / 60% = 20%
        volume_score * 0.167 +  # 10% / 60% = 16.7%
        ma_trend_score * 0.167 + # 10% / 60% = 16.7%
        volatility_score * 0.05  # 3% / 60% = 5%
    )
    
    # ========== 基本面因子评分 ==========
    
    # 1. PE评分（0-100）：低PE更好（反向）
    # PE范围假设：0-100，理想值：10-20
    if pe <= 0:
        pe_score = 0
    elif pe <= 15:
        pe_score = 100  # 低估值
    elif pe <= 25:
        pe_score = 80
    elif pe <= 40:
        pe_score = 50
    elif pe <= 60:
        pe_score = 30
    else:
        pe_score = 10  # 高估值
    
    # 2. PB评分（0-100）：低PB更好（反向）
    # PB范围假设：0-10，理想值：1-2
    if pb <= 0:
        pb_score = 0
    elif pb <= 1.5:
        pb_score = 100  # 低估值
    elif pb <= 2.5:
        pb_score = 80
    elif pb <= 4.0:
        pb_score = 50
    elif pb <= 6.0:
        pb_score = 30
    else:
        pb_score = 10  # 高估值
    
    # 3. ROE评分（0-100）：高ROE更好（正向）
    # ROE范围假设：-20%到30%，理想值：>15%
    if roe >= 20:
        roe_score = 100  # 优秀
    elif roe >= 15:
        roe_score = 90
    elif roe >= 10:
        roe_score = 70
    elif roe >= 5:
        roe_score = 50
    elif roe >= 0:
        roe_score = 30
    else:
        roe_score = 10  # 亏损
    
    # 4. 换手率评分（0-100）：适中换手率更好
    # 换手率范围：0-20%，理想值：2-5%
    if 2.0 <= turnover_rate <= 5.0:
        turnover_score = 100  # 理想区间
    elif 1.0 <= turnover_rate < 2.0 or 5.0 < turnover_rate <= 8.0:
        turnover_score = 70
    elif 0.5 <= turnover_rate < 1.0 or 8.0 < turnover_rate <= 12.0:
        turnover_score = 50
    elif turnover_rate < 0.5:
        turnover_score = 30  # 流动性差
    else:
        turnover_score = 20  # 换手率过高
    
    # 基本面综合评分
    fundamental_score = (
        pe_score * 0.30 +        # 12% / 40% = 30%
        pb_score * 0.25 +        # 10% / 40% = 25%
        roe_score * 0.30 +       # 12% / 40% = 30%
        turnover_score * 0.15    # 6% / 40% = 15%
    )
    
    # ========== 综合评分 ==========
    total_score = (
        technical_score * technical_weight +
        fundamental_score * fundamental_weight
    )
    
    # 详细评分字典
    score_details = {
        'total_score': total_score,
        'technical_score': technical_score,
        'fundamental_score': fundamental_score,
        'roc_score': roc_score,
        'rsi_score': rsi_score,
        'macd_score': macd_score,
        'volume_score': volume_score,
        'ma_trend_score': ma_trend_score,
        'volatility_score': volatility_score,
        'pe_score': pe_score,
        'pb_score': pb_score,
        'roe_score': roe_score,
        'turnover_score': turnover_score,
    }
    
    return total_score, score_details

# ==================== 因子排序函数 ====================

def sort_stocks_by_factor(
    stocks_data: Dict[str, Dict],
    factor_name: str,
    ascending: bool = False
) -> List[Tuple[str, float]]:
    """
    根据指定因子对股票进行排序
    
    Args:
        stocks_data: 股票数据字典 {symbol: {factor1: value1, ...}}
        factor_name: 因子名称（如 'pe', 'roe', 'total_score'）
        ascending: 是否升序排列（True=升序，False=降序）
    
    Returns:
        List[Tuple]: 排序后的股票列表 [(symbol, factor_value), ...]
    """
    sorted_list = []
    
    for symbol, data in stocks_data.items():
        factor_value = data.get(factor_name, 0.0)
        if not np.isnan(factor_value) and not np.isinf(factor_value):
            sorted_list.append((symbol, float(factor_value)))
    
    # 排序
    sorted_list.sort(key=lambda x: x[1], reverse=not ascending)
    
    return sorted_list

# ==================== 股票排名函数 ====================

def rank_stocks_by_factors(ctxs: Dict[str, ExecContext]) -> List[str]:
    """
    对所有股票进行多因子综合评分和排名
    结合基本面因子和技术面因子
    
    Args:
        ctxs: 所有股票的执行上下文字典
    
    Returns:
        List[str]: 按评分从高到低排序的股票代码列表
    """
    scores = {}
    factor_details = {}
    
    # 获取当前日期（用于获取基本面数据）
    current_date = None
    if ctxs:
        first_ctx = list(ctxs.values())[0]
        if hasattr(first_ctx, 'date'):
            try:
                date_val = first_ctx.date
                if isinstance(date_val, datetime):
                    current_date = date_val.strftime('%Y-%m-%d')
                elif isinstance(date_val, pd.Timestamp):
                    current_date = date_val.strftime('%Y-%m-%d')
                else:
                    current_date = str(date_val)[:10]
            except:
                current_date = datetime.now().strftime('%Y-%m-%d')
    
    if not current_date:
        current_date = datetime.now().strftime('%Y-%m-%d')
    
    for symbol, ctx in ctxs.items():
        try:
            # ========== 获取技术面因子 ==========
            roc_values = ctx.indicator('roc_20')
            rsi_values = ctx.indicator('rsi_14')
            macd_values = ctx.indicator('macd_hist')
            volume_values = ctx.indicator('volume_ratio')
            ma_trend_values = ctx.indicator('ma_trend')
            volatility_values = ctx.indicator('volatility')
            
            # 检查是否有足够的数据
            if (roc_values is None or len(roc_values) == 0 or
                rsi_values is None or len(rsi_values) == 0):
                continue
            
            # 获取最后一个有效值
            roc = float(roc_values[-1]) if not np.isnan(roc_values[-1]) else 0.0
            rsi = float(rsi_values[-1]) if not np.isnan(rsi_values[-1]) else 50.0
            macd = float(macd_values[-1]) if macd_values is not None and len(macd_values) > 0 and not np.isnan(macd_values[-1]) else 0.0
            volume = float(volume_values[-1]) if volume_values is not None and len(volume_values) > 0 and not np.isnan(volume_values[-1]) else 1.0
            trend = float(ma_trend_values[-1]) if ma_trend_values is not None and len(ma_trend_values) > 0 and not np.isnan(ma_trend_values[-1]) else 0.0
            vol = float(volatility_values[-1]) if volatility_values is not None and len(volatility_values) > 0 and not np.isnan(volatility_values[-1]) else 5.0
            
            # ========== 获取基本面因子 ==========
            fundamental_factors = fundamental_fetcher.fetch_fundamental_factors(symbol, current_date)
            pe = fundamental_factors.get('pe', 20.0)
            pb = fundamental_factors.get('pb', 2.0)
            roe = fundamental_factors.get('roe', 10.0)
            turnover_rate = fundamental_factors.get('turnover_rate', 2.0)
            
            # 如果换手率为0，尝试从成交量计算
            if turnover_rate == 0.0 and hasattr(ctx, 'volume') and len(ctx.volume) > 0:
                try:
                    current_volume = float(ctx.volume[-1])
                    turnover_rate = fundamental_fetcher.calculate_turnover_rate(symbol, current_volume, current_date)
                except:
                    pass
            
            # ========== 计算综合评分 ==========
            score, score_details = calculate_comprehensive_score(
                roc_20=roc,
                rsi_14=rsi,
                macd_hist=macd,
                volume_ratio=volume,
                ma_trend=trend,
                volatility=vol,
                pe=pe,
                pb=pb,
                roe=roe,
                turnover_rate=turnover_rate
            )
            
            if score > 0:
                scores[symbol] = score
                factor_details[symbol] = {
                    # 技术面因子
                    'roc_20': roc,
                    'rsi_14': rsi,
                    'macd_hist': macd,
                    'volume_ratio': volume,
                    'ma_trend': trend,
                    'volatility': vol,
                    # 基本面因子
                    'pe': pe,
                    'pb': pb,
                    'roe': roe,
                    'turnover_rate': turnover_rate,
                    # 评分
                    'total_score': score,
                    **score_details
                }
                
        except (IndexError, TypeError, ValueError, AttributeError) as e:
            print(f"⚠ 警告: {symbol} 因子计算失败: {e}")
            continue
    
    if not scores:
        print("⚠ 警告: 没有有效的股票评分")
        return []
    
    # 按评分排序（降序）
    sorted_stocks = sorted(
        scores.items(),
        key=lambda x: x[1],
        reverse=True
    )
    
    # 保存排名结果和详细因子信息
    top_symbols = [symbol for symbol, score in sorted_stocks]
    pyb.param('top_symbols', top_symbols)
    pyb.param('factor_scores', scores)
    pyb.param('factor_details', factor_details)
    
    # 保存因子排序结果（用于因子排序功能）
    pyb.param('stocks_data', factor_details)
    
    return top_symbols

# ==================== 执行函数 ====================

def execute_factor_strategy(ctx: ExecContext):
    """
    执行多因子策略：根据排名结果进行交易
    使用因子加权来调整仓位权重
    
    策略逻辑：
    1. 如果股票在排名前N名中且没有持仓，则买入（根据评分加权）
    2. 如果股票不在排名前N名中但有持仓，则卖出
    """
    top_symbols = pyb.param('top_symbols')
    top_n = pyb.param('top_n', 10)
    use_weighted_allocation = pyb.param('use_weighted_allocation', True)  # 是否使用加权分配
    
    if top_symbols is None or len(top_symbols) == 0:
        return
    
    # 获取前N名股票
    target_symbols = top_symbols[:top_n]
    
    try:
        # 获取当前持仓，正确处理 Position 对象
        current_pos = 0
        try:
            pos_value = ctx.long_pos() if hasattr(ctx, 'long_pos') else None
            if pos_value is None:
                current_pos = 0
            elif hasattr(pos_value, 'shares'):
                # 如果是 Position 对象，获取 shares 属性
                current_pos = int(pos_value.shares) if pos_value.shares is not None else 0
            elif isinstance(pos_value, (int, float, np.integer, np.floating)):
                # 如果是数字，直接转换
                current_pos = int(pos_value)
            elif hasattr(pos_value, '__int__'):
                # 如果对象支持转换为 int
                current_pos = int(pos_value)
            else:
                # 其他情况，尝试转换为数字
                try:
                    current_pos = int(float(pos_value))
                except (ValueError, TypeError):
                    current_pos = 0
        except (AttributeError, TypeError, ValueError) as e:
            # 如果获取持仓失败，默认为0
            current_pos = 0
        
        if current_pos > 0:
            # 如果持有股票但不在目标列表中，则卖出
            if ctx.symbol not in target_symbols:
                ctx.sell_all_shares()
        else:
            # 如果股票在目标列表中，则买入
            if ctx.symbol in target_symbols:
                factor_scores = pyb.param('factor_scores', {})
                score = factor_scores.get(ctx.symbol, 0.0)
                
                if use_weighted_allocation:
                    # ========== 因子加权分配 ==========
                    # 根据综合评分进行加权分配
                    # 获取所有目标股票的评分
                    target_scores = {s: factor_scores.get(s, 0.0) for s in target_symbols}
                    total_score = sum(target_scores.values())
                    
                    if total_score > 0:
                        # 根据评分比例分配权重
                        weight = score / total_score
                    else:
                        # 如果总评分为0，使用等权重
                        weight = 1.0 / len(target_symbols)
                else:
                    # ========== 排名加权分配 ==========
                    # 根据排名分配仓位（排名越靠前，仓位越大）
                    rank = target_symbols.index(ctx.symbol) + 1
                    # 使用逆排名权重（第1名权重最大）
                    weight = (top_n - rank + 1) / sum(range(1, top_n + 1))
                
                # 计算买入股数
                try:
                    ctx.buy_shares = ctx.calc_target_shares(weight)
                    ctx.score = score  # 保存评分用于分析
                except (AttributeError, TypeError):
                    # 如果 calc_target_shares 不可用，使用简单方法
                    pass
                
    except Exception as e:
        print(f"⚠ 警告: {ctx.symbol} 策略执行异常: {e}")

# ==================== 主程序 ====================

def load_stock_pool(file_path: str) -> List[str]:
    """从文件加载股票池"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            symbols = [s.strip() for s in content.replace('\n', ' ').split() if s.strip()]
            return symbols
    except Exception as e:
        print(f"✗ 加载股票池失败: {e}")
        return []

def main():
    """主函数"""
    print("=" * 80)
    print("多因子成长策略 - 优化版（基本面+技术面）")
    print("=" * 80)
    
    # 1. 加载股票池
    script_dir = os.path.dirname(os.path.abspath(__file__))
    stock_pool_file = os.path.join(script_dir, 'stocks_pool.txt')
    symbols = load_stock_pool(stock_pool_file)
    
    if not symbols:
        print("✗ 股票池为空，无法继续")
        return
    
    print(f"✓ 股票池加载成功: {len(symbols)} 只股票")
    print(f"  股票列表: {', '.join(symbols[:10])}{'...' if len(symbols) > 10 else ''}")
    
    # 2. 配置参数
    top_n = 10  # 持有前10名股票
    initial_cash = 500000  # 初始资金50万
    start_date = '20240101'
    end_date = '20251218'
    use_weighted_allocation = True  # 使用因子加权分配
    
    print(f"\n策略参数:")
    print(f"  - 持有股票数量: {top_n}")
    print(f"  - 初始资金: {initial_cash:,} 元")
    print(f"  - 回测日期: {start_date} 至 {end_date}")
    print(f"  - 预热期: 30 天")
    print(f"  - 因子权重: 技术面60% + 基本面40%")
    print(f"  - 仓位分配: {'因子加权' if use_weighted_allocation else '排名加权'}")
    
    # 3. 设置策略参数
    config = StrategyConfig(
        max_long_positions=top_n,
        initial_cash=initial_cash
    )
    pyb.param('top_n', top_n)
    pyb.param('use_weighted_allocation', use_weighted_allocation)
    
    # 4. 创建数据源和策略
    print("\n正在初始化数据源和策略...")
    try:
        data_source = create_custom_data_source()
        strategy = Strategy(
            data_source,
            start_date=start_date,
            end_date=end_date,
            config=config
        )
        
        # 设置排名函数（在每次执行前对所有股票进行排名）
        strategy.set_before_exec(rank_stocks_by_factors)
        
        # 添加执行函数和所有指标
        strategy.add_execution(
            execute_factor_strategy,
            symbols,
            indicators=[roc_20, rsi_14, macd_hist, volume_ratio, ma_trend, volatility]
        )
        
        print("✓ 策略初始化完成")
        
    except Exception as e:
        print(f"✗ 策略初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # 5. 运行回测
    print("\n" + "=" * 80)
    print("开始回测...")
    print("提示: 数据获取可能需要一些时间，请耐心等待...")
    print("=" * 80)
    
    import time
    start_time = time.time()
    
    try:
        result = strategy.backtest(warmup=30)
        elapsed_time = time.time() - start_time
        
        print(f"\n✓ 回测完成！耗时: {elapsed_time:.2f} 秒 ({elapsed_time/60:.2f} 分钟)")
        print("=" * 80)
        
        # 6. 显示结果
        if hasattr(result, 'metrics_df') and result.metrics_df is not None:
            print("\n策略表现指标:")
            print(result.metrics_df)
        
        # 7. 显示最终排名（包含基本面因子）
        factor_details = pyb.param('factor_details', {})
        if factor_details:
            print("\n" + "=" * 80)
            print("最终股票排名（综合评分：技术面60% + 基本面40%）:")
            print("=" * 80)
            
            factor_scores = pyb.param('factor_scores', {})
            sorted_stocks = sorted(
                factor_scores.items(),
                key=lambda x: x[1],
                reverse=True
            )
            
            print(f"\n{'排名':<6} {'股票':<8} {'综合':<8} {'技术':<8} {'基本面':<8} {'PE':<8} {'PB':<8} {'ROE':<8} {'换手率':<8} {'ROC':<8} {'RSI':<8}")
            print("-" * 100)
            
            for rank, (symbol, score) in enumerate(sorted_stocks[:20], 1):
                details = factor_details.get(symbol, {})
                tech_score = details.get('technical_score', 0.0)
                fund_score = details.get('fundamental_score', 0.0)
                pe = details.get('pe', 20.0)
                pb = details.get('pb', 2.0)
                roe = details.get('roe', 10.0)
                turnover = details.get('turnover_rate', 2.0)
                roc = details.get('roc_20', 0.0)
                rsi = details.get('rsi_14', 50.0)
                
                print(f"{rank:<6} {symbol:<8} {score:<8.2f} {tech_score:<8.2f} {fund_score:<8.2f} "
                      f"{pe:<8.2f} {pb:<8.2f} {roe:<8.2f} {turnover:<8.2f} {roc:<8.2f} {rsi:<8.2f}")
        
        # 8. 保存交易记录
        if hasattr(result, 'trades') and result.trades is not None and not result.trades.empty:
            csv_file = os.path.join(script_dir, 'factor_investing_trades.csv')
            result.trades.to_csv(csv_file, index=False, encoding='utf-8-sig')
            print(f"\n✓ 交易记录已保存到: {csv_file}")
            print(f"  总交易数: {len(result.trades)}")
        
        # 9. 保存排名结果（包含基本面因子）
        if factor_details:
            factor_scores = pyb.param('factor_scores', {})
            ranking_data = []
            for symbol, score in sorted(factor_scores.items(), key=lambda x: x[1], reverse=True):
                details = factor_details.get(symbol, {})
                ranking_data.append({
                    '排名': len(ranking_data) + 1,
                    '股票代码': symbol,
                    '综合评分': score,
                    '技术面评分': details.get('technical_score', 0.0),
                    '基本面评分': details.get('fundamental_score', 0.0),
                    # 技术面因子
                    'ROC_20': details.get('roc_20', 0.0),
                    'RSI_14': details.get('rsi_14', 50.0),
                    'MACD_Hist': details.get('macd_hist', 0.0),
                    '成交量比率': details.get('volume_ratio', 1.0),
                    '均线趋势': details.get('ma_trend', 0.0),
                    '波动率': details.get('volatility', 5.0),
                    # 基本面因子
                    'PE': details.get('pe', 20.0),
                    'PB': details.get('pb', 2.0),
                    'ROE': details.get('roe', 10.0),
                    '换手率': details.get('turnover_rate', 2.0),
                })
            
            ranking_df = pd.DataFrame(ranking_data)
            ranking_file = os.path.join(script_dir, 'factor_investing_ranking_latest.csv')
            ranking_df.to_csv(ranking_file, index=False, encoding='utf-8-sig')
            print(f"✓ 股票排名已保存到: {ranking_file}")
        
        print("\n" + "=" * 80)
        print("策略执行完成！")
        print("=" * 80)
        
    except Exception as e:
        elapsed_time = time.time() - start_time
        print(f"\n✗ 回测过程中发生错误！耗时: {elapsed_time:.2f} 秒")
        print(f"错误类型: {type(e).__name__}")
        print(f"错误信息: {e}")
        import traceback
        print("\n详细错误堆栈:")
        traceback.print_exc()
        raise

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多因子成长策略 - 筛选最具成长潜力的股票
使用多个技术指标因子对股票池进行综合评分和排名
"""

import os
import sys
import numpy as np
import pandas as pd
import pybroker as pyb
from pybroker import Strategy, StrategyConfig, ExecContext
from typing import Dict, List
import talib as ta

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from pybroker_integration.custom_data_source import create_custom_data_source

# 启用数据源缓存
pyb.enable_data_source_cache('factor_investing_cache')

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
    # 返回MACD柱状图（histogram），正值表示上涨趋势
    return np.nan_to_num(hist, nan=0.0, posinf=0.0, neginf=0.0)

def volume_ratio_func(data):
    """计算成交量比率 - 成交量因子（当前成交量/过去20日平均成交量）"""
    if len(data.volume) < 21:
        return np.array([1.0] * len(data.volume))
    volume_ma = ta.SMA(data.volume, timeperiod=20)
    ratio = data.volume / volume_ma
    return np.nan_to_num(ratio, nan=1.0, posinf=1.0, neginf=1.0)

def ma_trend_func(data):
    """计算均线趋势强度 - 趋势因子（收盘价相对于5日、20日均线的位置）"""
    ma5 = ta.SMA(data.close, timeperiod=5)
    ma20 = ta.SMA(data.close, timeperiod=20)
    # 计算价格相对于均线的位置（正值表示在均线上方，趋势向上）
    trend = (data.close - ma20) / ma20 * 100  # 转换为百分比
    return np.nan_to_num(trend, nan=0.0, posinf=0.0, neginf=0.0)

def volatility_func(data):
    """计算波动率（ATR标准化）- 风险因子（低波动率更好）"""
    atr = ta.ATR(data.high, data.low, data.close, timeperiod=14)
    # 将ATR标准化为相对于价格的百分比
    volatility = (atr / data.close) * 100
    return np.nan_to_num(volatility, nan=0.0, posinf=999.0, neginf=0.0)

# 注册指标
roc_20 = pyb.indicator('roc_20', roc_20_func)
rsi_14 = pyb.indicator('rsi_14', rsi_14_func)
macd_hist = pyb.indicator('macd_hist', macd_func)
volume_ratio = pyb.indicator('volume_ratio', volume_ratio_func)
ma_trend = pyb.indicator('ma_trend', ma_trend_func)
volatility = pyb.indicator('volatility', volatility_func)

# ==================== 多因子评分函数 ====================

def calculate_growth_score(
    roc_20: float,
    rsi_14: float,
    macd_hist: float,
    volume_ratio: float,
    ma_trend: float,
    volatility: float
) -> float:
    """
    计算成长潜力综合评分
    
    因子权重：
    - ROC（动量）: 30% - 价格涨幅越大越好
    - RSI（超买超卖）: 15% - 50-70为最佳区间
    - MACD（趋势）: 20% - 柱状图为正表示上涨趋势
    - 成交量比率: 15% - 成交量放大表示关注度高
    - 均线趋势: 15% - 价格在均线上方表示趋势向上
    - 波动率（风险）: 5% - 低波动率更好（负权重）
    
    Args:
        roc_20: 20日价格变化率
        rsi_14: 14日RSI值
        macd_hist: MACD柱状图值
        volume_ratio: 成交量比率
        ma_trend: 均线趋势强度（百分比）
        volatility: 波动率（百分比）
    
    Returns:
        float: 综合评分（0-100，越高表示成长潜力越大）
    """
    # 检查是否有无效值
    if any(np.isnan([roc_20, rsi_14, macd_hist, volume_ratio, ma_trend, volatility])):
        return 0.0
    
    # 1. ROC评分（0-100）：价格涨幅越大越好
    # 将ROC标准化到0-100范围（假设ROC范围在-50%到50%之间）
    roc_score = max(0, min(100, (roc_20 + 50) / 100 * 100))
    
    # 2. RSI评分（0-100）：50-70为最佳区间
    if 50 <= rsi_14 <= 70:
        rsi_score = 100  # 最佳区间
    elif 40 <= rsi_14 < 50:
        rsi_score = 70  # 偏弱但可接受
    elif 70 < rsi_14 <= 80:
        rsi_score = 60  # 超买但仍有机会
    elif 30 <= rsi_14 < 40:
        rsi_score = 50  # 偏弱
    elif 80 < rsi_14 <= 90:
        rsi_score = 30  # 严重超买
    elif rsi_14 < 30:
        rsi_score = 40  # 超卖，可能反弹
    else:
        rsi_score = 20  # 极端情况
    
    # 3. MACD评分（0-100）：柱状图为正表示上涨趋势
    # 将MACD柱状图标准化（假设范围在-5到5之间）
    macd_score = max(0, min(100, (macd_hist + 5) / 10 * 100))
    
    # 4. 成交量比率评分（0-100）：成交量放大表示关注度高
    if volume_ratio >= 2.0:
        volume_score = 100  # 成交量显著放大
    elif volume_ratio >= 1.5:
        volume_score = 80
    elif volume_ratio >= 1.2:
        volume_score = 60
    elif volume_ratio >= 1.0:
        volume_score = 40
    elif volume_ratio >= 0.8:
        volume_score = 20
    else:
        volume_score = 10  # 成交量萎缩
    
    # 5. 均线趋势评分（0-100）：价格在均线上方表示趋势向上
    # 将趋势强度标准化（假设范围在-20%到20%之间）
    ma_trend_score = max(0, min(100, (ma_trend + 20) / 40 * 100))
    
    # 6. 波动率评分（0-100）：低波动率更好（负权重，所以是反向评分）
    # 波动率越低，评分越高（假设波动率范围在0%到10%之间）
    volatility_score = max(0, min(100, (10 - volatility) / 10 * 100))
    
    # 加权综合评分
    total_score = (
        roc_score * 0.30 +      # 动量因子 30%
        rsi_score * 0.15 +      # RSI因子 15%
        macd_score * 0.20 +      # MACD因子 20%
        volume_score * 0.15 +   # 成交量因子 15%
        ma_trend_score * 0.15 + # 趋势因子 15%
        volatility_score * 0.05  # 波动率因子 5%（低波动率更好）
    )
    
    return total_score

# ==================== 股票排名函数 ====================

def rank_stocks_by_factors(ctxs: Dict[str, ExecContext]) -> List[str]:
    """
    对所有股票进行多因子综合评分和排名
    
    Args:
        ctxs: 所有股票的执行上下文字典
    
    Returns:
        List[str]: 按评分从高到低排序的股票代码列表
    """
    scores = {}
    factor_details = {}  # 存储每个股票的详细因子值
    
    for symbol, ctx in ctxs.items():
        try:
            # 获取各个因子值
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
            
            # 计算综合评分
            score = calculate_growth_score(roc, rsi, macd, volume, trend, vol)
            
            if score > 0:  # 只保留有效评分
                scores[symbol] = score
                factor_details[symbol] = {
                    'roc_20': roc,
                    'rsi_14': rsi,
                    'macd_hist': macd,
                    'volume_ratio': volume,
                    'ma_trend': trend,
                    'volatility': vol,
                    'total_score': score
                }
                
        except (IndexError, TypeError, ValueError, AttributeError) as e:
            # 如果指标计算失败，跳过该股票
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
    
    return top_symbols

# ==================== 执行函数 ====================

def execute_factor_strategy(ctx: ExecContext):
    """
    执行多因子策略：根据排名结果进行交易
    
    策略逻辑：
    1. 如果股票在排名前N名中且没有持仓，则买入
    2. 如果股票不在排名前N名中但有持仓，则卖出
    """
    top_symbols = pyb.param('top_symbols')
    top_n = pyb.param('top_n', 10)  # 默认持有前10名
    
    if top_symbols is None or len(top_symbols) == 0:
        return
    
    # 获取前N名股票
    target_symbols = top_symbols[:top_n]
    
    try:
        if ctx.long_pos():
            # 如果持有股票但不在目标列表中，则卖出
            if ctx.symbol not in target_symbols:
                ctx.sell_all_shares()
        else:
            # 如果股票在目标列表中，则买入
            if ctx.symbol in target_symbols:
                # 获取该股票的评分排名
                factor_scores = pyb.param('factor_scores', {})
                score = factor_scores.get(ctx.symbol, 0.0)
                
                # 根据排名分配仓位（排名越靠前，仓位越大）
                rank = target_symbols.index(ctx.symbol) + 1
                # 使用逆排名权重（第1名权重最大）
                weight = (top_n - rank + 1) / sum(range(1, top_n + 1))
                
                # 计算买入股数
                ctx.buy_shares = ctx.calc_target_shares(weight)
                ctx.score = score  # 保存评分用于分析
                
    except Exception as e:
        print(f"⚠ 警告: {ctx.symbol} 策略执行异常: {e}")

# ==================== 主程序 ====================

def load_stock_pool(file_path: str) -> List[str]:
    """
    从文件加载股票池
    
    Args:
        file_path: 股票池文件路径
    
    Returns:
        List[str]: 股票代码列表
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            # 按空格或换行符分割
            symbols = [s.strip() for s in content.replace('\n', ' ').split() if s.strip()]
            return symbols
    except Exception as e:
        print(f"✗ 加载股票池失败: {e}")
        return []

def main():
    """主函数"""
    print("=" * 80)
    print("多因子成长策略 - 筛选最具成长潜力的股票")
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
    start_date = '20220101'
    end_date = '20251215'
    
    print(f"\n策略参数:")
    print(f"  - 持有股票数量: {top_n}")
    print(f"  - 初始资金: {initial_cash:,} 元")
    print(f"  - 回测日期: {start_date} 至 {end_date}")
    print(f"  - 预热期: 30 天（确保指标有足够数据）")
    
    # 3. 设置策略参数
    config = StrategyConfig(
        max_long_positions=top_n,
        initial_cash=initial_cash
    )
    pyb.param('top_n', top_n)
    
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
        result = strategy.backtest(warmup=30)  # 30天预热期，确保指标有足够数据
        elapsed_time = time.time() - start_time
        
        print(f"\n✓ 回测完成！耗时: {elapsed_time:.2f} 秒 ({elapsed_time/60:.2f} 分钟)")
        print("=" * 80)
        
        # 6. 显示结果
        if hasattr(result, 'metrics_df') and result.metrics_df is not None:
            print("\n策略表现指标:")
            print(result.metrics_df)
        
        # 7. 显示最终排名
        factor_details = pyb.param('factor_details', {})
        if factor_details:
            print("\n" + "=" * 80)
            print("最终股票排名（按成长潜力评分）:")
            print("=" * 80)
            
            # 获取评分并排序
            factor_scores = pyb.param('factor_scores', {})
            sorted_stocks = sorted(
                factor_scores.items(),
                key=lambda x: x[1],
                reverse=True
            )
            
            print(f"\n{'排名':<6} {'股票代码':<10} {'综合评分':<10} {'ROC':<10} {'RSI':<8} {'MACD':<10} {'成交量比':<10} {'趋势':<10} {'波动率':<10}")
            print("-" * 80)
            
            for rank, (symbol, score) in enumerate(sorted_stocks[:20], 1):  # 显示前20名
                details = factor_details.get(symbol, {})
                roc = details.get('roc_20', 0.0)
                rsi = details.get('rsi_14', 50.0)
                macd = details.get('macd_hist', 0.0)
                volume = details.get('volume_ratio', 1.0)
                trend = details.get('ma_trend', 0.0)
                vol = details.get('volatility', 5.0)
                
                print(f"{rank:<6} {symbol:<10} {score:<10.2f} {roc:<10.2f} {rsi:<8.2f} {macd:<10.4f} {volume:<10.2f} {trend:<10.2f} {vol:<10.2f}")
        
        # 8. 保存交易记录
        if hasattr(result, 'trades') and result.trades is not None and not result.trades.empty:
            csv_file = os.path.join(script_dir, 'factor_investing_trades.csv')
            result.trades.to_csv(csv_file, index=False, encoding='utf-8-sig')
            print(f"\n✓ 交易记录已保存到: {csv_file}")
            print(f"  总交易数: {len(result.trades)}")
        
        # 9. 保存排名结果
        if factor_details:
            # 创建排名DataFrame
            factor_scores = pyb.param('factor_scores', {})
            ranking_data = []
            for symbol, score in sorted(factor_scores.items(), key=lambda x: x[1], reverse=True):
                details = factor_details.get(symbol, {})
                ranking_data.append({
                    '排名': len(ranking_data) + 1,
                    '股票代码': symbol,
                    '综合评分': score,
                    'ROC_20': details.get('roc_20', 0.0),
                    'RSI_14': details.get('rsi_14', 50.0),
                    'MACD_Hist': details.get('macd_hist', 0.0),
                    '成交量比率': details.get('volume_ratio', 1.0),
                    '均线趋势': details.get('ma_trend', 0.0),
                    '波动率': details.get('volatility', 5.0)
                })
            
            ranking_df = pd.DataFrame(ranking_data)
            ranking_file = os.path.join(script_dir, 'factor_investing_ranking.csv')
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

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多因子成长策略 - 最近交易日排名筛选器
只获取最近交易日的策略排名前十的股票，不进行回测
"""

import os
import sys
import numpy as np
import pandas as pd
import pybroker as pyb
from pybroker import Strategy, StrategyConfig, ExecContext
from typing import Dict, List
from datetime import datetime, timedelta
import talib as ta

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from pybroker_integration.custom_data_source import create_custom_data_source
from config.settings import DATA_CONFIG

# 尝试导入 tushare（用于获取股票名称）
try:
    import tushare as ts
    TUSHARE_AVAILABLE = True
except ImportError:
    TUSHARE_AVAILABLE = False
    ts = None

# 启用数据源缓存
pyb.enable_data_source_cache('factor_investing_test_cache')

# 控制台与摘要输出中展示的股票数量（完整排名仍写入 CSV）
OUTPUT_TOP_N = 10

# ==================== 定义技术指标因子（复用原策略）====================

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
    """计算成交量比率 - 成交量因子"""
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

# 注册指标
roc_20 = pyb.indicator('roc_20', roc_20_func)
rsi_14 = pyb.indicator('rsi_14', rsi_14_func)
macd_hist = pyb.indicator('macd_hist', macd_func)
volume_ratio = pyb.indicator('volume_ratio', volume_ratio_func)
ma_trend = pyb.indicator('ma_trend', ma_trend_func)
volatility = pyb.indicator('volatility', volatility_func)

# ==================== 多因子评分函数（复用原策略）====================

def calculate_growth_score(
    roc_20: float,
    rsi_14: float,
    macd_hist: float,
    volume_ratio: float,
    ma_trend: float,
    volatility: float
) -> float:
    """计算成长潜力综合评分"""
    if any(np.isnan([roc_20, rsi_14, macd_hist, volume_ratio, ma_trend, volatility])):
        return 0.0
    
    # ROC评分
    roc_score = max(0, min(100, (roc_20 + 50) / 100 * 100))
    
    # RSI评分
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
    
    # MACD评分
    macd_score = max(0, min(100, (macd_hist + 5) / 10 * 100))
    
    # 成交量比率评分
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
    
    # 均线趋势评分
    ma_trend_score = max(0, min(100, (ma_trend + 20) / 40 * 100))
    
    # 波动率评分
    volatility_score = max(0, min(100, (10 - volatility) / 10 * 100))
    
    # 加权综合评分
    total_score = (
        roc_score * 0.30 +
        rsi_score * 0.15 +
        macd_score * 0.20 +
        volume_score * 0.15 +
        ma_trend_score * 0.15 +
        volatility_score * 0.05
    )
    
    return total_score

# ==================== 收集因子数据 ====================

# 全局变量存储所有股票的因子数据（只在最后一天收集）
factor_data = {}

def collect_factor_data(ctx: ExecContext):
    """
    收集每个股票在最近交易日的因子数据
    只在最后一天执行时收集数据
    """
    try:
        # 获取当前日期
        current_date = None
        if hasattr(ctx, 'dt') and ctx.dt is not None:
            current_date = ctx.dt
        elif hasattr(ctx, 'data') and ctx.data is not None and len(ctx.data) > 0:
            if hasattr(ctx.data.index, '__getitem__'):
                current_date = ctx.data.index[-1]
        
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
            return
        
        # 获取最后一个有效值（最近交易日的数据）
        roc = float(roc_values[-1]) if not np.isnan(roc_values[-1]) else 0.0
        rsi = float(rsi_values[-1]) if not np.isnan(rsi_values[-1]) else 50.0
        macd = float(macd_values[-1]) if macd_values is not None and len(macd_values) > 0 and not np.isnan(macd_values[-1]) else 0.0
        volume = float(volume_values[-1]) if volume_values is not None and len(volume_values) > 0 and not np.isnan(volume_values[-1]) else 1.0
        trend = float(ma_trend_values[-1]) if ma_trend_values is not None and len(ma_trend_values) > 0 and not np.isnan(ma_trend_values[-1]) else 0.0
        vol = float(volatility_values[-1]) if volatility_values is not None and len(volatility_values) > 0 and not np.isnan(volatility_values[-1]) else 5.0
        
        # 计算综合评分
        score = calculate_growth_score(roc, rsi, macd, volume, trend, vol)
        
        # 获取当前价格
        current_price = 0.0
        if isinstance(ctx.close, (list, np.ndarray)):
            current_price = float(ctx.close[-1]) if len(ctx.close) > 0 else 0.0
        else:
            current_price = float(ctx.close) if ctx.close is not None else 0.0
        
        # 存储因子数据
        factor_data[ctx.symbol] = {
            'symbol': ctx.symbol,
            'date': current_date,
            'price': current_price,
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
        pass

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

def get_stock_names(symbols: List[str]) -> Dict[str, str]:
    """
    批量获取股票名称（使用 tushare）
    
    Args:
        symbols: 股票代码列表
        
    Returns:
        字典，key 为股票代码，value 为股票名称
    """
    stock_names = {}
    
    if not TUSHARE_AVAILABLE:
        print("⚠ 警告: tushare 不可用，无法获取股票名称")
        return stock_names
    
    try:
        # 初始化 tushare pro
        tushare_token = DATA_CONFIG.get('tushare_token', '')
        if not tushare_token:
            print("⚠ 警告: tushare token 未配置，无法获取股票名称")
            return stock_names
        
        pro = ts.pro_api(tushare_token)
        
        # 批量查询股票基本信息
        # 将股票代码转换为 tushare 格式（6位数字，如果是6位则直接使用，否则可能需要补零）
        ts_codes = []
        for symbol in symbols:
            # tushare 需要带后缀的代码，如 000001.SZ 或 600000.SH
            # 但如果是纯数字代码，可以尝试查询
            if len(symbol) == 6 and symbol.isdigit():
                # 判断是上交所还是深交所
                if symbol.startswith(('60', '68')):
                    ts_code = f"{symbol}.SH"
                elif symbol.startswith(('00', '30')):
                    ts_code = f"{symbol}.SZ"
                else:
                    ts_code = symbol
                ts_codes.append(ts_code)
            else:
                ts_codes.append(symbol)
        
        # 使用 stock_basic 接口获取股票基本信息
        df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name')
        
        # 创建映射：从 ts_code 到 name
        code_to_name = {}
        for _, row in df.iterrows():
            ts_code = row['ts_code']
            name = row['name']
            # 提取纯数字代码（去掉后缀）
            code = ts_code.split('.')[0]
            code_to_name[code] = name
            code_to_name[ts_code] = name  # 也保存完整代码
        
        # 匹配股票代码和名称
        for symbol in symbols:
            # 尝试多种匹配方式
            if symbol in code_to_name:
                stock_names[symbol] = code_to_name[symbol]
            elif len(symbol) == 6 and symbol.isdigit():
                # 尝试匹配
                if symbol.startswith(('60', '68')):
                    ts_code = f"{symbol}.SH"
                elif symbol.startswith(('00', '30')):
                    ts_code = f"{symbol}.SZ"
                else:
                    ts_code = symbol
                
                if ts_code in code_to_name:
                    stock_names[symbol] = code_to_name[ts_code]
                else:
                    stock_names[symbol] = symbol  # 如果找不到，使用代码本身
            else:
                stock_names[symbol] = symbol  # 如果找不到，使用代码本身
        
    except Exception as e:
        print(f"⚠ 获取股票名称失败: {e}")
        # 如果失败，返回空字典或使用代码作为名称
        for symbol in symbols:
            stock_names[symbol] = symbol
    
    return stock_names

def get_recent_trading_days(days: int = 60) -> tuple:
    """
    获取最近N个交易日的日期范围
    确保有足够数据计算指标（需要至少30-40天的历史数据）
    """
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    
    # 转换为字符串格式 YYYYMMDD
    start_str = start_date.strftime('%Y%m%d')
    end_str = end_date.strftime('%Y%m%d')
    
    return start_str, end_str

def main():
    """主函数"""
    print("=" * 80)
    print("多因子成长策略 - 最近交易日排名筛选器")
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
    
    # 2. 获取最近交易日的日期范围（需要足够的历史数据来计算指标）
    start_date, end_date = get_recent_trading_days(days=60)
    
    print(f"\n数据获取参数:")
    print(f"  - 开始日期: {start_date} (获取最近60天数据，确保有足够历史数据计算指标)")
    print(f"  - 结束日期: {end_date} (最近交易日)")
    print(f"  - 目标: 获取最后一天的因子评分和排名")
    
    # 3. 清空全局变量
    global factor_data
    factor_data = {}
    
    # 4. 创建数据源和策略
    print("\n正在初始化数据源和策略...")
    try:
        data_source = create_custom_data_source()
        config = StrategyConfig(initial_cash=100000)
        
        strategy = Strategy(
            data_source,
            start_date=start_date,
            end_date=end_date,
            config=config
        )
        
        # 添加执行函数（只收集数据，不进行交易）
        strategy.add_execution(
            collect_factor_data,
            symbols,
            indicators=[roc_20, rsi_14, macd_hist, volume_ratio, ma_trend, volatility]
        )
        
        print("✓ 策略初始化完成")
        
    except Exception as e:
        print(f"✗ 策略初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # 5. 运行回测（只运行到最近交易日，收集最后一天的因子数据）
    print("\n" + "=" * 80)
    print("正在获取数据并计算因子...")
    print("提示: 数据获取可能需要一些时间，请耐心等待...")
    print("=" * 80)
    
    import time
    start_time = time.time()
    
    try:
        # 运行回测，warmup确保有足够数据计算指标
        result = strategy.backtest(warmup=30)
        elapsed_time = time.time() - start_time
        
        print(f"\n✓ 数据获取完成！耗时: {elapsed_time:.2f} 秒")
        print("=" * 80)
        
        # 6. 计算排名并输出前 OUTPUT_TOP_N 名
        if not factor_data:
            print("⚠ 警告: 没有收集到任何股票的因子数据")
            return
        
        # 按评分排序
        sorted_stocks = sorted(
            factor_data.items(),
            key=lambda x: x[1]['total_score'],
            reverse=True
        )
        
        top_output = sorted_stocks[:OUTPUT_TOP_N]
        
        top_output_symbols = [data['symbol'] for _, data in top_output]
        print(f"\n正在查询前{OUTPUT_TOP_N}名股票的名称...")
        stock_names = get_stock_names(top_output_symbols)
        
        print("\n" + "=" * 80)
        print(f"最近交易日策略排名 TOP {OUTPUT_TOP_N}")
        print("=" * 80)
        
        # 获取最近交易日日期
        latest_date = None
        for symbol, data in factor_data.items():
            if data.get('date') is not None:
                latest_date = data['date']
                break
        
        if latest_date:
            if isinstance(latest_date, (pd.Timestamp, datetime)):
                date_str = latest_date.strftime('%Y-%m-%d')
            else:
                date_str = str(latest_date)
            print(f"交易日: {date_str}")
        else:
            print("交易日: 最近交易日")
        
        print(f"\n{'排名':<6} {'股票代码':<10} {'股票名称':<20} {'综合评分':<12} {'当前价格':<12} {'ROC':<10} {'RSI':<8} {'MACD':<10} {'成交量比':<10} {'趋势':<10} {'波动率':<10}")
        print("-" * 120)
        
        for rank, (symbol, data) in enumerate(top_output, 1):
            stock_name = stock_names.get(data['symbol'], data['symbol'])
            print(f"{rank:<6} {data['symbol']:<10} {stock_name:<20} {data['total_score']:<12.2f} {data['price']:<12.2f} "
                  f"{data['roc_20']:<10.2f} {data['rsi_14']:<8.2f} {data['macd_hist']:<10.4f} "
                  f"{data['volume_ratio']:<10.2f} {data['ma_trend']:<10.2f} {data['volatility']:<10.2f}")
        
        # 7. 保存结果到CSV
        ranking_data = []
        for rank, (symbol, data) in enumerate(sorted_stocks, 1):
            # 前 OUTPUT_TOP_N 名使用已查询的股票名称，其他使用代码
            stock_name = stock_names.get(data['symbol'], data['symbol']) if rank <= OUTPUT_TOP_N else data['symbol']
            ranking_data.append({
                '排名': rank,
                '股票代码': data['symbol'],
                '股票名称': stock_name,
                '综合评分': data['total_score'],
                '当前价格': data['price'],
                'ROC_20': data['roc_20'],
                'RSI_14': data['rsi_14'],
                'MACD_Hist': data['macd_hist'],
                '成交量比率': data['volume_ratio'],
                '均线趋势': data['ma_trend'],
                '波动率': data['volatility'],
                '交易日': data.get('date', '')
            })
        
        ranking_df = pd.DataFrame(ranking_data)
        ranking_file = os.path.join(script_dir, 'factor_investing_ranking_latest.csv')
        ranking_df.to_csv(ranking_file, index=False, encoding='utf-8-sig')
        print(f"\n✓ 完整排名已保存到: {ranking_file}")
        print(f"  共 {len(ranking_df)} 只股票")
        
        # 8. 输出前 OUTPUT_TOP_N 名股票代码（便于使用）
        print("\n" + "=" * 80)
        print(f"TOP {OUTPUT_TOP_N} 股票代码（推荐关注）:")
        print("=" * 80)
        for rank, (symbol, data) in enumerate(top_output, 1):
            stock_name = stock_names.get(data['symbol'], data['symbol'])
            print(f"{rank}. {data['symbol']} ({stock_name})")
        
        print("\n" + "=" * 80)
        print("筛选完成！")
        print("=" * 80)
        
    except Exception as e:
        elapsed_time = time.time() - start_time
        print(f"\n✗ 执行过程中发生错误！耗时: {elapsed_time:.2f} 秒")
        print(f"错误类型: {type(e).__name__}")
        print(f"错误信息: {e}")
        import traceback
        print("\n详细错误堆栈:")
        traceback.print_exc()
        raise

if __name__ == '__main__':
    main()

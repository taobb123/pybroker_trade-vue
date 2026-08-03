#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
轮动策略实时信号生成器
基于 rotation_trade.py 的轮动策略逻辑，使用 tushare 数据源生成最新的买入信号

功能：
1. 使用 tushare 获取最新股票数据
2. 计算 ROC 20 指标
3. 对股票进行排名
4. 输出买入信号（前2名）用于人工建仓
"""

import os
import sys
import pandas as pd
import numpy as np
import talib as ta
from datetime import datetime, timedelta
from typing import List, Dict, Optional

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data.fetcher import DataFetcher
from config.settings import DATA_CONFIG


class RotationSignalGenerator:
    """轮动策略信号生成器"""
    
    def __init__(self, use_tushare_only: bool = True):
        """
        初始化信号生成器
        
        Args:
            use_tushare_only: 是否仅使用 tushare 数据源
        """
        self.fetcher = DataFetcher()
        self.use_tushare_only = use_tushare_only
        
        # 策略参数（与 rotation_trade.py 保持一致）
        self.roc_period = 20  # ROC 计算周期
        self.max_positions = 2  # 最大持仓数量
        self.rank_threshold = 5  # 排名阈值（前5名）
        self.lookback_days = 60  # 获取历史数据的天数（需要足够计算 ROC 20）
        
    def fetch_stock_data(self, symbol: str, end_date: Optional[str] = None) -> Optional[pd.DataFrame]:
        """
        获取股票数据（强制使用 tushare）
        
        Args:
            symbol: 股票代码
            end_date: 结束日期（格式：YYYY-MM-DD），如果为 None 则使用今天
            
        Returns:
            DataFrame 或 None
        """
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')
        
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        start_date = (end_dt - timedelta(days=self.lookback_days)).strftime('%Y-%m-%d')
        
        if self.use_tushare_only:
            # 强制使用 tushare
            data = self.fetcher._fetch_from_tushare(symbol, start_date, end_date)
        else:
            # 使用默认数据获取流程（数据库 -> API）
            data = self.fetcher.fetch_stock_data(
                code=symbol,
                start_date=start_date,
                end_date=end_date,
                use_mock_if_fail=False
            )
        
        if data is None or data.empty:
            return None
        
        # 确保数据格式正确
        if 'date' not in data.columns and isinstance(data.index, pd.DatetimeIndex):
            data = data.reset_index()
        
        # 确保日期列为 datetime 类型
        if 'date' in data.columns:
            data['date'] = pd.to_datetime(data['date'])
            data = data.sort_values('date').reset_index(drop=True)
        
        return data
    
    def calculate_roc(self, data: pd.DataFrame) -> Optional[float]:
        """
        计算 ROC 指标
        
        Args:
            data: 股票数据 DataFrame
            
        Returns:
            ROC 值（最新值）或 None
        """
        if data is None or data.empty:
            return None
        
        if 'close' not in data.columns:
            return None
        
        if len(data) < self.roc_period:
            return None
        
        try:
            # 计算 ROC
            close_prices = data['close'].values.astype(float)
            roc = ta.ROC(close_prices, timeperiod=self.roc_period)
            
            # 返回最后一个有效值
            valid_roc = roc[~np.isnan(roc)]
            if len(valid_roc) > 0:
                return float(valid_roc[-1])
            else:
                return None
        except Exception as e:
            print(f"计算 ROC 指标失败: {e}")
            return None
    
    def rank_stocks(self, symbols: List[str]) -> List[Dict]:
        """
        对股票进行排名（基于 ROC 指标）
        
        Args:
            symbols: 股票代码列表
            
        Returns:
            排名结果列表，每个元素包含 {symbol, roc, rank}
        """
        print(f"\n开始获取数据并计算 ROC 指标...")
        print(f"股票数量: {len(symbols)}")
        print(f"使用数据源: {'tushare' if self.use_tushare_only else '自动'}")
        print("-" * 60)
        
        results = []
        success_count = 0
        fail_count = 0
        
        for i, symbol in enumerate(symbols, 1):
            try:
                # 获取数据
                data = self.fetch_stock_data(symbol)
                
                if data is None or data.empty:
                    print(f"[{i}/{len(symbols)}] {symbol}: 数据获取失败")
                    fail_count += 1
                    continue
                
                # 计算 ROC
                roc = self.calculate_roc(data)
                
                if roc is None:
                    print(f"[{i}/{len(symbols)}] {symbol}: ROC 计算失败（数据不足）")
                    fail_count += 1
                    continue
                
                # 获取最新价格
                latest_price = float(data['close'].iloc[-1])
                latest_date = data['date'].iloc[-1].strftime('%Y-%m-%d')
                
                results.append({
                    'symbol': symbol,
                    'roc': roc,
                    'price': latest_price,
                    'date': latest_date,
                    'data_points': len(data)
                })
                
                success_count += 1
                print(f"[{i}/{len(symbols)}] {symbol}: ROC={roc:.2f}%, 价格={latest_price:.2f}, 日期={latest_date}")
                
            except Exception as e:
                print(f"[{i}/{len(symbols)}] {symbol}: 处理异常 - {e}")
                fail_count += 1
                continue
        
        print("-" * 60)
        print(f"成功: {success_count}, 失败: {fail_count}")
        
        # 按 ROC 降序排序
        results.sort(key=lambda x: x['roc'], reverse=True)
        
        # 添加排名
        for i, result in enumerate(results, 1):
            result['rank'] = i
        
        return results
    
    def generate_buy_signals(self, symbols: List[str]) -> Dict:
        """
        生成买入信号
        
        Args:
            symbols: 股票代码列表
            
        Returns:
            包含买入信号的字典
        """
        # 对股票进行排名
        ranked_stocks = self.rank_stocks(symbols)
        
        if not ranked_stocks:
            return {
                'signals': [],
                'top_ranked': [],
                'message': '没有可用的股票数据',
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            }
        
        # 获取前 N 名（rank_threshold）
        top_ranked = ranked_stocks[:self.rank_threshold]
        
        # 买入信号：前 max_positions 名
        buy_signals = ranked_stocks[:self.max_positions]
        
        return {
            'signals': buy_signals,
            'top_ranked': top_ranked,
            'all_ranked': ranked_stocks,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
    
    def print_signals(self, result: Dict):
        """
        打印买入信号
        
        Args:
            result: generate_buy_signals 返回的结果
        """
        print("\n" + "=" * 80)
        print("轮动策略买入信号")
        print("=" * 80)
        print(f"生成时间: {result.get('timestamp', '')}")
        print(f"策略参数: ROC周期={self.roc_period}, 最大持仓={self.max_positions}, 排名阈值={self.rank_threshold}")
        print("-" * 80)
        
        if not result['signals']:
            print("⚠ 警告: 没有生成买入信号")
            print(result.get('message', ''))
            return
        
        print(f"\n【买入信号】前 {self.max_positions} 名（建议建仓）:")
        print("-" * 80)
        for i, signal in enumerate(result['signals'], 1):
            print(f"{i}. 股票代码: {signal['symbol']}")
            print(f"   ROC 20: {signal['roc']:.2f}%")
            print(f"   当前价格: {signal['price']:.2f} 元")
            print(f"   数据日期: {signal['date']}")
            print(f"   排名: 第 {signal['rank']} 名")
            print()
        
        print(f"\n【参考信息】前 {self.rank_threshold} 名排名:")
        print("-" * 80)
        for signal in result['top_ranked']:
            marker = "✓" if signal in result['signals'] else " "
            print(f"{marker} {signal['rank']:2d}. {signal['symbol']:8s} - ROC: {signal['roc']:7.2f}% - 价格: {signal['price']:8.2f} 元")
        
        print("\n" + "=" * 80)
        print("建仓建议:")
        print(f"1. 建议买入前 {self.max_positions} 只股票")
        print(f"2. 每只股票分配 {100/self.max_positions:.0f}% 的资金")
        print(f"3. 如果持仓股票跌出前 {self.rank_threshold} 名，建议卖出")
        print("=" * 80 + "\n")
    
    def save_signals_to_csv(self, result: Dict, filename: Optional[str] = None):
        """
        保存信号到 CSV 文件
        
        Args:
            result: generate_buy_signals 返回的结果
            filename: 文件名，如果为 None 则自动生成
        """
        if filename is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            filename = os.path.join(script_dir, f'rotation_signals.csv')
        
        # 创建 DataFrame
        if result['signals']:
            df = pd.DataFrame(result['signals'])
            df.to_csv(filename, index=False, encoding='utf-8-sig')
            print(f"信号已保存到: {filename}")
        else:
            print("没有信号可保存")


def load_stocks_pool(file_path):
    """从文件读取股票池列表（支持每行多个股票代码，用空格分隔）"""
    if os.path.exists(file_path):
        try:
            symbols = []
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        # 按空格分割，支持每行多个股票代码
                        line_symbols = line.split()
                        symbols.extend(line_symbols)
            print(f"从文件 {file_path} 读取到 {len(symbols)} 只股票")
            return symbols
        except Exception as e:
            print(f"读取股票池文件失败: {e}")
            return None
    else:
        print(f"股票池文件 {file_path} 不存在，将使用默认股票池")
        return None


def main():
    """主函数"""
    # 获取脚本所在目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    stocks_pool_file = os.path.join(script_dir, 'stocks_pool.txt')
    
    # 从文件读取股票池，如果文件不存在则使用默认股票池
    symbols = load_stocks_pool(stocks_pool_file)
    
    # 如果文件不存在或读取失败，使用默认股票池
    if symbols is None:
        # 默认股票代码列表（与 rotation_trade.py 保持一致）
        symbols = [
        '603194',
        '301626',
        '603596',
        '300308',
        '300502',
        '600536',
        '300394',
        '603392',
        '300760',
        '600085',
        '301269',
        '600588',
        '002085',
        '003033',
        '300673',
        '159959',
        '560700',
        '600809',
        '600570',
        '002463',
        '601360',
        '600480',
        '603859',
        '600143',
        '600435',
        '000738',
        '603712',
        '002179',
        '000651',
        '600690',
        '600887',
        '515650',
        '002891',
        '603019',
        '000977',
        '603501',
        '002371',
        '002142',
        '002352',
        '600206',
        '601939'
    ]
    
    # 检查 tushare token
    tushare_token = DATA_CONFIG.get('tushare_token', '')
    if not tushare_token:
        print("⚠ 警告: tushare token 未配置")
        print("请在 config/settings.py 中设置 DATA_CONFIG['tushare_token']")
        print("将尝试使用其他数据源...")
        use_tushare_only = False
    else:
        use_tushare_only = True
        print(f"✓ 使用 tushare 数据源")
    
    # 创建信号生成器
    generator = RotationSignalGenerator(use_tushare_only=use_tushare_only)
    
    # 生成买入信号
    result = generator.generate_buy_signals(symbols)
    
    # 打印信号
    generator.print_signals(result)
    
    # 保存到 CSV
    generator.save_signals_to_csv(result)
    
    return result


if __name__ == '__main__':
    main()


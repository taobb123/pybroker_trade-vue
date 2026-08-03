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

# 尝试导入 tushare（用于获取股票名称）
try:
    import tushare as ts
    TUSHARE_AVAILABLE = True
except ImportError:
    TUSHARE_AVAILABLE = False
    ts = None


class RotationSignalGenerator:
    """轮动策略信号生成器"""
    
    def __init__(self, use_tushare_only: bool = True, end_date: Optional[str] = None):
        """
        初始化信号生成器
        
        Args:
            use_tushare_only: 是否仅使用 tushare 数据源
            end_date: 结束日期（格式：YYYY-MM-DD），如果为 None 则使用今天
        """
        self.fetcher = DataFetcher()
        self.use_tushare_only = use_tushare_only
        self.end_date = end_date  # 全局结束日期配置
        
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
            end_date: 结束日期（格式：YYYY-MM-DD），如果为 None 则使用实例配置的 end_date，再为 None 则使用今天
            
        Returns:
            DataFrame 或 None
        """
        # 优先使用传入的参数，其次使用实例配置，最后使用今天
        if end_date is None:
            end_date = self.end_date
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')
        
        # 开始日期与 end_date 对齐（避免截止日写死在过去时仍用「今天」倒推导致窗口过短）
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
    
    def get_stock_names(self, symbols: List[str]) -> Dict[str, str]:
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
        
        # 仅对前5名查询股票名称
        top_5_symbols = [stock['symbol'] for stock in top_ranked]
        print(f"\n正在查询前 {len(top_5_symbols)} 名股票的名称...")
        stock_names = self.get_stock_names(top_5_symbols)
        
        # 将股票名称添加到结果中
        for stock in top_ranked:
            stock['name'] = stock_names.get(stock['symbol'], stock['symbol'])
        
        for stock in buy_signals:
            if 'name' not in stock:
                stock['name'] = stock_names.get(stock['symbol'], stock['symbol'])
        
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
            stock_name = signal.get('name', signal['symbol'])
            print(f"{i}. 股票代码: {signal['symbol']} ({stock_name})")
            print(f"   ROC 20: {signal['roc']:.2f}%")
            print(f"   当前价格: {signal['price']:.2f} 元")
            print(f"   数据日期: {signal['date']}")
            print(f"   排名: 第 {signal['rank']} 名")
            print()
        
        print(f"\n【参考信息】前 {self.rank_threshold} 名排名:")
        print("-" * 80)
        for signal in result['top_ranked']:
            marker = "✓" if signal in result['signals'] else " "
            stock_name = signal.get('name', signal['symbol'])
            print(f"{marker} {signal['rank']:2d}. {signal['symbol']:8s} ({stock_name:10s}) - ROC: {signal['roc']:7.2f}% - 价格: {signal['price']:8.2f} 元")
        
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
        '301626'
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
    
    # 结束日 None = 使用当天；回测可传入 end_date='YYYY-MM-DD'
    generator = RotationSignalGenerator(use_tushare_only=use_tushare_only, end_date=None)
    
    # 生成买入信号
    result = generator.generate_buy_signals(symbols)
    
    # 打印信号
    generator.print_signals(result)
    
    # 保存到 CSV
    # generator.save_signals_to_csv(result)
    
    return result


if __name__ == '__main__':
    main()


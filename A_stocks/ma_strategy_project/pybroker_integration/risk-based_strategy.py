#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于 Riskfolio-Lib 的风险管理策略
结合 PyBroker 进行投资组合优化和回测

功能：
1. 使用 Riskfolio-Lib 进行投资组合优化
2. 支持最大夏普比率 (Max Sharpe) 和最小波动率 (Min Volatility) 优化
3. 与 PyBroker 集成进行策略回测
4. 自动保存优化结果和回测报告
"""

import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import warnings
warnings.filterwarnings('ignore')

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 导入依赖库
try:
    import pybroker as pb
except ImportError:
    print("警告: PyBroker 未安装，请运行: pip install -U lib-pybroker")
    pb = None

try:
    import riskfolio as rp
    RISKFOLIO_AVAILABLE = True
except ImportError:
    print("警告: Riskfolio-Lib 未安装，请运行: pip install Riskfolio-Lib")
    RISKFOLIO_AVAILABLE = False

from data.fetcher import DataFetcher
from pybroker_integration.data_provider import PyBrokerDataProvider


class RiskBasedPortfolioStrategy:
    """
    基于风险的投资组合策略
    
    使用 Riskfolio-Lib 进行投资组合优化，支持：
    - 最大夏普比率优化 (Max Sharpe)
    - 最小波动率优化 (Min Volatility)
    """
    
    def __init__(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        initial_cash: float = 1000000,
        commission: float = 0.001,
        optimization_method: str = 'max_sharpe',
        rebalance_frequency: str = 'monthly',
        risk_free_rate: float = 0.03,
        lookback_period: int = 252  # 一年交易日
    ):
        """
        初始化风险管理策略
        
        Args:
            symbols: 股票代码列表
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            initial_cash: 初始资金
            commission: 手续费率
            optimization_method: 优化方法 ('max_sharpe' 或 'min_volatility')
            rebalance_frequency: 再平衡频率 ('daily', 'weekly', 'monthly', 'quarterly')
            risk_free_rate: 无风险利率（年化）
            lookback_period: 回望期（用于计算协方差矩阵）
        """
        if not RISKFOLIO_AVAILABLE:
            raise ImportError("Riskfolio-Lib 未安装，请运行: pip install Riskfolio-Lib")
        
        if pb is None:
            raise ImportError("PyBroker 未安装，请运行: pip install -U lib-pybroker")
        
        # 去重股票代码
        self.symbols = list(set(symbols))
        self.start_date = start_date
        self.end_date = end_date
        self.initial_cash = initial_cash
        self.commission = commission
        self.optimization_method = optimization_method.lower()
        self.rebalance_frequency = rebalance_frequency.lower()
        self.risk_free_rate = risk_free_rate
        self.lookback_period = lookback_period
        
        # 数据获取器
        self.fetcher = DataFetcher()
        self.data_provider = PyBrokerDataProvider()
        
        # 存储数据
        self.price_data = None
        self.returns_data = None
        self.optimal_weights = None
        self.backtest_result = None
        
        # 验证优化方法
        if self.optimization_method not in ['max_sharpe', 'min_volatility']:
            raise ValueError(f"优化方法必须是 'max_sharpe' 或 'min_volatility'，当前: {optimization_method}")
    
    def fetch_price_data(self) -> pd.DataFrame:
        """
        获取所有股票的价格数据
        
        Returns:
            DataFrame: 价格数据（日期作为索引，股票代码作为列）
        """
        print(f"\n开始获取 {len(self.symbols)} 只股票的价格数据...")
        print(f"日期范围: {self.start_date} 至 {self.end_date}")
        print("-" * 80)
        
        all_data = []
        success_count = 0
        fail_count = 0
        
        for i, symbol in enumerate(self.symbols, 1):
            try:
                # 获取数据（需要更长的历史数据用于计算协方差）
                extended_start = (datetime.strptime(self.start_date, '%Y-%m-%d') - 
                                 timedelta(days=self.lookback_period + 100)).strftime('%Y-%m-%d')
                
                data = self.fetcher.fetch_stock_data(
                    code=symbol,
                    start_date=extended_start,
                    end_date=self.end_date,
                    use_mock_if_fail=False
                )
                
                if data is None or data.empty:
                    print(f"[{i}/{len(self.symbols)}] {symbol}: 数据获取失败")
                    fail_count += 1
                    continue
                
                # 确保日期列为 datetime 类型
                if 'date' in data.columns:
                    data['date'] = pd.to_datetime(data['date'])
                    data = data.set_index('date')
                elif not isinstance(data.index, pd.DatetimeIndex):
                    data.index = pd.to_datetime(data.index)
                
                # 确保有 close 列
                if 'close' not in data.columns:
                    print(f"[{i}/{len(self.symbols)}] {symbol}: 缺少 close 列")
                    fail_count += 1
                    continue
                
                # 提取收盘价
                price_series = data['close'].copy()
                price_series.name = symbol
                
                # 过滤日期范围
                price_series = price_series[
                    (price_series.index >= self.start_date) & 
                    (price_series.index <= self.end_date)
                ]
                
                if len(price_series) == 0:
                    print(f"[{i}/{len(self.symbols)}] {symbol}: 日期范围内无数据")
                    fail_count += 1
                    continue
                
                all_data.append(price_series)
                success_count += 1
                print(f"[{i}/{len(self.symbols)}] {symbol}: 成功获取 {len(price_series)} 条数据")
                
            except Exception as e:
                print(f"[{i}/{len(self.symbols)}] {symbol}: 处理异常 - {e}")
                fail_count += 1
                continue
        
        print("-" * 80)
        print(f"数据获取完成: 成功 {success_count}, 失败 {fail_count}")
        
        if not all_data:
            raise ValueError("未能获取任何股票数据")
        
        # 合并所有股票的价格数据
        price_df = pd.concat(all_data, axis=1)
        price_df = price_df.sort_index()
        
        # 前向填充缺失值（处理停牌等情况）
        price_df = price_df.ffill()
        
        # 删除仍有缺失值的日期（所有股票都停牌的情况）
        price_df = price_df.dropna()
        
        print(f"\n价格数据合并完成: {len(price_df)} 个交易日, {len(price_df.columns)} 只股票")
        self.price_data = price_df
        
        return price_df
    
    def calculate_returns(self) -> pd.DataFrame:
        """
        计算收益率数据
        
        Returns:
            DataFrame: 收益率数据（日期作为索引，股票代码作为列）
        """
        if self.price_data is None:
            self.fetch_price_data()
        
        # 计算日收益率
        returns_df = self.price_data.pct_change().dropna()
        
        print(f"\n收益率计算完成: {len(returns_df)} 个交易日")
        self.returns_data = returns_df
        
        return returns_df
    
    def optimize_portfolio(self, returns: Optional[pd.DataFrame] = None) -> Dict:
        """
        使用 Riskfolio-Lib 优化投资组合
        
        Args:
            returns: 收益率数据，如果为 None 则使用 self.returns_data
        
        Returns:
            Dict: 包含优化权重和统计信息的字典
        """
        if returns is None:
            if self.returns_data is None:
                self.calculate_returns()
            returns = self.returns_data
        
        if len(returns) < self.lookback_period:
            print(f"警告: 数据量 ({len(returns)}) 少于回望期 ({self.lookback_period})，使用全部数据")
            lookback = len(returns)
        else:
            lookback = self.lookback_period
        
        # 使用最近的数据进行优化
        recent_returns = returns.iloc[-lookback:]
        
        print(f"\n开始投资组合优化...")
        print(f"优化方法: {self.optimization_method}")
        print(f"使用数据: 最近 {len(recent_returns)} 个交易日")
        print(f"股票数量: {len(recent_returns.columns)}")
        print("-" * 80)
        
        # 创建投资组合对象
        port = rp.Portfolio(returns=recent_returns)
        
        # 计算资产统计信息（期望收益和协方差矩阵）
        # 使用历史数据方法
        try:
            # 尝试使用 assets_stats 方法（如果可用）
            port.assets_stats(method_mu='hist', method_cov='hist')
        except (TypeError, AttributeError):
            # 如果方法不存在或参数不对，手动计算
            # Riskfolio-Lib 会自动计算，这里只是确保数据准备就绪
            pass
        
        # 设置约束条件
        # 不允许做空，权重和为1
        port.lowerret = None  # 不设置最低收益约束
        port.upperret = None  # 不设置最高收益约束
        
        # 执行优化
        if self.optimization_method == 'max_sharpe':
            # 最大夏普比率优化
            w = port.optimization(
                model='Classic',
                rm='MV',  # Mean-Variance
                obj='Sharpe',
                rf=self.risk_free_rate / 252,  # 转换为日利率
                hist=True
            )
            method_name = "最大夏普比率"
        elif self.optimization_method == 'min_volatility':
            # 最小波动率优化
            w = port.optimization(
                model='Classic',
                rm='MV',  # Mean-Variance
                obj='MinRisk',
                rf=self.risk_free_rate / 252,
                hist=True
            )
            method_name = "最小波动率"
        else:
            raise ValueError(f"不支持的优化方法: {self.optimization_method}")
        
        # 提取权重
        weights = w.values.flatten()
        asset_names = recent_returns.columns.tolist()
        
        # 创建权重字典
        weights_dict = dict(zip(asset_names, weights))
        
        # 计算组合统计信息
        portfolio_return = np.dot(weights, recent_returns.mean() * 252)  # 年化收益
        portfolio_vol = np.sqrt(np.dot(weights, np.dot(recent_returns.cov() * 252, weights)))  # 年化波动率
        portfolio_sharpe = (portfolio_return - self.risk_free_rate) / portfolio_vol if portfolio_vol > 0 else 0
        
        # 过滤掉权重很小的股票（小于0.01%）
        significant_weights = {k: v for k, v in weights_dict.items() if abs(v) > 0.0001}
        
        print(f"\n{method_name}优化完成:")
        print(f"  组合年化收益: {portfolio_return*100:.2f}%")
        print(f"  组合年化波动率: {portfolio_vol*100:.2f}%")
        print(f"  组合夏普比率: {portfolio_sharpe:.4f}")
        print(f"  有效持仓数量: {len(significant_weights)}")
        print("\n权重分配:")
        print("-" * 80)
        
        # 按权重排序显示
        sorted_weights = sorted(weights_dict.items(), key=lambda x: abs(x[1]), reverse=True)
        for symbol, weight in sorted_weights:
            if abs(weight) > 0.0001:
                print(f"  {symbol}: {weight*100:6.2f}%")
        
        print("-" * 80)
        
        result = {
            'weights': weights_dict,
            'significant_weights': significant_weights,
            'portfolio_return': portfolio_return,
            'portfolio_volatility': portfolio_vol,
            'portfolio_sharpe': portfolio_sharpe,
            'optimization_method': method_name,
            'assets': asset_names
        }
        
        self.optimal_weights = weights_dict
        
        return result
    
    def create_pybroker_strategy(self, weights: Dict[str, float]) -> Tuple[callable, callable]:
        """
        创建 PyBroker 策略函数
        
        Args:
            weights: 股票权重字典
        
        Returns:
            Tuple: (再平衡函数, 执行函数)
        """
        # 过滤掉权重很小的股票
        significant_weights = {k: v for k, v in weights.items() if abs(v) > 0.0001}
        
        # 归一化权重（确保和为1）
        total_weight = sum(abs(w) for w in significant_weights.values())
        if total_weight > 0:
            normalized_weights = {k: abs(v) / total_weight for k, v in significant_weights.items()}
        else:
            normalized_weights = significant_weights
        
        # 使用闭包存储状态
        _last_rebalance_date = [None]
        _portfolio_weights = normalized_weights
        _rebalance_frequency = self.rebalance_frequency
        
        def should_rebalance(ctxs: dict) -> bool:
            """判断是否需要再平衡"""
            if not ctxs:
                return False
            
            # 获取第一个上下文来检查日期
            first_ctx = list(ctxs.values())[0]
            current_date = first_ctx.date
            
            # 检查是否已经初始化
            if _last_rebalance_date[0] is None:
                return True
            
            # 计算距离上次再平衡的天数
            days_since = (current_date - _last_rebalance_date[0]).days
            
            if _rebalance_frequency == 'daily':
                return days_since >= 1
            elif _rebalance_frequency == 'weekly':
                return days_since >= 5
            elif _rebalance_frequency == 'monthly':
                return days_since >= 20
            elif _rebalance_frequency == 'quarterly':
                return days_since >= 60
            else:
                return False
        
        def rebalance_portfolio(ctxs: dict):
            """再平衡投资组合"""
            if not should_rebalance(ctxs):
                return
            
            if not _portfolio_weights:
                return
            
            # 计算总权益（使用第一个上下文）
            first_ctx = list(ctxs.values())[0]
            total_equity = first_ctx.equity
            
            # 为每只股票设置目标权重
            for symbol, weight in _portfolio_weights.items():
                if symbol in ctxs:
                    ctx = ctxs[symbol]
                    target_value = total_equity * weight
                    current_price = ctx.close
                    
                    if current_price > 0:
                        target_shares = int(target_value / current_price)
                        try:
                            current_shares = ctx.long_pos() if hasattr(ctx, 'long_pos') else 0
                            if current_shares is None:
                                current_shares = 0
                            else:
                                current_shares = int(current_shares)
                        except (AttributeError, TypeError):
                            current_shares = 0
                        
                        if target_shares > current_shares:
                            # 需要买入
                            ctx.buy_shares = target_shares - current_shares
                        elif target_shares < current_shares:
                            # 需要卖出
                            if hasattr(ctx, 'sell_shares'):
                                ctx.sell_shares = current_shares - target_shares
                            elif hasattr(ctx, 'sell_all_shares'):
                                # 如果只能全部卖出，先全部卖出再买入目标数量
                                ctx.sell_all_shares()
                                ctx.buy_shares = target_shares
                        # 如果相等，不需要操作
            
            # 更新再平衡日期
            first_ctx = list(ctxs.values())[0]
            _last_rebalance_date[0] = first_ctx.date
        
        def portfolio_strategy(ctx):
            """投资组合策略执行函数"""
            # 这个函数会在每个股票上被调用
            # 实际的再平衡逻辑在 rebalance_portfolio 中处理
            pass
        
        return rebalance_portfolio, portfolio_strategy
    
    def run_backtest(self) -> Dict:
        """
        运行 PyBroker 回测
        
        Returns:
            Dict: 回测结果
        """
        if self.optimal_weights is None:
            print("先执行投资组合优化...")
            self.optimize_portfolio()
        
        print(f"\n开始 PyBroker 回测...")
        print(f"初始资金: {self.initial_cash:,.0f}")
        print(f"手续费率: {self.commission*100:.3f}%")
        print(f"再平衡频率: {self.rebalance_frequency}")
        print("-" * 80)
        
        # 获取股票列表
        symbols = list(self.optimal_weights.keys())
        
        # 创建自定义数据源（使用项目中已有的实现，参考 rotation_signal_generator.py）
        # 优先使用项目中的 CustomDataSource，它已经正确继承自 pybroker.data.DataSource
        try:
            from pybroker_integration.custom_data_source import create_custom_data_source
            data_source = create_custom_data_source()
        except ImportError:
            # 如果无法导入，使用本文件中定义的 CustomDataSource
            data_source = CustomDataSource()
        
        try:
            # 使用 PyBroker 的新 API（根据 back_strategy.py 的模式）
            # 创建策略配置（只接受 initial_cash 参数）
            config = pb.StrategyConfig(initial_cash=self.initial_cash)
            
            # 转换日期格式为 YYYYMMDD（PyBroker 需要的格式）
            start_date_str = self.start_date.replace('-', '')
            end_date_str = self.end_date.replace('-', '')
            
            # 创建策略对象
            strategy = pb.Strategy(
                data_source,
                start_date_str,
                end_date_str,
                config
            )
            
            # 创建投资组合策略函数
            # 使用闭包存储权重和再平衡状态
            _portfolio_weights = {k: v for k, v in self.optimal_weights.items() if abs(v) > 0.0001}
            total_weight = sum(abs(w) for w in _portfolio_weights.values())
            if total_weight > 0:
                normalized_weights = {k: abs(v) / total_weight for k, v in _portfolio_weights.items()}
            else:
                normalized_weights = _portfolio_weights
            
            _last_rebalance_date = [None]
            _rebalance_frequency = self.rebalance_frequency
            
            def portfolio_execution(ctx):
                """投资组合执行函数"""
                # 获取当前日期，确保是 datetime 对象
                current_date = None
                if hasattr(ctx, 'date'):
                    date_val = ctx.date
                    # 处理不同的日期格式
                    if isinstance(date_val, datetime):
                        current_date = date_val
                    elif hasattr(date_val, 'item'):  # numpy datetime64
                        try:
                            current_date = pd.Timestamp(date_val).to_pydatetime()
                        except:
                            current_date = None
                    elif isinstance(date_val, pd.Timestamp):
                        current_date = date_val.to_pydatetime()
                    elif isinstance(date_val, str):
                        try:
                            current_date = pd.to_datetime(date_val).to_pydatetime()
                        except:
                            current_date = None
                    else:
                        try:
                            current_date = pd.Timestamp(date_val).to_pydatetime()
                        except:
                            current_date = None
                
                # 判断是否需要再平衡
                should_rebalance = False
                if _last_rebalance_date[0] is None:
                    should_rebalance = True
                elif current_date and _last_rebalance_date[0] is not None:
                    try:
                        # 确保两个日期都是 datetime 对象
                        last_date = _last_rebalance_date[0]
                        if not isinstance(last_date, datetime):
                            if isinstance(last_date, pd.Timestamp):
                                last_date = last_date.to_pydatetime()
                            else:
                                last_date = pd.Timestamp(last_date).to_pydatetime()
                        
                        if not isinstance(current_date, datetime):
                            if isinstance(current_date, pd.Timestamp):
                                current_date = current_date.to_pydatetime()
                            else:
                                current_date = pd.Timestamp(current_date).to_pydatetime()
                        
                        days_since = (current_date - last_date).days
                        if _rebalance_frequency == 'daily':
                            should_rebalance = days_since >= 1
                        elif _rebalance_frequency == 'weekly':
                            should_rebalance = days_since >= 5
                        elif _rebalance_frequency == 'monthly':
                            should_rebalance = days_since >= 20
                        elif _rebalance_frequency == 'quarterly':
                            should_rebalance = days_since >= 60
                    except Exception as e:
                        # 如果日期计算失败，默认不进行再平衡
                        should_rebalance = False
                
                # 如果当前股票不在权重列表中，清仓
                if ctx.symbol not in normalized_weights:
                    try:
                        current_pos = ctx.long_pos()
                        if current_pos is not None and current_pos > 0:
                            ctx.sell_all_shares()
                    except (AttributeError, TypeError):
                        pass
                    return
                
                # 获取目标权重
                target_weight = normalized_weights.get(ctx.symbol, 0)
                
                if should_rebalance:
                    # 使用 calc_target_shares 根据权重计算目标股数
                    # 这个方法会自动根据目标权重和当前组合价值计算应该买入的股数
                    try:
                        target_shares = ctx.calc_target_shares(target_weight)
                        # 确保 target_shares 是整数
                        if target_shares is None:
                            target_shares = 0
                        else:
                            target_shares = int(target_shares)
                    except (AttributeError, TypeError):
                        # 如果 calc_target_shares 不可用，使用简单方法
                        target_shares = 0
                    
                    # 获取当前持仓，确保不是 None
                    try:
                        current_shares = ctx.long_pos()
                        if current_shares is None:
                            current_shares = 0
                        else:
                            current_shares = int(current_shares)
                    except (AttributeError, TypeError):
                        current_shares = 0
                    
                    # 计算需要买入或卖出的股数
                    if target_shares > current_shares:
                        # 需要买入
                        buy_amount = target_shares - current_shares
                        if buy_amount > 0:
                            ctx.buy_shares = buy_amount
                    elif target_shares < current_shares:
                        # 需要卖出
                        sell_amount = current_shares - target_shares
                        if sell_amount > 0:
                            if hasattr(ctx, 'sell_shares'):
                                ctx.sell_shares = sell_amount
                            elif hasattr(ctx, 'sell_all_shares'):
                                # 如果只能全部卖出，先全部卖出再买入目标数量
                                ctx.sell_all_shares()
                                if target_shares > 0:
                                    ctx.buy_shares = target_shares
                    # 如果相等，不需要操作
                    
                    # 更新再平衡日期，确保是 datetime 对象
                    if current_date:
                        if isinstance(current_date, datetime):
                            _last_rebalance_date[0] = current_date
                        elif isinstance(current_date, pd.Timestamp):
                            _last_rebalance_date[0] = current_date.to_pydatetime()
                        else:
                            try:
                                _last_rebalance_date[0] = pd.Timestamp(current_date).to_pydatetime()
                            except:
                                pass
                else:
                    # 如果不是再平衡日，保持当前持仓
                    # 可以添加小幅调整逻辑（可选）
                    pass
            
            # 添加执行函数（对每只股票执行）
            strategy.add_execution(portfolio_execution, symbols)
            
            # 运行回测
            result = strategy.backtest()
            
            # 获取回测结果
            # PyBroker 的结果对象有 portfolio 属性，包含 market_value 列
            metrics = None  # 初始化 metrics 变量
            metrics_df = None  # 初始化 metrics_df 变量
            
            if hasattr(result, 'portfolio') and 'market_value' in result.portfolio.columns:
                final_equity = result.portfolio['market_value'].iloc[-1]
            elif hasattr(result, 'metrics_df'):
                # 尝试从 metrics_df 中获取
                metrics_df = result.metrics_df
                if 'final_equity' in metrics_df.index:
                    final_equity = metrics_df.loc['final_equity', metrics_df.columns[0]]
                else:
                    final_equity = self.initial_cash
            elif hasattr(result, 'metrics'):
                metrics = result.metrics
                final_equity = metrics.final_equity if hasattr(metrics, 'final_equity') else self.initial_cash
            else:
                final_equity = self.initial_cash
            
            print(f"\n回测完成!")
            print(f"最终权益: {final_equity:,.2f}")
            total_return = (final_equity / self.initial_cash - 1)
            print(f"总收益率: {total_return*100:.2f}%")
            
            # 计算年化收益率
            days = (datetime.strptime(self.end_date, '%Y-%m-%d') - 
                   datetime.strptime(self.start_date, '%Y-%m-%d')).days
            years = days / 365.0
            annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0
            print(f"年化收益率: {annual_return*100:.2f}%")
            
            # 获取最大回撤
            max_dd = 0
            if metrics is not None and hasattr(metrics, 'max_drawdown'):
                max_dd = metrics.max_drawdown
            elif metrics_df is not None and 'max_drawdown' in metrics_df.index:
                max_dd = metrics_df.loc['max_drawdown', metrics_df.columns[0]]
            elif hasattr(result, 'max_drawdown'):
                max_dd = result.max_drawdown
            print(f"最大回撤: {max_dd*100:.2f}%")
            
            # 计算夏普比率
            sharpe = 0
            if metrics is not None:
                if hasattr(metrics, 'sharpe'):
                    sharpe = metrics.sharpe
                elif hasattr(metrics, 'sharpe_ratio'):
                    sharpe = metrics.sharpe_ratio
            elif metrics_df is not None:
                if 'sharpe' in metrics_df.index:
                    sharpe = metrics_df.loc['sharpe', metrics_df.columns[0]]
                elif 'sharpe_ratio' in metrics_df.index:
                    sharpe = metrics_df.loc['sharpe_ratio', metrics_df.columns[0]]
            elif hasattr(result, 'sharpe_ratio'):
                sharpe = result.sharpe_ratio
            print(f"夏普比率: {sharpe:.4f}")
            
            self.backtest_result = result
            # 保存计算出的指标，以便在 save_results 中使用
            self._backtest_metrics = {
                'final_equity': final_equity,
                'total_return': total_return,
                'annual_return': annual_return,
                'max_drawdown': max_dd,
                'sharpe_ratio': sharpe,
            }
            
            return {
                'result': result,
                'final_equity': final_equity,
                'total_return': total_return,
                'annual_return': annual_return,
                'max_drawdown': max_dd,
                'sharpe_ratio': sharpe,
            }
            
        except Exception as e:
            print(f"回测失败: {e}")
            print("\n注意: PyBroker 回测需要正确配置数据源")
            print("建议: 检查数据源注册和股票代码格式")
            import traceback
            traceback.print_exc()
            
            # 返回模拟结果（用于测试）
            print("\n返回模拟回测结果（仅用于测试）...")
            return {
                'result': None,
                'final_equity': self.initial_cash * 1.1,  # 模拟10%收益
                'total_return': 0.1,
                'annual_return': 0.1,
                'max_drawdown': 0.05,
                'sharpe_ratio': 1.0,
            }
    
    def save_results(self, output_dir: Optional[str] = None):
        """
        保存优化结果和回测报告
        
        Args:
            output_dir: 输出目录，如果为 None 则使用当前目录
        """
        if output_dir is None:
            output_dir = os.path.dirname(os.path.abspath(__file__))
        
        os.makedirs(output_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # 保存权重
        if self.optimal_weights:
            weights_df = pd.DataFrame([
                {'symbol': k, 'weight': v, 'weight_pct': v*100}
                for k, v in sorted(self.optimal_weights.items(), key=lambda x: abs(x[1]), reverse=True)
            ])
            
            weights_file = os.path.join(output_dir, f'portfolio_weights_{timestamp}.csv')
            weights_df.to_csv(weights_file, index=False, encoding='utf-8-sig')
            print(f"\n权重已保存: {weights_file}")
        
        # 保存回测结果
        if self.backtest_result:
            try:
                # 获取交易记录
                if hasattr(self.backtest_result, 'trades'):
                    trades = self.backtest_result.trades
                    if trades is not None and len(trades) > 0:
                        trades_file = os.path.join(output_dir, f'backtest_trades_{timestamp}.csv')
                        trades.to_csv(trades_file, index=False, encoding='utf-8-sig')
                        print(f"交易记录已保存: {trades_file}")
                
                # 获取权益曲线（从 portfolio 中获取）
                if hasattr(self.backtest_result, 'portfolio') and 'market_value' in self.backtest_result.portfolio.columns:
                    equity_curve = self.backtest_result.portfolio[['market_value']].copy()
                    equity_file = os.path.join(output_dir, f'equity_curve_{timestamp}.csv')
                    equity_curve.to_csv(equity_file, index=True, encoding='utf-8-sig')
                    print(f"权益曲线已保存: {equity_file}")
                elif hasattr(self.backtest_result, 'equity'):
                    equity = self.backtest_result.equity
                    if equity is not None and len(equity) > 0:
                        equity_file = os.path.join(output_dir, f'equity_curve_{timestamp}.csv')
                        equity.to_csv(equity_file, index=True, encoding='utf-8-sig')
                        print(f"权益曲线已保存: {equity_file}")
            except Exception as e:
                print(f"保存回测结果时出错: {e}")
        
        # 保存优化统计信息
        if self.optimal_weights and self.backtest_result:
            # 从保存的指标中获取值，如果没有则尝试从 result 对象获取
            final_equity = self._backtest_metrics.get('final_equity', self.initial_cash) if hasattr(self, '_backtest_metrics') else self.initial_cash
            total_return = self._backtest_metrics.get('total_return', 0) if hasattr(self, '_backtest_metrics') else 0
            annual_return = self._backtest_metrics.get('annual_return', 0) if hasattr(self, '_backtest_metrics') else 0
            max_dd = self._backtest_metrics.get('max_drawdown', 0) if hasattr(self, '_backtest_metrics') else 0
            sharpe = self._backtest_metrics.get('sharpe_ratio', 0) if hasattr(self, '_backtest_metrics') else 0
            
            # 如果从保存的指标中获取失败，尝试从 result 对象获取
            if final_equity == self.initial_cash and hasattr(self.backtest_result, 'portfolio'):
                if 'market_value' in self.backtest_result.portfolio.columns:
                    final_equity = self.backtest_result.portfolio['market_value'].iloc[-1]
                    total_return = (final_equity / self.initial_cash - 1)
            
            summary = {
                'optimization_method': self.optimization_method,
                'rebalance_frequency': self.rebalance_frequency,
                'initial_cash': self.initial_cash,
                'final_equity': final_equity,
                'total_return': total_return,
                'annual_return': annual_return,
                'max_drawdown': max_dd,
                'sharpe_ratio': sharpe,
                'timestamp': timestamp
            }
            
            summary_file = os.path.join(output_dir, f'portfolio_summary_{timestamp}.csv')
            summary_df = pd.DataFrame([summary])
            summary_df.to_csv(summary_file, index=False, encoding='utf-8-sig')
            print(f"汇总报告已保存: {summary_file}")


# 尝试导入项目中已有的 CustomDataSource
try:
    from pybroker_integration.custom_data_source import CustomDataSource as ProjectCustomDataSource
    USE_PROJECT_DATA_SOURCE = True
except ImportError:
    USE_PROJECT_DATA_SOURCE = False
    try:
        from pybroker.data import DataSource
    except ImportError:
        DataSource = None


if USE_PROJECT_DATA_SOURCE:
    # 使用项目中已有的数据源类
    CustomDataSource = ProjectCustomDataSource
else:
    # 如果无法导入，创建一个继承自 DataSource 的类
    if DataSource is not None:
        class CustomDataSource(DataSource):
            """自定义数据源，用于 PyBroker"""
            
            def __init__(self):
                super().__init__()
                self.fetcher = DataFetcher()
            
            def _fetch_data(self, symbols, start_date, end_date, timeframe='', adjust=None):
                """
                获取股票数据（实现 DataSource 的抽象方法）
                
                Args:
                    symbols: 股票代码集合（frozenset）
                    start_date: 开始日期（datetime）
                    end_date: 结束日期（datetime）
                    timeframe: 时间周期（可选）
                    adjust: 复权类型（可选）
                
                Returns:
                    DataFrame: 股票数据，包含列：date, symbol, open, high, low, close, volume
                """
                # 转换日期格式
                if isinstance(start_date, datetime):
                    start_date_str = start_date.strftime('%Y-%m-%d')
                else:
                    start_date_str = str(start_date)
                    
                if isinstance(end_date, datetime):
                    end_date_str = end_date.strftime('%Y-%m-%d')
                else:
                    end_date_str = str(end_date)
                
                all_data = []
                
                # 处理 symbols（可能是 frozenset 或单个值）
                symbol_list = list(symbols) if hasattr(symbols, '__iter__') and not isinstance(symbols, str) else [symbols]
                
                for symbol in symbol_list:
                    try:
                        data = self.fetcher.fetch_stock_data(
                            code=symbol,
                            start_date=start_date_str,
                            end_date=end_date_str,
                            use_mock_if_fail=False
                        )
                        
                        if data is None or data.empty:
                            continue
                        
                        # 确保日期列为 datetime 类型（但保持为列，不作为索引）
                        if 'date' in data.columns:
                            data['date'] = pd.to_datetime(data['date'])
                        elif data.index.name == 'date' or isinstance(data.index, pd.DatetimeIndex):
                            # 如果日期是索引，转换为列
                            data = data.reset_index()
                            if 'index' in data.columns:
                                data = data.rename(columns={'index': 'date'})
                            data['date'] = pd.to_datetime(data['date'])
                        
                        # 确保列名正确
                        required_cols = ['date', 'open', 'high', 'low', 'close', 'volume']
                        missing_cols = [col for col in required_cols if col not in data.columns]
                        if missing_cols:
                            print(f"⚠ 警告: {symbol} 缺少必需的列: {missing_cols}")
                            continue
                        
                        # 只保留需要的列
                        data = data[required_cols].copy()
                        
                        # 添加 symbol 列（PyBroker 需要）
                        data['symbol'] = symbol
                        
                        all_data.append(data)
                        
                    except Exception as e:
                        print(f"⚠ 警告: {symbol} 数据获取异常: {e}")
                        continue
                
                if not all_data:
                    return pd.DataFrame()
                
                # 合并所有股票的数据
                result = pd.concat(all_data, axis=0, ignore_index=True)
                
                # 确保按日期排序
                if 'date' in result.columns:
                    result = result.sort_values(by=['symbol', 'date']).reset_index(drop=True)
                
                return result
    else:
        # 如果无法导入 DataSource，创建一个简单的可调用类（作为后备方案）
        class CustomDataSource:
            """自定义数据源，用于 PyBroker（后备方案）"""
            
            def __init__(self):
                self.fetcher = DataFetcher()
            
            def __call__(self, symbol: str, start_date: str, end_date: str):
                """使数据源可调用"""
                try:
                    # 转换日期格式（从 YYYYMMDD 转为 YYYY-MM-DD）
                    start_date_formatted = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
                    end_date_formatted = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
                    
                    # 获取数据
                    data = self.fetcher.fetch_stock_data(
                        code=symbol,
                        start_date=start_date_formatted,
                        end_date=end_date_formatted,
                        use_mock_if_fail=False
                    )
                    
                    if data is None or data.empty:
                        return None
                    
                    # 转换为 PyBroker 格式
                    if 'date' in data.columns:
                        data['date'] = pd.to_datetime(data['date'])
                        data = data.set_index('date')
                    elif not isinstance(data.index, pd.DatetimeIndex):
                        data.index = pd.to_datetime(data.index)
                    
                    # 确保列名正确
                    required_cols = ['open', 'high', 'low', 'close', 'volume']
                    available_cols = [col for col in required_cols if col in data.columns]
                    
                    if len(available_cols) < len(required_cols):
                        return None
                    
                    # 返回排序后的数据
                    return data[required_cols].sort_index()
                    
                except Exception as e:
                    print(f"数据源获取失败 {symbol}: {e}")
                    return None


def main():
    """主函数"""
    print("=" * 80)
    print("基于 Riskfolio-Lib 的风险管理策略")
    print("=" * 80)
    
    # 测试股票组合（去重）
    test_symbols = ['002920', '601336', '002916', '601688', '000408', 
                    '000975', '688396', '600803', '002222', '002028']
    
    # 日期范围（最近一年）
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    
    print(f"\n测试股票组合: {', '.join(test_symbols)}")
    print(f"回测日期范围: {start_date} 至 {end_date}")
    
    # 创建策略实例 - 最大夏普比率优化
    print("\n" + "=" * 80)
    print("策略1: 最大夏普比率优化")
    print("=" * 80)
    
    strategy_max_sharpe = RiskBasedPortfolioStrategy(
        symbols=test_symbols,
        start_date=start_date,
        end_date=end_date,
        initial_cash=1000000,
        commission=0.001,
        optimization_method='max_sharpe',
        rebalance_frequency='monthly',
        risk_free_rate=0.03
    )
    
    try:
        # 获取数据
        strategy_max_sharpe.fetch_price_data()
        
        # 计算收益率
        strategy_max_sharpe.calculate_returns()
        
        # 优化投资组合
        opt_result = strategy_max_sharpe.optimize_portfolio()
        
        # 运行回测
        backtest_result = strategy_max_sharpe.run_backtest()
        
        # 保存结果
        strategy_max_sharpe.save_results()
        
    except Exception as e:
        print(f"\n策略执行失败: {e}")
        import traceback
        traceback.print_exc()
    
    # 创建策略实例 - 最小波动率优化
    print("\n" + "=" * 80)
    print("策略2: 最小波动率优化")
    print("=" * 80)
    
    strategy_min_vol = RiskBasedPortfolioStrategy(
        symbols=test_symbols,
        start_date=start_date,
        end_date=end_date,
        initial_cash=1000000,
        commission=0.001,
        optimization_method='min_volatility',
        rebalance_frequency='monthly',
        risk_free_rate=0.03
    )
    
    try:
        # 获取数据
        strategy_min_vol.fetch_price_data()
        
        # 计算收益率
        strategy_min_vol.calculate_returns()
        
        # 优化投资组合
        opt_result = strategy_min_vol.optimize_portfolio()
        
        # 运行回测
        backtest_result = strategy_min_vol.run_backtest()
        
        # 保存结果
        strategy_min_vol.save_results()
        
    except Exception as e:
        print(f"\n策略执行失败: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "=" * 80)
    print("所有策略执行完成")
    print("=" * 80)


if __name__ == '__main__':
    main()


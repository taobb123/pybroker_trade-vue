#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据验证工具
检查传入图表函数的数据完整性和有效性
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional


def validate_plot_data(data: pd.DataFrame, plot_type: str = "mr") -> Dict[str, Tuple[bool, str]]:
    """
    验证绘图数据的完整性和有效性
    
    Args:
        data: 要验证的DataFrame
        plot_type: 图表类型 ("mr" 或 "ma")
    
    Returns:
        验证结果字典，格式: {检查项: (是否通过, 消息)}
    """
    results = {}
    
    # 1. 基本检查
    if data is None:
        results['data_not_none'] = (False, "数据为None")
        return results
    else:
        results['data_not_none'] = (True, "数据不为None")
    
    if not isinstance(data, pd.DataFrame):
        results['data_type'] = (False, f"数据类型错误: {type(data)}")
        return results
    else:
        results['data_type'] = (True, "数据类型正确: DataFrame")
    
    # 2. 空数据检查
    if data.empty:
        results['data_empty'] = (False, "数据为空")
        return results
    else:
        results['data_empty'] = (True, f"数据不为空: {len(data)} 行")
    
    # 3. 检查必需列
    if plot_type == "mr":
        required_cols = ['close', 'mr_mean', 'mr_std', 'z']
        optional_cols = ['date', 'positions', 'signal']
    elif plot_type == "ma":
        required_cols = ['close']
        optional_cols = ['date', 'ma_short', 'ma_long', 'positions', 'signal']
    else:
        results['plot_type'] = (False, f"未知的图表类型: {plot_type}")
        return results
    
    results['plot_type'] = (True, f"图表类型: {plot_type}")
    
    # 检查必需列
    missing_required = [col for col in required_cols if col not in data.columns]
    if missing_required:
        results['required_columns'] = (False, f"缺少必需列: {missing_required}")
    else:
        results['required_columns'] = (True, f"包含所有必需列: {required_cols}")
    
    # 检查可选列
    missing_optional = [col for col in optional_cols if col not in data.columns]
    if missing_optional:
        results['optional_columns'] = (False, f"缺少可选列: {missing_optional}")
    else:
        results['optional_columns'] = (True, f"包含所有可选列: {optional_cols}")
    
    # 4. 数据有效性检查
    if 'close' in data.columns:
        close_valid = data['close'].notna().any()
        close_all_nan = data['close'].isna().all()
        
        if close_all_nan:
            results['close_validity'] = (False, "close列全为NaN")
        elif not close_valid:
            results['close_validity'] = (False, "close列无有效数据")
        else:
            valid_count = data['close'].notna().sum()
            results['close_validity'] = (True, f"close列有效数据: {valid_count}/{len(data)}")
            
            # 检查数值范围
            if valid_count > 0:
                min_val = data['close'].min()
                max_val = data['close'].max()
                results['close_range'] = (True, f"close范围: [{min_val:.2f}, {max_val:.2f}]")
    
    # MR策略特定检查
    if plot_type == "mr":
        for col in ['mr_mean', 'mr_std', 'z']:
            if col in data.columns:
                col_valid = data[col].notna().any()
                col_all_nan = data[col].isna().all()
                
                if col_all_nan:
                    results[f'{col}_validity'] = (False, f"{col}列全为NaN")
                elif not col_valid:
                    results[f'{col}_validity'] = (False, f"{col}列无有效数据")
                else:
                    valid_count = data[col].notna().sum()
                    results[f'{col}_validity'] = (True, f"{col}列有效数据: {valid_count}/{len(data)}")
    
    # MA策略特定检查
    if plot_type == "ma":
        for col in ['ma_short', 'ma_long']:
            if col in data.columns:
                col_valid = data[col].notna().any()
                if not col_valid:
                    results[f'{col}_validity'] = (False, f"{col}列无有效数据")
                else:
                    valid_count = data[col].notna().sum()
                    results[f'{col}_validity'] = (True, f"{col}列有效数据: {valid_count}/{len(data)}")
    
    # 5. 日期列检查
    if 'date' in data.columns:
        date_valid = data['date'].notna().any()
        if not date_valid:
            results['date_validity'] = (False, "date列无有效数据")
        else:
            valid_count = data['date'].notna().sum()
            results['date_validity'] = (True, f"date列有效数据: {valid_count}/{len(data)}")
            
            # 检查日期格式
            try:
                pd.to_datetime(data['date'].dropna())
                results['date_format'] = (True, "date格式正确")
            except Exception as e:
                results['date_format'] = (False, f"date格式错误: {str(e)}")
    else:
        results['date_validity'] = (False, "缺少date列（可选但推荐）")
    
    # 6. 信号列检查
    if 'positions' in data.columns:
        buy_signals = (data['positions'] > 0).sum()
        sell_signals = (data['positions'] < 0).sum()
        results['signals'] = (True, f"买入信号: {buy_signals}, 卖出信号: {sell_signals}")
    elif 'signal' in data.columns:
        buy_signals = (data['signal'] > 0).sum()
        sell_signals = (data['signal'] < 0).sum()
        results['signals'] = (True, f"买入信号: {buy_signals}, 卖出信号: {sell_signals}")
    else:
        results['signals'] = (False, "缺少信号列（positions或signal）")
    
    # 7. 数据长度一致性检查
    if len(data) > 0:
        results['data_length'] = (True, f"数据长度: {len(data)} 行")
        
        # 检查是否有重复索引
        if data.index.duplicated().any():
            results['index_duplicates'] = (False, "存在重复索引")
        else:
            results['index_duplicates'] = (True, "索引无重复")
    
    # 8. 数据摘要
    results['summary'] = (
        True,
        f"数据形状: {data.shape}, 列数: {len(data.columns)}, 列名: {list(data.columns)}"
    )
    
    return results


def print_validation_results(results: Dict[str, Tuple[bool, str]], title: str = "数据验证结果"):
    """打印验证结果"""
    print("=" * 70)
    print(title)
    print("=" * 70)
    
    passed = 0
    failed = 0
    
    for key, (status, message) in results.items():
        if status:
            symbol = "✓"
            passed += 1
        else:
            symbol = "✗"
            failed += 1
        
        print(f"{symbol} {key}: {message}")
    
    print("-" * 70)
    print(f"总计: {len(results)} 项检查")
    print(f"通过: {passed} 项")
    print(f"失败: {failed} 项")
    print(f"通过率: {passed/len(results)*100:.1f}%")
    print("=" * 70)
    
    return passed == len(results)


def validate_data_for_plot(data: pd.DataFrame, plot_type: str = "mr", 
                          verbose: bool = True) -> bool:
    """
    验证数据并返回是否通过
    
    Args:
        data: 要验证的DataFrame
        plot_type: 图表类型
        verbose: 是否打印详细信息
    
    Returns:
        是否通过验证
    """
    results = validate_plot_data(data, plot_type)
    
    if verbose:
        print_validation_results(results, f"{plot_type.upper()}策略数据验证")
    
    # 检查关键项是否通过
    critical_checks = ['data_not_none', 'data_type', 'data_empty', 'required_columns', 'close_validity']
    
    for check in critical_checks:
        if check in results:
            status, _ = results[check]
            if not status:
                return False
    
    return True


if __name__ == "__main__":
    # 测试
    import sys
    import os
    
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    
    from strategies.mean_reversion import MeanReversionStrategy
    
    # 创建测试数据
    dates = pd.date_range('2024-01-01', periods=50, freq='D')
    prices = np.random.uniform(10, 20, 50)
    test_data = pd.DataFrame({
        'date': dates,
        'open': prices * 0.99,
        'high': prices * 1.02,
        'low': prices * 0.98,
        'close': prices,
        'volume': np.random.uniform(1000000, 5000000, 50),
    })
    
    # 生成信号
    strategy = MeanReversionStrategy()
    sig_df = strategy.generate_signals(test_data)
    
    # 验证MR数据
    validate_data_for_plot(sig_df, plot_type="mr")


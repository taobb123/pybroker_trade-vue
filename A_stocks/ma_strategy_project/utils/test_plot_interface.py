#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
验证 plot_mean_reversion_signals() 绘图接口的正常运行
"""

import sys
import os
import pandas as pd
import numpy as np
from pathlib import Path

# 添加项目路径
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from strategies.mean_reversion import MeanReversionStrategy
from utils.visualization import plot_mean_reversion_signals


def create_test_data(num_days=100):
    """创建测试数据"""
    dates = pd.date_range('2024-01-01', periods=num_days, freq='D')
    
    # 生成模拟价格数据（带趋势和波动）
    np.random.seed(42)
    base_price = 20.0
    trend = np.linspace(0, 2, num_days)
    noise = np.random.normal(0, 1, num_days)
    prices = base_price + trend + np.cumsum(noise * 0.1)
    
    # 确保价格为正
    prices = np.maximum(prices, 1.0)
    
    data = pd.DataFrame({
        'date': dates,
        'open': prices * (1 + np.random.uniform(-0.02, 0.02, num_days)),
        'high': prices * (1 + np.random.uniform(0, 0.03, num_days)),
        'low': prices * (1 - np.random.uniform(0, 0.03, num_days)),
        'close': prices,
        'volume': np.random.uniform(1000000, 5000000, num_days),
    })
    
    return data


def test_plot_interface():
    """测试绘图接口"""
    print("=" * 70)
    print("验证 plot_mean_reversion_signals() 绘图接口")
    print("=" * 70)
    
    # 1. 创建测试数据
    print("\n【步骤1】创建测试数据...")
    test_data = create_test_data(100)
    print(f"✓ 测试数据创建成功: {test_data.shape}")
    print(f"  列: {list(test_data.columns)}")
    
    # 2. 生成策略信号
    print("\n【步骤2】生成策略信号...")
    try:
        strategy = MeanReversionStrategy(window=20, entry_z=2.0, exit_z=0.0)
        sig_df = strategy.generate_signals(test_data)
        print(f"✓ 信号生成成功: {sig_df.shape}")
        
        # 检查必要的列
        required_cols = ['close', 'mr_mean', 'mr_std', 'z', 'date']
        missing_cols = [col for col in required_cols if col not in sig_df.columns]
        if missing_cols:
            print(f"✗ 缺少必要的列: {missing_cols}")
            return False
        else:
            print(f"✓ 包含所有必要列: {required_cols}")
        
        # 检查数据有效性
        if sig_df['close'].isna().all() or sig_df['mr_mean'].isna().all():
            print("✗ 关键数据列全为NaN")
            return False
        
        print(f"✓ 数据有效性检查通过")
        print(f"  买入信号数: {(sig_df['positions'] > 0).sum()}")
        print(f"  卖出信号数: {(sig_df['positions'] < 0).sum()}")
        
    except Exception as e:
        print(f"✗ 信号生成失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    
    # 3. 测试非交互模式
    print("\n【步骤3】测试非交互模式...")
    try:
        result = plot_mean_reversion_signals(
            sig_df,
            outfile="test_mr_chart.png",
            entry_z=2.0,
            exit_z=0.0,
            interactive=False
        )
        
        if result:
            if os.path.exists(result):
                file_size = os.path.getsize(result)
                print(f"✓ 图表文件生成成功: {result}")
                print(f"  文件大小: {file_size} 字节")
                if file_size > 0:
                    print("✓ 文件大小正常")
                else:
                    print("⚠ 文件大小为0，可能有问题")
            else:
                print(f"✗ 文件不存在: {result}")
                return False
        else:
            print("✗ 函数返回空结果")
            return False
            
    except Exception as e:
        print(f"✗ 非交互模式测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    
    # 4. 测试交互模式
    print("\n【步骤4】测试交互模式...")
    try:
        result = plot_mean_reversion_signals(
            sig_df,
            entry_z=2.0,
            exit_z=0.0,
            interactive=True
        )
        
        if result:
            # 检查是否是HTML字符串
            if isinstance(result, str):
                if result.strip().lower().startswith(('<!doctype', '<html', '<div')):
                    print(f"✓ HTML生成成功")
                    print(f"  HTML长度: {len(result)} 字符")
                    
                    # 检查关键元素
                    checks = {
                        'mpld3': 'mpld3' in result.lower(),
                        'svg': '<svg' in result.lower(),
                        'javascript': '<script' in result.lower() or 'javascript' in result.lower(),
                        'tooltip': 'tooltip' in result.lower() or 'PointHTMLTooltip' in result,
                    }
                    
                    print("  关键元素检查:")
                    all_ok = True
                    for key, value in checks.items():
                        status = "✓" if value else "✗"
                        print(f"    {status} {key}: {value}")
                        if not value:
                            all_ok = False
                    
                    if all_ok:
                        print("✓ HTML结构完整")
                    else:
                        print("⚠ HTML结构可能不完整")
                    
                    # 保存HTML用于检查
                    html_file = "test_mr_chart.html"
                    with open(html_file, 'w', encoding='utf-8') as f:
                        f.write(result)
                    print(f"✓ HTML已保存到: {html_file}")
                    
                else:
                    print(f"⚠ 返回的不是标准HTML格式")
                    print(f"  前100字符: {result[:100]}")
            else:
                print(f"✗ 返回类型错误: {type(result)}")
                return False
        else:
            print("✗ 函数返回空结果")
            return False
            
    except Exception as e:
        print(f"✗ 交互模式测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False
    
    # 5. 测试边界情况
    print("\n【步骤5】测试边界情况...")
    
    # 5.1 空数据
    try:
        empty_df = pd.DataFrame()
        result = plot_mean_reversion_signals(empty_df, interactive=False)
        if result == "":
            print("✓ 空数据处理正确（返回空字符串）")
        else:
            print("⚠ 空数据未正确处理")
    except Exception as e:
        print(f"⚠ 空数据测试异常: {str(e)}")
    
    # 5.2 缺少必要列
    try:
        incomplete_df = sig_df[['date', 'close']].copy()
        result = plot_mean_reversion_signals(incomplete_df, interactive=False)
        if result == "":
            print("✓ 缺少列处理正确（返回空字符串）")
        else:
            print("⚠ 缺少列未正确处理")
    except Exception as e:
        print(f"⚠ 缺少列测试异常: {str(e)}")
    
    # 6. 验证数据属性传递
    print("\n【步骤6】验证数据属性传递...")
    try:
        # 设置window属性
        if not hasattr(sig_df, 'attrs'):
            sig_df.attrs = {}
        sig_df.attrs['window'] = 20
        
        result = plot_mean_reversion_signals(
            sig_df,
            entry_z=2.0,
            exit_z=0.0,
            interactive=True
        )
        
        if result and 'window=20' in result or '窗口=20' in result:
            print("✓ 数据属性传递成功")
        else:
            print("⚠ 数据属性可能未正确传递")
            
    except Exception as e:
        print(f"⚠ 属性传递测试异常: {str(e)}")
    
    print("\n" + "=" * 70)
    print("✓ 所有测试完成！")
    print("=" * 70)
    
    return True


if __name__ == "__main__":
    success = test_plot_interface()
    sys.exit(0 if success else 1)


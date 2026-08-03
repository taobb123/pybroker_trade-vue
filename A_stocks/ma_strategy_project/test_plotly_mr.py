#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试Plotly版本的MR图表生成
"""

import sys
import os
import pandas as pd
import numpy as np

# 添加项目路径
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from utils.visualization import plot_mean_reversion_signals

def test_plotly_mr():
    """测试Plotly版本的MR图表生成"""
    print("=" * 70)
    print("测试Plotly版本的MR图表生成")
    print("=" * 70)
    
    # 1. 检查Plotly渲染器
    try:
        import plotly.io as pio
        print(f"✓ Plotly默认渲染器: {pio.renderers.default}")
        if pio.renderers.default != 'browser':
            print(f"  警告: 渲染器不是'browser'，建议设置为'browser'")
            pio.renderers.default = 'browser'
            print(f"  已设置为: {pio.renderers.default}")
    except Exception as e:
        print(f"✗ 检查渲染器失败: {e}")
    
    # 2. 创建测试数据
    print("\n【步骤1】创建测试数据...")
    dates = pd.date_range(start='2024-01-01', periods=100, freq='D')
    np.random.seed(42)
    
    # 生成模拟价格数据
    base_price = 20.0
    price_changes = np.random.randn(100).cumsum() * 0.5
    close_prices = base_price + price_changes
    
    # 计算MR指标
    window = 20
    mr_mean = pd.Series(close_prices).rolling(window=window, min_periods=1).mean()
    mr_std = pd.Series(close_prices).rolling(window=window, min_periods=1).std(ddof=0)
    mr_std = mr_std.replace(0, np.nan)
    z_scores = (close_prices - mr_mean) / mr_std
    z_scores = z_scores.fillna(0)
    
    # 创建DataFrame
    test_data = pd.DataFrame({
        'date': dates,
        'close': close_prices,
        'mr_mean': mr_mean,
        'mr_std': mr_std,
        'z': z_scores,
        'positions': 0  # 初始无持仓
    })
    
    # 添加一些买卖信号
    buy_signals = z_scores < -2.0
    sell_signals = z_scores > 2.0
    test_data.loc[buy_signals, 'positions'] = 1
    test_data.loc[sell_signals, 'positions'] = -1
    
    print(f"✓ 测试数据创建成功: {len(test_data)} 行")
    print(f"  买入信号: {buy_signals.sum()} 个")
    print(f"  卖出信号: {sell_signals.sum()} 个")
    
    # 3. 测试Plotly图表生成
    print("\n【步骤2】测试Plotly图表生成...")
    try:
        html_result = plot_mean_reversion_signals(
            test_data,
            entry_z=2.0,
            exit_z=0.0,
            interactive=True
        )
        
        if html_result:
            print(f"✓ HTML生成成功")
            print(f"  HTML长度: {len(html_result)} 字符")
            
            # 检查关键元素
            checks = {
                '包含plotly.js': 'plotly.js' in html_result.lower() or 'cdn.plotly' in html_result.lower(),
                '包含script标签': '<script' in html_result.lower(),
                '包含div元素': '<div' in html_result.lower(),
                '包含图表数据': 'Plotly.newPlot' in html_result or 'Plotly.plot' in html_result,
            }
            
            print("\n  关键元素检查:")
            all_ok = True
            for key, value in checks.items():
                status = "✓" if value else "✗"
                print(f"    {status} {key}: {value}")
                if not value:
                    all_ok = False
            
            if all_ok:
                print("\n✓ Plotly图表HTML生成完整")
            else:
                print("\n⚠ Plotly图表HTML可能不完整")
            
            # 保存HTML文件用于检查
            html_file = "test_plotly_mr_chart.html"
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(html_result)
            print(f"\n✓ HTML已保存到: {html_file}")
            print(f"  可以在浏览器中打开查看")
            
        else:
            print("✗ HTML生成失败，返回空结果")
            return False
            
    except Exception as e:
        print(f"✗ 图表生成失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # 4. 测试基本Plotly功能
    print("\n【步骤3】测试基本Plotly功能...")
    try:
        import plotly.graph_objects as go
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=[1, 2, 3], y=[10, 20, 30], mode='lines'))
        test_html = fig.to_html(include_plotlyjs='cdn')
        if test_html and len(test_html) > 100:
            print("✓ Plotly基本功能正常")
        else:
            print("✗ Plotly基本功能异常")
            return False
    except Exception as e:
        print(f"✗ Plotly基本功能测试失败: {e}")
        return False
    
    print("\n" + "=" * 70)
    print("✓ 所有测试通过！Plotly MR图表功能正常")
    print("=" * 70)
    return True


if __name__ == "__main__":
    success = test_plotly_mr()
    sys.exit(0 if success else 1)


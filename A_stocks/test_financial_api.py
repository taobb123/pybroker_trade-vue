#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试不同财务数据API接口的可用性
"""

import akshare as ak
import pandas as pd
import time

def test_stock_financial_abstract(code='601888'):
    """测试 stock_financial_abstract 接口"""
    print(f"\n[测试1] stock_financial_abstract - {code}")
    try:
        df = ak.stock_financial_abstract(symbol=code)
        if df is not None and not df.empty:
            print(f"  ✓ 成功: {len(df)} 行, {len(df.columns)} 列")
            print(f"  列名示例: {list(df.columns)[:5]}")
            
            # 检查关键指标
            if '指标' in df.columns:
                indicators = df['指标'].tolist()
                key_indicators = ['净利润', '营业收入', 'ROE', '净资产收益率']
                found = [ind for ind in key_indicators if any(ind in str(i) for i in indicators)]
                print(f"  找到关键指标: {found}")
            
            return True
        else:
            print("  ✗ 返回空数据")
            return False
    except Exception as e:
        print(f"  ✗ 失败: {e}")
        return False

def test_alternative_apis(code='601888'):
    """测试其他可能的接口"""
    print(f"\n[测试2] 其他接口 - {code}")
    
    # 提取纯数字代码
    stock_code = code.replace('SZ', '').replace('SH', '').replace('sz', '').replace('sh', '').strip()
    
    # 可能的接口列表
    api_candidates = [
        ('stock_financial_report_sina', lambda: ak.stock_financial_report_sina(symbol=stock_code)),
        # 添加更多可能的接口
    ]
    
    for api_name, api_func in api_candidates:
        try:
            print(f"  尝试 {api_name}...", end='', flush=True)
            df = api_func()
            if df is not None and not df.empty:
                print(f" ✓ ({len(df)} 行)")
                return True
            else:
                print(" ✗ (空数据)")
        except Exception as e:
            print(f" ✗ ({str(e)[:30]})")
    
    return False

def analyze_available_data(code='601888'):
    """分析获取到的数据"""
    print(f"\n[分析] 数据结构 - {code}")
    try:
        df = ak.stock_financial_abstract(symbol=code)
        if df is None or df.empty:
            print("  ✗ 无数据")
            return
        
        print(f"  数据形状: {df.shape}")
        print(f"  列名: {list(df.columns)[:10]}...")
        
        # 查找日期列
        date_cols = [col for col in df.columns if col != '指标' and (col.isdigit() or '2024' in str(col) or '2023' in str(col))]
        print(f"  日期列: {date_cols[:5]}")
        
        # 查找净利润
        if '指标' in df.columns:
            profit_rows = df[df['指标'].str.contains('净利润', na=False)]
            if not profit_rows.empty:
                print(f"  净利润指标存在: 是")
                # 显示最新一期的净利润
                latest_col = None
                for col in df.columns:
                    if col != '指标' and (col.isdigit() or '2024' in str(col)):
                        if latest_col is None or str(col) > str(latest_col):
                            latest_col = col
                if latest_col:
                    print(f"  最新数据列: {latest_col}")
                    profit_val = profit_rows[latest_col].iloc[0] if len(profit_rows) > 0 else None
                    print(f"  最新净利润值: {profit_val}")
        
    except Exception as e:
        print(f"  ✗ 分析失败: {e}")

if __name__ == '__main__':
    print("="*70)
    print("财务数据API接口测试")
    print("="*70)
    
    # 测试几个不同的股票代码
    test_codes = ['601888', '000001', '600519']
    
    for code in test_codes:
        print(f"\n{'='*70}")
        print(f"测试股票代码: {code}")
        print(f"{'='*70}")
        
        # 测试主接口
        test_stock_financial_abstract(code)
        
        # 分析数据
        analyze_available_data(code)
        
        # 延迟避免频率限制
        time.sleep(1)
    
    print(f"\n{'='*70}")
    print("测试完成")
    print(f"{'='*70}")


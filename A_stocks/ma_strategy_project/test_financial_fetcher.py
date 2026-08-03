#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试财务数据获取模块
"""

import sys
import os

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from data.financial_fetcher import FinancialDataFetcher


def test_single_stock():
    """测试单只股票财务数据获取"""
    print("="*70)
    print("测试：单只股票财务数据获取")
    print("="*70)
    
    with FinancialDataFetcher() as fetcher:
        # 测试不同的股票代码格式
        test_codes = [
            '000001',      # 平安银行（深交所）
            '600519',      # 贵州茅台（上交所）
            'SZ000001',    # 带前缀格式
            'SH600519',    # 带前缀格式
        ]
        
        for code in test_codes:
            print(f"\n{'='*70}")
            print(f"测试股票代码: {code}")
            print(f"{'='*70}")
            
            financial_data = fetcher.get_financial_data(code)
            
            if financial_data:
                print(f"\n✓ 成功获取财务数据")
                print(f"\n关键指标:")
                print(f"  股票代码: {financial_data.get('code', 'N/A')}")
                print(f"  净利润: {financial_data.get('net_profit', 'N/A'):,.0f} 元" 
                      if financial_data.get('net_profit') else f"  净利润: N/A")
                print(f"  营业收入: {financial_data.get('revenue', 'N/A'):,.0f} 元" 
                      if financial_data.get('revenue') else f"  营业收入: N/A")
                print(f"  ROE: {financial_data.get('roe', 'N/A')}%" 
                      if financial_data.get('roe') else f"  ROE: N/A")
                print(f"  ROA: {financial_data.get('roa', 'N/A')}%" 
                      if financial_data.get('roa') else f"  ROA: N/A")
                print(f"  每股收益: {financial_data.get('eps', 'N/A')} 元" 
                      if financial_data.get('eps') else f"  每股收益: N/A")
                print(f"  净利润率: {financial_data.get('profit_margin', 'N/A'):.2f}%" 
                      if financial_data.get('profit_margin') else f"  净利润率: N/A")
                print(f"  总资产: {financial_data.get('total_assets', 'N/A'):,.0f} 元" 
                      if financial_data.get('total_assets') else f"  总资产: N/A")
                print(f"  资产负债率: {financial_data.get('asset_liability_ratio', 'N/A'):.2f}%" 
                      if financial_data.get('asset_liability_ratio') else f"  资产负债率: N/A")
                
                # 统计数据完整性
                total_fields = len(financial_data)
                non_null_fields = len([v for v in financial_data.values() if v is not None])
                print(f"\n数据完整性: {non_null_fields}/{total_fields} 个字段有数据")
            else:
                print(f"\n✗ 获取财务数据失败")
    
    print(f"\n{'='*70}")
    print("测试完成")
    print(f"{'='*70}\n")


def test_cache():
    """测试缓存功能"""
    print("="*70)
    print("测试：缓存功能")
    print("="*70)
    
    with FinancialDataFetcher() as fetcher:
        code = '000001'
        
        print(f"\n第一次获取 {code} 的财务数据（会调用API）...")
        import time
        start = time.time()
        data1 = fetcher.get_financial_data(code)
        time1 = time.time() - start
        print(f"  耗时: {time1:.2f} 秒")
        
        print(f"\n第二次获取 {code} 的财务数据（从缓存读取）...")
        start = time.time()
        data2 = fetcher.get_financial_data(code)
        time2 = time.time() - start
        print(f"  耗时: {time2:.4f} 秒")
        
        if data1 and data2:
            print(f"\n✓ 缓存工作正常")
            print(f"  缓存加速: {time1/time2:.1f}x")
        else:
            print(f"\n✗ 缓存测试失败")


def test_error_handling():
    """测试错误处理"""
    print("="*70)
    print("测试：错误处理")
    print("="*70)
    
    with FinancialDataFetcher() as fetcher:
        # 测试无效代码
        invalid_codes = ['', None, '999999', 'INVALID']
        
        for code in invalid_codes:
            print(f"\n测试无效代码: {code}")
            result = fetcher.get_financial_data(code)
            if result is None:
                print(f"  ✓ 正确处理了无效代码（返回None）")
            else:
                print(f"  ⚠ 警告：无效代码返回了数据")


if __name__ == '__main__':
    print("\n" + "="*70)
    print("财务数据获取模块测试")
    print("="*70 + "\n")
    
    try:
        # 测试1: 单只股票数据获取
        test_single_stock()
        
        # 测试2: 缓存功能
        test_cache()
        
        # 测试3: 错误处理
        test_error_handling()
        
    except KeyboardInterrupt:
        print("\n\n测试被用户中断")
    except Exception as e:
        print(f"\n\n测试过程中出现错误: {e}")
        import traceback
        traceback.print_exc()


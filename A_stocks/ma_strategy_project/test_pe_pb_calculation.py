#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试PE和PB计算功能
"""

import sys
import os

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from utils.financial_metrics import get_financial_display_data

def test_calculation():
    """测试PE/PB计算"""
    print("="*70)
    print("测试：PE和PB计算功能")
    print("="*70)
    
    test_codes = [
        ('000001', 10.0),  # 平安银行
        ('600519', 1500.0),  # 贵州茅台
    ]
    
    for code, price in test_codes:
        print(f"\n测试股票: {code}, 价格: {price}")
        print("-"*70)
        
        info = get_financial_display_data(code, current_price=price)
        
        if info.get('data_available'):
            print("✓ 财务数据获取成功")
            print(f"\n【盈利能力】")
            if info.get('net_profit_yi') is not None:
                print(f"  净利润: {info['net_profit_yi']:.2f} 亿元")
            if info.get('roe') is not None:
                print(f"  ROE: {info['roe']:.2f}%")
            if info.get('profit_margin') is not None:
                print(f"  净利润率: {info['profit_margin']:.2f}%")
            
            print(f"\n【估值指标】")
            if info.get('pe_ratio') is not None:
                print(f"  市盈率(PE): {info['pe_ratio']:.2f}")
            else:
                print(f"  市盈率(PE): 计算失败（缺少必要数据）")
            
            if info.get('pb_ratio') is not None:
                print(f"  市净率(PB): {info['pb_ratio']:.2f}")
            else:
                print(f"  市净率(PB): 计算失败（缺少必要数据）")
            
            if info.get('comprehensive_score') is not None:
                print(f"  综合得分: {info['comprehensive_score']:.4f}")
            
        else:
            print("✗ 财务数据获取失败")
    
    print(f"\n{'='*70}")
    print("测试完成")
    print(f"{'='*70}\n")

if __name__ == '__main__':
    test_calculation()


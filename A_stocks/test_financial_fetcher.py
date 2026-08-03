#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试财务数据获取模块
"""

import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ma_strategy_project.data.financial_fetcher import FinancialDataFetcher

def test_single_stock():
    """测试单只股票财务数据获取"""
    print("="*70)
    print("测试单只股票财务数据获取")
    print("="*70)
    
    fetcher = FinancialDataFetcher()
    
    # 测试不同格式的股票代码
    test_codes = [
        '000001',      # 平安银行 - 纯数字
        'SZ000001',    # 平安银行 - 带市场前缀
        '600519',      # 贵州茅台 - 纯数字
        'SH600519',    # 贵州茅台 - 带市场前缀
    ]
    
    for code in test_codes:
        print(f"\n{'='*70}")
        print(f"测试股票代码: {code}")
        print(f"{'='*70}")
        
        try:
            # 1. 获取全部财务数据
            print("\n[1] 获取全部财务数据...")
            financial_data = fetcher.get_financial_data(code, use_cache=True)
            
            if financial_data:
                print(f"  ✓ 成功获取，共 {len(financial_data)} 个指标")
                report_date = financial_data.get('_report_date', 'N/A')
                print(f"  报告期: {report_date}")
                
                # 显示前10个指标示例
                print("\n  指标示例（前10个）:")
                count = 0
                for key, value in financial_data.items():
                    if key != '_report_date' and count < 10:
                        if isinstance(value, float):
                            if abs(value) > 1e8:
                                print(f"    {key}: {value/1e8:.2f}亿")
                            else:
                                print(f"    {key}: {value}")
                        else:
                            print(f"    {key}: {value}")
                        count += 1
            else:
                print("  ✗ 获取失败")
                continue
            
            # 2. 获取常用指标
            print("\n[2] 获取常用指标...")
            common_indicators = fetcher.get_common_indicators(code)
            
            if common_indicators:
                print("  ✓ 常用指标:")
                indicator_names = {
                    'net_profit': '净利润',
                    'revenue': '营业收入',
                    'roe': 'ROE（净资产收益率）',
                    'roa': 'ROA（总资产收益率）',
                    'eps': '每股收益',
                    'bps': '每股净资产',
                    'profit_margin': '净利润率',
                    'asset_liability_ratio': '资产负债率',
                }
                
                for key, display_name in indicator_names.items():
                    value = common_indicators.get(key)
                    if value is not None:
                        if key in ['net_profit', 'revenue', 'total_assets', 'total_liabilities']:
                            if abs(value) > 1e8:
                                print(f"    {display_name}: {value/1e8:.2f}亿")
                            elif abs(value) > 1e4:
                                print(f"    {display_name}: {value/1e4:.2f}万")
                            else:
                                print(f"    {display_name}: {value:.2f}")
                        elif key in ['roe', 'roa', 'profit_margin', 'asset_liability_ratio']:
                            print(f"    {display_name}: {value:.2f}%")
                        else:
                            print(f"    {display_name}: {value:.4f}")
                else:
                    print(f"    （部分指标未获取到）")
            else:
                print("  ✗ 无法获取常用指标")
            
            # 3. 测试获取单个指标
            print("\n[3] 测试获取单个指标...")
            net_profit = fetcher.get_financial_indicator(
                code, 
                '净利润',
                aliases=['净利润', '净利润(元)', '归母净利润']
            )
            if net_profit:
                print(f"  ✓ 净利润: {net_profit/1e8:.2f}亿")
            else:
                print("  ✗ 未找到净利润指标")
            
            roe = fetcher.get_financial_indicator(code, 'ROE', aliases=['净资产收益率(ROE)', 'ROE'])
            if roe:
                print(f"  ✓ ROE: {roe:.2f}%")
            else:
                print("  ✗ 未找到ROE指标")
        
        except Exception as e:
            print(f"  ✗ 测试失败: {e}")
            import traceback
            traceback.print_exc()
        
        print()
    
    # 显示缓存信息
    print(f"{'='*70}")
    print("缓存信息:")
    cache_info = fetcher.get_cache_info()
    print(f"  缓存股票数: {cache_info['cached_count']}")
    print(f"  已缓存代码: {cache_info['cached_codes']}")
    print(f"{'='*70}")


def test_code_normalization():
    """测试代码标准化功能"""
    print("\n" + "="*70)
    print("测试代码标准化")
    print("="*70)
    
    fetcher = FinancialDataFetcher()
    
    test_cases = [
        ('000001', 'sz000001'),
        ('SZ000001', 'sz000001'),
        ('sz000001', 'sz000001'),
        ('600519', 'sh600519'),
        ('SH600519', 'sh600519'),
        ('300979', 'sz300979'),
    ]
    
    for input_code, expected in test_cases:
        result = fetcher.normalize_stock_code(input_code)
        status = "✓" if result == expected else "✗"
        print(f"{status} {input_code:12} -> {result:12} (期望: {expected})")


if __name__ == '__main__':
    print("\n" + "="*70)
    print("财务数据获取模块测试")
    print("="*70 + "\n")
    
    # 测试代码标准化
    test_code_normalization()
    
    # 测试单只股票数据获取
    test_single_stock()
    
    print("\n" + "="*70)
    print("测试完成！")
    print("="*70 + "\n")


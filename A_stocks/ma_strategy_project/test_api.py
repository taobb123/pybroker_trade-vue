#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试API数据源接入
"""

# 该文件为手动联通性测试脚本。为避免在 pytest 收集阶段因包上下文导致导入错误，
# 在自动化测试中直接跳过本模块的收集。
try:
    import pytest  # type: ignore
    if __name__ != "__main__":
        pytest.skip("skip manual API connectivity test during pytest collection", allow_module_level=True)
except Exception:
    # 非 pytest 场景正常继续
    pass

from .data.fetcher import DataFetcher
from .utils.logger import logger

def test_api_connection():
    """测试API连接"""
    print("\n" + "="*70)
    print("API数据源测试")
    print("="*70)
    
    fetcher = DataFetcher()
    
    # 测试参数
    test_code = '000001'  # 平安银行
    start_date = '2024-01-01'
    end_date = '2024-12-31'
    
    print(f"\n测试股票: {test_code}")
    print(f"日期范围: {start_date} 至 {end_date}\n")
    
    # 测试1: akshare
    print("[1] 测试 akshare API...")
    try:
        df = fetcher._fetch_from_akshare(test_code, start_date, end_date)
        if df is not None and not df.empty:
            print(f"[OK] akshare 连接成功！")
            print(f"  获取数据: {len(df)} 条")
            print(f"  日期范围: {df['date'].min()} 至 {df['date'].max()}")
            print(f"  最新价格: {df['close'].iloc[-1]:.2f}")
        else:
            print("[FAIL] akshare 返回空数据")
    except Exception as e:
        print(f"[FAIL] akshare 测试失败: {e}")
    
    print()
    
    # 测试2: tushare
    print("[2] 测试 tushare API...")
    try:
        df = fetcher._fetch_from_tushare(test_code, start_date, end_date)
        if df is not None and not df.empty:
            print(f"[OK] tushare 连接成功！")
            print(f"  获取数据: {len(df)} 条")
            print(f"  日期范围: {df['date'].min()} 至 {df['date'].max()}")
            print(f"  最新价格: {df['close'].iloc[-1]:.2f}")
        else:
            print("[FAIL] tushare 未配置或返回空数据")
            print("  提示: 如需使用tushare，请在config/settings.py中配置token")
    except Exception as e:
        print(f"[FAIL] tushare 测试失败: {e}")
    
    print()
    
    # 测试3: 完整的fetch_stock_data（混合方案）
    print("[3] 测试完整数据获取流程（数据库 → API → 模拟数据）...")
    try:
        df = fetcher.fetch_stock_data(
            code=test_code,
            start_date=start_date,
            end_date=end_date,
            use_mock_if_fail=True
        )
        
        if df is not None and not df.empty:
            print(f"[OK] 数据获取成功！")
            print(f"  获取数据: {len(df)} 条")
            print(f"  日期范围: {df['date'].min()} 至 {df['date'].max()}")
            print(f"  数据列: {df.columns.tolist()}")
            print(f"\n  数据样例（前5条）:")
            print(df[['date', 'open', 'close', 'volume']].head().to_string(index=False))
        else:
            print("[FAIL] 数据获取失败")
    except Exception as e:
        print(f"[FAIL] 数据获取失败: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "="*70)
    print("测试完成")
    print("="*70 + "\n")

if __name__ == '__main__':
    test_api_connection()






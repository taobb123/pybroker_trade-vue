#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析交易记录，计算总收益和盈亏比
"""

import pandas as pd
import os

# 读取交易记录
script_dir = os.path.dirname(os.path.abspath(__file__))
csv_file = os.path.join(script_dir, 'factor_investing_trades.csv')

df = pd.read_csv(csv_file)

print("=" * 80)
print("交易记录分析")
print("=" * 80)
print(f"总交易数: {len(df)}")
print(f"\n最后5条记录:")
print(df[['symbol', 'entry_date', 'exit_date', 'pnl', 'agg_pnl', 'return_pct']].tail().to_string())

print("\n" + "=" * 80)
print("总盈亏统计")
print("=" * 80)

# 总盈亏：使用最后一条记录的 agg_pnl（累计盈亏）
total_pnl = df['agg_pnl'].iloc[-1] if len(df) > 0 else 0
total_pnl_sum = df['pnl'].sum()  # 所有单笔盈亏的总和（应该等于最后的agg_pnl）

print(f"单笔盈亏总和 (所有pnl相加): {total_pnl_sum:.2f} 元")
print(f"最后一条记录的累计盈亏 (agg_pnl): {total_pnl:.2f} 元")
print(f"\n总盈亏: {total_pnl:.2f} 元 ({'盈利' if total_pnl > 0 else '亏损' if total_pnl < 0 else '持平'})")

# 计算盈亏比
wins = df[df['pnl'] > 0]
losses = df[df['pnl'] < 0]
breakeven = df[df['pnl'] == 0]

print("\n" + "=" * 80)
print("盈亏比计算")
print("=" * 80)
print(f"盈利交易数: {len(wins)}")
print(f"亏损交易数: {len(losses)}")
print(f"持平交易数: {len(breakeven)}")
print(f"胜率: {len(wins) / len(df) * 100:.2f}%")

if len(wins) > 0:
    avg_win = wins['pnl'].mean()
    total_win = wins['pnl'].sum()
    print(f"\n平均盈利: {avg_win:.2f} 元")
    print(f"总盈利: {total_win:.2f} 元")
    print(f"最大单笔盈利: {wins['pnl'].max():.2f} 元")
else:
    avg_win = 0
    total_win = 0

if len(losses) > 0:
    avg_loss = abs(losses['pnl'].mean())
    total_loss = abs(losses['pnl'].sum())
    print(f"\n平均亏损: {avg_loss:.2f} 元")
    print(f"总亏损: {total_loss:.2f} 元")
    print(f"最大单笔亏损: {abs(losses['pnl'].min()):.2f} 元")
else:
    avg_loss = 0
    total_loss = 0

# 盈亏比 = 平均盈利 / 平均亏损
if avg_loss > 0:
    profit_loss_ratio = avg_win / avg_loss
    print(f"\n盈亏比 (平均盈利/平均亏损): {profit_loss_ratio:.2f}")
else:
    print(f"\n盈亏比: 无法计算（没有亏损交易）")

# 期望值 = 胜率 * 平均盈利 - (1-胜率) * 平均亏损
if len(df) > 0:
    win_rate = len(wins) / len(df)
    expected_value = win_rate * avg_win - (1 - win_rate) * avg_loss
    print(f"期望值: {expected_value:.2f} 元/笔")

print("\n" + "=" * 80)
print("说明:")
print("=" * 80)
print("1. pnl: 单笔交易的盈亏金额")
print("2. agg_pnl: 累计盈亏（从开始到该笔交易结束时的总盈亏）")
print("3. 总盈亏 = 最后一条记录的 agg_pnl 值")
print("4. 盈亏比 = 平均盈利 / 平均亏损（大于1表示策略有效）")
print("=" * 80)

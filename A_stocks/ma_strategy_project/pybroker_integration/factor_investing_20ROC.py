#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对 stocks_pool.txt 股票池，在全市场同一最近交易日截面上计算 20 日 ROC，
按 ROC 降序取前 20，输出到控制台作为「收益率 / 动量」维度的因子暴露参考。
数据源：create_custom_data_source（沿用 DATA_CONFIG / DataFetcher）
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List

import numpy as np
import pandas as pd
import talib as ta

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config.settings import DATA_CONFIG
from pybroker_integration.custom_data_source import create_custom_data_source

try:
    import tushare as ts
except ImportError:
    ts = None

ROC_PERIOD = 20
TOP_N = 20
LOOKBACK_CALENDAR_DAYS = 80


def load_stock_pool(file_path: str) -> List[str]:
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read().strip()
    return [s.strip() for s in content.replace('\n', ' ').split() if s.strip()]


def get_stock_names(symbols: List[str]) -> Dict[str, str]:
    """与 factor_Investing_signal 一致：tushare stock_basic 批量映射代码->名称。"""
    out: Dict[str, str] = {}
    if not symbols:
        return out
    if ts is None:
        return {s: s for s in symbols}
    token = (DATA_CONFIG or {}).get('tushare_token', '') or ''
    if not token:
        return {s: s for s in symbols}
    try:
        pro = ts.pro_api(token)
        df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name')
        code_to_name: Dict[str, str] = {}
        for _, row in df.iterrows():
            ts_code = row['ts_code']
            name = row['name']
            code_to_name[ts_code.split('.')[0]] = name
            code_to_name[ts_code] = name
        for symbol in symbols:
            if symbol in code_to_name:
                out[symbol] = code_to_name[symbol]
            elif len(symbol) == 6 and symbol.isdigit():
                suf = f'{symbol}.SH' if symbol.startswith(('60', '68')) else (
                    f'{symbol}.SZ' if symbol.startswith(('00', '30')) else symbol
                )
                out[symbol] = code_to_name.get(suf, symbol)
            else:
                out[symbol] = symbol
    except Exception:
        for s in symbols:
            out.setdefault(s, s)
    return out


def _roc_at_unified_date(g: pd.DataFrame, asof_ts: pd.Timestamp) -> float | None:
    """在单标的序列上，仅当最后交易日等于统一截面日且 бар 足够时返回 ROC(20)。"""
    g = g.sort_values('date').reset_index(drop=True)
    if g.empty:
        return None
    last = pd.Timestamp(g['date'].iloc[-1]).normalize()
    if last != asof_ts.normalize():
        return None
    close = g['close'].astype(float).values
    if len(close) < ROC_PERIOD + 1:
        return None
    roc = ta.ROC(close, timeperiod=ROC_PERIOD)
    val = float(roc[-1])
    if np.isnan(val):
        return None
    return val


def _exposure_weights(rocs: List[float]) -> List[float]:
    """Top 组内相对暴露：非负 ROC 归一；若全非正则平移后再归一。"""
    r = np.array(rocs, dtype=float)
    pos = np.maximum(r, 0.0)
    s = float(pos.sum())
    if s > 0:
        return (pos / s).tolist()
    shifted = r - r.min()
    s2 = float(shifted.sum())
    if s2 <= 0:
        return [1.0 / len(r)] * len(r)
    return (shifted / s2).tolist()


def _parse_args() -> argparse.Namespace:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_pool = os.path.join(script_dir, 'stocks_pool.txt')
    p = argparse.ArgumentParser(description='20 日 ROC 截面排序（Top N）')
    p.add_argument(
        '--pool',
        default=default_pool,
        help='股票池 txt 路径（每行或空格分隔 6 位代码）',
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    pool_file = os.path.abspath(os.path.expanduser(args.pool))
    if not os.path.isfile(pool_file):
        print(f'股票池文件不存在: {pool_file}')
        return
    symbols = load_stock_pool(pool_file)
    if not symbols:
        print('股票池为空，退出。')
        return

    end = datetime.now()
    start = end - timedelta(days=LOOKBACK_CALENDAR_DAYS)

    data_source = create_custom_data_source()
    df = data_source._fetch_data(frozenset(symbols), start, end)
    if df is None or df.empty:
        print('未获取到任何行情数据，退出。')
        return

    df = df.copy()
    df['date'] = pd.to_datetime(df['date'])
    asof = df['date'].max()
    asof_ts = pd.Timestamp(asof).normalize()

    rows = []
    for sym, g in df.groupby('symbol'):
        roc_val = _roc_at_unified_date(g, asof_ts)
        if roc_val is None:
            continue
        rows.append({'symbol': sym, 'roc_20': roc_val})

    if not rows:
        print(f'截面日 {asof_ts.date()}：无可用 ROC(20) 标的（需当日有 K 且历史足够）。')
        return

    out = pd.DataFrame(rows)
    out = out.sort_values('roc_20', ascending=False).head(TOP_N).reset_index(drop=True)
    weights = _exposure_weights(out['roc_20'].tolist())
    name_map = get_stock_names(out['symbol'].tolist())

    print('=' * 92)
    print('收益率因子暴露（20 日 ROC 截面 | 统一最近交易日）')
    print(f"截面交易日: {asof_ts.date()}  |  池文件: {pool_file}")
    print(f"股票池: {len(symbols)}，有效参与排名: {len(rows)}，输出 Top {TOP_N}")
    print('=' * 92)
    print(f"{'排名':<6}{'代码':<10}{'名称':<14}{'ROC20':>12}{'暴露权重(组内)':>18}")
    print('-' * 92)
    for i, (_, r) in enumerate(out.iterrows(), 1):
        nm = name_map.get(r['symbol'], r['symbol'])
        if len(nm) > 12:
            nm = nm[:11] + '…'
        print(f"{i:<6}{r['symbol']:<10}{nm:<14}{r['roc_20']:>12.4f}{weights[i - 1]:>18.4f}")
    print('=' * 92)
    rank_rows = []
    for i, (_, r) in enumerate(out.iterrows(), 1):
        sym = str(r['symbol'])
        rank_rows.append({
            'rank': i,
            'symbol': sym,
            'name': name_map.get(sym, sym),
            'roc_20': round(float(r['roc_20']), 4),
            'weight': round(float(weights[i - 1]), 4),
        })
    rank_payload = {
        'asof': str(asof_ts.date()),
        'pool': pool_file,
        'top_n': TOP_N,
        'rows': rank_rows,
    }
    print('ROC20_RANK_JSON:' + json.dumps(rank_payload, ensure_ascii=False))


if __name__ == '__main__':
    main()

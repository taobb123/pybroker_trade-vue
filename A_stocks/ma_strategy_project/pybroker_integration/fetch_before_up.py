#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
读取 CSV 股票列表（默认 fetch_a_share_spot_compare_prices.csv），按「相对脚本运行自然日的前一交易日」
日线涨跌幅排序，在控制台打印前 N 名（不写 CSV）。

前一交易日规则（与 A 股 SSE 交易日历一致）：
- 若运行当日为交易日：取「上一交易日」的 Tushare 日线 pct_chg。
- 若运行当日非交易日：取「不晚于运行日的最近一个交易日」的涨跌幅。

依赖：config.settings.DATA_CONFIG['tushare_token']（trade_cal + daily）。

用法（在 ma_strategy_project 目录下）：
    python pybroker_integration/fetch_before_up.py
    python pybroker_integration/fetch_before_up.py --table pybroker_integration/optimal_base_cost.csv
    python pybroker_integration/fetch_before_up.py --top 5
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from backtest_sy_002028_threshold import fetch_stock_name
from optimal_base_cost_store import load_optimal_base_table

DEFAULT_STOCK_LIST_CSV = os.path.join(_SCRIPT_DIR, "fetch_a_share_spot_compare_prices.csv")


def _try_tushare_pro():
    try:
        from config.settings import DATA_CONFIG
    except ImportError:
        return None
    token = ((DATA_CONFIG or {}).get("tushare_token") or "").strip()
    if not token:
        return None
    try:
        import tushare as ts

        ts.set_token(token)
        return ts.pro_api()
    except Exception:
        return None


def _six_digit_to_ts_code(code: str) -> str:
    c = "".join(filter(str.isdigit, str(code))).zfill(6)
    if c.startswith("6"):
        return f"{c}.SH"
    if c.startswith(("8", "4")):
        return f"{c}.BJ"
    return f"{c}.SZ"


def _fetch_sse_open_days(pro, start_compact: str, end_compact: str) -> List[pd.Timestamp]:
    try:
        cal = pro.trade_cal(exchange="SSE", start_date=start_compact, end_date=end_compact, is_open="1")
    except Exception:
        return []
    if cal is None or cal.empty:
        return []
    dates = pd.to_datetime(cal["cal_date"].astype(str), format="%Y%m%d", errors="coerce")
    return sorted(dates.dropna().dt.normalize().unique().tolist())


def _target_trade_day_for_run_date(run_day: pd.Timestamp, open_days: List[pd.Timestamp]) -> Optional[pd.Timestamp]:
    if not open_days:
        return None
    run_n = run_day.normalize()
    opens = [d for d in open_days if d <= run_n]
    if not opens:
        return None
    if run_n in opens:
        if len(opens) < 2:
            return None
        return opens[-2]
    return opens[-1]


def _daily_on_trade_date(pro, trade_compact: str) -> pd.DataFrame:
    try:
        df = pro.daily(trade_date=trade_compact)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    return df


def run_print_top_prev_day_pct(table_path: str, *, top_n: int) -> None:
    pro = _try_tushare_pro()
    if pro is None:
        print("错误: 未配置 tushare_token（config.settings.DATA_CONFIG），无法拉取交易日历与日线。", file=sys.stderr)
        return

    run_day = pd.Timestamp.today().normalize()
    start_c = (run_day - pd.Timedelta(days=120)).strftime("%Y%m%d")
    end_c = run_day.strftime("%Y%m%d")
    open_days = _fetch_sse_open_days(pro, start_c, end_c)
    target_day = _target_trade_day_for_run_date(run_day, open_days)
    if target_day is None:
        print("错误: 无法根据当前日期推断前一交易日（日历数据不足或非交易日边界）。", file=sys.stderr)
        return
    target_compact = target_day.strftime("%Y%m%d")

    df = load_optimal_base_table(table_path)
    if df.empty:
        print(f"表为空或不存在: {table_path}")
        return

    syms = (
        df["symbol"]
        .astype(str)
        .map(lambda x: "".join(filter(str.isdigit, x)).zfill(6))
        .unique()
        .tolist()
    )
    want_ts = {_six_digit_to_ts_code(s) for s in syms}

    daily_all = _daily_on_trade_date(pro, target_compact)
    if daily_all.empty:
        print(f"错误: trade_date={target_compact} 未取到日线数据。", file=sys.stderr)
        return

    pct_col = "pct_chg" if "pct_chg" in daily_all.columns else "pct_change"
    if pct_col not in daily_all.columns:
        print("错误: 日线结果中无 pct_chg / pct_change 字段。", file=sys.stderr)
        return

    sub = daily_all[daily_all["ts_code"].astype(str).isin(want_ts)].copy()
    sub["pct_val"] = pd.to_numeric(sub[pct_col], errors="coerce")
    sub = sub.dropna(subset=["pct_val"])
    if sub.empty:
        print(f"提示: 在 {target_compact} 日线中未匹配到表内任何 ts_code（共表内 {len(syms)} 只）。")
        return

    sub["code6"] = sub["ts_code"].astype(str).str.split(".").str[0].str.zfill(6)
    name_map = {
        str(r["symbol"]).zfill(6): str(r.get("stock_name", "") or "").strip()
        for _, r in df.iterrows()
    }

    n_matched = len(sub)
    best = sub.sort_values("pct_val", ascending=False, na_position="last").head(max(1, int(top_n)))

    print(f"运行日(自然日): {run_day.strftime('%Y-%m-%d')}  |  用于排序的交易日: {target_day.strftime('%Y-%m-%d')}（日线）")
    print(f"股票列表: {os.path.abspath(table_path)}  |  表内股票数: {len(syms)}  |  当日有行情匹配数: {n_matched}")
    print(f"涨幅前 {min(top_n, len(best))} 名（{pct_col}，单位与 Tushare 一致）:")
    print("-" * 72)
    for i, row in enumerate(best.itertuples(index=False), start=1):
        code6 = str(row.code6)
        pct = float(row.pct_val)
        nm = name_map.get(code6, "") or fetch_stock_name(code6)
        label = f"{nm}({code6})" if nm else code6
        print(f"  {i}. {label}  {pct:.4f}%")
    print("-" * 72)


def main() -> None:
    parser = argparse.ArgumentParser(description="股票列表：前一交易日日线涨幅排序（仅控制台）")
    parser.add_argument(
        "--table",
        default=DEFAULT_STOCK_LIST_CSV,
        help=f"含 symbol 的 CSV 路径（默认 {DEFAULT_STOCK_LIST_CSV}）",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=5,
        help="打印涨幅前 N 名（默认 5）",
    )
    args = parser.parse_args()
    run_print_top_prev_day_pct(args.table, top_n=args.top)


if __name__ == "__main__":
    main()

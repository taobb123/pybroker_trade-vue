#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多标的 MA20 网格轮动回测（与 backtest_sy_002028_threshold 的数据与费用口径对齐）。

规则摘要：
- 基准：每只股票用前复权收盘的 MA20（T 日基准 = 截至 T-1 的 20 日均值，避免用当日收盘做均线）。
- 网格价位：买入区间 3%~5% 取中点 -4%；卖出区间 7%~13% 取中点 +10%。
- 触发：盘中触及——买入 low<=buy_price<=high；卖出 high>=sell_price（与单标的阈值脚本一致）。
- 最多同时持有 2 只股票；若同日多于 2 只满足买入触及，按当日振幅 (ma20-low)/ma20 降序优先。
- 334：按「全账户」以初始资金为基数循环 30%/30%/40%，每笔买入至多使用该档金额（向下取整到 100 股）。
- 卖出：清空该标的持仓；仅卖出端印花税 0.05%。
- 股票池：同目录 stocks_pool.txt（一行一只，空行与 # 注释忽略）。
- 结果：写入 rotation_trade_result.csv（utf-8-sig）：首行 record_type=summary 为汇总（含 trade_count），其后每行 record_type=trade 为逐笔成交。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from backtest_sy_002028_threshold import (  # noqa: E402
    STAMP_DUTY_RATE,
    fetch_ohlc_qfq,
)
INITIAL_CASH = 50_000.0
MAX_SYMBOL_POSITIONS = 2
LOT = 100
# 买入 3%~5% 中点、卖出 7%~13% 中点
BUY_OFFSET = 0.04
SELL_OFFSET = 0.10
TRANCHES = (0.30, 0.30, 0.40)

RESULT_CSV = os.path.join(_SCRIPT_DIR, "rotation_trade_result.csv")
DEFAULT_POOL_TXT = os.path.join(_SCRIPT_DIR, "stocks_pool.txt")

TRADE_RECORD_COLUMNS = [
    "date",
    "symbol",
    "action",
    "exec_price",
    "shares",
    "shares_after",
    "cash_before",
    "cash_after",
    "stamp_duty",
]


def build_rotation_result_dataframe(summary: Dict, trade_rows: List[Dict]) -> pd.DataFrame:
    """首行汇总 + 后续逐笔，列并集；逐笔行汇总列为空，汇总行逐笔列为空。"""
    sk = list(summary.keys())
    srow: Dict = {"record_type": "summary", **summary}
    for c in TRADE_RECORD_COLUMNS:
        srow[c] = ""
    rows: List[Dict] = [srow]
    for tr in trade_rows:
        row = {k: "" for k in sk}
        row["record_type"] = "trade"
        for c in TRADE_RECORD_COLUMNS:
            v = tr.get(c, "")
            row[c] = "" if v is None else v
        rows.append(row)
    col_order = ["record_type"] + sk + TRADE_RECORD_COLUMNS
    return pd.DataFrame(rows)[col_order]


def _to_float(x) -> float:
    try:
        return float(x)
    except Exception:
        return float("nan")


def load_symbols_from_pool_file(pool_path: str) -> List[str]:
    """从文本文件加载股票代码：一行一只，忽略空行与 # 注释（与 rotation_trade.py 一致）。"""
    if not os.path.isfile(pool_path):
        raise FileNotFoundError(f"股票池文件不存在: {pool_path}")
    symbols: List[str] = []
    with open(pool_path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            symbols.append(s)
    return symbols


def _prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    for col in ("open", "high", "low", "close"):
        if col in d.columns:
            d[col] = d[col].apply(_to_float)
    d = d.sort_values("date").reset_index(drop=True)
    # 基准：截至昨收的 MA20
    d["ma20"] = d["close"].rolling(20).mean().shift(1)
    d["buy_price"] = (d["ma20"] * (1.0 - BUY_OFFSET)).round(2)
    d["sell_price"] = (d["ma20"] * (1.0 + SELL_OFFSET)).round(2)
    return d


def backtest_rotation_grid(
    symbols: List[str],
    start_date: str,
    end_date: str,
    initial_cash: float = INITIAL_CASH,
    *,
    pool_file: str = "stocks_pool.txt",
) -> Dict:
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)
    # 向前多取约 90 个自然日，保证回测起点起 MA20 已稳定
    warm_start = (start_ts - pd.Timedelta(days=90)).strftime("%Y-%m-%d")

    per_sym: Dict[str, pd.DataFrame] = {}
    all_dates: set = set()
    for sym in symbols:
        try:
            raw = fetch_ohlc_qfq(sym, warm_start, end_date)
        except Exception:
            continue
        if raw is None or raw.empty:
            continue
        prep = _prepare_frame(raw)
        prep = prep.dropna(subset=["ma20", "buy_price", "sell_price"])
        prep = prep[(prep["date"] >= start_ts) & (prep["date"] <= end_ts)]
        if prep.empty:
            continue
        per_sym[sym] = prep.set_index("date")
        all_dates.update(prep["date"].tolist())

    if not per_sym:
        raise RuntimeError("股票池无有效行情数据，请检查日期区间与数据源。")

    dates = sorted(all_dates)
    cash = float(initial_cash)
    positions: Dict[str, int] = {s: 0 for s in per_sym}
    tranche_i = 0
    stamp_duty_total = 0.0
    trades: List[Dict] = []

    for dt in dates:
        date_str = pd.Timestamp(dt).strftime("%Y-%m-%d")
        rows: Dict[str, pd.Series] = {}
        for sym, sdf in per_sym.items():
            if dt in sdf.index:
                rows[sym] = sdf.loc[dt]

        # ---------- 先卖 ----------
        for sym in list(per_sym.keys()):
            sh = positions.get(sym, 0)
            if sh <= 0 or sym not in rows:
                continue
            r = rows[sym]
            high = _to_float(r["high"])
            sell_p = _to_float(r["sell_price"])
            if high >= sell_p:
                cash_before = cash
                gross = sh * sell_p
                duty = gross * STAMP_DUTY_RATE
                stamp_duty_total += duty
                cash += gross - duty
                positions[sym] = 0
                trades.append(
                    {
                        "date": date_str,
                        "symbol": sym,
                        "action": "SELL",
                        "exec_price": sell_p,
                        "shares": sh,
                        "shares_after": 0,
                        "cash_before": cash_before,
                        "cash_after": cash,
                        "stamp_duty": duty,
                    }
                )

        # ---------- 再买：收集候选 ----------
        candidates: List[Tuple[str, float, float]] = []
        for sym, r in rows.items():
            low = _to_float(r["low"])
            high = _to_float(r["high"])
            buy_p = _to_float(r["buy_price"])
            ma = _to_float(r["ma20"])
            if ma <= 0 or not (low <= buy_p <= high):
                continue
            amp = (ma - low) / ma
            candidates.append((sym, amp, buy_p))

        candidates.sort(key=lambda x: x[1], reverse=True)

        for sym, _amp, buy_p in candidates:
            sh = positions.get(sym, 0)
            is_new = sh == 0
            if is_new and sum(1 for s, v in positions.items() if v > 0) >= MAX_SYMBOL_POSITIONS:
                continue

            budget = TRANCHES[tranche_i % 3] * float(initial_cash)
            spend_cap = min(budget, cash)
            if spend_cap < buy_p * LOT:
                continue
            add_sh = int(spend_cap // buy_p // LOT) * LOT
            if add_sh < LOT:
                continue
            cost = add_sh * buy_p
            if cost > cash + 1e-9:
                continue
            cash_before = cash
            cash -= cost
            positions[sym] = sh + add_sh
            tranche_i += 1
            trades.append(
                {
                    "date": date_str,
                    "symbol": sym,
                    "action": "BUY",
                    "exec_price": buy_p,
                    "shares": add_sh,
                    "shares_after": sh + add_sh,
                    "cash_before": cash_before,
                    "cash_after": cash,
                    "stamp_duty": 0.0,
                }
            )

    last_dt = dates[-1]
    mkt = 0.0
    for sym, sdf in per_sym.items():
        if last_dt not in sdf.index:
            continue
        c = _to_float(sdf.loc[last_dt]["close"])
        mkt += positions.get(sym, 0) * c
    end_assets = cash + mkt
    ret_pct = (end_assets - float(initial_cash)) / float(initial_cash) * 100.0

    return {
        "strategy": "rotation_grid_ma20",
        "pool_file": os.path.basename(pool_file),
        "symbol_count": len(symbols),
        "tradeable_symbol_count": len(per_sym),
        "start_date": start_date,
        "end_date": end_date,
        "initial_cash": float(initial_cash),
        "final_cash": float(cash),
        "final_market_value": float(mkt),
        "final_assets": float(end_assets),
        "return_pct": float(ret_pct),
        "stamp_duty_total": float(stamp_duty_total),
        "trade_count": len(trades),
        "buy_mid_offset": BUY_OFFSET,
        "sell_mid_offset": SELL_OFFSET,
        "max_long_positions": MAX_SYMBOL_POSITIONS,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "trades": trades,
    }


def main() -> None:
    end = datetime.now().date()
    start = end - timedelta(days=180)
    start_date = start.strftime("%Y-%m-%d")
    end_date = end.strftime("%Y-%m-%d")

    pool_path = DEFAULT_POOL_TXT
    symbols = load_symbols_from_pool_file(pool_path)
    if not symbols:
        raise SystemExit(f"股票池为空: {pool_path}")
    print(f"rotation_grid_ma20  区间: {start_date} ~ {end_date}")
    print(f"初始资金: {INITIAL_CASH:,.2f}  股票池: {len(symbols)} 只（来自 stocks_pool.txt）")
    print(f"买入中点 -{BUY_OFFSET*100:.0f}% / 卖出中点 +{SELL_OFFSET*100:.0f}%  最多 {MAX_SYMBOL_POSITIONS} 只  334 以初始资金为基数")

    result = backtest_rotation_grid(
        symbols,
        start_date,
        end_date,
        initial_cash=INITIAL_CASH,
        pool_file=pool_path,
    )
    trade_rows: List[Dict] = result.pop("trades", [])
    summary = result

    # out_df = build_rotation_result_dataframe(summary, trade_rows)
    # out_df.to_csv(RESULT_CSV, index=False, encoding="utf-8-sig")

    print("=" * 72)
    print(f"总交易次数: {summary['trade_count']}")
    print(f"期末总资产: {summary['final_assets']:,.2f}")
    print(f"总收益率 return_pct: {summary['return_pct']:.4f}%")
    print(f"印花税合计: {summary['stamp_duty_total']:,.2f}")
    # print(f"已写入（汇总 1 行 + 逐笔 {summary['trade_count']} 行）: {RESULT_CSV}")
    print("暂不写入 CSV（已注释 out_df / to_csv）")


if __name__ == "__main__":
    main()

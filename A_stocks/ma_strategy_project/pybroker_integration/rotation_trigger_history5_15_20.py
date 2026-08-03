#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
N 日均线策略：均线之上阈值触发买入 → 前 K 只等权 → 多持仓 N 收益率对比（仅控制台）。

1) 触发：与 rotation_grid 一致，均线为前复权收盘的 rolling(N).mean().shift(1)，无未来函数。
   当日收盘价 >= 均线 × (1 + 溢价阈值) 视为买入信号；N 默认 20（--ma-period），阈值默认 5%%（--ma-above-pct 0.05）。
2) 选股：每个信号日 T 取「高于均线幅度」close/MA-1 降序的前 K 只（--top-k），等权分配 T+1 开盘可用资金。
3) 交易：T+1 开盘买入，T+N 收盘卖出；对比表固定含 N=5、15、20，可用 --hold-days 追加其它 N。
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Set, Tuple

import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from backtest_sy_002028_threshold import fetch_ohlc_qfq  # noqa: E402

import rotation_grid as rg  # noqa: E402
from config.settings import DATA_CONFIG  # noqa: E402

DEFAULT_POOL = os.path.join(_SCRIPT_DIR, "stocks_pool.txt")
DEFAULT_LOOKBACK_DAYS = 180
DEFAULT_TOP_K = 2
DEFAULT_MA_PERIOD = 20
DEFAULT_MA_ABOVE_PCT = 0.05
HOLD_COMPARE_ANCHOR_DAYS: Tuple[int, ...] = (5, 15, 20)


def _prepare_grid_base(raw: pd.DataFrame) -> pd.DataFrame:
    return rg._prepare_frame(raw)


def load_symbols(path: str) -> List[str]:
    return rg.load_symbols_from_pool_file(path)


def fetch_symbol_names(symbols: List[str]) -> Dict[str, str]:
    """
    取股票名称映射（6位 code -> name）。
    依赖 Tushare stock_basic；若失败则返回空 dict（输出 name 置空）。
    """
    try:
        import tushare as ts  # type: ignore
    except Exception:
        return {}

    token = (DATA_CONFIG.get("tushare_token") or "").strip()
    if not token:
        return {}

    try:
        ts.set_token(token)
        pro = ts.pro_api()
        df = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
    except Exception:
        return {}

    if df is None or df.empty:
        return {}
    df = df.copy()
    df["symbol"] = df["ts_code"].map(lambda x: str(x).split(".")[0]).astype(str).str.zfill(6)
    m = dict(zip(df["symbol"].astype(str), df["name"].astype(str)))
    wanted = set(str(s).zfill(6) for s in symbols)
    return {s: m.get(s, "") for s in wanted}


def build_per_symbol_frames(
    symbols: List[str],
    start_date: str,
    end_date: str,
    *,
    ma_period: int = DEFAULT_MA_PERIOD,
) -> Tuple[Dict[str, pd.DataFrame], Set[pd.Timestamp]]:
    """grid 版日表（含用于触发的 ma_line，索引为 date）。"""
    start_ts = pd.Timestamp(start_date)
    warm_start = (start_ts - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
    n = max(1, int(ma_period))

    per_g: Dict[str, pd.DataFrame] = {}
    all_dates: Set[pd.Timestamp] = set()

    for sym in symbols:
        try:
            raw = fetch_ohlc_qfq(sym, warm_start, end_date)
        except Exception:
            continue
        if raw is None or raw.empty:
            continue
        g = _prepare_grid_base(raw)
        g["ma_line"] = g["close"].rolling(n).mean().shift(1)
        g = g.dropna(subset=["ma_line"])
        g = g[(g["date"] >= start_ts) & (g["date"] <= pd.Timestamp(end_date))]
        if g.empty:
            continue
        per_g[str(sym).zfill(6)] = g.set_index("date")
        all_dates.update(g["date"].tolist())

    return per_g, all_dates


def build_daily_ma_buy_signals(
    per_g: Dict[str, pd.DataFrame],
    name_map: Dict[str, str],
    *,
    ma_above_pct: float = 0.05,
) -> pd.DataFrame:
    """
    每个交易日、每只标的：若 close >= ma_line * (1+ma_above_pct)，则记为信号。
    同日多标的按高于均线幅度 (close/ma_line - 1) 降序排名，供前 K 只选用。
    """
    cols = ["date", "rank", "symbol", "name", "excess_over_ma", "close", "ma_line"]
    if not per_g:
        return pd.DataFrame(columns=cols)

    mult = 1.0 + float(ma_above_pct)
    rows: List[Dict[str, Any]] = []

    for sym, sdf in per_g.items():
        sym = str(sym).zfill(6)
        for dt in sdf.index:
            r = sdf.loc[dt]
            ma = rg._to_float(r["ma_line"])
            close = rg._to_float(r["close"])
            if ma <= 0 or pd.isna(ma) or pd.isna(close):
                continue
            if close < ma * mult:
                continue
            excess = close / ma - 1.0
            rows.append(
                {
                    "date": pd.Timestamp(dt).normalize(),
                    "symbol": sym,
                    "name": name_map.get(sym, ""),
                    "excess_over_ma": excess,
                    "close": close,
                    "ma_line": ma,
                }
            )

    if not rows:
        return pd.DataFrame(columns=cols)

    x = pd.DataFrame(rows)
    x = x.sort_values(["date", "excess_over_ma"], ascending=[True, False]).reset_index(drop=True)
    x["rank"] = x.groupby("date").cumcount() + 1
    x["date"] = x["date"].dt.strftime("%Y-%m-%d")
    return x[cols]


def parse_hold_trading_days_extra(s: str) -> List[int]:
    """解析 --hold-days 额外 N；空串表示无额外项（对比表仍含 HOLD_COMPARE_ANCHOR_DAYS）。"""
    if not s or not str(s).strip():
        return []
    out: List[int] = []
    for p in str(s).split(","):
        p = p.strip()
        if not p:
            continue
        try:
            n = int(p)
        except Exception:
            continue
        if n >= 1:
            out.append(n)
    return sorted(set(out))


def merge_hold_days_for_compare(anchor: Tuple[int, ...], extra: List[int]) -> List[int]:
    return sorted(set(anchor) | set(extra))


def run_ma_signal_backtest(
    signals_daily: pd.DataFrame,
    per_g: Dict[str, pd.DataFrame],
    all_dates: Set[pd.Timestamp],
    *,
    top_k: int,
    start_date: str = "",
    end_date: str = "",
    initial_cash: float = 100000.0,
    commission_rate: float = 0.001,
    hold_trading_days: int = 5,
) -> tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """
    每个交易日 T:
    - 取 T 日信号榜 rank<=top_k（已按高于均线幅度排序）
    - T+1 开盘买入，T+hold_trading_days 收盘卖出
    """
    if signals_daily is None or signals_daily.empty:
        summary = {
            "initial_cash": float(initial_cash),
            "final_assets": float(initial_cash),
            "total_return_pct": 0.0,
            "trade_days": 0,
            "trade_count": 0,
            "hold_trading_days": int(hold_trading_days),
        }
        return pd.DataFrame(), pd.DataFrame(), summary

    ht = int(hold_trading_days)
    tk = max(1, int(top_k))
    if ht < 1:
        summary = {
            "initial_cash": float(initial_cash),
            "final_assets": float(initial_cash),
            "total_return_pct": 0.0,
            "trade_days": 0,
            "trade_count": 0,
            "hold_trading_days": ht,
        }
        return pd.DataFrame(), pd.DataFrame(), summary

    dates = sorted(pd.to_datetime(list(all_dates)))
    md = signals_daily.copy()
    md["date"] = pd.to_datetime(md["date"])
    md["symbol"] = md["symbol"].astype(str).str.zfill(6)

    equity = float(initial_cash)
    trades: List[Dict[str, Any]] = []
    daily: List[Dict[str, Any]] = []

    for i in range(len(dates) - ht):
        d = pd.Timestamp(dates[i]).normalize()
        d_buy = pd.Timestamp(dates[i + 1]).normalize()
        d_sell = pd.Timestamp(dates[i + ht]).normalize()
        day_rank = md[(md["date"] == d) & (md["rank"] <= tk)].sort_values("rank")
        if day_rank.empty:
            daily.append(
                {"date": d.strftime("%Y-%m-%d"), "equity_start": equity, "equity_end": equity, "day_return": 0.0}
            )
            continue

        picks: List[Tuple[int, str, str, float]] = []
        for row in day_rank.itertuples(index=False):
            rk = int(row.rank)
            sym = str(row.symbol).zfill(6)
            if sym not in per_g:
                continue
            sdf = per_g[sym]
            if d_buy not in sdf.index or d_sell not in sdf.index:
                continue
            nm = str(getattr(row, "name", "") or "")
            picks.append((rk, sym, nm, float(row.excess_over_ma)))
        if not picks:
            daily.append(
                {"date": d.strftime("%Y-%m-%d"), "equity_start": equity, "equity_end": equity, "day_return": 0.0}
            )
            continue

        ws = [1.0 / len(picks)] * len(picks)

        equity_start = equity
        equity_end = 0.0
        for (rk, sym, name, excess), w in zip(picks, ws):
            sdf = per_g[sym]
            buy_px = float(sdf.loc[d_buy]["open"])
            sell_px = float(sdf.loc[d_sell]["close"])
            alloc = equity_start * w
            if buy_px <= 0:
                continue
            shares = alloc / buy_px
            buy_fee = alloc * commission_rate
            gross_sell = shares * sell_px
            sell_fee = gross_sell * commission_rate
            net_cash = gross_sell - buy_fee - sell_fee
            equity_end += net_cash
            trades.append(
                {
                    "buy_date": d_buy.strftime("%Y-%m-%d"),
                    "sell_date": d_sell.strftime("%Y-%m-%d"),
                    "symbol": sym,
                    "name": name,
                    "rank": rk,
                    "excess_over_ma": excess,
                    "weight": w,
                    "buy_open": buy_px,
                    "sell_close": sell_px,
                    "shares": shares,
                    "alloc_cash": alloc,
                    "net_cash_after_sell": net_cash,
                    "trade_return": (net_cash / alloc - 1.0) if alloc > 0 else 0.0,
                }
            )
        if equity_end <= 0:
            equity_end = equity_start
        day_ret = equity_end / equity_start - 1.0 if equity_start > 0 else 0.0
        daily.append(
            {
                "date": d.strftime("%Y-%m-%d"),
                "equity_start": equity_start,
                "equity_end": equity_end,
                "day_return": day_ret,
                "pick_count": len(picks),
            }
        )
        equity = equity_end

    trades_df = pd.DataFrame(trades)
    daily_df = pd.DataFrame(daily)
    summary = {
        "initial_cash": float(initial_cash),
        "final_assets": float(equity),
        "total_return_pct": float((equity / initial_cash - 1.0) * 100.0),
        "trade_days": int(len(daily_df)),
        "trade_count": int(len(trades_df)),
        "start_date": start_date,
        "end_date": end_date,
        "top_k": tk,
        "commission_rate": float(commission_rate),
        "hold_trading_days": ht,
    }
    return trades_df, daily_df, summary


def main() -> None:
    ap = argparse.ArgumentParser(description="N日均线之上阈值触发 → 前K只 → 多持仓N收益率对比（控制台）")
    ap.add_argument("--pool", default=DEFAULT_POOL, help="股票列表文件，一行一只代码")
    ap.add_argument("--start", default=None, help="YYYY-MM-DD；不传则按 end/lookback-days 推导")
    ap.add_argument("--end", default=None, help="YYYY-MM-DD；不传默认今天")
    ap.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS, help="回测窗口自然日跨度（默认180）")
    ap.add_argument(
        "--ma-period",
        type=int,
        default=DEFAULT_MA_PERIOD,
        help="均线周期 N（前复权收盘 rolling(N).mean().shift(1)，与 rotation_grid 的 ma20 定义一致），默认 20",
    )
    ap.add_argument(
        "--ma-above-pct",
        type=float,
        default=DEFAULT_MA_ABOVE_PCT,
        help="收盘相对均线的溢价阈值，默认 0.05 表示收盘价 >= 均线×1.05 触发",
    )
    ap.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
        help="每个信号日取高于均线幅度排序后的前 K 只，等权",
    )
    ap.add_argument("--initial-cash", type=float, default=100000.0, help="回测初始资金")
    ap.add_argument("--commission-rate", type=float, default=0.001, help="买卖双边手续费率")
    ap.add_argument(
        "--hold-days",
        default="",
        help="可选，逗号分隔额外 N；与固定的 5、15、20 合并后做收益率对比（如填 2 可同时看 T+2 收盘卖）",
    )
    args = ap.parse_args()
    if args.end:
        end_ts = pd.Timestamp(args.end).normalize()
    else:
        end_ts = pd.Timestamp.today().normalize()
    if args.start:
        start_ts = pd.Timestamp(args.start).normalize()
    else:
        start_ts = (end_ts - pd.Timedelta(days=max(1, int(args.lookback_days)))).normalize()
    if start_ts > end_ts:
        raise SystemExit("start 不能晚于 end")
    start_str = start_ts.strftime("%Y-%m-%d")
    end_str = end_ts.strftime("%Y-%m-%d")

    hold_days_list = merge_hold_days_for_compare(
        HOLD_COMPARE_ANCHOR_DAYS,
        parse_hold_trading_days_extra(args.hold_days),
    )

    syms = load_symbols(args.pool)
    if not syms:
        raise SystemExit(f"股票列表为空: {args.pool}")

    name_map = fetch_symbol_names(syms)
    per_g, all_dates = build_per_symbol_frames(syms, start_str, end_str, ma_period=args.ma_period)
    if not per_g:
        raise SystemExit("未能加载任何标的日线数据，请检查 pool 与日期区间")

    signals = build_daily_ma_buy_signals(per_g, name_map, ma_above_pct=args.ma_above_pct)

    compare_rows: List[Dict[str, Any]] = []
    for hd in hold_days_list:
        _, _, s_one = run_ma_signal_backtest(
            signals,
            per_g,
            all_dates,
            top_k=args.top_k,
            start_date=start_str,
            end_date=end_str,
            initial_cash=args.initial_cash,
            commission_rate=args.commission_rate,
            hold_trading_days=hd,
        )
        compare_rows.append(
            {
                "持仓N(T+N收盘卖)": hd,
                "总收益率%": round(float(s_one["total_return_pct"]), 4),
                "期末资产": round(float(s_one["final_assets"]), 2),
                "信号日数": int(s_one["trade_days"]),
                "逐笔数": int(s_one["trade_count"]),
            }
        )
    if compare_rows:
        print(
            f"=== MA{int(args.ma_period)} 触发（收盘>=均线×{1.0 + float(args.ma_above_pct):.4f}），前 {args.top_k} 只等权 | "
            f"持仓天数对比（T+1 开盘买，T+N 收盘卖；固定含 N∈{list(HOLD_COMPARE_ANCHOR_DAYS)}）"
            f" | 初始资金 {args.initial_cash:.2f}，手续费率 {args.commission_rate} ==="
        )
        print(pd.DataFrame(compare_rows).to_string(index=False))


if __name__ == "__main__":
    main()

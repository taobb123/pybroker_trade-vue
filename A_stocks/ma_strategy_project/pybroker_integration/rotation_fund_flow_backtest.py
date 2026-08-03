#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
资金驱动回测：场景3（龙虎榜跟随）+ 场景4（融资情绪反转）。
股票池默认读取同目录下 stocks_pool.txt；行情/龙虎榜/融资融券来自 Tushare pro。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_CURRENT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if _CURRENT_DIR not in sys.path:
    sys.path.insert(0, _CURRENT_DIR)

from config.settings import DATA_CONFIG  # noqa: E402

from rotation_fund_flow_signals import (  # noqa: E402
    event_dragon_daily_net_buy,
    exec_exit_date_after_hold,
    get_ohlc_on_date,
    rotation_s3_candidates_on_list_day,
    rotation_s3_should_buy_at_next_open,
    rotation_s4_eligible_symbols,
    to_symbol_from_ts_code,
)


DEFAULT_POOL_FILE = os.path.join(_CURRENT_DIR, "stocks_pool.txt")


def load_stock_pool(path: str) -> list[str]:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"股票池文件不存在: {path}")
    out: list[str] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                out.append(s)
    return out


def to_ts_code(code: str) -> str:
    c = str(code).strip()
    if c.endswith(".SH") or c.endswith(".SZ"):
        return c
    if c.startswith(("0", "3", "1")):
        return f"{c}.SZ"
    if c.startswith(("6", "5", "688")):
        return f"{c}.SH"
    return f"{c}.SZ"


def init_pro():
    import tushare as ts

    token = (DATA_CONFIG.get("tushare_token") or "").strip()
    if not token:
        raise RuntimeError("请在 config/settings.py 配置 DATA_CONFIG['tushare_token']")
    ts.set_token(token)
    return ts.pro_api()


def fetch_trade_calendar(pro, start_date: str, end_date: str) -> pd.DatetimeIndex:
    df = pro.trade_cal(
        exchange="SSE",
        start_date=start_date.replace("-", ""),
        end_date=end_date.replace("-", ""),
        is_open="1",
    )
    if df is None or df.empty:
        return pd.DatetimeIndex([])
    df["cal_date"] = pd.to_datetime(df["cal_date"].astype(str))
    return pd.DatetimeIndex(sorted(df["cal_date"].unique()))


def fetch_top_list_range(pro, cal: pd.DatetimeIndex, sleep_sec: float = 0.12) -> pd.DataFrame:
    chunks: list[pd.DataFrame] = []
    for i, d in enumerate(cal):
        ds = d.strftime("%Y%m%d")
        try:
            df = pro.top_list(trade_date=ds)
            if df is not None and not df.empty:
                chunks.append(df)
        except Exception:
            pass
        if sleep_sec > 0 and (i + 1) % 20 == 0:
            time.sleep(sleep_sec * 2)
        elif sleep_sec > 0:
            time.sleep(sleep_sec)
    if not chunks:
        return pd.DataFrame()
    return pd.concat(chunks, ignore_index=True)


def fetch_margin_detail_range(pro, cal: pd.DatetimeIndex, sleep_sec: float = 0.12) -> pd.DataFrame:
    chunks: list[pd.DataFrame] = []
    for i, d in enumerate(cal):
        ds = d.strftime("%Y%m%d")
        try:
            df = pro.margin_detail(trade_date=ds)
            if df is not None and not df.empty:
                chunks.append(df)
        except Exception:
            pass
        if sleep_sec > 0 and (i + 1) % 20 == 0:
            time.sleep(sleep_sec * 2)
        elif sleep_sec > 0:
            time.sleep(sleep_sec)
    if not chunks:
        return pd.DataFrame()
    raw = pd.concat(chunks, ignore_index=True)
    if "ts_code" in raw.columns:
        raw["symbol"] = raw["ts_code"].map(to_symbol_from_ts_code)
    raw["trade_date"] = pd.to_datetime(raw["trade_date"].astype(str))
    return raw


def fetch_daily_with_turnover(
    pro, ts_code: str, start_date: str, end_date: str
) -> pd.DataFrame:
    s = start_date.replace("-", "")
    e = end_date.replace("-", "")
    d1 = pro.daily(ts_code=ts_code, start_date=s, end_date=e)
    if d1 is None or d1.empty:
        return pd.DataFrame()
    d1["trade_date"] = pd.to_datetime(d1["trade_date"].astype(str))
    try:
        d2 = pro.daily_basic(
            ts_code=ts_code,
            start_date=s,
            end_date=e,
            fields="ts_code,trade_date,turnover_rate",
        )
    except Exception:
        d2 = None
    if d2 is not None and not d2.empty:
        d2["trade_date"] = pd.to_datetime(d2["trade_date"].astype(str))
        d1 = d1.merge(d2[["trade_date", "turnover_rate"]], on="trade_date", how="left")
    else:
        d1["turnover_rate"] = pd.NA
    d1 = d1.rename(columns={"vol": "volume"})
    for col in ("open", "high", "low", "close"):
        if col in d1.columns:
            d1[col] = pd.to_numeric(d1[col], errors="coerce")
    d1["volume"] = pd.to_numeric(d1["volume"], errors="coerce")
    return d1.sort_values("trade_date").reset_index(drop=True)


def prev_trading_day(
    trade_date: pd.Timestamp, cal: pd.DatetimeIndex
) -> Optional[pd.Timestamp]:
    cal = pd.DatetimeIndex(sorted(pd.to_datetime(cal).normalize().unique()))
    td = pd.Timestamp(trade_date).normalize()
    pos = int(cal.searchsorted(td))
    if pos <= 0:
        return None
    return cal[pos - 1]


@dataclass
class BacktestState:
    cash: float
    commission: float
    position: Optional[dict[str, Any]] = None
    trades: list[dict[str, Any]] = field(default_factory=list)


def _sell_at_open(state: BacktestState, sym: str, dt: pd.Timestamp, bars: pd.DataFrame) -> None:
    ohlc = get_ohlc_on_date(bars, dt, date_col="trade_date")
    if ohlc is None:
        return
    op = ohlc[0]
    sh = int(state.position["shares"])
    gross = sh * op
    fee = gross * state.commission
    state.cash += gross - fee
    state.trades.append(
        {
            "date": dt,
            "symbol": sym,
            "side": "sell",
            "price": op,
            "shares": sh,
            "reason": state.position.get("reason"),
        }
    )
    state.position = None


def _buy_at_open(
    state: BacktestState,
    sym: str,
    dt: pd.Timestamp,
    bars: pd.DataFrame,
    reason: str,
    hold_days: int,
    cal: pd.DatetimeIndex,
) -> bool:
    ohlc = get_ohlc_on_date(bars, dt, date_col="trade_date")
    if ohlc is None:
        return False
    op = ohlc[0]
    if op <= 0:
        return False
    budget = state.cash * (1 - state.commission)
    shares = int(budget // op)
    if shares <= 0:
        return False
    cost = shares * op * (1 + state.commission)
    if cost > state.cash:
        return False
    state.cash -= cost
    ex = exec_exit_date_after_hold(dt, cal, hold_trading_days=hold_days)
    if ex is None:
        state.cash += cost
        return False
    state.position = {
        "symbol": sym,
        "shares": shares,
        "exit_date": ex,
        "reason": reason,
    }
    state.trades.append(
        {
            "date": dt,
            "symbol": sym,
            "side": "buy",
            "price": op,
            "shares": shares,
            "reason": reason,
            "planned_exit": ex,
        }
    )
    return True


def run_scenario_3(
    pool: list[str],
    cal: pd.DatetimeIndex,
    dragon_daily: pd.DataFrame,
    margin_df: pd.DataFrame,
    bars_by_symbol: dict[str, pd.DataFrame],
    initial_cash: float = 100_000.0,
    commission: float = 0.001,
    hold_trading_days: int = 3,
    min_net_buy: float = 50_000_000.0,
    max_gap_up_pct: float = 0.02,
) -> BacktestState:
    state = BacktestState(cash=initial_cash, commission=commission)

    for d in cal:
        d = pd.Timestamp(d).normalize()
        if state.position:
            sym_p = state.position["symbol"]
            if d == state.position["exit_date"]:
                _sell_at_open(state, sym_p, d, bars_by_symbol[sym_p])

        if state.position is not None:
            continue

        prev = prev_trading_day(d, cal)
        if prev is None:
            continue

        cand = rotation_s3_candidates_on_list_day(
            prev,
            dragon_daily,
            pool,
            bars_by_symbol,
            min_net_buy=min_net_buy,
            use_limit_up_filter=True,
            use_turnover_filter=False,
            margin_df=margin_df if not margin_df.empty else None,
            use_margin_flat_or_down=False,
            date_col="trade_date",
        )
        for sym in pool:
            if sym not in cand:
                continue
            bars = bars_by_symbol.get(sym)
            if bars is None or bars.empty:
                continue
            row_prev = get_ohlc_on_date(bars, prev, date_col="trade_date")
            row_today = get_ohlc_on_date(bars, d, date_col="trade_date")
            if row_prev is None or row_today is None:
                continue
            _, _, _, c_prev = row_prev
            o_today, _, _, _ = row_today
            if not rotation_s3_should_buy_at_next_open(
                c_prev, o_today, max_gap_up_pct=max_gap_up_pct
            ):
                continue
            if _buy_at_open(
                state,
                sym,
                d,
                bars,
                reason="s3_dragon",
                hold_days=hold_trading_days,
                cal=cal,
            ):
                break

    if state.position:
        last = cal[-1]
        sym_p = state.position["symbol"]
        _sell_at_open(state, sym_p, last, bars_by_symbol[sym_p])

    return state


def run_scenario_4(
    pool: list[str],
    cal: pd.DatetimeIndex,
    margin_df: pd.DataFrame,
    bars_by_symbol: dict[str, pd.DataFrame],
    initial_cash: float = 100_000.0,
    commission: float = 0.001,
    hold_trading_days: int = 3,
) -> BacktestState:
    state = BacktestState(cash=initial_cash, commission=commission)

    for d in cal:
        d = pd.Timestamp(d).normalize()
        if state.position:
            sym_p = state.position["symbol"]
            if d == state.position["exit_date"]:
                _sell_at_open(state, sym_p, d, bars_by_symbol[sym_p])

        if state.position is not None:
            continue

        prev = prev_trading_day(d, cal)
        if prev is None or margin_df.empty:
            continue

        elig = rotation_s4_eligible_symbols(
            prev,
            pool,
            margin_df,
            bars_by_symbol,
            date_col="trade_date",
        )
        for sym in pool:
            if sym not in elig:
                continue
            bars = bars_by_symbol.get(sym)
            if bars is None or bars.empty:
                continue
            if _buy_at_open(
                state,
                sym,
                d,
                bars,
                reason="s4_margin",
                hold_days=hold_trading_days,
                cal=cal,
            ):
                break

    if state.position:
        last = cal[-1]
        sym_p = state.position["symbol"]
        _sell_at_open(state, sym_p, last, bars_by_symbol[sym_p])

    return state


def summarize(name: str, state: BacktestState, initial: float) -> None:
    print(f"\n=== {name} ===")
    print(f"成交笔数(买+卖): {len(state.trades)}")
    print(f"期末现金: {state.cash:.2f}")
    ret = state.cash / initial - 1.0
    print(f"总收益率(近似，已平仓): {ret:.2%}")
    if state.trades:
        df = pd.DataFrame(state.trades)
        print(df.tail(8).to_string(index=False))


def main():
    ap = argparse.ArgumentParser(description="场景3/4 资金驱动回测（Tushare + stocks_pool.txt）")
    ap.add_argument(
        "--pool",
        default=DEFAULT_POOL_FILE,
        help="股票池文件路径（每行一个6位代码）",
    )
    ap.add_argument("--start", required=True, help="开始日 YYYYMMDD 或 YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="结束日")
    ap.add_argument(
        "--scenario",
        choices=["3", "4", "both"],
        default="both",
        help="3=龙虎榜，4=融资反转，both=各用独立初始资金各跑一遍",
    )
    ap.add_argument("--cash", type=float, default=100_000.0, help="初始资金（both 时两套各此金额）")
    ap.add_argument("--commission", type=float, default=0.001, help="双边费率近似")
    ap.add_argument("--hold", type=int, default=3, help="持仓交易日数（卖出用）")
    ap.add_argument("--min-net-buy", type=float, default=50_000_000.0, help="场景3 龙虎榜净买入阈值（元）")
    ap.add_argument("--no-top-list-fetch", action="store_true", help="跳过拉取龙虎榜（场景3 无信号）")
    ap.add_argument("--no-margin-fetch", action="store_true", help="跳过融资融券（场景4 无信号）")
    args = ap.parse_args()

    start = args.start.replace("-", "")
    end = args.end.replace("-", "")

    pool = load_stock_pool(args.pool)
    print(f"股票池 {args.pool}: {len(pool)} 只")

    pro = init_pro()
    cal = fetch_trade_calendar(pro, start, end)
    if len(cal) == 0:
        print("交易日历为空，请检查起止日期")
        return

    ext_start = (cal[0] - pd.Timedelta(days=120)).strftime("%Y%m%d")
    ext_end = cal[-1].strftime("%Y%m%d")

    print("拉取行情（含换手率）…")
    bars_by_symbol: dict[str, pd.DataFrame] = {}
    for code in pool:
        tc = to_ts_code(code)
        df = fetch_daily_with_turnover(pro, tc, ext_start, ext_end)
        if not df.empty:
            bars_by_symbol[code] = df
        time.sleep(0.05)

    dragon_daily = pd.DataFrame(columns=["trade_date", "symbol", "net_buy"])
    if args.scenario in ("3", "both") and not args.no_top_list_fetch:
        print("拉取龙虎榜（按日请求，可能较慢）…")
        raw_tl = fetch_top_list_range(pro, cal, sleep_sec=0.12)
        if raw_tl.empty:
            print("  警告: 龙虎榜数据为空（权限或区间无数据）")
        else:
            dragon_daily = event_dragon_daily_net_buy(raw_tl)

    margin_df = pd.DataFrame()
    if args.scenario in ("4", "both") and not args.no_margin_fetch:
        print("拉取融资融券明细 margin_detail（按日）…")
        margin_df = fetch_margin_detail_range(pro, cal, sleep_sec=0.12)
        if margin_df.empty:
            print("  警告: margin_detail 为空（权限或区间无数据）")

    initial = args.cash
    if args.scenario in ("3", "both"):
        s3 = run_scenario_3(
            pool,
            cal,
            dragon_daily,
            margin_df,
            bars_by_symbol,
            initial_cash=initial,
            commission=args.commission,
            hold_trading_days=args.hold,
            min_net_buy=args.min_net_buy,
        )
        summarize("场景3 龙虎榜跟随", s3, initial)

    if args.scenario in ("4", "both"):
        s4 = run_scenario_4(
            pool,
            cal,
            margin_df,
            bars_by_symbol,
            initial_cash=initial,
            commission=args.commission,
            hold_trading_days=args.hold,
        )
        summarize("场景4 融资情绪反转", s4, initial)


if __name__ == "__main__":
    main()

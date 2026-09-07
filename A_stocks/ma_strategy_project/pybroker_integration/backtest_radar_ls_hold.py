#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""雷达强度：T0锁定第1/第2，分批买入，T2锁仓，T3清仓轮动；股票池对齐强度轮动前六。"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import numpy as np
import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
for _p in (_SCRIPT_DIR, _PROJECT_ROOT):
    if _p in sys.path:
        sys.path.remove(_p)
    sys.path.insert(0, _p)

from backtest_strength_rotation import (  # noqa: E402
    COMMISSION,
    DEFAULT_CASH,
    DEFAULT_START,
    LOT,
    STAMP,
    _finite,
    bar_on,
    build_daily_ranks,
    commission_fee,
    fetch_index_daily,
    fetch_stock_bars,
    fetch_sw_daily,
    get_pro,
    is_halted,
    is_limit_down,
    is_limit_up,
)
from market_radar import _sector_display, resolve_sw_map, to_ts_code  # noqa: E402

OUT_DIR = os.path.join(_SCRIPT_DIR, "output", "radar_ls_hold")
ALIGN_END_DEFAULT = "2026-08-30"
# 雷达当前自选：M加/Q 各前 3（界面截图）
RADAR_CURRENT_SIX = (
    {"symbol": "002558", "name": "巨人网络", "group": "M加", "group_rank": 1, "industry": "互联网服务"},
    {"symbol": "600857", "name": "宁波中百", "group": "M加", "group_rank": 2, "industry": "商业连锁"},
    {"symbol": "000056", "name": "*ST皇庭", "group": "M加", "group_rank": 3, "industry": "其他商业"},
    {"symbol": "002517", "name": "恺英网络", "group": "Q", "group_rank": 1, "industry": "游戏Ⅱ"},
    {"symbol": "600661", "name": "昂立教育", "group": "Q", "group_rank": 2, "industry": "教育"},
    {"symbol": "603367", "name": "辰欣药业", "group": "Q", "group_rank": 3, "industry": "化学制药"},
)


@dataclass
class Sleeve:
    key: str
    symbol: str = ""
    shares: int = 0
    last_buy: Optional[pd.Timestamp] = field(default=None)


def load_aligned_universe() -> pd.DataFrame:
    """雷达当前自选：M加/Q 各前 3，冻结为本轮回测名单。"""
    return pd.DataFrame(list(RADAR_CURRENT_SIX))


def _safe_print(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("gbk", errors="replace").decode("gbk", errors="replace"), flush=True)


def sell_cost(notional: float) -> float:
    return commission_fee(notional) + abs(float(notional)) * STAMP


def buy_cost(notional: float) -> float:
    return commission_fee(notional)


def close_of(bars: dict[str, pd.DataFrame], symbol: str, dt: pd.Timestamp) -> Optional[float]:
    row = bar_on(bars, symbol, dt)
    if row is not None:
        px = _finite(row.get("close"))
        if px and px > 0:
            return px
    df = bars.get(symbol)
    if df is None or df.empty:
        return None
    sub = df[df["date"] <= dt].sort_values("date")
    if sub.empty:
        return None
    return _finite(sub.iloc[-1].get("close"))


def can_buy(bars: dict[str, pd.DataFrame], names: dict[str, str], symbol: str, dt: pd.Timestamp) -> bool:
    row = bar_on(bars, symbol, dt)
    if is_halted(row):
        return False
    assert row is not None
    return not is_limit_up(row, symbol, names.get(symbol, ""))


def can_sell(bars: dict[str, pd.DataFrame], names: dict[str, str], symbol: str, dt: pd.Timestamp) -> bool:
    row = bar_on(bars, symbol, dt)
    if is_halted(row):
        return False
    assert row is not None
    return not is_limit_down(row, symbol, names.get(symbol, ""))


def pick_top2(day: pd.DataFrame) -> tuple[Optional[str], Optional[str]]:
    """T0 当日全池强度第 1、第 2，全程锁定不再改排名。"""
    if day is None or day.empty:
        return None, None
    work = day.dropna(subset=["strength"]).copy()
    if work.empty:
        return None, None
    work = work.sort_values(["strength", "symbol"], ascending=[False, True])
    first = str(work.iloc[0]["symbol"])
    if len(work) < 2:
        return first, None
    second = str(work.iloc[1]["symbol"])
    if second == first:
        return first, None
    return first, second


def pick_strongest(day: pd.DataFrame, old: Optional[str]) -> Optional[str]:
    if day is None or day.empty:
        return None
    work = day.dropna(subset=["strength"]).copy()
    if work.empty:
        return None
    work = work.sort_values(["strength", "symbol"], ascending=[False, True])
    s1 = float(work.iloc[0]["strength"])
    tied = work[pd.to_numeric(work["strength"], errors="coerce") == s1]
    if old and old in set(tied["symbol"].astype(str)):
        return old
    return str(work.iloc[0]["symbol"])


def lots_for(cash_alloc: float, price: float) -> int:
    if price is None or price <= 0 or cash_alloc <= 0:
        return 0
    raw = cash_alloc / (price * (1.0 + COMMISSION))
    n = int(raw // LOT)
    return n * LOT if n >= 1 else 0


def shift_trading_day(calendar: list[pd.Timestamp], dt: pd.Timestamp, n: int) -> Optional[pd.Timestamp]:
    if n <= 0:
        return dt
    try:
        i = calendar.index(dt)
    except ValueError:
        return None
    j = i + n
    if j >= len(calendar):
        return None
    return calendar[j]


def metrics_from_equity(
    equity_df: pd.DataFrame,
    trades_df: pd.DataFrame,
    initial_cash: float,
    *,
    strategy: str,
    hold_days: int,
    skipped: int,
    pair_pnls: list[float],
) -> dict[str, Any]:
    if equity_df is None or equity_df.empty:
        return {
            "strategy": strategy,
            "hold_days": hold_days,
            "total_return": 0.0,
            "annual_return": 0.0,
            "max_drawdown": 0.0,
            "sharpe": 0.0,
        }
    eq = equity_df.copy()
    eq["date"] = pd.to_datetime(eq["date"])
    rets = pd.to_numeric(eq["day_return"], errors="coerce").fillna(0.0)
    total_ret = float(eq["equity"].iloc[-1] / float(initial_cash) - 1.0)
    n = max(1, len(eq))
    years = n / 252.0
    annual = (1.0 + total_ret) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    cum = eq["equity"] / float(initial_cash)
    peak = cum.cummax()
    mdd = float((cum / peak - 1.0).min()) if len(cum) else 0.0
    vol = float(rets.std(ddof=0)) * np.sqrt(252) if len(rets) > 1 else 0.0
    sharpe = float(annual / vol) if vol > 1e-12 else 0.0
    n_open = (
        int((trades_df["action"].isin(["OPEN_LONG", "OPEN_SHORT", "BUY", "ADD"])).sum())
        if not trades_df.empty
        else 0
    )
    n_close = (
        int((trades_df["action"].isin(["CLOSE_LONG", "COVER_SHORT", "SELL"])).sum())
        if not trades_df.empty
        else 0
    )
    win_rate = float(np.mean([p > 0 for p in pair_pnls])) if pair_pnls else 0.0
    return {
        "strategy": strategy,
        "hold_days": hold_days,
        "total_return": total_ret,
        "annual_return": annual,
        "max_drawdown": mdd,
        "sharpe": sharpe,
        "avg_day_return": float(rets.mean()) if len(rets) else 0.0,
        "trade_days": int(n),
        "n_open": n_open,
        "n_close": n_close,
        "n_roundtrips": int(len(pair_pnls)),
        "win_rate": win_rate,
        "skipped": int(skipped),
        "end_equity": float(eq["equity"].iloc[-1]),
        "end_long": str(eq["long_symbol"].iloc[-1] or "") if "long_symbol" in eq.columns else "",
        "end_short": str(eq["short_symbol"].iloc[-1] or "") if "short_symbol" in eq.columns else "",
    }


def run_staggered(
    ranks: pd.DataFrame,
    bars: dict[str, pd.DataFrame],
    names: dict[str, str],
    initial_cash: float,
    *,
    mode: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """
    4 日一轮：T0 锁定当日第 1 / 第 2。
    combined: T0/T1 各买第 1 的 25% 权益，T1/T2 各买第 2 的 25%，T2 锁第 1，T3 全清。
    first:     T0/T1 各买第 1 的 50%，T2 锁仓，T3 清仓。
    second:    T0 只记名，T1/T2 各买第 2 的 50%，T3 清仓。
    """
    calendar = sorted(pd.Timestamp(d).normalize() for d in ranks["date"].unique())
    by_date = {pd.Timestamp(dt).normalize(): g.copy() for dt, g in ranks.groupby("date")}
    cash = float(initial_cash)
    first = Sleeve("first")
    second = Sleeve("second")
    phase = 0
    flattening = False
    t0_first: Optional[str] = None
    t0_second: Optional[str] = None
    cycle_equity = 0.0
    cycle_open_mark = 0.0
    cycle_pnls: list[float] = []
    skipped = 0
    equity_rows: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    strategy_key = {"combined": "stagger", "first": "stagger1", "second": "stagger2"}[mode]
    metric_name = {
        "combined": "stagger_combo",
        "first": "stagger_first",
        "second": "stagger_second",
    }[mode]

    def mark(dt: pd.Timestamp) -> float:
        total = cash
        for sl in (first, second):
            if sl.shares <= 0 or not sl.symbol:
                continue
            px = close_of(bars, sl.symbol, dt)
            if px:
                total += sl.shares * px
        return total

    def record_trade(dt: pd.Timestamp, action: str, sl: Sleeve, px: float, sh: int, fee: float) -> None:
        trades.append(
            {
                "date": dt,
                "strategy": strategy_key,
                "hold_days": 3,
                "action": action,
                "sleeve": sl.key,
                "symbol": sl.symbol if action == "SELL" else sl.symbol,
                "name": names.get(sl.symbol, ""),
                "price": round(px, 4),
                "shares": sh,
                "fee": round(fee, 4),
                "cash_after": round(cash, 2),
            }
        )

    def try_buy(sl: Sleeve, dt: pd.Timestamp, symbol: Optional[str], alloc: float) -> bool:
        nonlocal cash, skipped
        if not symbol or alloc <= 0:
            return False
        if sl.symbol and sl.symbol != symbol:
            skipped += 1
            return False
        if not can_buy(bars, names, symbol, dt):
            skipped += 1
            return False
        px = close_of(bars, symbol, dt)
        if not px:
            skipped += 1
            return False
        sh = lots_for(min(alloc, cash), px)
        if sh < LOT:
            skipped += 1
            return False
        notional = sh * px
        fee = buy_cost(notional)
        if notional + fee > cash + 1e-6:
            skipped += 1
            return False
        cash -= notional + fee
        existed = sl.shares > 0
        sl.symbol = symbol
        sl.shares += sh
        sl.last_buy = dt
        record_trade(dt, "ADD" if existed else "BUY", sl, px, sh, fee)
        return True

    def try_sell(sl: Sleeve, dt: pd.Timestamp) -> bool:
        nonlocal cash, skipped
        if sl.shares <= 0:
            return True
        if sl.last_buy is not None and dt <= sl.last_buy:
            skipped += 1
            return False
        if not can_sell(bars, names, sl.symbol, dt):
            skipped += 1
            return False
        px = close_of(bars, sl.symbol, dt)
        if not px:
            skipped += 1
            return False
        notional = sl.shares * px
        fee = sell_cost(notional)
        cash += notional - fee
        record_trade(dt, "SELL", sl, px, sl.shares, fee)
        sl.symbol = ""
        sl.shares = 0
        sl.last_buy = None
        return True

    def flatten_all(dt: pd.Timestamp) -> bool:
        ok1 = try_sell(first, dt)
        ok2 = try_sell(second, dt)
        return ok1 and ok2

    def tranche_size() -> float:
        if mode == "combined":
            return cycle_equity * 0.25
        return cycle_equity * 0.50

    for dt in calendar:
        day = by_date.get(dt)
        action = "hold"
        reason = ""
        notes: list[str] = []

        if flattening:
            if flatten_all(dt):
                flattening = False
                phase = 0
                if cycle_open_mark > 0:
                    cycle_pnls.append(mark(dt) / cycle_open_mark - 1.0)
                    cycle_open_mark = 0.0
                action = "flat"
                reason = "延期清仓完成，次日新一轮 T0"
            else:
                action = "hold_fail"
                reason = "T3 清仓未完成，继续锁仓待卖"
            t_first, t_second = t0_first, t0_second
        elif phase == 0:
            t0_first, t0_second = pick_top2(day)
            t_first, t_second = t0_first, t0_second
            cycle_equity = mark(dt)
            cycle_open_mark = cycle_equity
            alloc = tranche_size()
            if mode in ("combined", "first") and t0_first:
                if try_buy(first, dt, t0_first, alloc):
                    notes.append(f"T0买第一 {t0_first}")
                else:
                    notes.append("T0第一未买进")
            elif mode == "second":
                notes.append(f"T0只锁定第二 {t0_second or '无'}")
            else:
                notes.append("T0无第一名")
            phase = 1
            action = "t0"
            reason = "；".join(notes) or "T0"
        elif phase == 1:
            t_first, t_second = t0_first, t0_second
            alloc = tranche_size()
            if mode in ("combined", "first") and t0_first:
                if try_buy(first, dt, t0_first, alloc):
                    notes.append(f"T1加第一 {t0_first}")
                else:
                    notes.append("T1第一未加仓")
            if mode in ("combined", "second") and t0_second:
                if try_buy(second, dt, t0_second, alloc):
                    notes.append(f"T1买第二 {t0_second}")
                else:
                    notes.append("T1第二未买进")
            phase = 2
            action = "t1"
            reason = "；".join(notes) or "T1"
        elif phase == 2:
            t_first, t_second = t0_first, t0_second
            alloc = tranche_size()
            notes.append("T2锁第一")
            if mode in ("combined", "second") and t0_second:
                if try_buy(second, dt, t0_second, alloc):
                    notes.append(f"T2加第二 {t0_second}")
                else:
                    notes.append("T2第二未加仓")
            phase = 3
            action = "t2_lock"
            reason = "；".join(notes)
        else:
            t_first, t_second = t0_first, t0_second
            if flatten_all(dt):
                flattening = False
                phase = 0
                if cycle_open_mark > 0:
                    cycle_pnls.append(mark(dt) / cycle_open_mark - 1.0)
                    cycle_open_mark = 0.0
                action = "t3_flat"
                reason = "T3清仓，次日新一轮 T0"
            else:
                flattening = True
                action = "hold_fail"
                reason = "T3未能清完，次日续卖"

        eq = mark(dt)
        equity_rows.append(
            {
                "date": dt,
                "strategy": strategy_key,
                "hold_days": 3,
                "equity": round(eq, 2),
                "cash": round(cash, 2),
                "long_symbol": first.symbol,
                "long_name": names.get(first.symbol, "") if first.symbol else "",
                "short_symbol": second.symbol,
                "short_name": names.get(second.symbol, "") if second.symbol else "",
                "target_long": t_first or "",
                "target_short": t_second or "",
                "action": action,
                "reason": reason,
                "rebalance": action in {"t0", "t1", "t3_flat", "flat"},
            }
        )

    equity_df = pd.DataFrame(equity_rows)
    trades_df = pd.DataFrame(trades)
    if not equity_df.empty:
        equity_df["day_return"] = equity_df["equity"].pct_change().fillna(0.0)
    met = metrics_from_equity(
        equity_df,
        trades_df,
        initial_cash,
        strategy=metric_name,
        hold_days=3,
        skipped=skipped,
        pair_pnls=cycle_pnls,
    )
    return equity_df, trades_df, met


def run_long_strongest(
    ranks: pd.DataFrame,
    bars: dict[str, pd.DataFrame],
    names: dict[str, str],
    initial_cash: float,
    hold_days: int,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    calendar = sorted(pd.Timestamp(d).normalize() for d in ranks["date"].unique())
    by_date = {pd.Timestamp(dt).normalize(): g.copy() for dt, g in ranks.groupby("date")}
    cash = float(initial_cash)
    symbol = ""
    shares = 0
    last_buy: Optional[pd.Timestamp] = None
    next_rebal: Optional[pd.Timestamp] = calendar[0] if calendar else None
    open_mark = 0.0
    pnls: list[float] = []
    skipped = 0
    equity_rows: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []

    def mark(dt: pd.Timestamp) -> float:
        if shares <= 0 or not symbol:
            return cash
        px = close_of(bars, symbol, dt)
        return cash + (shares * px if px else 0.0)

    for dt in calendar:
        is_rebal = next_rebal is None or dt >= next_rebal
        action = "hold"
        reason = "锁仓" if not is_rebal else ""
        day = by_date.get(dt)
        old = symbol or None
        target = pick_strongest(day, old) if is_rebal else old

        if is_rebal:
            if shares > 0 and target == symbol:
                action = "hold"
                reason = "目标未变"
                next_rebal = shift_trading_day(calendar, dt, hold_days) or calendar[-1]
            else:
                sold = True
                if shares > 0:
                    if last_buy is not None and dt <= last_buy:
                        sold = False
                    elif not can_sell(bars, names, symbol, dt):
                        sold = False
                    else:
                        px = close_of(bars, symbol, dt)
                        if not px:
                            sold = False
                        else:
                            notional = shares * px
                            fee = sell_cost(notional)
                            cash += notional - fee
                            trades.append(
                                {
                                    "date": dt,
                                    "strategy": "long1",
                                    "hold_days": hold_days,
                                    "action": "SELL",
                                    "symbol": symbol,
                                    "name": names.get(symbol, ""),
                                    "price": round(px, 4),
                                    "shares": shares,
                                    "fee": round(fee, 4),
                                    "cash_after": round(cash, 2),
                                }
                            )
                            if open_mark:
                                pnls.append(cash / open_mark - 1.0)
                                open_mark = 0.0
                            symbol = ""
                            shares = 0
                            last_buy = None
                            sold = True
                if not sold:
                    skipped += 1
                    action = "hold_fail"
                    reason = "未能卖出旧仓"
                    next_rebal = shift_trading_day(calendar, dt, 1) or calendar[-1]
                elif not target:
                    action = "flat"
                    reason = "无目标"
                    next_rebal = shift_trading_day(calendar, dt, 1) or calendar[-1]
                elif can_buy(bars, names, target, dt):
                    px = close_of(bars, target, dt)
                    sh = lots_for(cash, px) if px else 0
                    if px and sh >= LOT:
                        notional = sh * px
                        fee = buy_cost(notional)
                        cash -= notional + fee
                        symbol = target
                        shares = sh
                        last_buy = dt
                        open_mark = mark(dt)
                        trades.append(
                            {
                                "date": dt,
                                "strategy": "long1",
                                "hold_days": hold_days,
                                "action": "BUY",
                                "symbol": target,
                                "name": names.get(target, ""),
                                "price": round(px, 4),
                                "shares": sh,
                                "fee": round(fee, 4),
                                "cash_after": round(cash, 2),
                            }
                        )
                        action = "switch" if old and old != target else "open"
                        reason = f"做多最强 {target}"
                        next_rebal = shift_trading_day(calendar, dt, hold_days) or calendar[-1]
                    else:
                        skipped += 1
                        action = "skip_open"
                        reason = "买不足一手"
                        next_rebal = shift_trading_day(calendar, dt, 1) or calendar[-1]
                else:
                    skipped += 1
                    action = "skip_open"
                    reason = "涨停/停牌，未开仓"
                    next_rebal = shift_trading_day(calendar, dt, 1) or calendar[-1]

        eq = mark(dt)
        equity_rows.append(
            {
                "date": dt,
                "strategy": "long1",
                "hold_days": hold_days,
                "equity": round(eq, 2),
                "cash": round(cash, 2),
                "long_symbol": symbol,
                "long_name": names.get(symbol, "") if symbol else "",
                "short_symbol": "",
                "short_name": "",
                "target_long": target or "",
                "target_short": "",
                "action": action,
                "reason": reason,
                "rebalance": is_rebal,
            }
        )

    equity_df = pd.DataFrame(equity_rows)
    trades_df = pd.DataFrame(trades)
    if not equity_df.empty:
        equity_df["day_return"] = equity_df["equity"].pct_change().fillna(0.0)
    met = metrics_from_equity(
        equity_df,
        trades_df,
        initial_cash,
        strategy="long_strongest",
        hold_days=hold_days,
        skipped=skipped,
        pair_pnls=pnls,
    )
    return equity_df, trades_df, met


def run_hs300(hs300: pd.DataFrame, initial_cash: float, calendar: list[pd.Timestamp]) -> tuple[pd.DataFrame, dict[str, Any]]:
    h = hs300.copy()
    h["date"] = pd.to_datetime(h["date"]).dt.normalize()
    h = h[h["date"].isin(calendar)].sort_values("date")
    if h.empty:
        return pd.DataFrame(), {
            "strategy": "hs300",
            "hold_days": 0,
            "total_return": 0.0,
            "annual_return": 0.0,
            "max_drawdown": 0.0,
            "sharpe": 0.0,
        }
    c0 = float(h["close"].iloc[0])
    rows = []
    for r in h.itertuples(index=False):
        nav = initial_cash * (float(r.close) / c0) if c0 > 0 else initial_cash
        rows.append(
            {
                "date": r.date,
                "strategy": "hs300",
                "hold_days": 0,
                "equity": round(nav, 2),
                "cash": 0.0,
                "long_symbol": "000300.SH",
                "long_name": "沪深300",
                "short_symbol": "",
                "short_name": "",
                "target_long": "000300.SH",
                "target_short": "",
                "action": "hold",
                "reason": "买入持有",
                "rebalance": False,
            }
        )
    eq = pd.DataFrame(rows)
    eq["day_return"] = eq["equity"].pct_change().fillna(0.0)
    met = metrics_from_equity(eq, pd.DataFrame(), initial_cash, strategy="hs300", hold_days=0, skipped=0, pair_pnls=[])
    met["n_roundtrips"] = 1
    met["win_rate"] = 1.0 if met["total_return"] > 0 else 0.0
    return eq, met


def plot_compare(equity_all: pd.DataFrame, path: str) -> None:
    if equity_all is None or equity_all.empty:
        return
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        _safe_print(f"  [report] 跳过绘图: {exc}")
        return
    fig, ax = plt.subplots(figsize=(10.5, 5.6))
    labels = {
        ("stagger", 3): "Stagger #1+#2",
        ("stagger1", 3): "T0#1 only",
        ("stagger2", 3): "T0#2 only",
        ("long1", 3): "Long strongest T3",
        ("hs300", 0): "CSI 300",
    }
    styles = {
        ("stagger", 3): {"color": "#1d4ed8", "lw": 2.0},
        ("stagger1", 3): {"color": "#047857", "lw": 1.5},
        ("stagger2", 3): {"color": "#b45309", "lw": 1.5},
        ("long1", 3): {"color": "#6ee7b7", "lw": 1.4, "ls": "--"},
        ("hs300", 0): {"color": "#888888", "lw": 1.2, "ls": ":"},
    }
    for (st, hd), g in equity_all.groupby(["strategy", "hold_days"]):
        g = g.sort_values("date")
        y0 = float(g["equity"].iloc[0])
        if y0 <= 0:
            continue
        sty = styles.get((st, int(hd)), {"lw": 1.2})
        ax.plot(
            pd.to_datetime(g["date"]),
            g["equity"] / y0,
            label=labels.get((st, int(hd)), f"{st}-{hd}"),
            **sty,
        )
    ax.set_title("Staggered long T0#1 / T0#2, clear on T3")
    ax.set_xlabel("Date")
    ax.set_ylabel("NAV")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    _safe_print(f"  [report] 净值图 -> {path}")


def _pct(x: float) -> str:
    return f"{100.0 * float(x):.1f}%"


def write_summary(
    path: str,
    universe: pd.DataFrame,
    metrics_df: pd.DataFrame,
    cfg: dict[str, Any],
) -> None:
    lines = [
        "# 雷达强度 · T0/T1 买第一 · T1/T2 买第二 · T3 清仓轮动",
        "",
        "## 口径",
        "",
        "- 股票池：雷达当前自选 M加/Q 各前 3（巨人网络 / 宁波中百 / *ST皇庭 / 恺英网络 / 昂立教育 / 辰欣药业）",
        "- 每个 T0 按当日雷达强度锁定第 1、第 2，本轮不再改名",
        "- 强度：`50 + 10×(个股−沪深300) + 8×(个股−申万板块)`",
        "- 轨道一：T0、T1 买入 T0 第一；T2 锁仓；T3 清仓",
        "- 轨道二：T1、T2 买入 T0 第二；T3 清仓",
        "- 合并账户：T0/T1/T1/T2 四笔各约 25% 权益；单轨道对照各两笔 50%",
        "- T3 清完后次日才开新一轮 T0；卖不出则延期清仓",
        "- T+1；涨停买不进 / 跌停卖不出；佣金万三（最低 5 元）+ 卖出印花税 0.05%",
        f"- 区间：{cfg['start']} ~ {cfg['end']}　初始资金 {cfg['cash']:,.0f}",
        "",
        f"固定名单 {len(universe)} 只：",
        "",
        "| 代码 | 名称 | 来源组 |",
        "| --- | --- | --- |",
    ]
    for r in universe.itertuples(index=False):
        lines.append(f"| {r.symbol} | {r.name} | {r.group}#{r.group_rank} |")
    lines += [
        "",
        "## 对比",
        "",
        "| 策略 | 持有 | 总收益 | 年化 | 最大回撤 | 夏普 | 完整轮次 | 胜率 | 跳过 | 期末权益 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    name_map = {
        "stagger_combo": "合并：第一+第二分批",
        "stagger_first": "只做 T0 第一",
        "stagger_second": "只做 T0 第二",
        "long_strongest": "做多最强(对照)",
        "hs300": "沪深300",
    }
    for r in metrics_df.itertuples(index=False):
        hold = "—" if int(r.hold_days) == 0 else f"T{int(r.hold_days)}"
        lines.append(
            f"| {name_map.get(str(r.strategy), r.strategy)} | {hold} | "
            f"{_pct(r.total_return)} | {_pct(r.annual_return)} | {_pct(r.max_drawdown)} | "
            f"{float(r.sharpe):.2f} | {int(r.n_roundtrips)} | {_pct(r.win_rate)} | "
            f"{int(r.skipped)} | {float(r.end_equity):,.0f} |"
        )
    lines += ["", f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ""]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="雷达 T0/T1 买第一、T1/T2 买第二、T3 清仓轮动")
    p.add_argument("--start", default=DEFAULT_START)
    p.add_argument("--end", default=ALIGN_END_DEFAULT, help="默认对齐强度轮动 2026-08-30")
    p.add_argument("--cash", type=float, default=DEFAULT_CASH)
    p.add_argument("--out", default="")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    start = str(args.start).strip()
    end = str(args.end).strip() or ALIGN_END_DEFAULT
    cash = float(args.cash)
    out = os.path.abspath(str(args.out).strip() or OUT_DIR)
    os.makedirs(out, exist_ok=True)

    _safe_print("【1/5】读取雷达当前自选前六")
    universe = load_aligned_universe()
    _safe_print(
        f"  {len(universe)} 只: "
        + "、".join(f"{r.name}{r.symbol}" for r in universe.itertuples(index=False))
    )
    universe.to_csv(os.path.join(out, "universe.csv"), index=False, encoding="utf-8-sig")

    _safe_print("【2/5】拉取日线 / 沪深300 / 申万")
    pro = get_pro()
    names = {r.symbol: r.name for r in universe.itertuples(index=False)}
    symbols = universe["symbol"].tolist()
    bars = fetch_stock_bars(symbols, start, end)
    missing = [s for s in symbols if s not in bars]
    if missing:
        _safe_print(f"  无行情: {', '.join(missing)}")
    hs300 = fetch_index_daily(pro, start, end)
    ts_codes = [to_ts_code(s) for s in bars]
    sw_map = resolve_sw_map(pro, ts_codes)
    sector_of: dict[str, tuple[str, str]] = {}
    sector_codes: list[str] = []
    for sym in bars:
        sw = sw_map.get(to_ts_code(sym)) or {}
        sc, sn, _lv = _sector_display(sw)
        sector_of[sym] = (sc, sn)
        if sc and sc not in sector_codes:
            sector_codes.append(sc)
    sector_pct: dict[str, pd.DataFrame] = {}
    for sc in sector_codes:
        sector_pct[sc] = fetch_sw_daily(pro, sc, start, end)

    _safe_print("【3/5】按日计算强度")
    ranks = build_daily_ranks(universe, bars, hs300, sector_of, sector_pct, start, end)
    if ranks.empty:
        raise RuntimeError("没有可用的日度强度")
    ranks.to_csv(os.path.join(out, "daily_rank.csv"), index=False, encoding="utf-8-sig")
    calendar = sorted(pd.Timestamp(d).normalize() for d in ranks["date"].unique())
    _safe_print(f"  {len(calendar)} 个交易日")

    _safe_print("【4/5】回测 分批轮动 / 单轨道 / 做多最强 / 沪深300")
    eq_frames = []
    tr_frames = []
    metrics_rows = []
    for mode, label in (
        ("combined", "合并第一+第二"),
        ("first", "只做T0第一"),
        ("second", "只做T0第二"),
    ):
        eq, tr, met = run_staggered(ranks, bars, names, cash, mode=mode)
        eq_frames.append(eq)
        if not tr.empty:
            tr_frames.append(tr)
        metrics_rows.append(met)
        _safe_print(
            f"  {label}  收益={100*met['total_return']:.1f}%  "
            f"回撤={100*met['max_drawdown']:.1f}%  夏普={met['sharpe']:.2f}"
        )

    eq1, tr1, met1 = run_long_strongest(ranks, bars, names, cash, 3)
    eq_frames.append(eq1)
    if not tr1.empty:
        tr_frames.append(tr1)
    metrics_rows.append(met1)
    _safe_print(
        f"  做多最强 T3  收益={100*met1['total_return']:.1f}%  "
        f"回撤={100*met1['max_drawdown']:.1f}%  夏普={met1['sharpe']:.2f}"
    )

    hs_eq, hs_met = run_hs300(hs300, cash, calendar)
    if not hs_eq.empty:
        eq_frames.append(hs_eq)
    metrics_rows.append(hs_met)
    _safe_print(f"  沪深300  收益={100*hs_met['total_return']:.1f}%  回撤={100*hs_met['max_drawdown']:.1f}%")

    equity_all = pd.concat(eq_frames, ignore_index=True)
    trades_all = pd.concat(tr_frames, ignore_index=True) if tr_frames else pd.DataFrame()
    metrics_df = pd.DataFrame(metrics_rows)

    _safe_print("【5/5】写报告")
    for col in ("long_symbol", "short_symbol", "target_long", "target_short"):
        if col in equity_all.columns:
            equity_all[col] = equity_all[col].astype(str).replace({"nan": "", "None": ""})
    if not trades_all.empty and "symbol" in trades_all.columns:
        trades_all["symbol"] = trades_all["symbol"].astype(str).str.replace(r"\.0$", "", regex=True)
    equity_all.to_csv(os.path.join(out, "equity_curve.csv"), index=False, encoding="utf-8-sig")
    trades_all.to_csv(os.path.join(out, "trades.csv"), index=False, encoding="utf-8-sig")
    metrics_df.to_csv(os.path.join(out, "metrics.csv"), index=False, encoding="utf-8-sig")
    plot_compare(equity_all, os.path.join(out, "equity_curve.png"))
    write_summary(
        os.path.join(out, "summary.md"),
        universe,
        metrics_df,
        {"start": start, "end": end, "cash": cash},
    )
    _safe_print(f"  输出 -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
雷达「强度」多轨道轮动回测（收盘换仓口径）。

固定名单：成长因子指定分组各前 3（默认六组；`--groups M加,Q` 可缩池），全池去重后按日强度排序。
强度与盘中雷达一致：50 + 10×相对沪深300 + 8×相对申万板块（涨跌幅为百分点）。

交易规则：
- 默认三条独立轨道，跟踪强度第 1 / 2 / 3 名（`--tracks` 可改）
- `--freq weekly|daily|both`：周频 / 日频 / 两套都出
- 换仓日收盘卖旧、收盘买新；目标不变则不交易
- T+1：买入当日不可卖
- 涨停买不进 / 跌停卖不出 / 停牌或买不足 1 手 → 换仓失败，继续持有旧票
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Optional

import numpy as np
import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
for _p in (_SCRIPT_DIR, _PROJECT_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backtest_sy_002028_threshold import fetch_ohlc_qfq, six_digit_to_ts_code  # noqa: E402
from market_radar import (  # noqa: E402
    _sector_display,
    load_growth_factor_picks,
    resolve_sw_map,
    six_digit,
    strength_score,
    to_ts_code,
)

HS300 = "000300.SH"
LOT = 100
COMMISSION = 0.0003
STAMP = 0.0005
MIN_COMMISSION = 5.0
DEFAULT_CASH = 100_000.0
DEFAULT_START = "2026-01-01"
DEFAULT_FREQ = "weekly"
DEFAULT_TRACKS = (1, 2, 3)
OUT_DIR = os.path.join(_SCRIPT_DIR, "output", "strength_rotation")
OUT_DIR_MQ = os.path.join(_SCRIPT_DIR, "output", "strength_rotation_mq")


def _sleep(sec: float = 0.12) -> None:
    time.sleep(sec)


def _ymd(s: str) -> str:
    return str(s).replace("-", "")[:8]


def _to_date(v: Any) -> pd.Timestamp:
    return pd.Timestamp(v).normalize()


def _finite(v: Any) -> Optional[float]:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n != n:
        return None
    return n


def get_pro():
    from trend_pullback_chips import get_tushare_pro

    return get_tushare_pro()


def limit_pct(symbol: str, name: str) -> float:
    n = str(name or "").upper()
    if "ST" in n:
        return 4.85
    s = six_digit(symbol)
    if s.startswith(("300", "301", "688", "689")):
        return 19.5
    if s.startswith(("8", "4")):
        return 29.5
    return 9.8


def commission_fee(notional: float) -> float:
    return max(MIN_COMMISSION, abs(float(notional)) * COMMISSION)


def load_universe(groups: Optional[list[str]] = None) -> pd.DataFrame:
    picks, hint = load_growth_factor_picks()
    if not picks:
        raise RuntimeError(hint or "成长因子名单为空，请先运行「按成长因子排序」。")
    allow = {str(g).strip() for g in (groups or []) if str(g).strip()}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for p in picks:
        grp = str(p.get("group") or "").strip()
        if allow and grp not in allow:
            continue
        sym = six_digit(p.get("symbol") or "")
        if not sym or sym in seen:
            continue
        seen.add(sym)
        rows.append(
            {
                "symbol": sym,
                "name": str(p.get("name") or "").strip(),
                "group": grp,
                "group_rank": p.get("rank"),
                "industry": p.get("industry") or "",
            }
        )
    if not rows:
        want = "、".join(allow) if allow else "全部组"
        raise RuntimeError(f"成长因子名单中没有可用标的（筛选：{want}）。")
    return pd.DataFrame(rows)


def fetch_index_daily(pro, start: str, end: str, ts_code: str = HS300) -> pd.DataFrame:
    df = pro.index_daily(ts_code=ts_code, start_date=_ymd(start), end_date=_ymd(end))
    _sleep()
    if df is None or df.empty:
        raise RuntimeError(f"无法获取指数 {ts_code} 日线")
    d = df.copy()
    d["date"] = pd.to_datetime(d["trade_date"].astype(str)).dt.normalize()
    d["close"] = pd.to_numeric(d["close"], errors="coerce")
    pre = (
        pd.to_numeric(d["pre_close"], errors="coerce")
        if "pre_close" in d.columns
        else pd.Series(np.nan, index=d.index)
    )
    named = (
        pd.to_numeric(d["pct_chg"], errors="coerce")
        if "pct_chg" in d.columns
        else pd.Series(np.nan, index=d.index)
    )
    from_px = np.where(pre.abs() > 1e-6, (d["close"] / pre - 1.0) * 100.0, np.nan)
    d["pct"] = np.where(named.notna(), named, from_px)
    return d[["date", "close", "pct"]].sort_values("date").reset_index(drop=True)


def fetch_sw_daily(pro, ts_code: str, start: str, end: str) -> pd.DataFrame:
    try:
        df = pro.sw_daily(ts_code=ts_code, start_date=_ymd(start), end_date=_ymd(end))
    except Exception:
        df = None
    _sleep()
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "pct"])
    d = df.copy()
    d["date"] = pd.to_datetime(d["trade_date"].astype(str)).dt.normalize()
    named = pd.to_numeric(d["pct_change"], errors="coerce") if "pct_change" in d.columns else pd.Series(np.nan, index=d.index)
    close = pd.to_numeric(d["close"], errors="coerce") if "close" in d.columns else pd.Series(np.nan, index=d.index)
    pre = (
        pd.to_numeric(d["pre_close"], errors="coerce")
        if "pre_close" in d.columns
        else pd.Series(np.nan, index=d.index)
    )
    from_px = np.where(pre.abs() > 1e-6, (close / pre - 1.0) * 100.0, np.nan)
    d["pct"] = np.where(named.notna(), named, from_px)
    return d[["date", "pct"]].dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def fetch_stock_bars(symbols: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    warm = (pd.Timestamp(start) - timedelta(days=12)).strftime("%Y-%m-%d")
    out: dict[str, pd.DataFrame] = {}
    n = len(symbols)
    for i, sym in enumerate(symbols):
        try:
            df = fetch_ohlc_qfq(sym, warm, end)
        except Exception as exc:
            print(f"  [bars] {sym} 跳过: {exc}", flush=True)
            continue
        if df is None or df.empty:
            continue
        d = df.copy()
        d["date"] = pd.to_datetime(d["date"]).dt.normalize()
        for c in ("open", "high", "low", "close"):
            d[c] = pd.to_numeric(d[c], errors="coerce")
        if "volume" in d.columns:
            d["volume"] = pd.to_numeric(d["volume"], errors="coerce")
        else:
            d["volume"] = np.nan
        d = d.sort_values("date").drop_duplicates("date").reset_index(drop=True)
        d["pct"] = d["close"].pct_change() * 100.0
        out[sym] = d
        if (i + 1) % 5 == 0 or i + 1 == n:
            print(f"  [bars] {i + 1}/{n}", flush=True)
        _sleep()
    return out


def bar_on(bars: dict[str, pd.DataFrame], symbol: str, dt: pd.Timestamp) -> Optional[pd.Series]:
    df = bars.get(symbol)
    if df is None or df.empty:
        return None
    sub = df[df["date"] == dt]
    if sub.empty:
        return None
    return sub.iloc[0]


def is_halted(row: Optional[pd.Series]) -> bool:
    if row is None:
        return True
    close = _finite(row.get("close"))
    if close is None or close <= 0:
        return True
    vol = _finite(row.get("volume"))
    if vol is not None and vol <= 0:
        return True
    return False


def is_limit_up(row: pd.Series, symbol: str, name: str) -> bool:
    pct = _finite(row.get("pct"))
    close = _finite(row.get("close"))
    high = _finite(row.get("high"))
    if pct is None or close is None or high is None:
        return False
    if pct < limit_pct(symbol, name):
        return False
    return close >= high * 0.995


def is_limit_down(row: pd.Series, symbol: str, name: str) -> bool:
    pct = _finite(row.get("pct"))
    close = _finite(row.get("close"))
    low = _finite(row.get("low"))
    if pct is None or close is None or low is None:
        return False
    if pct > -limit_pct(symbol, name):
        return False
    return close <= low * 1.005


def build_daily_ranks(
    universe: pd.DataFrame,
    bars: dict[str, pd.DataFrame],
    hs300: pd.DataFrame,
    sector_of: dict[str, tuple[str, str]],
    sector_pct: dict[str, pd.DataFrame],
    start: str,
    end: str,
) -> pd.DataFrame:
    names = {r.symbol: r.name for r in universe.itertuples(index=False)}
    hs = hs300.set_index("date")["pct"]
    sec_map = {k: v.set_index("date")["pct"] for k, v in sector_pct.items() if v is not None and not v.empty}
    start_ts, end_ts = _to_date(start), _to_date(end)
    calendar = sorted(
        {d for df in bars.values() for d in df["date"] if start_ts <= d <= end_ts}
        & set(hs300["date"])
    )
    rows: list[dict[str, Any]] = []
    for dt in calendar:
        hs_pct = _finite(hs.loc[dt]) if dt in hs.index else None
        scored: list[dict[str, Any]] = []
        for sym, df in bars.items():
            row = bar_on(bars, sym, dt)
            if row is None or _finite(row.get("pct")) is None:
                continue
            stock_pct = float(row["pct"])
            sc, sn = sector_of.get(sym, ("", ""))
            sp = None
            if sc and sc in sec_map and dt in sec_map[sc].index:
                sp = _finite(sec_map[sc].loc[dt])
            rs_index = None if hs_pct is None else round(stock_pct - hs_pct, 4)
            rs_sector = None if sp is None else round(stock_pct - sp, 4)
            strength = strength_score(rs_index, rs_sector)
            if strength is None:
                continue
            scored.append(
                {
                    "date": dt,
                    "symbol": sym,
                    "name": names.get(sym, ""),
                    "strength": int(strength),
                    "rs_index": rs_index,
                    "rs_sector": rs_sector,
                    "stock_pct": round(stock_pct, 4),
                    "hs300_pct": hs_pct,
                    "sector_code": sc or None,
                    "sector_name": sn or None,
                    "sector_pct": sp,
                    "close": float(row["close"]),
                }
            )
        scored.sort(key=lambda x: (-x["strength"], x["symbol"]))
        for i, item in enumerate(scored, start=1):
            item["rank"] = i
            rows.append(item)
    return pd.DataFrame(rows)


def week_last_trading_days(calendar: list[pd.Timestamp]) -> list[pd.Timestamp]:
    """每个自然周（ISO 周）的最后一个交易日，作为周频调仓日。"""
    if not calendar:
        return []
    idx = pd.DatetimeIndex(pd.to_datetime(calendar)).normalize()
    iso = idx.isocalendar()
    df = pd.DataFrame(
        {
            "date": list(idx),
            "y": iso.year.astype(int),
            "w": iso.week.astype(int),
        }
    )
    last = df.groupby(["y", "w"], sort=True)["date"].max()
    return [pd.Timestamp(x).normalize() for x in last.tolist()]


def run_track(
    rank_k: int,
    ranks: pd.DataFrame,
    bars: dict[str, pd.DataFrame],
    names: dict[str, str],
    initial_cash: float,
    rebalance_dates: Optional[set[pd.Timestamp]] = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    calendar = sorted(pd.Timestamp(d).normalize() for d in ranks["date"].unique())
    by_date = {
        pd.Timestamp(dt).normalize(): g.sort_values("rank")
        for dt, g in ranks.groupby("date")
    }
    cash = float(initial_cash)
    shares = 0
    holding: Optional[str] = None
    buy_date: Optional[pd.Timestamp] = None
    equity_rows: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    skipped = 0
    locked_target: Optional[str] = None
    rebal_set = rebalance_dates

    def target_of(dt: pd.Timestamp) -> Optional[str]:
        g = by_date.get(dt)
        if g is None or g.empty:
            return None
        hit = g[g["rank"] == rank_k]
        if hit.empty:
            return None
        return str(hit.iloc[0]["symbol"])

    def close_of(sym: str, dt: pd.Timestamp) -> Optional[float]:
        row = bar_on(bars, sym, dt)
        if row is None:
            return None
        return _finite(row.get("close"))

    def can_buy(sym: str, dt: pd.Timestamp) -> bool:
        row = bar_on(bars, sym, dt)
        if is_halted(row):
            return False
        assert row is not None
        return not is_limit_up(row, sym, names.get(sym, ""))

    def can_sell(sym: str, dt: pd.Timestamp) -> bool:
        row = bar_on(bars, sym, dt)
        if is_halted(row):
            return False
        assert row is not None
        return not is_limit_down(row, sym, names.get(sym, ""))

    def mark_equity(dt: pd.Timestamp) -> float:
        px = close_of(holding, dt) if holding else None
        mv = shares * px if holding and px else 0.0
        return cash + mv

    for dt in calendar:
        is_rebal = rebal_set is None or dt in rebal_set
        if is_rebal:
            locked_target = target_of(dt)
        target = locked_target
        switched = False
        action = "hold"
        reason = ""

        want_entry = is_rebal and holding is None and target is not None
        want_switch = (
            is_rebal
            and holding is not None
            and target is not None
            and target != holding
            and buy_date is not None
            and dt > buy_date
        )

        if want_switch:
            old = holding
            new = target
            sell_px = close_of(old, dt) if old else None
            buy_px = close_of(new, dt) if new else None
            if (
                old
                and new
                and can_sell(old, dt)
                and can_buy(new, dt)
                and sell_px
                and buy_px
                and sell_px > 0
                and buy_px > 0
            ):
                notional = shares * sell_px
                fee_s = commission_fee(notional)
                stamp = notional * STAMP
                cash_after_sell = cash + notional - fee_s - stamp
                lots = int(cash_after_sell / (buy_px * (1.0 + COMMISSION)) // LOT)
                buy_shares = lots * LOT if lots >= 1 else 0
                fee_b = commission_fee(buy_shares * buy_px) if buy_shares else 0.0
                cost = buy_shares * buy_px + fee_b if buy_shares else 0.0
                if buy_shares >= LOT and cost <= cash_after_sell + 1e-6:
                    cash = cash_after_sell
                    trades.append(
                        {
                            "date": dt,
                            "track": rank_k,
                            "action": "SELL",
                            "symbol": old,
                            "name": names.get(old, ""),
                            "price": round(sell_px, 4),
                            "shares": shares,
                            "fee": round(fee_s + stamp, 4),
                            "cash_after": round(cash, 2),
                        }
                    )
                    cash -= cost
                    shares = buy_shares
                    holding = new
                    buy_date = dt
                    switched = True
                    action = "switch"
                    trades.append(
                        {
                            "date": dt,
                            "track": rank_k,
                            "action": "BUY",
                            "symbol": new,
                            "name": names.get(new, ""),
                            "price": round(buy_px, 4),
                            "shares": buy_shares,
                            "fee": round(fee_b, 4),
                            "cash_after": round(cash, 2),
                        }
                    )
                else:
                    skipped += 1
                    reason = "换仓后买不足一手，继续持有"
                    action = "hold_fail"
            else:
                skipped += 1
                reason = "涨停/跌停/停牌，继续持有"
                action = "hold_fail"
        elif want_entry:
            if can_buy(target, dt):
                buy_px = close_of(target, dt)
                if buy_px and buy_px > 0:
                    lots = int(cash / (buy_px * (1.0 + COMMISSION)) // LOT)
                    if lots >= 1:
                        buy_shares = lots * LOT
                        fee_b = commission_fee(buy_shares * buy_px)
                        cost = buy_shares * buy_px + fee_b
                        if cost <= cash + 1e-6:
                            cash -= cost
                            shares = buy_shares
                            holding = target
                            buy_date = dt
                            action = "entry"
                            trades.append(
                                {
                                    "date": dt,
                                    "track": rank_k,
                                    "action": "BUY",
                                    "symbol": target,
                                    "name": names.get(target, ""),
                                    "price": round(buy_px, 4),
                                    "shares": buy_shares,
                                    "fee": round(fee_b, 4),
                                    "cash_after": round(cash, 2),
                                }
                            )
                        else:
                            reason = "现金不足一手"
                    else:
                        reason = "现金不足一手"
                else:
                    reason = "缺收盘价"
            else:
                reason = "涨停/停牌，未开仓"
                skipped += 1
        elif holding and target == holding:
            action = "hold"
            reason = "目标未变" if is_rebal else "非调仓日"
        elif not is_rebal:
            action = "hold"
            reason = "非调仓日"

        eq = mark_equity(dt)
        strength_val = None
        if target:
            src = by_date.get(dt)
            if src is not None and not src.empty:
                hit = src[src["symbol"].astype(str) == str(target)]
                if not hit.empty:
                    strength_val = int(hit.iloc[0]["strength"])
        equity_rows.append(
            {
                "date": dt,
                "track": rank_k,
                "equity": round(eq, 2),
                "cash": round(cash, 2),
                "holding": holding or "",
                "holding_name": names.get(holding or "", ""),
                "shares": shares,
                "target": target or "",
                "target_name": names.get(target or "", ""),
                "target_strength": strength_val,
                "action": action,
                "reason": reason,
                "switched": switched,
                "rebalance": is_rebal,
            }
        )

    equity_df = pd.DataFrame(equity_rows)
    trades_df = pd.DataFrame(trades)
    if not equity_df.empty:
        equity_df["day_return"] = equity_df["equity"].pct_change().fillna(0.0)
    metrics = compute_metrics(equity_df, trades_df, initial_cash, rank_k, skipped)
    return equity_df, trades_df, metrics


def compute_metrics(
    equity_df: pd.DataFrame,
    trades_df: pd.DataFrame,
    initial_cash: float,
    rank_k: int,
    skipped: int,
) -> dict:
    if equity_df is None or equity_df.empty:
        return {"track": rank_k, "total_return": 0.0, "annual_return": 0.0, "max_drawdown": 0.0, "sharpe": 0.0}
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
    sells = trades_df[trades_df["action"] == "SELL"] if not trades_df.empty else pd.DataFrame()
    buys = trades_df[trades_df["action"] == "BUY"] if not trades_df.empty else pd.DataFrame()
    round_pnls: list[float] = []
    hold_days: list[int] = []
    if not buys.empty:
        buy_q = list(buys.itertuples(index=False))
        sell_q = list(sells.itertuples(index=False)) if not sells.empty else []
        for i, b in enumerate(buy_q):
            if i < len(sell_q):
                s = sell_q[i]
                buy_cost = float(b.shares) * float(b.price) + float(b.fee)
                sell_net = float(s.shares) * float(s.price) - float(s.fee)
                round_pnls.append(sell_net / buy_cost - 1.0 if buy_cost > 0 else 0.0)
                hold_days.append(int((pd.Timestamp(s.date) - pd.Timestamp(b.date)).days))
    win_rate = float(np.mean([p > 0 for p in round_pnls])) if round_pnls else 0.0
    return {
        "track": rank_k,
        "total_return": total_ret,
        "annual_return": annual,
        "max_drawdown": mdd,
        "sharpe": sharpe,
        "avg_day_return": float(rets.mean()) if len(rets) else 0.0,
        "trade_days": int(n),
        "n_buy": int(len(buys)),
        "n_sell": int(len(sells)),
        "n_roundtrips": int(len(round_pnls)),
        "win_rate": win_rate,
        "avg_hold_calendar_days": float(np.mean(hold_days)) if hold_days else 0.0,
        "skipped_switches": int(skipped),
        "end_equity": float(eq["equity"].iloc[-1]),
        "end_holding": str(eq["holding"].iloc[-1] or ""),
        "end_holding_name": str(eq["holding_name"].iloc[-1] or ""),
    }


def plot_equity(
    equity_all: pd.DataFrame,
    bench: pd.DataFrame,
    path: str,
    *,
    title: str = "Strength rotation NAV (close-to-close)",
) -> None:
    if equity_all is None or equity_all.empty:
        return
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        print(f"  [report] 跳过绘图: {exc}", flush=True)
        return
    fig, ax = plt.subplots(figsize=(10, 5.4))
    track_ids = sorted({int(x) for x in equity_all["track"].dropna().unique()})
    for k in track_ids:
        label = f"Rank {k}"
        g = equity_all[equity_all["track"] == k].sort_values("date")
        if g.empty:
            continue
        y0 = float(g["equity"].iloc[0])
        if y0 > 0:
            ax.plot(pd.to_datetime(g["date"]), g["equity"] / y0, label=label, linewidth=1.6)
    if bench is not None and not bench.empty:
        b = bench.copy()
        b["date"] = pd.to_datetime(b["date"])
        eq_dates = pd.to_datetime(equity_all["date"])
        b = b[(b["date"] >= eq_dates.min()) & (b["date"] <= eq_dates.max())]
        if not b.empty:
            c0 = float(b["close"].iloc[0])
            if c0 > 0:
                ax.plot(
                    b["date"],
                    b["close"] / c0,
                    label="CSI 300",
                    linewidth=1.2,
                    linestyle="--",
                    color="#888888",
                )
    ax.set_title(title)
    ax.set_xlabel("Date")
    ax.set_ylabel("NAV (rebased)")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    print(f"  [report] 净值图 → {path}", flush=True)


def _pct(x: float) -> str:
    return f"{100.0 * float(x):.1f}%"


def write_summary(
    *,
    path: str,
    universe: pd.DataFrame,
    metrics_df: pd.DataFrame,
    cfg: dict,
) -> None:
    groups = cfg.get("groups") or []
    tracks = cfg.get("tracks") or list(DEFAULT_TRACKS)
    pool_desc = "、".join(str(g) for g in groups) if groups else "六组"
    track_desc = "、".join(f"第 {k} 名" for k in tracks)
    freq_desc = (
        "每个自然周最后一个交易日"
        if cfg.get("freq") == "weekly"
        else "每个交易日"
    )
    n_track = len(tracks)
    lines = [
        f"# 雷达强度{n_track}轨道轮动回测",
        "",
        "## 口径",
        "",
        f"- 股票池：成长因子「{pool_desc}」各组前 3，回测期内**固定名单**（全池去重后按日强度排序）",
        f"- 调仓频率：{freq_desc}；调仓日按**当日**强度排名",
        f"- 轨道：{track_desc}各一条，独立满仓，持有/切换逻辑相同",
        "- 强度：`50 + 10×(个股涨跌−沪深300) + 8×(个股涨跌−申万板块)`，与雷达一致",
        "- 换仓：目标变了才换；**换仓日收盘卖旧、收盘买新**",
        "- T+1：买入当日不可卖；目标不变则等待",
        "- 涨停/跌停/停牌或不足 1 手：换仓失败，继续持有",
        f"- 区间：{cfg['start']} ~ {cfg['end']}　初始资金 {cfg['cash']:,.0f}　佣金万三（最低 5 元）+ 印花税 0.05%",
        "",
        f"固定名单 {len(universe)} 只（{pool_desc} 各组前 3，组间去重）：",
        "",
        "| 代码 | 名称 | 来源组 |",
        "| --- | --- | --- |",
    ]
    for r in universe.itertuples(index=False):
        lines.append(f"| {r.symbol} | {r.name} | {r.group}#{r.group_rank} |")
    lines += [
        "",
        "## 绩效",
        "",
        "| 轨道 | 总收益 | 年化 | 最大回撤 | 夏普 | 买入次数 | 完整轮次 | 胜率 | 平均持有(自然日) | 期末持仓 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for r in metrics_df.itertuples(index=False):
        hold = f"{r.end_holding_name} {r.end_holding}".strip()
        lines.append(
            f"| 第 {int(r.track)} 名 | {_pct(r.total_return)} | {_pct(r.annual_return)} | "
            f"{_pct(r.max_drawdown)} | {float(r.sharpe):.2f} | {int(r.n_buy)} | {int(r.n_roundtrips)} | "
            f"{_pct(r.win_rate)} | {float(r.avg_hold_calendar_days):.1f} | {hold or '—'} |"
        )
    lines += ["", f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ""]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _split_csv(raw: str) -> list[str]:
    return [x.strip() for x in str(raw or "").split(",") if x.strip()]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="雷达强度多轨道轮动回测（收盘换仓）")
    p.add_argument("--start", default=DEFAULT_START, help="起始日 YYYY-MM-DD")
    p.add_argument("--end", default="", help="结束日，默认最近交易日")
    p.add_argument("--cash", type=float, default=DEFAULT_CASH, help="每条轨道初始资金")
    p.add_argument(
        "--groups",
        default="",
        help="成长因子分组，逗号分隔；默认六组。例：M加,Q",
    )
    p.add_argument(
        "--tracks",
        default="1,2,3",
        help="回测轨道名次，逗号分隔（默认 1,2,3）",
    )
    p.add_argument(
        "--freq",
        choices=("weekly", "daily", "both"),
        default=DEFAULT_FREQ,
        help="调仓频率：weekly / daily / both=日频+周频各出一套",
    )
    p.add_argument("--out", default="", help="输出目录；freq=both 时在其下写 daily/ weekly")
    return p.parse_args()


def _write_freq_pack(
    *,
    freq: str,
    dest: str,
    ranks: pd.DataFrame,
    bars: dict[str, pd.DataFrame],
    names: dict[str, str],
    hs300: pd.DataFrame,
    universe: pd.DataFrame,
    tracks: list[int],
    cash: float,
    start: str,
    end: str,
    groups: list[str],
) -> pd.DataFrame:
    os.makedirs(dest, exist_ok=True)
    rebal_set: Optional[set[pd.Timestamp]] = None
    if freq == "weekly":
        cal = sorted(pd.Timestamp(d).normalize() for d in ranks["date"].unique())
        rebal_days = week_last_trading_days(cal)
        rebal_set = set(rebal_days)
        print(f"  周频调仓日 {len(rebal_days)} 个", flush=True)
    print(f"【回测】轨道 {' / '.join(str(k) for k in tracks)}（{freq}）", flush=True)
    equity_frames = []
    trade_frames = []
    metrics_rows = []
    for k in tracks:
        eq, tr, met = run_track(
            k, ranks, bars, names, cash, rebalance_dates=rebal_set
        )
        equity_frames.append(eq)
        if not tr.empty:
            trade_frames.append(tr)
        metrics_rows.append(met)
        print(
            f"  第 {k} 名  收益={100*met['total_return']:.1f}%  "
            f"年化={100*met['annual_return']:.1f}%  回撤={100*met['max_drawdown']:.1f}%  "
            f"换仓买入 {met['n_buy']} 次",
            flush=True,
        )
    equity_all = pd.concat(equity_frames, ignore_index=True)
    trades_all = pd.concat(trade_frames, ignore_index=True) if trade_frames else pd.DataFrame()
    metrics_df = pd.DataFrame(metrics_rows)
    equity_all.to_csv(os.path.join(dest, "equity_curve.csv"), index=False, encoding="utf-8-sig")
    trades_all.to_csv(os.path.join(dest, "trades.csv"), index=False, encoding="utf-8-sig")
    metrics_df.to_csv(os.path.join(dest, "metrics.csv"), index=False, encoding="utf-8-sig")
    plot_equity(
        equity_all,
        hs300,
        os.path.join(dest, "equity_curve.png"),
        title=f"Strength rotation NAV ({freq} rebalance)",
    )
    write_summary(
        path=os.path.join(dest, "summary.md"),
        universe=universe,
        metrics_df=metrics_df,
        cfg={
            "start": start,
            "end": end,
            "cash": cash,
            "freq": freq,
            "groups": groups,
            "tracks": tracks,
        },
    )
    print(f"  输出 → {dest}", flush=True)
    return metrics_df


def _write_compare(path: str, daily: pd.DataFrame, weekly: pd.DataFrame, cfg: dict) -> None:
    lines = [
        "# M加+Q 三轨道 · 日频 vs 周频",
        "",
        f"- 区间：{cfg['start']} ~ {cfg['end']}",
        f"- 股票池：{'、'.join(cfg.get('groups') or [])} 各组前 3",
        "- 换仓：收盘卖旧买新；目标不变不换；T+1",
        "",
        "| 轨道 | 日频收益 | 周频收益 | 日频回撤 | 周频回撤 | 日频买入 | 周频买入 | 日频夏普 | 周频夏普 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    dmap = {int(r.track): r for r in daily.itertuples(index=False)} if daily is not None and not daily.empty else {}
    wmap = {int(r.track): r for r in weekly.itertuples(index=False)} if weekly is not None and not weekly.empty else {}
    for k in cfg.get("tracks") or []:
        d, w = dmap.get(int(k)), wmap.get(int(k))
        lines.append(
            f"| 第 {int(k)} 名 | "
            f"{_pct(d.total_return) if d else '—'} | {_pct(w.total_return) if w else '—'} | "
            f"{_pct(d.max_drawdown) if d else '—'} | {_pct(w.max_drawdown) if w else '—'} | "
            f"{int(d.n_buy) if d else '—'} | {int(w.n_buy) if w else '—'} | "
            f"{(f'{float(d.sharpe):.2f}' if d else '—')} | {(f'{float(w.sharpe):.2f}' if w else '—')} |"
        )
    lines += ["", f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> int:
    args = parse_args()
    end = str(args.end).strip() or datetime.now().strftime("%Y-%m-%d")
    start = str(args.start).strip()
    groups = _split_csv(args.groups)
    tracks = [int(x) for x in _split_csv(args.tracks)] or list(DEFAULT_TRACKS)
    freq_arg = str(args.freq).strip().lower() or DEFAULT_FREQ
    freqs = ["daily", "weekly"] if freq_arg == "both" else [freq_arg]
    default_out = OUT_DIR_MQ if groups == ["M加", "Q"] else OUT_DIR
    out_root = os.path.abspath(str(args.out).strip() or default_out)
    os.makedirs(out_root, exist_ok=True)

    print("【1/5】读取固定名单", flush=True)
    universe = load_universe(groups or None)
    print(
        f"  组={('、'.join(groups) if groups else '六组')}  {len(universe)} 只: "
        + "、".join(f"{r.name}{r.symbol}" for r in universe.itertuples(index=False)),
        flush=True,
    )
    universe.to_csv(os.path.join(out_root, "universe.csv"), index=False, encoding="utf-8-sig")

    print("【2/5】拉取日线 / 沪深300 / 申万板块", flush=True)
    pro = get_pro()
    symbols = universe["symbol"].tolist()
    names = {r.symbol: r.name for r in universe.itertuples(index=False)}
    bars = fetch_stock_bars(symbols, start, end)
    missing = [s for s in symbols if s not in bars]
    if missing:
        print(f"  无行情: {', '.join(missing)}", flush=True)
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
    for i, sc in enumerate(sector_codes):
        sector_pct[sc] = fetch_sw_daily(pro, sc, start, end)
        if (i + 1) % 5 == 0 or i + 1 == len(sector_codes):
            print(f"  [sw] {i + 1}/{len(sector_codes)}", flush=True)

    print("【3/5】按日计算强度并排序", flush=True)
    ranks = build_daily_ranks(universe, bars, hs300, sector_of, sector_pct, start, end)
    if ranks.empty:
        raise RuntimeError("没有可用的日度强度，请检查行情区间。")
    ranks.to_csv(os.path.join(out_root, "daily_rank.csv"), index=False, encoding="utf-8-sig")
    print(f"  {ranks['date'].nunique()} 个交易日 × {ranks['symbol'].nunique()} 只", flush=True)

    metrics_by_freq: dict[str, pd.DataFrame] = {}
    for freq in freqs:
        dest = os.path.join(out_root, freq) if len(freqs) > 1 else out_root
        metrics_by_freq[freq] = _write_freq_pack(
            freq=freq,
            dest=dest,
            ranks=ranks,
            bars=bars,
            names=names,
            hs300=hs300,
            universe=universe,
            tracks=tracks,
            cash=float(args.cash),
            start=start,
            end=end,
            groups=groups,
        )

    if "daily" in metrics_by_freq and "weekly" in metrics_by_freq:
        cmp_path = os.path.join(out_root, "compare_daily_weekly.md")
        _write_compare(
            cmp_path,
            metrics_by_freq["daily"],
            metrics_by_freq["weekly"],
            {"start": start, "end": end, "groups": groups, "tracks": tracks},
        )
        print(f"  日频/周频对照 → {cmp_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
场景3（龙虎榜跟随）与场景4（融资情绪反转）的纯函数信号逻辑。
与《市场数据一些应用场景.txt》中的扁平接口对齐，便于单测。
"""

from __future__ import annotations

from typing import Optional

import pandas as pd


def to_symbol_from_ts_code(ts_code: str) -> str:
    """000001.SZ -> 000001"""
    return ts_code.split(".")[0] if ts_code and "." in ts_code else ts_code


def exec_overnight_gap_below_pct(
    prior_close: float, open_t1: float, max_gap_up_pct: float = 0.02
) -> bool:
    if prior_close is None or prior_close <= 0 or open_t1 is None:
        return False
    return (open_t1 - prior_close) / prior_close < max_gap_up_pct


def event_dragon_daily_net_buy(dragon_raw: pd.DataFrame) -> pd.DataFrame:
    """
    将龙虎榜原始表聚合为 trade_date, symbol, net_buy。
    优先使用 net_amount；否则尝试 l_buy - l_sell。
    """
    if dragon_raw is None or dragon_raw.empty:
        return pd.DataFrame(columns=["trade_date", "symbol", "net_buy"])

    df = dragon_raw.copy()
    if "trade_date" in df.columns:
        df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str))
    if "ts_code" in df.columns:
        df["symbol"] = df["ts_code"].map(to_symbol_from_ts_code)
    elif "symbol" not in df.columns:
        raise ValueError("dragon_raw 需含 ts_code 或 symbol")

    if "net_amount" in df.columns:
        df["net_buy"] = pd.to_numeric(df["net_amount"], errors="coerce")
    elif "l_buy" in df.columns and "l_sell" in df.columns:
        df["net_buy"] = pd.to_numeric(df["l_buy"], errors="coerce") - pd.to_numeric(
            df["l_sell"], errors="coerce"
        )
    else:
        raise ValueError("dragon_raw 需含 net_amount 或 l_buy/l_sell")

    g = (
        df.groupby(["trade_date", "symbol"], as_index=False)["net_buy"]
        .sum()
        .sort_values(["trade_date", "symbol"])
    )
    return g


def event_dragon_net_buy_screen(
    dragon_daily: pd.DataFrame,
    trade_date: pd.Timestamp,
    universe_symbols: Optional[list[str]],
    min_net_buy: float = 50_000_000.0,
    net_buy_col: str = "net_buy",
    date_col: str = "trade_date",
    symbol_col: str = "symbol",
) -> list[str]:
    td = pd.Timestamp(trade_date).normalize()
    sub = dragon_daily[dragon_daily[date_col].dt.normalize() == td]
    sub = sub[sub[net_buy_col] >= min_net_buy]
    syms = sub[symbol_col].astype(str).tolist()
    if universe_symbols is not None:
        u = set(str(x) for x in universe_symbols)
        syms = [s for s in syms if s in u]
    return syms


def _bars_on_or_before(
    bars: pd.DataFrame, trade_date: pd.Timestamp, date_col: str
) -> pd.DataFrame:
    td = pd.Timestamp(trade_date).normalize()
    b = bars.copy()
    b[date_col] = pd.to_datetime(b[date_col]).dt.normalize()
    return b[b[date_col] <= td].sort_values(date_col)


def tech_consecutive_limit_up_streak(
    bars: pd.DataFrame,
    trade_date: pd.Timestamp,
    date_col: str = "trade_date",
    limit_pct: float = 0.098,
    price_col: str = "close",
) -> int:
    b = _bars_on_or_before(bars, trade_date, date_col)
    if len(b) < 2:
        return 0
    closes = b[price_col].astype(float).values
    streak = 0
    # 从最后一行（T 日）向过去数连续涨停
    i = len(b) - 1
    while i > 0:
        prev_c = closes[i - 1]
        cur_c = closes[i]
        if prev_c <= 0:
            break
        chg = cur_c / prev_c - 1.0
        if chg >= limit_pct:
            streak += 1
            i -= 1
        else:
            break
    return streak


def risk_exclude_hot_streak_limit_up(streak: int, min_streak_exclude: int = 2) -> bool:
    """True = 可保留（未触发连板剔除）。"""
    return streak < min_streak_exclude


def tech_turnover_between(
    bars: pd.DataFrame,
    trade_date: pd.Timestamp,
    turnover_col: str = "turnover_rate",
    date_col: str = "trade_date",
    min_turnover: Optional[float] = None,
    max_turnover: Optional[float] = None,
    turnover_is_pct: bool = True,
) -> bool:
    b = bars.copy()
    b[date_col] = pd.to_datetime(b[date_col]).dt.normalize()
    td = pd.Timestamp(trade_date).normalize()
    row = b[b[date_col] == td]
    if row.empty or turnover_col not in row.columns:
        return False
    t = float(row.iloc[-1][turnover_col])
    if turnover_is_pct and t is not None and t > 1.0:
        # 数据源若已是小数（0.05）则保持；若像 5.2 表示 5.2% 则 /100 可选，此处按「已为百分比数值」转小数
        t = t / 100.0
    if min_turnover is not None and t < min_turnover:
        return False
    if max_turnover is not None and t > max_turnover:
        return False
    return True


def flow_margin_balance_flat_or_down(
    margin_df: pd.DataFrame,
    symbol: str,
    trade_date: pd.Timestamp,
    date_col: str = "trade_date",
    symbol_col: str = "symbol",
    balance_col: str = "rzye",
) -> bool:
    m = margin_df.copy()
    m[date_col] = pd.to_datetime(m[date_col]).dt.normalize()
    td = pd.Timestamp(trade_date).normalize()
    sub = m[(m[symbol_col].astype(str) == str(symbol)) & (m[date_col] <= td)]
    if sub.empty:
        return False
    sub = sub.sort_values(date_col)
    last = sub[sub[date_col] == td]
    if last.empty:
        return False
    r_t = float(last.iloc[-1][balance_col])
    prev = sub[sub[date_col] < td]
    if prev.empty:
        return False
    r_prev = float(prev.iloc[-1][balance_col])
    return r_t <= r_prev


def rotation_s3_candidates_on_list_day(
    trade_date: pd.Timestamp,
    dragon_daily: pd.DataFrame,
    universe_symbols: list[str],
    bars_by_symbol: dict[str, pd.DataFrame],
    min_net_buy: float = 50_000_000.0,
    use_limit_up_filter: bool = True,
    min_streak_exclude: int = 2,
    use_turnover_filter: bool = False,
    turnover_min: Optional[float] = None,
    turnover_max: Optional[float] = None,
    margin_df: Optional[pd.DataFrame] = None,
    use_margin_flat_or_down: bool = False,
    date_col: str = "trade_date",
) -> list[str]:
    raw = event_dragon_net_buy_screen(
        dragon_daily, trade_date, universe_symbols, min_net_buy=min_net_buy
    )
    out: list[str] = []
    for sym in raw:
        if sym not in bars_by_symbol:
            continue
        bars = bars_by_symbol[sym]
        if use_limit_up_filter:
            st = tech_consecutive_limit_up_streak(bars, trade_date, date_col=date_col)
            if not risk_exclude_hot_streak_limit_up(st, min_streak_exclude):
                continue
        if use_turnover_filter:
            if not tech_turnover_between(
                bars,
                trade_date,
                date_col=date_col,
                min_turnover=turnover_min,
                max_turnover=turnover_max,
            ):
                continue
        if use_margin_flat_or_down and margin_df is not None:
            if not flow_margin_balance_flat_or_down(
                margin_df, sym, trade_date, date_col=date_col
            ):
                continue
        out.append(sym)
    return out


def rotation_s3_should_buy_at_next_open(
    prior_close: float, open_t1: float, max_gap_up_pct: float = 0.02
) -> bool:
    return exec_overnight_gap_below_pct(prior_close, open_t1, max_gap_up_pct)


def exec_exit_date_after_hold(
    entry_trade_date: pd.Timestamp,
    trading_calendar: pd.DatetimeIndex,
    hold_trading_days: int = 3,
) -> Optional[pd.Timestamp]:
    cal = pd.DatetimeIndex(sorted(pd.to_datetime(trading_calendar).normalize().unique()))
    entry_trade_date = pd.Timestamp(entry_trade_date).normalize()
    pos = cal.searchsorted(entry_trade_date)
    if pos >= len(cal) or cal[pos] != entry_trade_date:
        return None
    j = pos + hold_trading_days
    if j >= len(cal):
        return None
    return cal[j]


def flow_margin_rzye_series_until(
    margin_df: pd.DataFrame,
    symbol: str,
    trade_date: pd.Timestamp,
    date_col: str = "trade_date",
    symbol_col: str = "symbol",
    balance_col: str = "rzye",
) -> pd.Series:
    m = margin_df.copy()
    m[date_col] = pd.to_datetime(m[date_col]).dt.normalize()
    td = pd.Timestamp(trade_date).normalize()
    sub = m[(m[symbol_col].astype(str) == str(symbol)) & (m[date_col] <= td)]
    sub = sub.sort_values(date_col).drop_duplicates(date_col, keep="last")
    s = sub.set_index(date_col)[balance_col].astype(float)
    return s.sort_index()


def flow_rzye_strict_down_steps(
    rzye_series: pd.Series,
    trade_date: pd.Timestamp,
    n_steps: int = 5,
) -> bool:
    td = pd.Timestamp(trade_date).normalize()
    s = rzye_series.sort_index()
    if td not in s.index:
        return False
    pos = s.index.get_loc(td)
    if isinstance(pos, slice):
        return False
    start = int(pos) - n_steps
    if start < 0:
        return False
    window = s.iloc[start : pos + 1]
    if len(window) != n_steps + 1:
        return False
    z = window.values.astype(float)
    for i in range(n_steps):
        if not (z[i + 1] < z[i]):
            return False
    return True


def tech_cumulative_return_from_lag_close(
    bars: pd.DataFrame,
    trade_date: pd.Timestamp,
    lag_trading_days: int = 5,
    date_col: str = "trade_date",
    close_col: str = "close",
) -> Optional[float]:
    b = _bars_on_or_before(bars, trade_date, date_col)
    if len(b) < lag_trading_days + 1:
        return None
    close_now = float(b.iloc[-1][close_col])
    close_lag = float(b.iloc[-1 - lag_trading_days][close_col])
    if close_lag <= 0:
        return None
    return close_now / close_lag - 1.0


def tech_price_resilience_ok(
    cum_ret: Optional[float], min_cum_return: float = -0.05
) -> bool:
    if cum_ret is None:
        return False
    return cum_ret >= min_cum_return


def tech_bull_bar(
    bars: pd.DataFrame,
    trade_date: pd.Timestamp,
    date_col: str = "trade_date",
    require_close_ge_prev_close: bool = False,
) -> bool:
    b = _bars_on_or_before(bars, trade_date, date_col)
    if len(b) < 1:
        return False
    row = b.iloc[-1]
    o, c = float(row["open"]), float(row["close"])
    if c <= o:
        return False
    if require_close_ge_prev_close and len(b) >= 2:
        pc = float(b.iloc[-2]["close"])
        if c < pc:
            return False
    return True


def tech_volume_vs_ma_ratio(
    bars: pd.DataFrame,
    trade_date: pd.Timestamp,
    window: int = 5,
    exclude_today_from_ma: bool = True,
    date_col: str = "trade_date",
    vol_col: str = "volume",
) -> Optional[float]:
    b = _bars_on_or_before(bars, trade_date, date_col)
    if len(b) < window + 1:
        return None
    vol_t = float(b.iloc[-1][vol_col])
    hist = b.iloc[: -1] if exclude_today_from_ma else b
    hist = hist.tail(window)
    if len(hist) < window:
        return None
    ma_v = float(hist[vol_col].astype(float).mean())
    if ma_v <= 0:
        return None
    return vol_t / ma_v


def tech_volume_spike_ok(
    bars: pd.DataFrame,
    trade_date: pd.Timestamp,
    window: int = 5,
    min_ratio: float = 1.2,
    exclude_today_from_ma: bool = True,
    date_col: str = "trade_date",
) -> bool:
    r = tech_volume_vs_ma_ratio(
        bars,
        trade_date,
        window=window,
        exclude_today_from_ma=exclude_today_from_ma,
        date_col=date_col,
    )
    if r is None:
        return False
    return r >= min_ratio


def rotation_s4_signal_at_close(
    margin_df: pd.DataFrame,
    bars: pd.DataFrame,
    trade_date: pd.Timestamp,
    symbol: str,
    n_rzye_steps: int = 5,
    lag_trading_days: int = 5,
    min_cum_return: float = -0.05,
    vol_window: int = 5,
    vol_min_ratio: float = 1.2,
    date_col: str = "trade_date",
) -> bool:
    s = flow_margin_rzye_series_until(margin_df, symbol, trade_date, date_col=date_col)
    if not flow_rzye_strict_down_steps(s, trade_date, n_steps=n_rzye_steps):
        return False
    cr = tech_cumulative_return_from_lag_close(
        bars, trade_date, lag_trading_days=lag_trading_days, date_col=date_col
    )
    if not tech_price_resilience_ok(cr, min_cum_return=min_cum_return):
        return False
    if not tech_bull_bar(bars, trade_date, date_col=date_col):
        return False
    if not tech_volume_spike_ok(
        bars,
        trade_date,
        window=vol_window,
        min_ratio=vol_min_ratio,
        date_col=date_col,
    ):
        return False
    return True


def rotation_s4_eligible_symbols(
    trade_date: pd.Timestamp,
    universe_symbols: list[str],
    margin_df: pd.DataFrame,
    bars_by_symbol: dict[str, pd.DataFrame],
    date_col: str = "trade_date",
    **kwargs,
) -> list[str]:
    out: list[str] = []
    for sym in universe_symbols:
        if sym not in bars_by_symbol:
            continue
        if rotation_s4_signal_at_close(
            margin_df,
            bars_by_symbol[sym],
            trade_date,
            sym,
            date_col=date_col,
            **kwargs,
        ):
            out.append(sym)
    return out


def get_ohlc_on_date(
    bars: pd.DataFrame, trade_date: pd.Timestamp, date_col: str = "trade_date"
) -> Optional[tuple[float, float, float, float]]:
    """返回 (open, high, low, close) 或 None。"""
    b = bars.copy()
    b[date_col] = pd.to_datetime(b[date_col]).dt.normalize()
    td = pd.Timestamp(trade_date).normalize()
    row = b[b[date_col] == td]
    if row.empty:
        return None
    r = row.iloc[-1]
    return float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])


def next_trading_day(
    trade_date: pd.Timestamp, trading_calendar: pd.DatetimeIndex
) -> Optional[pd.Timestamp]:
    cal = pd.DatetimeIndex(sorted(pd.to_datetime(trading_calendar).normalize().unique()))
    td = pd.Timestamp(trade_date).normalize()
    pos = int(cal.searchsorted(td, side="right"))
    if pos >= len(cal):
        return None
    return cal[pos]

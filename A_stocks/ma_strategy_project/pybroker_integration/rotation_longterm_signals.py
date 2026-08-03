#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
场景1（成长+趋势）与场景2（高现金流价值错杀）的纯函数逻辑。
与《市场数据一些应用场景.txt》对齐。
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from rotation_fund_flow_signals import to_symbol_from_ts_code


def risk_st_exclude(
    st_flags: pd.DataFrame,
    trade_date: pd.Timestamp,
    universe_symbols: Optional[list[str]] = None,
    date_col: str = "trade_date",
    symbol_col: str = "symbol",
    is_st_col: str = "is_st",
) -> list[str]:
    if st_flags is None or st_flags.empty:
        return list(universe_symbols) if universe_symbols is not None else []
    td = pd.Timestamp(trade_date).normalize()
    sf = st_flags.copy()
    sf[date_col] = pd.to_datetime(sf[date_col]).dt.normalize()
    day = sf[sf[date_col] == td]
    st_set = set(day.loc[day[is_st_col] == True, symbol_col].astype(str))  # noqa: E712
    if universe_symbols is None:
        base = set(sf[sf[date_col] == td][symbol_col].astype(str).unique())
    else:
        base = set(str(x) for x in universe_symbols)
    return sorted(s for s in base if s not in st_set)


def fund_filter_announced_rows(
    fund_df: pd.DataFrame,
    trade_date: pd.Timestamp,
    ann_col: str = "ann_date",
) -> pd.DataFrame:
    if fund_df is None or fund_df.empty:
        return pd.DataFrame()
    df = fund_df.copy()
    df[ann_col] = pd.to_datetime(df[ann_col])
    td = pd.Timestamp(trade_date).normalize()
    return df[df[ann_col].dt.normalize() <= td].copy()


def fund_take_last_n_fiscal_per_symbol(
    df_ann: pd.DataFrame,
    n_rows: int,
    symbol_col: str = "symbol",
    end_col: str = "end_date",
) -> pd.DataFrame:
    if df_ann is None or df_ann.empty:
        return pd.DataFrame()
    df = df_ann.copy()
    df[end_col] = pd.to_datetime(df[end_col])
    parts: list[pd.DataFrame] = []
    for sym, g in df.groupby(symbol_col):
        g2 = g.sort_values(end_col, ascending=False).head(n_rows)
        parts.append(g2)
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True)


def fund_yoy_chain_all_above(
    df_tail: pd.DataFrame,
    rev_col: str,
    profit_col: str,
    symbol_col: str = "symbol",
    end_col: str = "end_date",
    n_compare: int = 3,
    min_yoy_rev: float = 0.15,
    min_yoy_profit: float = 0.15,
) -> pd.Series:
    """index=symbol, True=通过。"""
    out: dict[str, bool] = {}
    if df_tail is None or df_tail.empty:
        return pd.Series(dtype=bool)
    df = df_tail.copy()
    df[end_col] = pd.to_datetime(df[end_col])
    for sym, g in df.groupby(symbol_col):
        g = g.sort_values(end_col, ascending=True)
        if len(g) < n_compare + 1:
            out[str(sym)] = False
            continue
        rev = g[rev_col].astype(float).values
        ni = g[profit_col].astype(float).values
        ok = True
        for i in range(1, n_compare + 1):
            if rev[i - 1] <= 0 or ni[i - 1] == 0:
                ok = False
                break
            y_r = rev[i] / rev[i - 1] - 1.0
            y_n = ni[i] / ni[i - 1] - 1.0 if ni[i - 1] != 0 else -999
            if y_r < min_yoy_rev or y_n < min_yoy_profit:
                ok = False
                break
        out[str(sym)] = ok
    return pd.Series(out)


def fund_margin_non_decreasing_last_k(
    df_fiscal_asc: pd.DataFrame,
    k: int,
    margin_col: str = "grossprofit_margin",
    symbol_col: str = "symbol",
    end_col: str = "end_date",
    stable_max_spread: Optional[float] = None,
) -> pd.Series:
    out: dict[str, bool] = {}
    if df_fiscal_asc is None or df_fiscal_asc.empty:
        return pd.Series(dtype=bool)
    df = df_fiscal_asc.copy()
    df[end_col] = pd.to_datetime(df[end_col])
    for sym, g in df.groupby(symbol_col):
        g = g.sort_values(end_col, ascending=True).tail(k)
        if len(g) < k:
            out[str(sym)] = False
            continue
        m = g[margin_col].astype(float).values
        if stable_max_spread is not None:
            out[str(sym)] = float(m.max() - m.min()) <= stable_max_spread
        else:
            ok = all(m[i + 1] >= m[i] for i in range(len(m) - 1))
            out[str(sym)] = ok
    return pd.Series(out)


def tech_close_above_sma_stack(
    bars: pd.DataFrame,
    trade_date: pd.Timestamp,
    short: int = 60,
    long: int = 120,
    date_col: str = "trade_date",
    close_col: str = "close",
) -> bool:
    b = bars.copy()
    b[date_col] = pd.to_datetime(b[date_col]).dt.normalize()
    td = pd.Timestamp(trade_date).normalize()
    b = b[b[date_col] <= td].sort_values(date_col)
    if len(b) < long + 1:
        return False
    cl = b[close_col].astype(float)
    sma_s = cl.rolling(short, min_periods=short).mean().iloc[-1]
    sma_l = cl.rolling(long, min_periods=long).mean().iloc[-1]
    c = float(cl.iloc[-1])
    if pd.isna(sma_s) or pd.isna(sma_l):
        return False
    return c > sma_s > sma_l


def exec_is_monthly_rebalance_day(
    trading_days: pd.DatetimeIndex,
    trade_date: pd.Timestamp,
    rule: str = "first_trading_day_of_month",
) -> bool:
    cal = pd.DatetimeIndex(sorted(pd.to_datetime(trading_days).normalize().unique()))
    td = pd.Timestamp(trade_date).normalize()
    pos = int(cal.searchsorted(td))
    if pos >= len(cal) or cal[pos] != td:
        return False
    if rule == "first_trading_day_of_month":
        if pos == 0:
            return True
        prev_m = cal[pos - 1].month
        return td.month != prev_m
    if rule == "last_trading_day_of_month":
        if pos == len(cal) - 1:
            return True
        nxt_m = cal[pos + 1].month
        return td.month != nxt_m
    return False


def rotation_s1_eligible_symbols(
    trade_date: pd.Timestamp,
    universe_symbols: list[str],
    st_flags: Optional[pd.DataFrame],
    fund_df: pd.DataFrame,
    bars_by_symbol: dict[str, pd.DataFrame],
    trading_calendar: pd.DatetimeIndex,
    rev_col: str = "total_revenue",
    profit_col: str = "n_income",
    margin_col: str = "grossprofit_margin",
    n_fiscal_rows: int = 4,
    n_compare: int = 3,
    min_yoy_rev: float = 0.15,
    min_yoy_profit: float = 0.15,
    margin_k: int = 3,
    short_ma: int = 60,
    long_ma: int = 120,
    rebalance_rule: str = "first_trading_day_of_month",
    symbol_col: str = "symbol",
    end_col: str = "end_date",
    ann_col: str = "ann_date",
    date_col_bars: str = "trade_date",
) -> Optional[list[str]]:
    if not exec_is_monthly_rebalance_day(trading_calendar, trade_date, rule=rebalance_rule):
        return None
    allowed = risk_st_exclude(
        st_flags if st_flags is not None else pd.DataFrame(),
        trade_date,
        universe_symbols,
    )

    df_ann = fund_filter_announced_rows(fund_df, trade_date, ann_col=ann_col)
    df_tail = fund_take_last_n_fiscal_per_symbol(
        df_ann, n_fiscal_rows, symbol_col=symbol_col, end_col=end_col
    )
    yoy_ok = fund_yoy_chain_all_above(
        df_tail,
        rev_col=rev_col,
        profit_col=profit_col,
        symbol_col=symbol_col,
        end_col=end_col,
        n_compare=n_compare,
        min_yoy_rev=min_yoy_rev,
        min_yoy_profit=min_yoy_profit,
    )
    df_asc = df_tail.copy()
    m_ok = fund_margin_non_decreasing_last_k(
        df_asc,
        k=margin_k,
        margin_col=margin_col,
        symbol_col=symbol_col,
        end_col=end_col,
    )
    eligible: list[str] = []
    for sym in allowed:
        if sym not in yoy_ok.index or not bool(yoy_ok.get(sym, False)):
            continue
        if sym not in m_ok.index or not bool(m_ok.get(sym, False)):
            continue
        if sym not in bars_by_symbol:
            continue
        if tech_close_above_sma_stack(
            bars_by_symbol[sym],
            trade_date,
            short=short_ma,
            long=long_ma,
            date_col=date_col_bars,
        ):
            eligible.append(sym)
    return eligible


def fund_stmt_latest_merged_asof(
    bs_df: pd.DataFrame,
    cf_df: pd.DataFrame,
    trade_date: pd.Timestamp,
    ann_col: str = "ann_date",
    join_keys: tuple[str, str] = ("symbol", "end_date"),
    symbol_col: str = "symbol",
    end_col: str = "end_date",
) -> pd.DataFrame:
    T = pd.Timestamp(trade_date).normalize()
    bs = fund_filter_announced_rows(bs_df, T, ann_col=ann_col)
    cf = fund_filter_announced_rows(cf_df, T, ann_col=ann_col)
    if bs.empty or cf.empty:
        return pd.DataFrame()
    bs[end_col] = pd.to_datetime(bs[end_col])
    cf[end_col] = pd.to_datetime(cf[end_col])
    bs_idx = bs.groupby(symbol_col)[end_col].idxmax()
    bs_l = bs.loc[bs_idx]
    cf_idx = cf.groupby(symbol_col)[end_col].idxmax()
    cf_l = cf.loc[cf_idx]
    return pd.merge(bs_l, cf_l, on=list(join_keys), how="inner", suffixes=("_bs", "_cf"))


def fund_fcf_yield_ok(
    merged_stmt: pd.DataFrame,
    mcap_at_t: pd.Series,
    symbol_col: str = "symbol",
    ocf_col: str = "n_cashflow_act",
    capex_col: str = "c_pay_acq_const",
    capex_sign: str = "positive_is_outflow",
    min_fcf_yield: float = 0.05,
) -> pd.Series:
    out: dict[str, bool] = {}
    if merged_stmt is None or merged_stmt.empty:
        return pd.Series(dtype=bool)
    for _, row in merged_stmt.iterrows():
        sym = str(row[symbol_col])
        ocf = float(row.get(ocf_col, float("nan")))
        capex = float(row.get(capex_col, 0.0) or 0.0)
        if pd.isna(ocf):
            out[sym] = False
            continue
        if capex_sign == "positive_is_outflow":
            fcf = ocf - capex
        else:
            fcf = ocf + capex
        mv = float(mcap_at_t.get(sym, float("nan")))
        if mv <= 0 or pd.isna(mv):
            out[sym] = False
            continue
        out[sym] = (fcf / mv) >= min_fcf_yield
    return pd.Series(out)


def fund_debt_ratio_below(
    merged_stmt: pd.DataFrame,
    liab_col: str = "total_liab",
    asset_col: str = "total_assets",
    symbol_col: str = "symbol",
    max_debt_ratio: float = 0.6,
) -> pd.Series:
    out: dict[str, bool] = {}
    if merged_stmt is None or merged_stmt.empty:
        return pd.Series(dtype=bool)
    for _, row in merged_stmt.iterrows():
        sym = str(row[symbol_col])
        ta = float(row.get(asset_col, float("nan")))
        tl = float(row.get(liab_col, float("nan")))
        if pd.isna(ta) or ta <= 0 or pd.isna(tl):
            out[sym] = False
        else:
            out[sym] = (tl / ta) < max_debt_ratio
    return pd.Series(out)


def val_income_quarterly_ttm_net_asof(
    income_q_df: pd.DataFrame,
    trade_date: pd.Timestamp,
    symbol_col: str = "symbol",
    end_col: str = "end_date",
    ann_col: str = "ann_date",
    ni_col: str = "n_income",
) -> pd.Series:
    T = pd.Timestamp(trade_date).normalize()
    df = fund_filter_announced_rows(income_q_df, T, ann_col=ann_col)
    if df.empty:
        return pd.Series(dtype=float)
    df[end_col] = pd.to_datetime(df[end_col])
    ttm: dict[str, float] = {}
    for sym, g in df.groupby(symbol_col):
        g = g.sort_values(end_col, ascending=True)
        if len(g) < 4:
            ttm[str(sym)] = float("nan")
            continue
        last4 = g.tail(4)
        ttm[str(sym)] = float(last4[ni_col].astype(float).sum())
    return pd.Series(ttm)


def val_mcap_from_close_and_shares(
    close_at_t: pd.Series, shares: pd.Series
) -> pd.Series:
    c = close_at_t.astype(float)
    s = shares.astype(float)
    return c * s


def val_pe_ttm(mcap: pd.Series, ttm_net: pd.Series) -> pd.Series:
    pe = mcap.astype(float) / ttm_net.astype(float)
    pe = pe.where(ttm_net > 0)
    return pe


def val_pe_at_historical_low_quantile(
    current_pe: float,
    historical_pe: pd.Series,
    low_quantile: float = 0.2,
    min_hist_points: int = 60,
) -> bool:
    h = historical_pe.dropna()
    if len(h) < min_hist_points:
        return False
    if pd.isna(current_pe) or current_pe <= 0:
        return False
    q = float(h.quantile(low_quantile))
    return current_pe <= q


def tech_close_below_sma_by_pct(
    bars: pd.DataFrame,
    trade_date: pd.Timestamp,
    window: int = 20,
    min_below_pct: float = 0.03,
    date_col: str = "trade_date",
    close_col: str = "close",
) -> bool:
    b = bars.copy()
    b[date_col] = pd.to_datetime(b[date_col]).dt.normalize()
    td = pd.Timestamp(trade_date).normalize()
    b = b[b[date_col] <= td].sort_values(date_col)
    if len(b) < window + 1:
        return False
    cl = b[close_col].astype(float)
    sma = cl.rolling(window, min_periods=window).mean().iloc[-1]
    c = float(cl.iloc[-1])
    if pd.isna(sma) or sma <= 0:
        return False
    return (sma - c) / sma >= min_below_pct


def rotation_s2_eligible_symbols(
    trade_date: pd.Timestamp,
    universe_symbols: list[str],
    st_flags: Optional[pd.DataFrame],
    bs_df: pd.DataFrame,
    cf_df: pd.DataFrame,
    income_q_df: pd.DataFrame,
    close_at_t: pd.Series,
    shares_at_t: pd.Series,
    pe_history_by_symbol: dict[str, pd.Series],
    bars_by_symbol: dict[str, pd.DataFrame],
    trading_calendar: Optional[pd.DatetimeIndex] = None,
    rebalance_rule: str = "first_trading_day_of_month",
    use_st_filter: bool = True,
    date_col_bars: str = "trade_date",
    min_hist_points: int = 60,
    low_quantile: float = 0.2,
) -> Optional[list[str]]:
    """与 S1 相同：非月度调仓日返回 None，由调用方保留原持仓。"""
    if trading_calendar is not None and not exec_is_monthly_rebalance_day(
        trading_calendar, trade_date, rule=rebalance_rule
    ):
        return None
    if use_st_filter:
        if st_flags is not None and not st_flags.empty:
            allowed = risk_st_exclude(st_flags, trade_date, universe_symbols)
        else:
            allowed = list(universe_symbols)
    else:
        allowed = list(universe_symbols)

    merged = fund_stmt_latest_merged_asof(bs_df, cf_df, trade_date)
    mcap = val_mcap_from_close_and_shares(close_at_t, shares_at_t)
    fcf_ok = fund_fcf_yield_ok(merged, mcap)
    debt_ok = fund_debt_ratio_below(merged)

    ttm = val_income_quarterly_ttm_net_asof(income_q_df, trade_date)
    pe = val_pe_ttm(mcap.reindex(ttm.index).fillna(mcap), ttm)

    eligible: list[str] = []
    for sym in allowed:
        if sym not in fcf_ok.index or not bool(fcf_ok.get(sym, False)):
            continue
        if sym not in debt_ok.index or not bool(debt_ok.get(sym, False)):
            continue
        cpe = pe.get(sym, float("nan"))
        hist = pe_history_by_symbol.get(sym)
        if hist is None or hist.empty:
            continue
        past = hist[hist.index < pd.Timestamp(trade_date).normalize()]
        if not val_pe_at_historical_low_quantile(
            float(cpe),
            past,
            low_quantile=low_quantile,
            min_hist_points=min_hist_points,
        ):
            continue
        if sym not in bars_by_symbol:
            continue
        if not tech_close_below_sma_by_pct(
            bars_by_symbol[sym], trade_date, date_col=date_col_bars
        ):
            continue
        eligible.append(sym)
    return eligible


def add_symbol_from_ts_code(df: pd.DataFrame, ts_col: str = "ts_code") -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    out["symbol"] = out[ts_col].map(to_symbol_from_ts_code)
    return out


def normalize_fund_dates(
    df: pd.DataFrame,
    end_col: str = "end_date",
    ann_col: str = "ann_date",
) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    out[end_col] = pd.to_datetime(out[end_col], format="%Y%m%d", errors="coerce")
    if ann_col in out.columns:
        out[ann_col] = pd.to_datetime(out[ann_col], format="%Y%m%d", errors="coerce")
    return out

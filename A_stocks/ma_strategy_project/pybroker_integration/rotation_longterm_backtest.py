#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中长期回测：场景1（成长+双均线趋势）与场景2（现金流/杠杆/PE低位+错杀形态）。
股票池默认 stocks_pool.txt；财务与行情来自 Tushare pro。月度调仓：信号 T 日收盘，
成交 T+1 日开盘价；与文档全局约定一致。
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
    get_ohlc_on_date,
    next_trading_day,
    to_symbol_from_ts_code,
)
from rotation_longterm_signals import (  # noqa: E402
    add_symbol_from_ts_code,
    normalize_fund_dates,
    rotation_s1_eligible_symbols,
    rotation_s2_eligible_symbols,
    val_income_quarterly_ttm_net_asof,
)

DEFAULT_POOL = os.path.join(_CURRENT_DIR, "stocks_pool.txt")


def load_stock_pool(path: str) -> list[str]:
    with open(path, "r", encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]


def to_ts_code(code: str) -> str:
    c = str(code).strip()
    if c.endswith((".SH", ".SZ")):
        return c
    if c.startswith(("0", "3", "1")):
        return f"{c}.SZ"
    if c.startswith(("6", "5", "688")):
        return f"{c}.SH"
    return f"{c}.SZ"


def init_pro():
    import tushare as ts

    tok = (DATA_CONFIG.get("tushare_token") or "").strip()
    if not tok:
        raise RuntimeError("请配置 DATA_CONFIG['tushare_token']")
    ts.set_token(tok)
    return ts.pro_api()


def fetch_trade_cal(pro, start: str, end: str) -> pd.DatetimeIndex:
    df = pro.trade_cal(
        exchange="SSE",
        start_date=start.replace("-", ""),
        end_date=end.replace("-", ""),
        is_open="1",
    )
    if df is None or df.empty:
        return pd.DatetimeIndex([])
    df["cal_date"] = pd.to_datetime(df["cal_date"].astype(str))
    return pd.DatetimeIndex(sorted(df["cal_date"].unique()))


def fetch_daily_with_mv(pro, ts_code: str, s: str, e: str) -> pd.DataFrame:
    d1 = pro.daily(ts_code=ts_code, start_date=s, end_date=e)
    if d1 is None or d1.empty:
        return pd.DataFrame()
    d1["trade_date"] = pd.to_datetime(d1["trade_date"].astype(str))
    d1 = d1.rename(columns={"vol": "volume"})
    try:
        d2 = pro.daily_basic(
            ts_code=ts_code,
            start_date=s,
            end_date=e,
            fields="ts_code,trade_date,total_mv,total_share,turnover_rate",
        )
    except Exception:
        d2 = None
    if d2 is not None and not d2.empty:
        d2["trade_date"] = pd.to_datetime(d2["trade_date"].astype(str))
        d1 = d1.merge(
            d2[["trade_date", "total_mv", "total_share", "turnover_rate"]],
            on="trade_date",
            how="left",
        )
    else:
        d1["total_mv"] = pd.NA
        d1["total_share"] = pd.NA
        d1["turnover_rate"] = pd.NA
    for col in ("open", "high", "low", "close", "volume"):
        if col in d1.columns:
            d1[col] = pd.to_numeric(d1[col], errors="coerce")
    return d1.sort_values("trade_date").reset_index(drop=True)


def _sleep():
    time.sleep(0.11)


def _concat_nonempty(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """合并多表，排除空表与全空列，避免 pandas FutureWarning。"""
    cleaned: list[pd.DataFrame] = []
    for f in frames:
        if f is None or f.empty:
            continue
        f = f.dropna(axis=1, how="all")
        if f.empty or len(f.columns) == 0:
            continue
        cleaned.append(f)
    if not cleaned:
        return pd.DataFrame()
    return pd.concat(cleaned, ignore_index=True, sort=False)


def _with_symbol(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    return add_symbol_from_ts_code(df.copy())


def fetch_financials_pool(
    pro, pool: list[str], start: str, end: str, verbose: bool = True
) -> dict[str, pd.DataFrame]:
    """拉取利润表(含季报/年报)、资产负债表、现金流量表、fina_indicator。"""
    income_all: list[pd.DataFrame] = []
    bs_all: list[pd.DataFrame] = []
    cf_all: list[pd.DataFrame] = []
    fina_all: list[pd.DataFrame] = []

    n = len(pool)
    for i, code in enumerate(pool):
        if verbose:
            print(f"  [财务 {i + 1}/{n}] {code} …", flush=True)
        tc = to_ts_code(code)
        try:
            inc_all = pro.income(ts_code=tc, start_date=start, end_date=end)
            _sleep()
            bs = pro.balancesheet(ts_code=tc, start_date=start, end_date=end)
            _sleep()
            cf = pro.cashflow(ts_code=tc, start_date=start, end_date=end)
            _sleep()
            fi = pro.fina_indicator(ts_code=tc, start_date=start, end_date=end)
            _sleep()
            inc_all = _with_symbol(inc_all)
            if not inc_all.empty:
                income_all.append(normalize_fund_dates(inc_all))
            bs = _with_symbol(bs)
            if not bs.empty:
                bs_all.append(normalize_fund_dates(bs))
            cf = _with_symbol(cf)
            if not cf.empty:
                cf_all.append(normalize_fund_dates(cf))
            fi = _with_symbol(fi)
            if not fi.empty:
                fina_all.append(normalize_fund_dates(fi))
        except Exception:
            continue

    return {
        "income_raw": _concat_nonempty(income_all),
        "bs": _concat_nonempty(bs_all),
        "cf": _concat_nonempty(cf_all),
        "fina": _concat_nonempty(fina_all),
    }


def build_s1_fund_df(income_raw: pd.DataFrame, fina: pd.DataFrame) -> pd.DataFrame:
    """年报口径：期末 1231 + 合并 grossprofit_margin。"""
    if income_raw.empty:
        return pd.DataFrame()
    inc = income_raw.copy()
    inc["end_date"] = pd.to_datetime(inc["end_date"])
    # 年报：期末月为 12
    annual = inc[inc["end_date"].dt.month == 12].copy()
    rev_col = "total_revenue" if "total_revenue" in annual.columns else "revenue"
    if rev_col not in annual.columns:
        return pd.DataFrame()
    keep = ["symbol", "end_date", "ann_date", rev_col, "n_income"]
    annual = annual[[c for c in keep if c in annual.columns]]
    annual = annual.rename(columns={rev_col: "total_revenue"})
    if fina is not None and not fina.empty and "grossprofit_margin" in fina.columns:
        fi = fina.copy()
        fi["end_date"] = pd.to_datetime(fi["end_date"])
        fi = fi[["symbol", "end_date", "ann_date", "grossprofit_margin"]].drop_duplicates(
            subset=["symbol", "end_date"], keep="last"
        )
        annual = annual.merge(
            fi[["symbol", "end_date", "grossprofit_margin", "ann_date"]],
            on=["symbol", "end_date"],
            how="left",
            suffixes=("", "_fi"),
        )
        if "ann_date_fi" in annual.columns:
            annual["ann_date"] = annual["ann_date"].fillna(annual["ann_date_fi"])
            annual = annual.drop(columns=["ann_date_fi"], errors="ignore")
    return annual.drop_duplicates(subset=["symbol", "end_date"], keep="last")


def build_income_quarterly(income_raw: pd.DataFrame) -> pd.DataFrame:
    if income_raw.empty:
        return pd.DataFrame()
    df = income_raw.copy()
    df["end_date"] = pd.to_datetime(df["end_date"])
    # 去掉重复年报与季报混合时同一 end_date 多行，保留 ann_date 最新
    df = df.sort_values("ann_date").drop_duplicates(subset=["symbol", "end_date"], keep="last")
    return df


def pick_capex_col(cf: pd.DataFrame) -> str:
    for c in ("c_pay_acq_const", "c_pay_acq_disp_fiolta", "pay_working_cash"):
        if c in cf.columns:
            return c
    return "c_pay_acq_const"


def pick_bs_cols(bs: pd.DataFrame) -> tuple[str, str]:
    lc = "total_liab" if "total_liab" in bs.columns else "total_liab_sm"
    ac = "total_assets" if "total_assets" in bs.columns else "total_assets_sm"
    return lc, ac


def build_st_flags_for_pool(
    pro, pool: list[str], cal: pd.DatetimeIndex
) -> pd.DataFrame:
    try:
        basic = pro.stock_basic(
            exchange="",
            list_status="L",
            fields="ts_code,name",
        )
    except Exception:
        return pd.DataFrame()
    if basic is None or basic.empty:
        return pd.DataFrame()
    basic["symbol"] = basic["ts_code"].map(to_symbol_from_ts_code)
    st_pool = set()
    for _, r in basic.iterrows():
        name = str(r.get("name", ""))
        sym = str(r["symbol"])
        if sym not in pool:
            continue
        if "ST" in name.upper() or "*ST" in name or "退" in name:
            st_pool.add(sym)
    if not st_pool:
        return pd.DataFrame()
    rows = []
    for d in cal:
        for sym in st_pool:
            rows.append({"trade_date": pd.Timestamp(d).normalize(), "symbol": sym, "is_st": True})
    return pd.DataFrame(rows)


def build_pe_history_by_symbol(
    pool: list[str],
    income_q: pd.DataFrame,
    bars_by_symbol: dict[str, pd.DataFrame],
    pe_cal: pd.DatetimeIndex,
    min_hist_points: int,
    verbose: bool = True,
) -> dict[str, pd.Series]:
    """
    仅在 pe_cal 内的、且该股当日有 K 线的日期上算 PE，避免对整段日历暴力循环导致极慢。
    """
    out: dict[str, pd.Series] = {}
    cal_set = frozenset(pd.to_datetime(pe_cal).normalize().unique())
    n = len(pool)
    for si, sym in enumerate(pool):
        if verbose and (si == 0 or (si + 1) % 5 == 0 or si + 1 == n):
            print(f"  [PE 历史 {si + 1}/{n}] {sym} …", flush=True)
        if sym not in bars_by_symbol:
            continue
        bb = bars_by_symbol[sym]
        iq = income_q[income_q["symbol"] == sym] if not income_q.empty else pd.DataFrame()
        if iq.empty:
            out[sym] = pd.Series(dtype=float)
            continue
        pe_vals: dict[pd.Timestamp, float] = {}
        bar_dates = sorted(bb["trade_date"].dt.normalize().unique())
        for d in bar_dates:
            if d not in cal_set:
                continue
            ttm_s = val_income_quarterly_ttm_net_asof(iq, d)
            if sym not in ttm_s.index or pd.isna(ttm_s.get(sym, float("nan"))):
                continue
            ttm = float(ttm_s[sym])
            if ttm <= 0:
                continue
            row = bb[bb["trade_date"].dt.normalize() == d]
            if row.empty:
                continue
            mv_wan = row.iloc[-1].get("total_mv")
            if pd.isna(mv_wan):
                continue
            mcap = float(mv_wan) * 10000.0
            pe_vals[d] = mcap / ttm
        out[sym] = pd.Series(pe_vals).sort_index()
    return out


@dataclass
class LtState:
    cash: float
    commission: float
    positions: dict[str, int] = field(default_factory=dict)
    trades: list[dict[str, Any]] = field(default_factory=list)


def _liquidate_all(state: LtState, dt: pd.Timestamp, bars_by_symbol: dict[str, pd.DataFrame]):
    for sym, sh in list(state.positions.items()):
        if sh <= 0:
            continue
        bars = bars_by_symbol.get(sym)
        if bars is None:
            continue
        ohlc = get_ohlc_on_date(bars, dt, date_col="trade_date")
        if ohlc is None:
            continue
        op = ohlc[0]
        gross = sh * op
        fee = gross * state.commission
        state.cash += gross - fee
        state.trades.append(
            {"date": dt, "symbol": sym, "side": "sell", "price": op, "shares": sh}
        )
    state.positions.clear()


def _buy_equal_weight(
    state: LtState,
    symbols: list[str],
    dt: pd.Timestamp,
    bars_by_symbol: dict[str, pd.DataFrame],
    tag: str,
) -> None:
    if not symbols:
        return
    valid = [s for s in symbols if s in bars_by_symbol]
    if not valid:
        return
    budget = state.cash * (1 - state.commission)
    per = budget / len(valid)
    for sym in valid:
        bars = bars_by_symbol[sym]
        ohlc = get_ohlc_on_date(bars, dt, date_col="trade_date")
        if ohlc is None:
            continue
        op = ohlc[0]
        if op <= 0:
            continue
        sh = int(per // op)
        if sh <= 0:
            continue
        cost = sh * op * (1 + state.commission)
        if cost > state.cash:
            continue
        state.cash -= cost
        state.positions[sym] = state.positions.get(sym, 0) + sh
        state.trades.append(
            {"date": dt, "symbol": sym, "side": "buy", "price": op, "shares": sh, "tag": tag}
        )


def run_monthly_backtest_s1(
    pool: list[str],
    cal: pd.DatetimeIndex,
    fund_df: pd.DataFrame,
    st_flags: pd.DataFrame,
    bars_by_symbol: dict[str, pd.DataFrame],
    initial: float,
    commission: float,
) -> LtState:
    state = LtState(cash=initial, commission=commission)
    pending: Optional[tuple[list[str], pd.Timestamp]] = None

    for d in cal:
        d = pd.Timestamp(d).normalize()
        if pending is not None:
            tgt, ex = pending
            if d == ex:
                _liquidate_all(state, d, bars_by_symbol)
                _buy_equal_weight(state, tgt, d, bars_by_symbol, "s1")
                pending = None

        elig = rotation_s1_eligible_symbols(
            d,
            pool,
            st_flags if not st_flags.empty else None,
            fund_df,
            bars_by_symbol,
            cal,
            rev_col="total_revenue",
            profit_col="n_income",
            margin_col="grossprofit_margin",
        )
        if elig is not None:
            nxt = next_trading_day(d, cal)
            if nxt is not None:
                pending = (elig, nxt)

    if state.positions:
        _liquidate_all(state, cal[-1], bars_by_symbol)
    return state


def run_monthly_backtest_s2(
    pool: list[str],
    cal: pd.DatetimeIndex,
    bs: pd.DataFrame,
    cf: pd.DataFrame,
    income_q: pd.DataFrame,
    st_flags: pd.DataFrame,
    bars_by_symbol: dict[str, pd.DataFrame],
    pe_hist: dict[str, pd.Series],
    initial: float,
    commission: float,
    min_hist_points: int,
) -> LtState:
    state = LtState(cash=initial, commission=commission)
    pending: Optional[tuple[list[str], pd.Timestamp]] = None
    capex_col = pick_capex_col(cf) if not cf.empty else "c_pay_acq_const"

    for d in cal:
        d = pd.Timestamp(d).normalize()
        if pending is not None:
            tgt, ex = pending
            if d == ex:
                _liquidate_all(state, d, bars_by_symbol)
                _buy_equal_weight(state, tgt, d, bars_by_symbol, "s2")
                pending = None

        close_s = pd.Series(dtype=float)
        share_s = pd.Series(dtype=float)
        for sym in pool:
            bb = bars_by_symbol.get(sym)
            if bb is None or bb.empty:
                continue
            row = bb[bb["trade_date"].dt.normalize() == d]
            if row.empty:
                continue
            r = row.iloc[-1]
            close_s[sym] = float(r["close"])
            ts = r.get("total_share")
            if pd.notna(ts):
                share_s[sym] = float(ts) * 10000.0
            else:
                mv = r.get("total_mv")
                if pd.notna(mv) and float(r["close"]) > 0:
                    share_s[sym] = float(mv) * 10000.0 / float(r["close"])

        elig = rotation_s2_eligible_symbols(
            d,
            pool,
            st_flags if not st_flags.empty else None,
            bs,
            cf,
            income_q,
            close_s,
            share_s,
            pe_hist,
            bars_by_symbol,
            trading_calendar=cal,
            min_hist_points=min_hist_points,
        )
        if elig is not None:
            nxt = next_trading_day(d, cal)
            if nxt is not None:
                pending = (elig, nxt)

    if state.positions:
        _liquidate_all(state, cal[-1], bars_by_symbol)
    return state


def patch_cf_capex(cf: pd.DataFrame, capex_col: str) -> pd.DataFrame:
    if cf.empty:
        return cf
    out = cf.copy()
    if capex_col not in out.columns:
        out["c_pay_acq_const"] = 0.0
    else:
        out["c_pay_acq_const"] = pd.to_numeric(out[capex_col], errors="coerce").fillna(0.0)
    return out


def main():
    ap = argparse.ArgumentParser(description="场景1/2 中长期月度调仓回测")
    ap.add_argument("--pool", default=DEFAULT_POOL)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--scenario", choices=["1", "2", "both"], default="both")
    ap.add_argument("--cash", type=float, default=100_000.0)
    ap.add_argument("--commission", type=float, default=0.001)
    ap.add_argument("--pe-min-hist", type=int, default=60, help="场景2 PE 历史最低分位样本数下限")
    ap.add_argument("--quiet", action="store_true", help="关闭进度输出")
    args = ap.parse_args()
    verbose = not args.quiet

    start = args.start.replace("-", "")
    end = args.end.replace("-", "")
    pool = load_stock_pool(args.pool)
    if not pool:
        print("股票池为空")
        return

    pro = init_pro()
    cal = fetch_trade_cal(pro, start, end)
    if len(cal) == 0:
        print("交易日历为空")
        return

    ext_start = (cal[0] - pd.Timedelta(days=500)).strftime("%Y%m%d")
    ext_end = cal[-1].strftime("%Y%m%d")

    if verbose:
        print(
            "拉取财务与行情：每只股票约 5 次 Tushare 请求 + 限速 sleep，"
            f"池子 {len(pool)} 只须数分钟属正常；场景2 还会算 PE 历史。",
            flush=True,
        )
    fins = fetch_financials_pool(pro, pool, ext_start, ext_end, verbose=verbose)
    fund_s1 = build_s1_fund_df(fins["income_raw"], fins["fina"])
    if not fund_s1.empty and "ann_date" in fund_s1.columns:
        fund_s1 = fund_s1.dropna(subset=["ann_date"])
    income_q = build_income_quarterly(fins["income_raw"])
    if not income_q.empty and "ann_date" in income_q.columns:
        income_q = income_q.dropna(subset=["ann_date"])
    bs = fins["bs"]
    cf = fins["cf"]
    capex_col = pick_capex_col(cf)
    cf = patch_cf_capex(cf, capex_col)

    bars_by_symbol: dict[str, pd.DataFrame] = {}
    np = len(pool)
    for bi, code in enumerate(pool):
        if verbose:
            print(f"  [日线 {bi + 1}/{np}] {code} …", flush=True)
        tc = to_ts_code(code)
        df = fetch_daily_with_mv(pro, tc, ext_start, ext_end)
        if not df.empty:
            bars_by_symbol[code] = df
        _sleep()

    st_flags = build_st_flags_for_pool(pro, pool, cal)

    ext_cal = fetch_trade_cal(pro, ext_start, ext_end)
    # 缩短 PE 计算窗口：回测起点前约 280 个交易日 + 回测区间（仍满足 PE 历史分位样本）
    pos0 = int(ext_cal.searchsorted(cal[0].normalize()))
    pe_start = max(0, pos0 - 280)
    pe_cal = ext_cal[pe_start:]
    pe_hist: dict[str, pd.Series] = {}
    if args.scenario in ("2", "both"):
        if verbose:
            print(
                f"  构建 PE 历史（{len(pe_cal)} 个交易日 × {len(pool)} 只，已跳过无 K 线日期）…",
                flush=True,
            )
        pe_hist = build_pe_history_by_symbol(
            pool,
            income_q,
            bars_by_symbol,
            pe_cal,
            min_hist_points=args.pe_min_hist,
            verbose=verbose,
        )

    if args.scenario in ("1", "both"):
        if fund_s1.empty:
            print("场景1: 财务数据为空，跳过")
        else:
            s1 = run_monthly_backtest_s1(
                pool, cal, fund_s1, st_flags, bars_by_symbol, args.cash, args.commission
            )
            print("\n=== 场景1 成长+趋势（月度调仓）===")
            print(f"期末现金: {s1.cash:.2f} 交易条数: {len(s1.trades)} 收益率: {s1.cash / args.cash - 1:.2%}")

    if args.scenario in ("2", "both"):
        if bs.empty or cf.empty or income_q.empty:
            print("场景2: 资产负债表/现金流/季报为空，跳过")
        else:
            s2 = run_monthly_backtest_s2(
                pool,
                cal,
                bs,
                cf,
                income_q,
                st_flags,
                bars_by_symbol,
                pe_hist,
                args.cash,
                args.commission,
                min_hist_points=args.pe_min_hist,
            )
            print("\n=== 场景2 价值错杀（月度调仓）===")
            print(f"期末现金: {s2.cash:.2f} 交易条数: {len(s2.trades)} 收益率: {s2.cash / args.cash - 1:.2%}")


if __name__ == "__main__":
    main()

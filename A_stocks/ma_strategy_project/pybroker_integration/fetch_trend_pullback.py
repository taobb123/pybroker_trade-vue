#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trend Pullback：主升趋势中「震荡下沿」扫描（日线、前复权与项目 DataFetcher 一致）。

双路径命中（OR，见 docs/Trend Pullback模型.md）：
  路径 A「浅回踩 MA20」：均线多头 + 60日高点回撤约 4%~22% + 贴MA20 + 缩量阳线
  路径 B「高位箱体下沿」：主升未坏 + 20日箱体 position<35% + 相对20日高点回撤约 4%~25%
    + Low 贴 MA20/MA30（略破均线容差）+ 缩量阳线（偏敏感，覆盖约 15%~20% 深回踩）

默认：按 config/trend_pullback_range.yaml 拉取历史 K 线，在区间内寻找最近下沿命中（仅内部计算）。
第二层：最近下沿命中收盘 vs 截止日最新收盘 → 买入信号 / 可能新主升（展示标签）。
第三层（截止日）：股票池全量近期换手增大 + 成交量量稳 → 硬过滤（见 TURNOVER_VOLUME_CONFIG）。
第四层：Tushare 筹码分布 → 口诀3/4 硬过滤；口诀1/2 + 下沿结构 → 综合评分排序。

YAML `SKIP_PULLBACK_LAYERS_12: true` 时跳过第一、二层，全池直接第三层+第四层；
排序为换手率增幅 → 量稳天数 → 筹码分（score_total 仅含筹码三维度）。

数据：`backtest_sy_002028_threshold.fetch_ohlc_qfq`；筹码：`trend_pullback_chips`（cyq_chips）。
可选 PRINT_BACKTEST_LOWER（或 --print-backtest-lower）：控制台重显已算好的最近下沿参考（下沿区间价格=命中日收盘）。

数据：`backtest_sy_002028_threshold.fetch_ohlc_qfq`。

用法（在 ma_strategy_project 目录下）：
    python pybroker_integration/fetch_trend_pullback.py
    python pybroker_integration/fetch_trend_pullback.py --symbols 600563
    python pybroker_integration/fetch_trend_pullback.py --snapshot
    python pybroker_integration/fetch_trend_pullback.py --diagnose
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from backtest_sy_002028_threshold import (
    fetch_ohlc_qfq,
    fetch_stock_name,
    six_digit_to_ts_code,
)
from trend_pullback_chips import (
    CHIP_CONFIG,
    ChipAnalysis,
    ChipScores,
    classify_signal_type,
    compute_chip_only_scores,
    compute_chip_scores,
    fetch_chip_analysis_for_symbol,
    get_tushare_pro,
    score_pullback_structure,
)

DEFAULT_POOL_TXT = os.path.join(_SCRIPT_DIR, "config", "fetch_trend_pullback_symbols.txt")
DEFAULT_RANGE_YAML = os.path.join(_SCRIPT_DIR, "config", "trend_pullback_range.yaml")
DEFAULT_SCAN_OUT_CSV = os.path.join(_SCRIPT_DIR, "trend_pullback_scan.csv")

TREND_PULLBACK_CONFIG = {
    "ma20_period": 20,
    "ma30_period": 30,
    "ma60_period": 60,
    "ma120_period": 120,
    "history_calendar_days": 450,
    "rise_lookback": 60,
    "pullback_lookback": 60,
    "pullback_swing_lookback": 20,
    "rise_60_min_pct": 0.30,
    "pullback_min_pct": 0.04,
    "pullback_max_pct": 0.22,
    "pullback_swing_min_pct": 0.04,
    "pullback_swing_max_pct": 0.25,
    "ma20_touch_max_pct": 0.03,
    "ma_band_touch_max_pct": 0.05,
    "box_window": 20,
    "box_position_max": 0.35,
    "box_range_min_pct": 0.06,
    "box_range_max_pct": 0.35,
    "box_peak_near_60_max_pct": 0.08,
    "ma60_slope_bars": 5,
    "vol_ma5_period": 5,
    "buy_near_max_pct": 0.03,
    "buy_far_min_pct": 0.15,
}
TREND_PULLBACK_CONFIG.update(CHIP_CONFIG)

TURNOVER_VOLUME_CONFIG = {
    "turnover_recent_bars": 3,
    "turnover_prior_bars": 10,
    "turnover_rise_ratio_min": 1.15,
    "turnover_ma3_min_pct": 1.0,
    "volume_stable_lookback_bars": 10,
    "volume_band_low": 0.75,
    "volume_band_high": 1.40,
    "volume_stable_min_days": 7,
    "volume_ma_period": 5,
}


@dataclass(frozen=True)
class TrendPullbackSnapshot:
    symbol: str
    stock_name: str
    signal_date: str
    close: float
    low: float
    open_: float
    ma20: float
    ma60: float
    ma120: float
    rise_60_pct: float
    pullback_pct: float
    hhv_close_pullback: float
    low_ma20_gap_pct: float
    vol: float
    vol_ma5: float
    box_position: float
    pullback_swing_pct: float
    box_range_pct: float
    ma_stack_ok: bool
    rise_60_ok: bool
    pullback_ok: bool
    pullback_swing_ok: bool
    ma20_touch_ok: bool
    ma_band_touch_ok: bool
    box_lower_ok: bool
    box_consolidation_ok: bool
    trend_intact_ok: bool
    vol_shrink_ok: bool
    yang_ok: bool
    path_a_ok: bool
    path_b_ok: bool
    signal_path: str
    signal: bool


@dataclass(frozen=True)
class TrendPullbackBuyAlert:
    symbol: str
    stock_name: str
    last_hit_date: str
    ref_buy_close: float
    ref_buy_low: float
    signal_path: str
    latest_date: str
    latest_close: float
    gap_pct: float
    abs_gap_pct: float
    buy_signal: bool
    new_uptrend_signal: bool


@dataclass(frozen=True)
class TrendPullbackScoredAlert:
    symbol: str
    stock_name: str
    signal_type: str
    last_hit_date: str
    ref_buy_close: float
    ref_buy_low: float
    signal_path: str
    latest_date: str
    latest_close: float
    gap_pct: float
    abs_gap_pct: float
    buy_signal: bool
    new_uptrend_signal: bool
    main_rise_breakout: bool
    chip_pattern: str
    chip_pattern_label: str
    main_peak_price: float
    peak_position: float
    bottom_band_change_pct: float
    score_structure: float
    score_pullback_peak: float
    score_breakout: float
    score_chip_quality: float
    score_total: float
    turnover_today_pct: float
    turnover_ma3_pct: float
    turnover_ma10_prior_pct: float
    turnover_rise_ratio: float
    turnover_rising: bool
    volume_stable_days: int
    volume_stable_lookback: int
    volume_stable: bool
    chip_status: str
    chip_filter_reason: str


@dataclass(frozen=True)
class TurnoverVolumeEval:
    turnover_today: float
    turnover_ma3: float
    turnover_ma10_prior: float
    turnover_rise_ratio: float
    turnover_rising: bool
    volume_stable_days: int
    volume_stable_lookback: int
    volume_stable: bool
    passed: bool


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


def fetch_bars_with_turnover(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """前复权 OHLCV + Tushare daily_basic.turnover_rate（按 date 左连接）。"""
    ohlc = fetch_ohlc_qfq(symbol, start_date, end_date)
    out = ohlc.copy()
    out["turnover_rate"] = float("nan")

    pro = _try_tushare_pro()
    if pro is None:
        return out.sort_values("date").reset_index(drop=True)

    ts_code = six_digit_to_ts_code(symbol)
    s = start_date.replace("-", "")
    e = end_date.replace("-", "")
    try:
        basic = pro.daily_basic(
            ts_code=ts_code,
            start_date=s,
            end_date=e,
            fields="ts_code,trade_date,turnover_rate",
        )
    except Exception:
        basic = None

    if basic is not None and not basic.empty:
        basic = basic.copy()
        basic["date"] = pd.to_datetime(basic["trade_date"].astype(str), format="%Y%m%d", errors="coerce")
        basic["turnover_rate"] = pd.to_numeric(basic["turnover_rate"], errors="coerce")
        out = out.drop(columns=["turnover_rate"], errors="ignore")
        out = out.merge(basic[["date", "turnover_rate"]], on="date", how="left")

    return out.sort_values("date").reset_index(drop=True)


def _eval_turnover_rising(
    d: pd.DataFrame,
    *,
    recent_bars: int,
    prior_bars: int,
    rise_ratio_min: float,
    ma3_min_pct: float,
) -> Tuple[bool, float, float, float, float]:
    need = int(recent_bars) + int(prior_bars)
    if d is None or len(d) < need or "turnover_rate" not in d.columns:
        return False, float("nan"), float("nan"), float("nan"), float("nan")

    tr = pd.to_numeric(d["turnover_rate"], errors="coerce")
    if tr.iloc[-int(recent_bars) :].isna().all():
        return False, float("nan"), float("nan"), float("nan"), float("nan")

    recent = tr.iloc[-int(recent_bars) :]
    prior = tr.iloc[-(int(recent_bars) + int(prior_bars)) : -int(recent_bars)]
    ma3 = float(recent.mean())
    ma_prior = float(prior.mean()) if len(prior) else float("nan")
    today = float(tr.iloc[-1]) if tr.iloc[-1] == tr.iloc[-1] else float("nan")

    if ma3 != ma3 or ma_prior != ma_prior or ma_prior <= 0:
        return False, today, ma3, ma_prior, float("nan")

    ratio = ma3 / ma_prior
    ok = bool(ma3 >= float(ma3_min_pct) and ratio >= float(rise_ratio_min))
    return ok, today, ma3, ma_prior, ratio


def _eval_volume_stable(
    d: pd.DataFrame,
    *,
    lookback: int,
    band_low: float,
    band_high: float,
    min_days: int,
    ma_period: int,
) -> Tuple[bool, int]:
    lb = int(lookback)
    mp = max(2, int(ma_period))
    need = lb + mp
    if d is None or len(d) < need or "volume" not in d.columns:
        return False, 0

    vol = pd.to_numeric(d["volume"], errors="coerce")
    ma_vol = vol.rolling(mp, min_periods=mp).mean()

    stable = 0
    start = len(d) - lb
    for i in range(start, len(d)):
        v = float(vol.iloc[i])
        m = float(ma_vol.iloc[i])
        if v != v or m != m or m <= 0:
            continue
        ratio = v / m
        if float(band_low) <= ratio <= float(band_high) + 1e-9:
            stable += 1

    return stable >= int(min_days), stable


def _eval_turnover_volume_at_end(
    d: pd.DataFrame,
    cfg: dict,
) -> TurnoverVolumeEval:
    tv = TURNOVER_VOLUME_CONFIG
    rising, tr_today, tr_ma3, tr_prior, tr_ratio = _eval_turnover_rising(
        d,
        recent_bars=int(tv["turnover_recent_bars"]),
        prior_bars=int(tv["turnover_prior_bars"]),
        rise_ratio_min=float(tv["turnover_rise_ratio_min"]),
        ma3_min_pct=float(tv["turnover_ma3_min_pct"]),
    )
    vol_ok, stable_days = _eval_volume_stable(
        d,
        lookback=int(tv["volume_stable_lookback_bars"]),
        band_low=float(tv["volume_band_low"]),
        band_high=float(tv["volume_band_high"]),
        min_days=int(tv["volume_stable_min_days"]),
        ma_period=int(tv["volume_ma_period"]),
    )
    passed = bool(rising and vol_ok)
    return TurnoverVolumeEval(
        turnover_today=round(tr_today, 4) if tr_today == tr_today else float("nan"),
        turnover_ma3=round(tr_ma3, 4) if tr_ma3 == tr_ma3 else float("nan"),
        turnover_ma10_prior=round(tr_prior, 4) if tr_prior == tr_prior else float("nan"),
        turnover_rise_ratio=round(tr_ratio, 4) if tr_ratio == tr_ratio else float("nan"),
        turnover_rising=rising,
        volume_stable_days=stable_days,
        volume_stable_lookback=int(tv["volume_stable_lookback_bars"]),
        volume_stable=vol_ok,
        passed=passed,
    )


def _turnover_volume_filter_reason(ev: TurnoverVolumeEval) -> str:
    parts: List[str] = []
    if not ev.turnover_rising:
        parts.append("换手率未近期增大")
    if not ev.volume_stable:
        parts.append("成交量未稳定在设定范围")
    return "；".join(parts) if parts else "换手量稳未通过"


def _fetch_turnover_bars_cache(
    symbols: List[str],
    *,
    end_date: str,
    history_calendar_days: int,
) -> dict[str, pd.DataFrame]:
    end_dt = pd.to_datetime(end_date).to_pydatetime()
    start_dt = _calendar_start(end_dt, history_calendar_days)
    start_s = start_dt.strftime("%Y-%m-%d")
    end_s = pd.Timestamp(end_date).strftime("%Y-%m-%d")
    cache: dict[str, pd.DataFrame] = {}
    for raw in symbols:
        sym = "".join(filter(str.isdigit, str(raw))).zfill(6)
        if not sym or sym in cache:
            continue
        try:
            df = fetch_bars_with_turnover(sym, start_s, end_s)
            prepared = _prepare_ohlcv(df)
            if prepared is not None:
                if "turnover_rate" in df.columns:
                    tr = df[["date", "turnover_rate"]].copy()
                    tr["date"] = pd.to_datetime(tr["date"])
                    prepared = prepared.merge(tr, on="date", how="left")
                cache[sym] = prepared
        except Exception:
            continue
    return cache


def evaluate_pool_turnover_volume(
    symbols: List[str],
    *,
    evaluated_by_symbol: dict[str, TrendPullbackSnapshot],
    buy_alerts_by_symbol: dict[str, TrendPullbackBuyAlert],
    turnover_cache: dict[str, pd.DataFrame],
    cfg: dict,
) -> tuple[
    List[TrendPullbackBuyAlert],
    List[str],
    dict[str, TurnoverVolumeEval],
]:
    """对股票池全部标的做截止日换手增大 + 量稳评估；未通过者硬过滤。"""
    passed: List[TrendPullbackBuyAlert] = []
    filtered: List[str] = []
    eval_map: dict[str, TurnoverVolumeEval] = {}
    seen: set[str] = set()

    for raw in symbols:
        sym = "".join(filter(str.isdigit, str(raw))).zfill(6)
        if not sym or sym in seen:
            continue
        seen.add(sym)

        bars = turnover_cache.get(sym)
        if bars is None:
            filtered.append(f"{sym}(无K线/换手数据)")
            continue

        alert = buy_alerts_by_symbol.get(sym)
        snap = evaluated_by_symbol.get(sym)
        if alert is not None:
            end_ts = pd.Timestamp(alert.latest_date)
        elif snap is not None:
            end_ts = pd.Timestamp(snap.signal_date)
        else:
            end_ts = pd.Timestamp(bars["date"].iloc[-1])

        sub = bars[bars["date"] <= end_ts]
        if sub.empty:
            filtered.append(f"{sym}(截止日无数据)")
            continue

        ev = _eval_turnover_volume_at_end(sub, cfg)
        eval_map[sym] = ev
        if ev.passed:
            if alert is not None:
                passed.append(alert)
            elif snap is not None:
                passed.append(_buy_alert_without_hit(snap))
            else:
                passed.append(_buy_alert_from_bars(sym, sub))
        else:
            filtered.append(f"{sym}({_turnover_volume_filter_reason(ev)})")

    return passed, filtered, eval_map


def filter_alerts_by_turnover_volume(
    buy_alerts: List[TrendPullbackBuyAlert],
    turnover_cache: dict[str, pd.DataFrame],
    cfg: dict,
) -> tuple[
    List[TrendPullbackBuyAlert],
    List[str],
    dict[str, TurnoverVolumeEval],
]:
    """兼容旧接口：仅对 buy_alerts 子集评估换手量稳。"""
    evaluated_by_symbol: dict[str, TrendPullbackSnapshot] = {}
    buy_alerts_by_symbol = {a.symbol: a for a in buy_alerts}
    symbols = list(buy_alerts_by_symbol.keys())
    return evaluate_pool_turnover_volume(
        symbols,
        evaluated_by_symbol=evaluated_by_symbol,
        buy_alerts_by_symbol=buy_alerts_by_symbol,
        turnover_cache=turnover_cache,
        cfg=cfg,
    )


def _calendar_start(end_d: datetime, calendar_days: int) -> datetime:
    return end_d - timedelta(days=int(calendar_days))


def load_stocks_pool_txt(path: str) -> List[str]:
    p = os.path.abspath(path)
    if not os.path.isfile(p):
        return []
    raw: Optional[str] = None
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            with open(p, encoding=enc) as f:
                raw = f.read()
            break
        except UnicodeDecodeError:
            continue
    if raw is None:
        return []
    out: List[str] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        token = s.split(",")[0].strip()
        sym = "".join(filter(str.isdigit, token)).zfill(6)
        if len(sym) != 6 or not sym.isdigit():
            continue
        if sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


def _attach_symbol_meta(df: pd.DataFrame, symbol: str, stock_name: str) -> pd.DataFrame:
    out = df.copy()
    out["symbol"] = symbol
    out["stock_name"] = stock_name
    return out


def _prepare_ohlcv(d: pd.DataFrame) -> Optional[pd.DataFrame]:
    if d is None or d.empty or "volume" not in d.columns:
        return None
    out = d.sort_values("date").reset_index(drop=True).copy()
    out["date"] = pd.to_datetime(out["date"])
    for col in ("open", "high", "low", "close", "volume"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if out["volume"].isna().all():
        return None
    out["volume"] = out["volume"].fillna(0.0)
    return out


def _min_history_bars(cfg: dict) -> int:
    return max(
        int(cfg["ma120_period"]),
        int(cfg["ma30_period"]),
        int(cfg["rise_lookback"]),
        int(cfg["pullback_lookback"]),
        int(cfg["pullback_swing_lookback"]),
        int(cfg["box_window"]),
        int(cfg["vol_ma5_period"]),
        int(cfg["ma60_slope_bars"]),
    ) + 5


def _ma_rising(ma: pd.Series, idx: int, bars: int) -> bool:
    b = int(bars)
    if idx < b:
        return False
    return float(ma.iloc[idx]) > float(ma.iloc[idx - b])


def _box_stats(
    high: pd.Series, low: pd.Series, close: pd.Series, idx: int, window: int
) -> Tuple[float, float, float, float, float]:
    """返回 hh, ll, range_pct(相对中价), position, llv_gap_pct。"""
    a = max(0, idx - int(window) + 1)
    seg_h = high.iloc[a : idx + 1]
    seg_l = low.iloc[a : idx + 1]
    hh = float(seg_h.max())
    ll = float(seg_l.min())
    c = float(close.iloc[idx])
    l = float(low.iloc[idx])
    mid = (hh + ll) / 2.0
    span = hh - ll
    if span <= 1e-12 or mid <= 1e-12:
        return hh, ll, float("nan"), float("nan"), float("nan")
    pos = (c - ll) / span
    range_pct = span / mid
    llv_gap = (l - ll) / ll if ll > 1e-12 else float("nan")
    return hh, ll, range_pct, pos, llv_gap


def _ma_band_touch(
    low: float, m20: float, m30: float, max_pct: float
) -> bool:
    gaps: List[float] = []
    if m20 == m20 and m20 > 1e-12:
        gaps.append((low - m20) / m20)
    if m30 == m30 and m30 > 1e-12:
        gaps.append((low - m30) / m30)
    if not gaps:
        return False
    return min(gaps) <= float(max_pct) + 1e-9


def _eval_trend_pullback_at(
    d: pd.DataFrame,
    idx: int,
    cfg: dict,
) -> Optional[TrendPullbackSnapshot]:
    need = _min_history_bars(cfg)
    if idx < need:
        return None

    p20 = int(cfg["ma20_period"])
    p30 = int(cfg["ma30_period"])
    p60 = int(cfg["ma60_period"])
    p120 = int(cfg["ma120_period"])
    rb = int(cfg["pullback_lookback"])
    r60 = int(cfg["rise_lookback"])
    sw = int(cfg["pullback_swing_lookback"])
    bw = int(cfg["box_window"])

    ma20 = d["close"].rolling(p20, min_periods=p20).mean()
    ma30 = d["close"].rolling(p30, min_periods=p30).mean()
    ma60 = d["close"].rolling(p60, min_periods=p60).mean()
    ma120 = d["close"].rolling(p120, min_periods=p120).mean()

    m20 = float(ma20.iloc[idx])
    m30 = float(ma30.iloc[idx])
    m60 = float(ma60.iloc[idx])
    m120 = float(ma120.iloc[idx])
    if m20 != m20 or m60 != m60 or m120 != m120:
        return None

    o = float(d["open"].iloc[idx])
    l = float(d["low"].iloc[idx])
    c = float(d["close"].iloc[idx])
    v = float(d["volume"].iloc[idx])

    ma_stack_ok = m20 > m60 > m120

    a_rise = idx - r60 + 1
    seg_rise = d.iloc[a_rise : idx + 1]
    hh_r = float(seg_rise["high"].max())
    ll_r = float(seg_rise["low"].min())
    rise_60 = (hh_r - ll_r) / ll_r if ll_r > 1e-12 else float("nan")
    rise_min = float(cfg["rise_60_min_pct"])
    rise_60_ok = rise_60 == rise_60 and rise_60 > rise_min

    a_pb = idx - rb + 1
    hhv_c60 = float(d["close"].iloc[a_pb : idx + 1].max())
    pullback = (hhv_c60 - c) / hhv_c60 if hhv_c60 > 1e-12 else float("nan")
    pb_lo = float(cfg["pullback_min_pct"])
    pb_hi = float(cfg["pullback_max_pct"])
    pullback_ok = pullback == pullback and pb_lo < pullback < pb_hi

    touch_max = float(cfg["ma20_touch_max_pct"])
    low_gap = (l - m20) / m20 if m20 > 1e-12 else float("nan")
    ma20_touch_ok = low_gap == low_gap and low_gap <= touch_max + 1e-9

    a_sw = idx - sw + 1
    hhv_c20 = float(d["close"].iloc[a_sw : idx + 1].max())
    pullback_sw = (hhv_c20 - c) / hhv_c20 if hhv_c20 > 1e-12 else float("nan")
    sw_lo = float(cfg["pullback_swing_min_pct"])
    sw_hi = float(cfg["pullback_swing_max_pct"])
    pullback_swing_ok = (
        pullback_sw == pullback_sw and sw_lo < pullback_sw < sw_hi
    )

    vol_ma5 = float(d["volume"].iloc[idx - int(cfg["vol_ma5_period"]) : idx].mean())
    vol_shrink_ok = vol_ma5 == vol_ma5 and vol_ma5 > 0 and v < vol_ma5
    yang_ok = c > o

    _, _, box_range_pct, box_pos, _ = _box_stats(
        d["high"], d["low"], d["close"], idx, bw
    )
    pos_max = float(cfg["box_position_max"])
    box_lower_ok = box_pos == box_pos and box_pos < pos_max

    rng_lo = float(cfg["box_range_min_pct"])
    rng_hi = float(cfg["box_range_max_pct"])
    box_consolidation_ok = (
        box_range_pct == box_range_pct
        and rng_lo <= box_range_pct <= rng_hi
    )
    hh_20, _, _, _, _ = _box_stats(d["high"], d["low"], d["close"], idx, bw)
    near_pct = float(cfg["box_peak_near_60_max_pct"])
    peak_near_ok = hhv_c60 > 1e-12 and hh_20 >= hhv_c60 * (1.0 - near_pct)
    box_consolidation_ok = bool(box_consolidation_ok and peak_near_ok)

    ma_band_touch_ok = _ma_band_touch(
        l, m20, m30, float(cfg["ma_band_touch_max_pct"])
    )
    ma60_up = _ma_rising(ma60, idx, int(cfg["ma60_slope_bars"]))
    trend_intact_ok = bool(
        rise_60_ok and c > m60 and ma60_up and m60 > m120
    )

    path_a_ok = bool(
        ma_stack_ok
        and rise_60_ok
        and pullback_ok
        and ma20_touch_ok
        and vol_shrink_ok
        and yang_ok
    )
    path_b_ok = bool(
        trend_intact_ok
        and box_consolidation_ok
        and box_lower_ok
        and pullback_swing_ok
        and ma_band_touch_ok
        and vol_shrink_ok
        and yang_ok
    )

    if path_a_ok and path_b_ok:
        signal_path = "both"
    elif path_a_ok:
        signal_path = "ma20_pullback"
    elif path_b_ok:
        signal_path = "box_lower"
    else:
        signal_path = ""

    signal = bool(path_a_ok or path_b_ok)

    sym = str(d["symbol"].iloc[idx] if "symbol" in d.columns else "").strip()
    nm = str(d["stock_name"].iloc[idx] if "stock_name" in d.columns else "").strip()
    dt = d["date"].iloc[idx]
    try:
        ds = pd.Timestamp(dt).strftime("%Y-%m-%d")
    except Exception:
        ds = str(dt)[:10]

    return TrendPullbackSnapshot(
        symbol=sym,
        stock_name=nm,
        signal_date=ds,
        close=round(c, 4),
        low=round(l, 4),
        open_=round(o, 4),
        ma20=round(m20, 4),
        ma60=round(m60, 4),
        ma120=round(m120, 4),
        rise_60_pct=round(rise_60 * 100.0, 4) if rise_60 == rise_60 else float("nan"),
        pullback_pct=round(pullback * 100.0, 4) if pullback == pullback else float("nan"),
        hhv_close_pullback=round(hhv_c60, 4),
        low_ma20_gap_pct=round(low_gap * 100.0, 4) if low_gap == low_gap else float("nan"),
        vol=round(v, 2),
        vol_ma5=round(vol_ma5, 2) if vol_ma5 == vol_ma5 else float("nan"),
        box_position=round(box_pos, 4) if box_pos == box_pos else float("nan"),
        pullback_swing_pct=round(pullback_sw * 100.0, 4)
        if pullback_sw == pullback_sw
        else float("nan"),
        box_range_pct=round(box_range_pct * 100.0, 4)
        if box_range_pct == box_range_pct
        else float("nan"),
        ma_stack_ok=ma_stack_ok,
        rise_60_ok=rise_60_ok,
        pullback_ok=pullback_ok,
        pullback_swing_ok=pullback_swing_ok,
        ma20_touch_ok=ma20_touch_ok,
        ma_band_touch_ok=ma_band_touch_ok,
        box_lower_ok=box_lower_ok,
        box_consolidation_ok=box_consolidation_ok,
        trend_intact_ok=trend_intact_ok,
        vol_shrink_ok=vol_shrink_ok,
        yang_ok=yang_ok,
        path_a_ok=path_a_ok,
        path_b_ok=path_b_ok,
        signal_path=signal_path,
        signal=signal,
    )


def _eval_trend_pullback_last(d: pd.DataFrame, cfg: dict) -> Optional[TrendPullbackSnapshot]:
    d = _prepare_ohlcv(d)
    if d is None:
        return None
    return _eval_trend_pullback_at(d, len(d) - 1, cfg)


def _latest_hit_by_symbol(
    hits: List[TrendPullbackSnapshot],
) -> dict[str, TrendPullbackSnapshot]:
    out: dict[str, TrendPullbackSnapshot] = {}
    for h in hits:
        prev = out.get(h.symbol)
        if prev is None or h.signal_date > prev.signal_date:
            out[h.symbol] = h
    return out


def _find_latest_hit_from_prepared(
    prepared: pd.DataFrame, cfg: dict
) -> Optional[TrendPullbackSnapshot]:
    need = _min_history_bars(cfg)
    latest: Optional[TrendPullbackSnapshot] = None
    for idx in range(need, len(prepared)):
        snap = _eval_trend_pullback_at(prepared, idx, cfg)
        if snap is not None and snap.signal:
            latest = snap
    return latest


def compute_buy_near_alerts(
    evaluated_last: List[TrendPullbackSnapshot],
    latest_hits: dict[str, TrendPullbackSnapshot],
    cfg: dict,
) -> List[TrendPullbackBuyAlert]:
    """
    最新收盘 vs 最近一次历史下沿命中收盘：
    - 接近（|偏离|<=near_max）→ buy_signal
    - 明显高于命中价（涨幅>=far_min）→ new_uptrend_signal（可能进入新主升）
    """
    near_max = float(cfg["buy_near_max_pct"])
    far_min = float(cfg["buy_far_min_pct"])
    alerts: List[TrendPullbackBuyAlert] = []
    for snap in evaluated_last:
        hit = latest_hits.get(snap.symbol)
        if hit is None:
            continue
        ref = float(hit.close)
        if ref <= 1e-12:
            continue
        latest_c = float(snap.close)
        gap = (latest_c - ref) / ref
        abs_gap = abs(gap)
        near_ok = bool(abs_gap <= near_max + 1e-9)
        alerts.append(
            TrendPullbackBuyAlert(
                symbol=snap.symbol,
                stock_name=snap.stock_name or hit.stock_name,
                last_hit_date=hit.signal_date,
                ref_buy_close=round(ref, 4),
                ref_buy_low=round(float(hit.low), 4),
                signal_path=hit.signal_path,
                latest_date=snap.signal_date,
                latest_close=round(latest_c, 4),
                gap_pct=round(gap * 100.0, 4),
                abs_gap_pct=round(abs_gap * 100.0, 4),
                buy_signal=near_ok,
                new_uptrend_signal=bool(
                    not near_ok and gap >= far_min - 1e-9
                ),
            )
        )
    alerts.sort(
        key=lambda x: (not x.buy_signal, not x.new_uptrend_signal, x.symbol)
    )
    return alerts


def _buy_alert_without_hit(snap: TrendPullbackSnapshot) -> TrendPullbackBuyAlert:
    """无历史下沿命中时，用截止日快照构造换手/筹码评估用 alert。"""
    return TrendPullbackBuyAlert(
        symbol=snap.symbol,
        stock_name=snap.stock_name or "",
        last_hit_date="",
        ref_buy_close=float("nan"),
        ref_buy_low=float("nan"),
        signal_path="",
        latest_date=snap.signal_date,
        latest_close=round(float(snap.close), 4),
        gap_pct=float("nan"),
        abs_gap_pct=float("nan"),
        buy_signal=False,
        new_uptrend_signal=False,
    )


def _buy_alert_from_bars(sym: str, bars: pd.DataFrame) -> TrendPullbackBuyAlert:
    """仅有行情、无下沿评估快照时，用最近 K 线构造 alert。"""
    row = bars.iloc[-1]
    date_s = pd.Timestamp(row["date"]).strftime("%Y-%m-%d")
    close = round(float(row["close"]), 4)
    return TrendPullbackBuyAlert(
        symbol=sym,
        stock_name=fetch_stock_name(sym) or "",
        last_hit_date="",
        ref_buy_close=float("nan"),
        ref_buy_low=float("nan"),
        signal_path="",
        latest_date=date_s,
        latest_close=close,
        gap_pct=float("nan"),
        abs_gap_pct=float("nan"),
        buy_signal=False,
        new_uptrend_signal=False,
    )


def _fetch_prepared_ohlc_cache(
    symbols: List[str],
    *,
    end_date: str,
    history_calendar_days: int,
) -> dict[str, pd.DataFrame]:
    end_dt = pd.to_datetime(end_date).to_pydatetime()
    start_dt = _calendar_start(end_dt, history_calendar_days)
    start_s = start_dt.strftime("%Y-%m-%d")
    end_s = pd.Timestamp(end_date).strftime("%Y-%m-%d")
    cache: dict[str, pd.DataFrame] = {}
    for raw in symbols:
        sym = "".join(filter(str.isdigit, str(raw))).zfill(6)
        if not sym or sym in cache:
            continue
        try:
            ohlc = fetch_ohlc_qfq(sym, start_s, end_s)
            prepared = _prepare_ohlcv(ohlc)
            if prepared is not None:
                cache[sym] = prepared
        except Exception:
            continue
    return cache


def _structure_only_scores(
    hit: TrendPullbackSnapshot,
    cfg: dict,
) -> ChipScores:
    """无筹码数据时仅按下沿结构维度估算评分。"""
    s_struct = score_pullback_structure(
        signal_path=hit.signal_path,
        rise_60_pct=hit.rise_60_pct,
        pullback_pct=hit.pullback_pct,
        pullback_swing_pct=hit.pullback_swing_pct,
        box_position=hit.box_position,
        ma_stack_ok=hit.ma_stack_ok,
    )
    w_s = float(cfg.get("weight_structure", 0.30))
    w_p = float(cfg.get("weight_pullback_peak", 0.25))
    w_b = float(cfg.get("weight_breakout", 0.25))
    w_q = float(cfg.get("weight_chip_quality", 0.20))
    denom = w_s + w_p + w_b + w_q
    total = (s_struct / 30.0 * w_s) / denom * 100.0
    return ChipScores(
        score_structure=round(s_struct, 2),
        score_pullback_peak=0.0,
        score_breakout=0.0,
        score_chip_quality=0.0,
        score_total=round(float(min(100.0, max(0.0, total))), 2),
    )


def _empty_scores() -> ChipScores:
    return ChipScores(0.0, 0.0, 0.0, 0.0, 0.0)


def _turnover_alert_fields(
    symbol: str,
    turnover_eval_map: dict[str, TurnoverVolumeEval],
) -> dict:
    tv = turnover_eval_map.get(symbol)
    return {
        "turnover_today_pct": tv.turnover_today if tv else float("nan"),
        "turnover_ma3_pct": tv.turnover_ma3 if tv else float("nan"),
        "turnover_ma10_prior_pct": tv.turnover_ma10_prior if tv else float("nan"),
        "turnover_rise_ratio": tv.turnover_rise_ratio if tv else float("nan"),
        "turnover_rising": bool(tv.turnover_rising) if tv else False,
        "volume_stable_days": tv.volume_stable_days if tv else 0,
        "volume_stable_lookback": tv.volume_stable_lookback if tv else int(
            TURNOVER_VOLUME_CONFIG["volume_stable_lookback_bars"]
        ),
        "volume_stable": bool(tv.volume_stable) if tv else False,
    }


def _build_scored_alert(
    alert: TrendPullbackBuyAlert,
    hit: TrendPullbackSnapshot | None,
    chip: ChipAnalysis | None,
    turnover_eval_map: dict[str, TurnoverVolumeEval],
    cfg: dict,
    *,
    chip_status: str,
    chip_filter_reason: str = "",
    skip_layers_12: bool = False,
) -> TrendPullbackScoredAlert:
    scores = _empty_scores()
    main_rise_breakout = False
    new_uptrend_display = False
    signal_type = ""

    if chip is not None and skip_layers_12:
        scores = compute_chip_only_scores(chip, cfg)
        main_rise_breakout = bool(chip.main_rise_breakout)
        signal_type = classify_signal_type(
            buy_signal=False,
            new_uptrend_signal=False,
            main_rise_breakout=main_rise_breakout,
        )
    elif hit is not None and chip is not None:
        scores = compute_chip_scores(
            chip,
            signal_path=hit.signal_path,
            rise_60_pct=hit.rise_60_pct,
            pullback_pct=hit.pullback_pct,
            pullback_swing_pct=hit.pullback_swing_pct,
            box_position=hit.box_position,
            ma_stack_ok=hit.ma_stack_ok,
            cfg=cfg,
        )
        main_rise_breakout = bool(chip.main_rise_breakout)
        new_uptrend_display = bool(
            alert.new_uptrend_signal and not alert.buy_signal and not main_rise_breakout
        )
        signal_type = classify_signal_type(
            buy_signal=alert.buy_signal and not main_rise_breakout,
            new_uptrend_signal=new_uptrend_display,
            main_rise_breakout=main_rise_breakout,
        )
    elif hit is not None:
        scores = _structure_only_scores(hit, cfg)
        new_uptrend_display = bool(
            alert.new_uptrend_signal and not alert.buy_signal
        )
        signal_type = classify_signal_type(
            buy_signal=alert.buy_signal,
            new_uptrend_signal=new_uptrend_display,
            main_rise_breakout=False,
        )

    return TrendPullbackScoredAlert(
        symbol=alert.symbol,
        stock_name=alert.stock_name,
        signal_type=signal_type,
        last_hit_date=alert.last_hit_date,
        ref_buy_close=alert.ref_buy_close,
        ref_buy_low=alert.ref_buy_low,
        signal_path=alert.signal_path,
        latest_date=alert.latest_date,
        latest_close=alert.latest_close,
        gap_pct=alert.gap_pct,
        abs_gap_pct=alert.abs_gap_pct,
        buy_signal=alert.buy_signal,
        new_uptrend_signal=new_uptrend_display,
        main_rise_breakout=main_rise_breakout,
        chip_pattern=chip.pattern if chip else "",
        chip_pattern_label=chip.pattern_label if chip else "",
        main_peak_price=chip.main_peak_price if chip else float("nan"),
        peak_position=chip.peak_position if chip else float("nan"),
        bottom_band_change_pct=chip.bottom_band_change_pct if chip else float("nan"),
        score_structure=scores.score_structure,
        score_pullback_peak=scores.score_pullback_peak,
        score_breakout=scores.score_breakout,
        score_chip_quality=scores.score_chip_quality,
        score_total=scores.score_total,
        chip_status=chip_status,
        chip_filter_reason=chip_filter_reason,
        **_turnover_alert_fields(alert.symbol, turnover_eval_map),
    )


_CHIP_STATUS_ORDER = {"通过": 0, "硬过滤剔除": 1, "无筹码数据": 2, "无K线": 3}


def _scored_alert_sort_key(
    a: TrendPullbackScoredAlert,
    *,
    skip_layers_12: bool,
) -> tuple:
    status = _CHIP_STATUS_ORDER.get(a.chip_status, 9)
    if skip_layers_12:
        tr = a.turnover_rise_ratio
        tr_key = -(tr if tr == tr else 0.0)
        return (status, tr_key, -a.volume_stable_days, -a.score_total, a.symbol)
    return (status, -a.score_total, a.symbol)


def enrich_alerts_with_chips(
    buy_alerts: List[TrendPullbackBuyAlert],
    latest_hits: dict[str, TrendPullbackSnapshot],
    ohlc_cache: dict[str, pd.DataFrame],
    turnover_eval_map: dict[str, TurnoverVolumeEval],
    cfg: dict,
    pro=None,
    *,
    skip_layers_12: bool = False,
) -> tuple[List[TrendPullbackScoredAlert], List[str], List[str]]:
    """
    对换手量稳已通过的标的做筹码分析与评分。
    返回 (全部换手通过标的及筹码状态/评分, 筹码硬过滤剔除, 无筹码/K线)。
    """
    if pro is None:
        pro = get_tushare_pro()

    all_alerts: List[TrendPullbackScoredAlert] = []
    chip_filtered: List[str] = []
    chip_missing: List[str] = []

    for alert in buy_alerts:
        hit = latest_hits.get(alert.symbol)
        ohlc = ohlc_cache.get(alert.symbol)
        if ohlc is None:
            chip_missing.append(f"{alert.symbol}(无K线)")
            all_alerts.append(
                _build_scored_alert(
                    alert,
                    hit,
                    None,
                    turnover_eval_map,
                    cfg,
                    chip_status="无K线",
                    skip_layers_12=skip_layers_12,
                )
            )
            continue

        chip = fetch_chip_analysis_for_symbol(
            pro, alert.symbol, alert.latest_date, ohlc, cfg
        )
        if chip is None:
            chip_missing.append(f"{alert.symbol}(无筹码数据)")
            all_alerts.append(
                _build_scored_alert(
                    alert,
                    hit,
                    None,
                    turnover_eval_map,
                    cfg,
                    chip_status="无筹码数据",
                    skip_layers_12=skip_layers_12,
                )
            )
            continue

        if chip.hard_filtered:
            reason = chip.hard_filter_reason or chip.pattern_label
            chip_filtered.append(f"{alert.symbol}({reason})")
            all_alerts.append(
                _build_scored_alert(
                    alert,
                    hit,
                    chip,
                    turnover_eval_map,
                    cfg,
                    chip_status="硬过滤剔除",
                    chip_filter_reason=reason,
                    skip_layers_12=skip_layers_12,
                )
            )
            continue

        all_alerts.append(
            _build_scored_alert(
                alert,
                hit,
                chip,
                turnover_eval_map,
                cfg,
                chip_status="通过",
                skip_layers_12=skip_layers_12,
            )
        )

    all_alerts.sort(
        key=lambda x: _scored_alert_sort_key(x, skip_layers_12=skip_layers_12)
    )
    return all_alerts, chip_filtered, chip_missing


def _alert_row(a: TrendPullbackBuyAlert, signal_type: str) -> dict:
    return {
        "signal_type": signal_type,
        "symbol": a.symbol,
        "stock_name": a.stock_name,
        "signal_path": a.signal_path,
        "latest_date": a.latest_date,
        "latest_close": a.latest_close,
        "last_hit_date": a.last_hit_date,
        "ref_buy_close": a.ref_buy_close,
        "ref_buy_low": a.ref_buy_low,
        "gap_pct": a.gap_pct,
        "abs_gap_pct": a.abs_gap_pct,
    }


def _scored_alert_row(a: TrendPullbackScoredAlert) -> dict:
    return {
        "signal_type": a.signal_type,
        "symbol": a.symbol,
        "stock_name": a.stock_name,
        "signal_path": a.signal_path,
        "latest_date": a.latest_date,
        "latest_close": a.latest_close,
        "last_hit_date": a.last_hit_date,
        "ref_buy_close": a.ref_buy_close,
        "ref_buy_low": a.ref_buy_low,
        "gap_pct": a.gap_pct,
        "abs_gap_pct": a.abs_gap_pct,
        "main_rise_breakout": a.main_rise_breakout,
        "chip_pattern": a.chip_pattern,
        "chip_pattern_label": a.chip_pattern_label,
        "main_peak_price": a.main_peak_price,
        "peak_position": a.peak_position,
        "bottom_band_change_pct": a.bottom_band_change_pct,
        "score_structure": a.score_structure,
        "score_pullback_peak": a.score_pullback_peak,
        "score_breakout": a.score_breakout,
        "score_chip_quality": a.score_chip_quality,
        "score_total": a.score_total,
        "turnover_today_pct": a.turnover_today_pct,
        "turnover_ma3_pct": a.turnover_ma3_pct,
        "turnover_ma10_prior_pct": a.turnover_ma10_prior_pct,
        "turnover_rise_ratio": a.turnover_rise_ratio,
        "turnover_rising": a.turnover_rising,
        "volume_stable_days": a.volume_stable_days,
        "volume_stable_lookback": a.volume_stable_lookback,
        "volume_stable": a.volume_stable,
        "chip_status": a.chip_status,
        "chip_filter_reason": a.chip_filter_reason,
    }


def active_signals_to_dataframe(
    scored_alerts: List[TrendPullbackScoredAlert],
) -> pd.DataFrame:
    """工作流输出表：换手量稳通过的全部标的，含筹码状态/评分（按筹码通过优先、评分排序）。"""
    rows = [_scored_alert_row(a) for a in scored_alerts]
    return pd.DataFrame(rows)


def chip_passed_alerts(
    scored_alerts: List[TrendPullbackScoredAlert],
) -> List[TrendPullbackScoredAlert]:
    """控制台买入/主升展示：筹码硬过滤通过且有信号类型。"""
    return [
        a for a in scored_alerts
        if a.chip_status == "通过" and a.signal_type
    ]


def legacy_active_signals_to_dataframe(
    buy_signals: List[TrendPullbackBuyAlert],
    new_uptrend_signals: List[TrendPullbackBuyAlert],
) -> pd.DataFrame:
    rows = [_alert_row(a, "买入信号") for a in buy_signals]
    rows.extend(_alert_row(a, "可能新主升") for a in new_uptrend_signals)
    return pd.DataFrame(rows)


def _scored_alert_brief_line(a: TrendPullbackScoredAlert, cfg: dict) -> str:
    label = f"{a.stock_name}({a.symbol})" if a.stock_name else a.symbol
    tag = _path_tag(a.signal_path)
    chip = a.chip_pattern_label or a.chip_pattern
    base = (
        f"  [{a.signal_type}/{tag}] {label}  score={a.score_total:.1f}  "
        f"筹码={chip}  最新 {a.latest_date} close={a.latest_close:.4f}  "
        f"下沿 {a.last_hit_date} close={a.ref_buy_close:.4f}  偏离 {a.gap_pct:+.2f}%"
    )
    if a.main_rise_breakout:
        base += "  [主升突破]"
    return base


def _buy_alert_brief_line(a: TrendPullbackBuyAlert, cfg: dict) -> str:
    label = f"{a.stock_name}({a.symbol})" if a.stock_name else a.symbol
    tag = _path_tag(a.signal_path)
    near_pct = float(cfg["buy_near_max_pct"]) * 100.0
    if a.buy_signal:
        return (
            f"  [买入信号/{tag}] {label}  "
            f"最新 {a.latest_date} close={a.latest_close:.4f}  "
            f"~ 最近下沿 {a.last_hit_date} close={a.ref_buy_close:.4f}  "
            f"偏离 {a.gap_pct:+.2f}%（<={near_pct:.1f}%）"
        )
    return (
        f"  [未接近/{tag}] {label}  "
        f"最新 close={a.latest_close:.4f}  vs 下沿 {a.last_hit_date} "
        f"close={a.ref_buy_close:.4f}  偏离 {a.gap_pct:+.2f}%"
    )


def _backtest_lower_ref_brief_line(a: TrendPullbackBuyAlert) -> str:
    label = f"{a.stock_name}({a.symbol})" if a.stock_name else a.symbol
    tag = _path_tag(a.signal_path)
    return (
        f"  [{tag}] {label}  "
        f"下沿区间价格(命中日收盘)={a.ref_buy_close:.4f}  "
        f"命中日={a.last_hit_date}  "
        f"最新 {a.latest_date} close={a.latest_close:.4f}  "
        f"偏离 {a.gap_pct:+.2f}%"
    )


def _print_backtest_lower_refs(
    buy_alerts: List[TrendPullbackBuyAlert],
    *,
    range_mode: bool,
    scan_from: str,
    scan_to: str,
) -> None:
    print("=" * 72)
    if range_mode:
        print(
            f"【回测下沿参考】（{scan_from}～{scan_to} 内最近命中；"
            "下沿区间价格=命中日收盘）"
        )
    else:
        print("【回测下沿参考】（已拉取历史内最近命中；下沿区间价格=命中日收盘）")
    if buy_alerts:
        for a in sorted(buy_alerts, key=lambda x: x.symbol):
            print(_backtest_lower_ref_brief_line(a))
    else:
        print("  （无：池内标的在回测/历史窗口内未出现下沿命中）")


def _new_uptrend_alert_brief_line(a: TrendPullbackBuyAlert, cfg: dict) -> str:
    label = f"{a.stock_name}({a.symbol})" if a.stock_name else a.symbol
    tag = _path_tag(a.signal_path)
    far_pct = float(cfg["buy_far_min_pct"]) * 100.0
    return (
        f"  [可能新主升/{tag}] {label}  "
        f"最新 {a.latest_date} close={a.latest_close:.4f}  "
        f"较下沿 {a.last_hit_date} close={a.ref_buy_close:.4f}  "
        f"已涨 {a.gap_pct:+.2f}%（>={far_pct:.1f}%）"
    )


def _index_range_for_dates(
    d: pd.DataFrame, scan_from: str, scan_to: str
) -> List[int]:
    t0 = pd.Timestamp(scan_from)
    t1 = pd.Timestamp(scan_to)
    out: List[int] = []
    for i in range(len(d)):
        t = pd.Timestamp(d["date"].iloc[i])
        if t0 <= t <= t1:
            out.append(i)
    return out


def scan_trend_pullback_snapshot(
    symbols: List[str],
    *,
    end_date: str,
    history_calendar_days: int,
    cfg: dict,
) -> tuple[
    List[TrendPullbackSnapshot],
    List[str],
    List[TrendPullbackSnapshot],
    dict[str, TrendPullbackSnapshot],
]:
    end_dt = pd.to_datetime(end_date).to_pydatetime()
    start_dt = _calendar_start(end_dt, history_calendar_days)
    start_s = start_dt.strftime("%Y-%m-%d")
    end_s = pd.Timestamp(end_date).strftime("%Y-%m-%d")

    hits: List[TrendPullbackSnapshot] = []
    evaluated: List[TrendPullbackSnapshot] = []
    latest_hits: dict[str, TrendPullbackSnapshot] = {}
    skipped: List[str] = []

    for raw in symbols:
        sym = "".join(filter(str.isdigit, str(raw))).zfill(6)
        if not sym:
            continue
        sname = fetch_stock_name(sym)
        try:
            ohlc = fetch_ohlc_qfq(sym, start_s, end_s)
        except Exception:
            skipped.append(f"{sym}(无日线)")
            continue

        df = _attach_symbol_meta(ohlc, sym, sname)
        prepared = _prepare_ohlcv(df)
        if prepared is None:
            skipped.append(f"{sym}(数据不足或无volume)")
            continue
        snap = _eval_trend_pullback_at(prepared, len(prepared) - 1, cfg)
        if snap is None:
            skipped.append(f"{sym}(历史K线不足)")
            continue
        evaluated.append(snap)
        last_hit = _find_latest_hit_from_prepared(prepared, cfg)
        if last_hit is not None:
            latest_hits[sym] = last_hit
        if snap.signal:
            hits.append(snap)

    return hits, skipped, evaluated, latest_hits


def scan_trend_pullback_range(
    symbols: List[str],
    *,
    scan_from: str,
    scan_to: str,
    end_date: str,
    history_calendar_days: int,
    cfg: dict,
) -> tuple[
    List[TrendPullbackSnapshot],
    List[str],
    List[TrendPullbackSnapshot],
    dict[str, TrendPullbackSnapshot],
]:
    end_dt = pd.to_datetime(end_date).to_pydatetime()
    scan_start = pd.to_datetime(scan_from).to_pydatetime()
    fetch_start = min(scan_start, _calendar_start(end_dt, history_calendar_days))
    start_s = fetch_start.strftime("%Y-%m-%d")
    end_s = pd.Timestamp(end_date).strftime("%Y-%m-%d")

    hits: List[TrendPullbackSnapshot] = []
    evaluated_last: List[TrendPullbackSnapshot] = []
    skipped: List[str] = []

    for raw in symbols:
        sym = "".join(filter(str.isdigit, str(raw))).zfill(6)
        if not sym:
            continue
        sname = fetch_stock_name(sym)
        try:
            ohlc = fetch_ohlc_qfq(sym, start_s, end_s)
        except Exception:
            skipped.append(f"{sym}(无日线)")
            continue

        df = _attach_symbol_meta(ohlc, sym, sname)
        prepared = _prepare_ohlcv(df)
        if prepared is None:
            skipped.append(f"{sym}(数据不足或无volume)")
            continue

        last = _eval_trend_pullback_at(prepared, len(prepared) - 1, cfg)
        if last is not None:
            evaluated_last.append(last)

        for idx in _index_range_for_dates(prepared, scan_from, scan_to):
            snap = _eval_trend_pullback_at(prepared, idx, cfg)
            if snap is not None and snap.signal:
                hits.append(snap)

    hits.sort(key=lambda x: (x.symbol, x.signal_date))
    latest_hits = _latest_hit_by_symbol(hits)
    return hits, skipped, evaluated_last, latest_hits


def snapshots_to_dataframe(snaps: List[TrendPullbackSnapshot]) -> pd.DataFrame:
    rows = []
    for s in snaps:
        rows.append(
            {
                "symbol": s.symbol,
                "stock_name": s.stock_name,
                "signal_date": s.signal_date,
                "signal_path": s.signal_path,
                "close": s.close,
                "low": s.low,
                "ma20": s.ma20,
                "ma60": s.ma60,
                "ma120": s.ma120,
                "rise_60_pct": s.rise_60_pct,
                "pullback_pct": s.pullback_pct,
                "pullback_swing_pct": s.pullback_swing_pct,
                "hhv_close_pullback": s.hhv_close_pullback,
                "low_ma20_gap_pct": s.low_ma20_gap_pct,
                "vol": s.vol,
                "vol_ma5": s.vol_ma5,
                "box_position": s.box_position,
                "box_range_pct": s.box_range_pct,
                "signal": s.signal,
            }
        )
    return pd.DataFrame(rows)


def _path_tag(path: str) -> str:
    if path == "ma20_pullback":
        return "A"
    if path == "box_lower":
        return "B"
    if path == "both":
        return "AB"
    return "?"


def _failed_path_a(s: TrendPullbackSnapshot, cfg: dict) -> List[str]:
    f: List[str] = []
    if not s.ma_stack_ok:
        f.append("均线非多头")
    if not s.rise_60_ok:
        f.append("60日涨幅不足")
    if not s.pullback_ok:
        f.append(f"{int(cfg['pullback_lookback'])}日回撤不符")
    if not s.ma20_touch_ok:
        f.append("未贴MA20")
    if not s.vol_shrink_ok:
        f.append("未缩量")
    if not s.yang_ok:
        f.append("非阳线")
    return f


def _failed_path_b(s: TrendPullbackSnapshot, cfg: dict) -> List[str]:
    f: List[str] = []
    if not s.trend_intact_ok:
        f.append("主升未坏不满足")
    if not s.box_consolidation_ok:
        f.append("非高位箱体")
    if not s.box_lower_ok:
        f.append(f"箱体position≥{float(cfg['box_position_max']):.0%}")
    if not s.pullback_swing_ok:
        f.append(f"{int(cfg['pullback_swing_lookback'])}日回撤不符")
    if not s.ma_band_touch_ok:
        f.append("未贴MA20/30")
    if not s.vol_shrink_ok:
        f.append("未缩量")
    if not s.yang_ok:
        f.append("非阳线")
    return f


def _failed_pullback_reasons(s: TrendPullbackSnapshot, cfg: dict) -> List[str]:
    return [
        "A:" + ("OK" if s.path_a_ok else "；".join(_failed_path_a(s, cfg))),
        "B:" + ("OK" if s.path_b_ok else "；".join(_failed_path_b(s, cfg))),
    ]


def _symbol_brief_line(s: TrendPullbackSnapshot, cfg: dict) -> str:
    label = f"{s.stock_name}({s.symbol})" if s.stock_name else s.symbol
    if s.signal:
        tag = _path_tag(s.signal_path)
        bp = s.box_position
        bp_txt = f"{bp:.2f}" if bp == bp else "—"
        pb_txt = (
            f"20日回撤{s.pullback_swing_pct:.2f}%"
            if s.signal_path in ("box_lower", "both")
            else f"60日回撤{s.pullback_pct:.2f}%"
        )
        if s.signal_path == "both":
            pb_txt = (
                f"60日{s.pullback_pct:.2f}%/20日{s.pullback_swing_pct:.2f}%"
            )
        return (
            f"  [命中/{tag}] {label}  {s.signal_date}  close={s.close:.4f}  "
            f"{pb_txt}  position={bp_txt}"
        )
    reason = " | ".join(_failed_pullback_reasons(s, cfg))
    return f"  [未中] {label}  {s.signal_date}  {reason}"


def _symbol_diagnosis_lines(s: TrendPullbackSnapshot, cfg: dict) -> List[str]:
    label = f"{s.stock_name}({s.symbol})" if s.stock_name else s.symbol
    lines: List[str] = [f"—— {label}  {s.signal_date}  path={s.signal_path or '-'} ——"]
    lines.append(
        f"  收盘 {s.close:.4f}  Low {s.low:.4f}  Open {s.open_:.4f}  "
        f"MA20={s.ma20:.4f}  MA60={s.ma60:.4f}  MA120={s.ma120:.4f}"
    )
    bp = s.box_position
    bp_txt = f"{bp:.4f}" if bp == bp else "—"
    lines.append(
        f"  60日涨幅={s.rise_60_pct:.2f}%  60日回撤={s.pullback_pct:.2f}%  "
        f"20日回撤={s.pullback_swing_pct:.2f}%  箱体position={bp_txt}  "
        f"振幅={s.box_range_pct:.2f}%"
    )
    lines.append(
        f"  路径A(浅回踩): {'满足' if s.path_a_ok else '未满足 — ' + '；'.join(_failed_path_a(s, cfg))}"
    )
    lines.append(
        f"  路径B(箱体下沿): {'满足' if s.path_b_ok else '未满足 — ' + '；'.join(_failed_path_b(s, cfg))}"
    )
    if s.signal:
        lines.append(f"  **结论: 命中 [{_path_tag(s.signal_path)}]。**")
    else:
        lines.append("  **结论: 未触发。**")
    lines.append("")
    return lines


def _merge_cfg(base: dict, overrides: dict) -> dict:
    out = dict(base)
    out.update({k: v for k, v in overrides.items() if v is not None})
    return out


def _yaml_bool(val: object) -> bool:
    if isinstance(val, bool):
        return val
    if val is None:
        return False
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _load_trend_pullback_yaml(path: str) -> dict:
    p = os.path.abspath(path)
    if not os.path.isfile(p):
        return {}
    try:
        import yaml

        with open(p, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def load_print_backtest_lower(path: str) -> bool:
    """从 YAML 读取 PRINT_BACKTEST_LOWER：控制台重显已算好的最近下沿参考。"""
    return _yaml_bool(_load_trend_pullback_yaml(path).get("PRINT_BACKTEST_LOWER"))


def load_skip_pullback_layers_12(path: str) -> bool:
    """从 YAML 读取 SKIP_PULLBACK_LAYERS_12：关闭下沿结构+接近买入层。"""
    return _yaml_bool(_load_trend_pullback_yaml(path).get("SKIP_PULLBACK_LAYERS_12"))


def load_trend_pullback_range(
    path: str,
    *,
    end_date_fallback: str,
) -> tuple[str, str, str]:
    """
    从 YAML 读取 SCAN_FROM / SCAN_TO / END_DATE。
    SCAN_TO、END_DATE 留空时使用 end_date_fallback（通常为今天）。
    """
    scan_from_d = (pd.Timestamp(end_date_fallback) - timedelta(days=540)).strftime("%Y-%m-%d")
    scan_to_d = end_date_fallback
    end_d = end_date_fallback

    d = _load_trend_pullback_yaml(path)
    sf = str(d.get("SCAN_FROM", "")).strip()
    st = str(d.get("SCAN_TO", "")).strip()
    ed = str(d.get("END_DATE", "")).strip()
    if sf:
        scan_from_d = sf
    if st:
        scan_to_d = st
    if ed:
        end_d = ed
    elif st:
        end_d = st

    if pd.Timestamp(scan_from_d) > pd.Timestamp(scan_to_d):
        scan_from_d, scan_to_d = scan_to_d, scan_from_d
    if pd.Timestamp(end_d) < pd.Timestamp(scan_to_d):
        end_d = scan_to_d
    return scan_from_d, scan_to_d, end_d


def _parse_symbols_arg(raw: str) -> List[str]:
    syms: List[str] = []
    for x in str(raw).split(","):
        tok = x.strip()
        if not tok:
            continue
        sym = "".join(filter(str.isdigit, tok)).zfill(6)
        if len(sym) == 6:
            syms.append(sym)
    return list(dict.fromkeys(syms))


def main() -> None:
    base_cfg = dict(TREND_PULLBACK_CONFIG)
    parser = argparse.ArgumentParser(
        description="Trend Pullback：路径A浅回踩MA20 + 路径B高位箱体下沿（历史回测默认）"
    )
    parser.add_argument("--pool", default=DEFAULT_POOL_TXT, help="股票池 txt")
    parser.add_argument("--symbols", default="", help="逗号分隔代码；非空则忽略 --pool")
    parser.add_argument(
        "--range-config",
        default=DEFAULT_RANGE_YAML,
        help="历史回测区间 YAML（SCAN_FROM / SCAN_TO / END_DATE）",
    )
    parser.add_argument("--scan-from", default="", help="覆盖 YAML：历史起始日（含）")
    parser.add_argument("--scan-to", default="", help="覆盖 YAML：历史结束日（含）")
    parser.add_argument(
        "--snapshot",
        action="store_true",
        help="仅评截止日最后一根 K（不写历史区间）",
    )
    parser.add_argument("--diagnose", action="store_true", help="追加逐股诊断（默认截止日快照）")
    parser.add_argument(
        "--end-date",
        default="",
        help="数据截止日；留空则用今天或 YAML END_DATE",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=int(base_cfg["history_calendar_days"]),
        help="向前拉取自然日长度",
    )
    parser.add_argument(
        "--pullback-lookback",
        type=int,
        default=None,
        help="回撤参照的收盘最高价窗口（默认 60）",
    )
    parser.add_argument("--pullback-min", type=float, default=None, help="路径A 60日回撤下限，如 0.04")
    parser.add_argument("--pullback-max", type=float, default=None, help="路径A 60日回撤上限，如 0.22")
    parser.add_argument(
        "--pullback-swing-min",
        type=float,
        default=None,
        help="路径B 20日回撤下限，如 0.04",
    )
    parser.add_argument(
        "--pullback-swing-max",
        type=float,
        default=None,
        help="路径B 20日回撤上限，如 0.25",
    )
    parser.add_argument(
        "--box-position-max",
        type=float,
        default=None,
        help="路径B 箱体下沿 position 上限，如 0.35",
    )
    parser.add_argument("--rise-60-min", type=float, default=None, help="60日振幅涨幅下限，如 0.30")
    parser.add_argument("--ma20-touch-max", type=float, default=None, help="Low 相对 MA20 上限比例，如 0.02")
    parser.add_argument(
        "--buy-near-max",
        type=float,
        default=None,
        help="最新收盘相对最近下沿命中收盘的最大偏离比例，如 0.03",
    )
    parser.add_argument(
        "--buy-far-min",
        type=float,
        default=None,
        help="最新收盘较最近下沿命中收盘的最小涨幅比例，触发可能新主升，如 0.15",
    )
    parser.add_argument(
        "--out-csv",
        default=DEFAULT_SCAN_OUT_CSV,
        help="输出 CSV（仅买入信号与可能新主升）",
    )
    parser.add_argument(
        "--hits-csv",
        default="",
        help="可选：另存历史区间内全部下沿命中（默认不写）",
    )
    parser.add_argument(
        "--print-hits",
        action="store_true",
        help="控制台追加打印历史回测逐日命中（默认不打印）",
    )
    parser.add_argument(
        "--print-backtest-lower",
        action="store_true",
        help="控制台重显已算好的最近下沿参考（等同 YAML PRINT_BACKTEST_LOWER: true）",
    )
    parser.add_argument(
        "--skip-layers-12",
        action="store_true",
        help="关闭下沿结构+接近买入层（等同 YAML SKIP_PULLBACK_LAYERS_12: true）",
    )
    args = parser.parse_args()

    cfg = _merge_cfg(
        base_cfg,
        {
            "history_calendar_days": int(args.days),
            "pullback_lookback": args.pullback_lookback,
            "rise_lookback": args.pullback_lookback,
            "pullback_min_pct": args.pullback_min,
            "pullback_max_pct": args.pullback_max,
            "pullback_swing_min_pct": args.pullback_swing_min,
            "pullback_swing_max_pct": args.pullback_swing_max,
            "box_position_max": args.box_position_max,
            "rise_60_min_pct": args.rise_60_min,
            "ma20_touch_max_pct": args.ma20_touch_max,
            "buy_near_max_pct": args.buy_near_max,
            "buy_far_min_pct": args.buy_far_min,
        },
    )
    if cfg.get("pullback_lookback") is not None:
        cfg["rise_lookback"] = int(cfg["pullback_lookback"])

    today_s = datetime.now().strftime("%Y-%m-%d")
    end_fallback = str(args.end_date).strip() or today_s
    range_mode = not bool(args.snapshot)
    range_config_path = os.path.abspath(str(args.range_config))
    skip_layers_12 = bool(args.skip_layers_12) or load_skip_pullback_layers_12(
        range_config_path
    )
    print_backtest_lower = (
        not skip_layers_12
        and (
            bool(args.print_backtest_lower)
            or load_print_backtest_lower(range_config_path)
        )
    )

    scan_from = str(args.scan_from).strip()
    scan_to = str(args.scan_to).strip()
    data_end = end_fallback

    if range_mode:
        if scan_from and scan_to:
            data_end = end_fallback
        else:
            y_from, y_to, y_end = load_trend_pullback_range(
                str(args.range_config),
                end_date_fallback=end_fallback,
            )
            if not scan_from:
                scan_from = y_from
            if not scan_to:
                scan_to = y_to
            if not str(args.end_date).strip():
                data_end = y_end
        if pd.Timestamp(scan_from) > pd.Timestamp(scan_to):
            print("--scan-from 不能晚于 --scan-to")
            sys.exit(2)
        if pd.Timestamp(data_end) < pd.Timestamp(scan_to):
            data_end = scan_to
    else:
        data_end = end_fallback

    symbols_from_cli = bool(str(args.symbols).strip())
    pool_path = ""
    if symbols_from_cli:
        syms = _parse_symbols_arg(args.symbols)
    else:
        pool_path = os.path.abspath(str(args.pool))
        syms = load_stocks_pool_txt(pool_path)
        if not syms:
            print(f"股票池为空或文件不存在: {pool_path}")
            sys.exit(2)

    if skip_layers_12:
        hits = []
        skipped = []
        evaluated = []
        latest_hits = {}
        buy_alerts = []
        buy_alerts_by_symbol = {}
        evaluated_by_symbol = {}
    elif range_mode:
        hits, skipped, evaluated, latest_hits = scan_trend_pullback_range(
            syms,
            scan_from=scan_from,
            scan_to=scan_to,
            end_date=data_end,
            history_calendar_days=int(cfg["history_calendar_days"]),
            cfg=cfg,
        )
        buy_alerts = compute_buy_near_alerts(evaluated, latest_hits, cfg)
        buy_alerts_by_symbol = {a.symbol: a for a in buy_alerts}
        evaluated_by_symbol = {s.symbol: s for s in evaluated}
    else:
        hits, skipped, evaluated, latest_hits = scan_trend_pullback_snapshot(
            syms,
            end_date=data_end,
            history_calendar_days=int(cfg["history_calendar_days"]),
            cfg=cfg,
        )
        buy_alerts = compute_buy_near_alerts(evaluated, latest_hits, cfg)
        buy_alerts_by_symbol = {a.symbol: a for a in buy_alerts}
        evaluated_by_symbol = {s.symbol: s for s in evaluated}

    turnover_cache = _fetch_turnover_bars_cache(
        syms,
        end_date=data_end,
        history_calendar_days=int(cfg["history_calendar_days"]),
    )
    turnover_passed, turnover_filtered, turnover_eval_map = evaluate_pool_turnover_volume(
        syms,
        evaluated_by_symbol=evaluated_by_symbol,
        buy_alerts_by_symbol=buy_alerts_by_symbol,
        turnover_cache=turnover_cache,
        cfg=cfg,
    )

    turnover_passed_symbols = sorted({a.symbol for a in turnover_passed})
    ohlc_cache = _fetch_prepared_ohlc_cache(
        turnover_passed_symbols,
        end_date=data_end,
        history_calendar_days=int(cfg["history_calendar_days"]),
    )
    try:
        scored_alerts, chip_filtered, chip_missing = enrich_alerts_with_chips(
            turnover_passed,
            latest_hits,
            ohlc_cache,
            turnover_eval_map,
            cfg,
            skip_layers_12=skip_layers_12,
        )
    except RuntimeError as e:
        print(f"筹码分析失败: {e}")
        sys.exit(2)

    buy_signals = [a for a in chip_passed_alerts(scored_alerts) if a.signal_type == "买入信号"]
    breakout_signals = [a for a in chip_passed_alerts(scored_alerts) if a.signal_type == "主升突破"]
    new_uptrend_signals = [
        a for a in chip_passed_alerts(scored_alerts) if a.signal_type == "可能新主升"
    ]
    chip_passed_count = sum(1 for a in scored_alerts if a.chip_status == "通过")

    signal_df = active_signals_to_dataframe(scored_alerts)
    out_path = os.path.abspath(args.out_csv)
    ddir = os.path.dirname(out_path)
    if ddir:
        os.makedirs(ddir, exist_ok=True)
    signal_df.to_csv(out_path, index=False, encoding="utf-8-sig")

    hits_csv_arg = str(args.hits_csv).strip()
    if hits_csv_arg:
        hits_path = os.path.abspath(hits_csv_arg)
        hits_dir = os.path.dirname(hits_path)
        if hits_dir:
            os.makedirs(hits_dir, exist_ok=True)
        snapshots_to_dataframe(hits).to_csv(
            hits_path, index=False, encoding="utf-8-sig"
        )

    if range_mode:
        mode_txt = f"历史回测 {scan_from}～{scan_to}（数据至 {data_end}）"
    else:
        mode_txt = f"截止日快照 {data_end}"
    if skip_layers_12:
        mode_txt += " | 简化模式（已关闭下沿/接近买入）"
    print(
        f"Trend Pullback | {mode_txt} | 扫描 {len(syms)} 只 | "
        f"输出表 {len(signal_df)} 条（换手量稳通过 {len(turnover_passed)}，"
        f"筹码通过 {chip_passed_count}；买入 {len(buy_signals)} + "
        f"主升突破 {len(breakout_signals)} + 主升展示 {len(new_uptrend_signals)}）"
    )
    if skip_layers_12:
        print(
            "简化规则: 全池第三层换手增大+量稳硬过滤 → 第四层筹码硬过滤；"
            "排序=换手率增幅↓、量稳天数↓、筹码分(score_total)↓"
        )
    elif range_mode:
        print(f"（区间内下沿命中 {len(hits)} 条，未写入主表）")
    if not symbols_from_cli and pool_path:
        print(f"股票池: {pool_path}")
    if range_mode and not skip_layers_12:
        print(f"区间配置: {os.path.abspath(str(args.range_config))}")
    elif skip_layers_12:
        print(f"区间配置: {os.path.abspath(str(args.range_config))}（SKIP_PULLBACK_LAYERS_12=true）")
    if not skip_layers_12:
        print(
            "规则: A=均线多头+"
            f"{int(cfg['pullback_lookback'])}日回撤"
            f"{float(cfg['pullback_min_pct']):.0%}~{float(cfg['pullback_max_pct']):.0%}+贴MA20；"
            "B=主升未坏+"
            f"20日箱体position<{float(cfg['box_position_max']):.0%}+"
            f"{int(cfg['pullback_swing_lookback'])}日回撤"
            f"{float(cfg['pullback_swing_min_pct']):.0%}~{float(cfg['pullback_swing_max_pct']):.0%}；"
            "共用缩量阳线；截止日换手增大+量稳硬过滤；筹码口诀3/4硬过滤，"
            "评分=下沿结构+回踩主峰+主升突破+筹码质量"
        )
    print(
        f"已写入输出表（换手量稳通过 {len(turnover_passed)} 只，"
        f"含筹码状态/评分，{'简化排序' if skip_layers_12 else '筹码通过优先排序'}）: {out_path}"
    )
    if hits_csv_arg:
        print(f"已写入历史命中表（--hits-csv）: {os.path.abspath(hits_csv_arg)}")
    if not skip_layers_12:
        print(
            f"接近下沿买入层: abs(最新收盘-最近命中收盘)/命中收盘 <= "
            f"{float(cfg['buy_near_max_pct']):.0%} -> 买入信号 {len(buy_signals)} 只"
        )
        print(
            f"远离下沿主升层: (最新收盘-最近命中收盘)/命中收盘 >= "
            f"{float(cfg['buy_far_min_pct']):.0%} -> 可能新主升(展示) {len(new_uptrend_signals)} 只"
        )
    tv = TURNOVER_VOLUME_CONFIG
    pool_eval_note = (
        "全池评估"
        if skip_layers_12
        else f"全池评估，其中 {len(buy_alerts)} 只有下沿命中"
    )
    print(
        f"截止日换手量稳层: 近{int(tv['turnover_recent_bars'])}日均换手>"
        f"前{int(tv['turnover_prior_bars'])}日×{float(tv['turnover_rise_ratio_min'])}"
        f"且≥{float(tv['turnover_ma3_min_pct'])}%；"
        f"近{int(tv['volume_stable_lookback_bars'])}日量稳≥{int(tv['volume_stable_min_days'])}天"
        f" -> 通过 {len(turnover_passed)}/{len(syms)} 只（{pool_eval_note}）"
    )
    if turnover_filtered:
        print(
            f"换手量稳硬过滤剔除 {len(turnover_filtered)} 只: "
            + ", ".join(turnover_filtered[:20])
            + (" ..." if len(turnover_filtered) > 20 else "")
        )
    if chip_filtered:
        print(
            f"筹码硬过滤剔除 {len(chip_filtered)} 只: "
            + ", ".join(chip_filtered[:20])
            + (" ..." if len(chip_filtered) > 20 else "")
        )
    if chip_missing:
        print(
            f"无筹码/K线跳过 {len(chip_missing)} 只: "
            + ", ".join(chip_missing[:20])
            + (" ..." if len(chip_missing) > 20 else "")
        )

    if print_backtest_lower:
        _print_backtest_lower_refs(
            buy_alerts,
            range_mode=range_mode,
            scan_from=scan_from,
            scan_to=scan_to,
        )

    print("=" * 72)
    if skip_layers_12:
        print("【主升突破】（简化模式：筹码通过 + 低位单峰放量突破）")
    else:
        print("【买入信号】（接近下沿 + 筹码通过 + 评分排序）")
        if buy_signals:
            for a in buy_signals:
                print(_scored_alert_brief_line(a, cfg))
        else:
            print("  （无）")
        print("=" * 72)
        print("【主升突破】（低位单峰 + 放量突破 + 筹码通过）")
    if breakout_signals:
        for a in breakout_signals:
            print(_scored_alert_brief_line(a, cfg))
    else:
        print("  （无）")

    print("=" * 72)
    if not skip_layers_12:
        print("【可能新主升】（展示标签：未满足主升突破时的补充识别）")
        if new_uptrend_signals:
            for a in new_uptrend_signals:
                print(_scored_alert_brief_line(a, cfg))
        else:
            print(
                "  （无：需有历史下沿命中，且最新收盘较命中收盘涨幅 >= "
                f"{float(cfg['buy_far_min_pct']):.0%}，且未触发主升突破）"
            )
        print("=" * 72)

    if bool(args.print_hits) and not skip_layers_12:
        print("=" * 72)
        print("【历史命中】" if range_mode else "【扫描结果】（--print-hits）")
        if hits:
            for s in hits:
                print(_symbol_brief_line(s, cfg))
        else:
            print("  （无命中日）" if range_mode else "  （无命中）")

        if range_mode and evaluated:
            hit_syms = {h.symbol for h in hits}
            no_hit = [x for x in evaluated if x.symbol not in hit_syms]
            if no_hit:
                print("—— 区间内无命中 ——")
                for snap in sorted(no_hit, key=lambda x: x.symbol):
                    label = (
                        f"{snap.stock_name}({snap.symbol})"
                        if snap.stock_name
                        else snap.symbol
                    )
                    print(f"  [无历史命中] {label}  （{scan_from}～{scan_to}）")
        elif not range_mode:
            misses = [x for x in evaluated if not x.signal]
            if misses:
                print("—— 未命中 ——")
                for snap in sorted(misses, key=lambda x: x.symbol):
                    print(_symbol_brief_line(snap, cfg))

    if skipped:
        print(
            "跳过: "
            + ", ".join(skipped[:40])
            + (" ..." if len(skipped) > 40 else "")
        )

    diag_list = evaluated
    if bool(args.diagnose) and diag_list and not skip_layers_12:
        print("=" * 72)
        print("【逐股诊断】（--diagnose）")
        print("=" * 72)
        for snap in sorted(diag_list, key=lambda x: (x.symbol, x.signal_date)):
            for line in _symbol_diagnosis_lines(snap, cfg):
                print(line)


if __name__ == "__main__":
    main()

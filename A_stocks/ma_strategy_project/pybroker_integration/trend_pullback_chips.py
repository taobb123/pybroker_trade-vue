#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trend Pullback 筹码分布分析（Tushare cyq_chips / cyq_perf）。

口诀映射：
  1 低位单峰底仓稳，放量突破主升起 → low_single_peak + 主升突破
  2 上涨多峰底不动，回踩主峰大胆拿 → multi_peak_stable + 回踩加分
  3 高位单峰底仓空，放量滞涨赶快走 → high_single_empty（硬过滤）
  4 多峰分散无主力，观望等待再突破 → scattered（硬过滤）
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

REQUEST_SLEEP_SEC = 0.35

CHIP_CONFIG = {
    "peak_min_pct": 2.5,
    "single_peak_concentration_min": 0.12,
    "scattered_peak_max_pct": 6.0,
    "scattered_spread_min": 0.18,
    "low_peak_position_max": 0.35,
    "high_peak_position_min": 0.70,
    "bottom_band_ratio": 0.25,
    "bottom_stable_max_drop_pct": 5.0,
    "bottom_empty_min_drop_pct": 10.0,
    "chip_compare_days": 5,
    "breakout_vol_ratio": 1.5,
    "breakout_lookback": 20,
    "stagnation_max_return_pct": 2.0,
    "main_peak_touch_max_pct": 0.04,
    "weight_structure": 0.30,
    "weight_pullback_peak": 0.25,
    "weight_breakout": 0.25,
    "weight_chip_quality": 0.20,
}


@dataclass(frozen=True)
class ChipPeak:
    price: float
    percent: float


@dataclass(frozen=True)
class ChipAnalysis:
    trade_date: str
    pattern: str
    pattern_label: str
    peak_count: int
    main_peak_price: float
    main_peak_pct: float
    concentration: float
    peak_position: float
    bottom_band_pct: float
    bottom_band_change_pct: float
    bottom_stable: bool
    bottom_empty: bool
    hard_filtered: bool
    hard_filter_reason: str
    main_rise_breakout: bool
    volume_breakout: bool
    volume_stagnation: bool
    pullback_main_peak_ok: bool


@dataclass(frozen=True)
class ChipScores:
    score_structure: float
    score_pullback_peak: float
    score_breakout: float
    score_chip_quality: float
    score_total: float


def _normalize_code(code: str) -> str:
    if not code or pd.isna(code):
        return ""
    s = str(code).strip().upper().replace("SZ", "").replace("SH", "")
    s = "".join(c for c in s if c.isdigit())
    return s.zfill(6) if len(s) <= 6 else s[:6]


def _to_ts_code(code: str) -> str:
    code = _normalize_code(code)
    if not code:
        return ""
    if code.startswith(("0", "3", "1")):
        return f"{code}.SZ"
    if code.startswith(("6", "5")):
        return f"{code}.SH"
    return f"{code}.SH"


def _date_compact(date_str: str) -> str:
    return str(date_str).replace("-", "")[:8]


def get_tushare_pro():
    token = (os.getenv("TUSHARE_TOKEN") or "").strip()
    if not token:
        try:
            from config.settings import DATA_CONFIG

            token = ((DATA_CONFIG or {}).get("tushare_token") or "").strip()
        except Exception:
            token = ""
    if not token:
        raise RuntimeError(
            "未找到 Tushare Token：请设置环境变量 TUSHARE_TOKEN 或 "
            "config.settings.DATA_CONFIG['tushare_token']"
        )
    import tushare as ts

    ts.set_token(token)
    return ts.pro_api()


def fetch_cyq_chips(
    pro,
    ts_code: str,
    trade_date: str,
) -> Optional[pd.DataFrame]:
    compact = _date_compact(trade_date)
    try:
        df = pro.cyq_chips(ts_code=ts_code, trade_date=compact)
        time.sleep(REQUEST_SLEEP_SEC)
    except Exception:
        return None
    if df is None or df.empty:
        return None
    out = df.copy()
    out["price"] = pd.to_numeric(out["price"], errors="coerce")
    out["percent"] = pd.to_numeric(out["percent"], errors="coerce")
    out = out.dropna(subset=["price", "percent"])
    if out.empty:
        return None
    return out.sort_values("price").reset_index(drop=True)


def fetch_cyq_perf_near(
    pro,
    ts_code: str,
    trade_date: str,
    compare_days: int,
) -> Tuple[Optional[pd.Series], Optional[pd.Series]]:
    compact = _date_compact(trade_date)
    start = (pd.Timestamp(trade_date) - pd.Timedelta(days=int(compare_days) * 3)).strftime(
        "%Y%m%d"
    )
    try:
        df = pro.cyq_perf(ts_code=ts_code, end_date=compact, start_date=start)
        time.sleep(REQUEST_SLEEP_SEC)
    except Exception:
        return None, None
    if df is None or df.empty:
        return None, None
    df = df.sort_values("trade_date").reset_index(drop=True)
    df["trade_date"] = df["trade_date"].astype(str)
    today_rows = df[df["trade_date"] == compact]
    if today_rows.empty:
        today_row = df.iloc[-1]
    else:
        today_row = today_rows.iloc[-1]
    prev_idx = max(0, len(df) - 1 - int(compare_days))
    prev_row = df.iloc[prev_idx]
    if str(prev_row["trade_date"]) >= compact:
        prev_row = df.iloc[max(0, len(df) - 2)]
    return today_row, prev_row


def _detect_peaks(chips: pd.DataFrame, min_pct: float) -> List[ChipPeak]:
    if chips is None or len(chips) < 3:
        return []
    prices = chips["price"].to_numpy(dtype=float)
    pcts = chips["percent"].to_numpy(dtype=float)
    peaks: List[ChipPeak] = []
    for i in range(1, len(pcts) - 1):
        if pcts[i] >= pcts[i - 1] and pcts[i] > pcts[i + 1] and pcts[i] >= min_pct:
            peaks.append(ChipPeak(price=float(prices[i]), percent=float(pcts[i])))
    if not peaks and len(pcts) > 0:
        idx = int(np.argmax(pcts))
        if pcts[idx] >= min_pct * 0.6:
            peaks.append(ChipPeak(price=float(prices[idx]), percent=float(pcts[idx])))
    peaks.sort(key=lambda p: p.percent, reverse=True)
    return peaks


def _bottom_band_percent(chips: pd.DataFrame, band_ratio: float) -> float:
    if chips is None or chips.empty:
        return float("nan")
    p_min = float(chips["price"].min())
    p_max = float(chips["price"].max())
    if p_max <= p_min + 1e-9:
        return float(chips["percent"].sum())
    cutoff = p_min + (p_max - p_min) * float(band_ratio)
    mask = chips["price"] <= cutoff + 1e-9
    return float(chips.loc[mask, "percent"].sum())


def _peak_position(price: float, range_low: float, range_high: float) -> float:
    span = range_high - range_low
    if span <= 1e-9:
        return 0.5
    return float(np.clip((price - range_low) / span, 0.0, 1.0))


def _concentration(peaks: List[ChipPeak], total_pct: float) -> float:
    if not peaks or total_pct <= 1e-9:
        return 0.0
    return float(peaks[0].percent) / total_pct


def _is_scattered(peaks: List[ChipPeak], chips: pd.DataFrame, cfg: dict) -> bool:
    if len(peaks) < 2:
        return False
    max_pct = float(cfg["scattered_peak_max_pct"])
    spread_min = float(cfg["scattered_spread_min"])
    sig = [p for p in peaks if p.percent >= max_pct * 0.5]
    if len(sig) < 2:
        return True
    prices = [p.price for p in sig[:3]]
    p_min = float(chips["price"].min())
    p_max = float(chips["price"].max())
    span = p_max - p_min
    if span <= 1e-9:
        return True
    price_spread = (max(prices) - min(prices)) / span
    top_share = sum(p.percent for p in sig[:3])
    total = float(chips["percent"].sum())
    share_ratio = top_share / total if total > 1e-9 else 0.0
    return price_spread >= spread_min and share_ratio < 0.45


def analyze_chips(
    chips_today: pd.DataFrame,
    chips_prev: Optional[pd.DataFrame],
    *,
    close: float,
    open_: float,
    high: float,
    volume: float,
    vol_ma5: float,
    range_low_60: float,
    range_high_60: float,
    hhv_high_n: float,
    cfg: dict,
) -> ChipAnalysis:
    min_peak = float(cfg["peak_min_pct"])
    peaks = _detect_peaks(chips_today, min_peak)
    peak_count = len(peaks)
    total_pct = float(chips_today["percent"].sum()) if not chips_today.empty else 0.0
    concentration = _concentration(peaks, total_pct)

    if peaks:
        main_peak = peaks[0]
        main_peak_price = main_peak.price
        main_peak_pct = main_peak.percent
    else:
        main_peak_price = float("nan")
        main_peak_pct = 0.0

    peak_pos = (
        _peak_position(main_peak_price, range_low_60, range_high_60)
        if main_peak_price == main_peak_price
        else 0.5
    )

    bottom_today = _bottom_band_percent(chips_today, float(cfg["bottom_band_ratio"]))
    bottom_prev = (
        _bottom_band_percent(chips_prev, float(cfg["bottom_band_ratio"]))
        if chips_prev is not None and not chips_prev.empty
        else bottom_today
    )
    if bottom_prev > 1e-9:
        bottom_change = (bottom_today - bottom_prev) / bottom_prev * 100.0
    else:
        bottom_change = 0.0

    stable_thr = float(cfg["bottom_stable_max_drop_pct"])
    empty_thr = float(cfg["bottom_empty_min_drop_pct"])
    bottom_stable = bottom_change >= -stable_thr
    bottom_empty = bottom_change <= -empty_thr

    single_peak = peak_count <= 1 or concentration >= float(cfg["single_peak_concentration_min"])
    low_peak = peak_pos <= float(cfg["low_peak_position_max"])
    high_peak = peak_pos >= float(cfg["high_peak_position_min"])
    scattered = _is_scattered(peaks, chips_today, cfg)

    vol_ratio_thr = float(cfg["breakout_vol_ratio"])
    vol_heavy = vol_ma5 > 0 and volume >= vol_ma5 * vol_ratio_thr
    daily_ret = (close - open_) / open_ if open_ > 1e-9 else 0.0
    volume_stagnation = bool(vol_heavy and daily_ret * 100.0 < float(cfg["stagnation_max_return_pct"]))

    volume_breakout = bool(
        vol_heavy
        and hhv_high_n > 1e-9
        and close >= hhv_high_n * 0.998
    )

    touch_max = float(cfg["main_peak_touch_max_pct"])
    if main_peak_price == main_peak_price and main_peak_price > 1e-9:
        peak_gap = abs(close - main_peak_price) / main_peak_price
        pullback_main_peak_ok = bool(peak_gap <= touch_max and volume < vol_ma5)
    else:
        pullback_main_peak_ok = False

    hard_filtered = False
    hard_reason = ""
    pattern = "unknown"
    label = "未知"

    if scattered and peak_count >= 2:
        pattern = "scattered"
        label = "多峰分散无主力"
        hard_filtered = True
        hard_reason = label
    elif single_peak and high_peak and bottom_empty:
        pattern = "high_single_empty"
        label = "高位单峰底仓空"
        hard_filtered = True
        hard_reason = label
        if volume_stagnation:
            hard_reason = f"{label}（放量滞涨）"
    elif single_peak and high_peak and volume_stagnation:
        pattern = "high_single_empty"
        label = "高位单峰底仓空"
        hard_filtered = True
        hard_reason = f"{label}（放量滞涨）"
    elif single_peak and low_peak and bottom_stable:
        pattern = "low_single_peak"
        label = "低位单峰底仓稳"
    elif peak_count >= 2 and bottom_stable:
        pattern = "multi_peak_stable"
        label = "上涨多峰底不动"
    elif single_peak:
        pattern = "single_peak"
        label = "单峰"
    elif peak_count >= 2:
        pattern = "multi_peak"
        label = "多峰"
    else:
        pattern = "unknown"
        label = "筹码形态未明"

    main_rise_breakout = bool(
        pattern == "low_single_peak"
        and volume_breakout
        and bottom_stable
    )

    return ChipAnalysis(
        trade_date="",
        pattern=pattern,
        pattern_label=label,
        peak_count=peak_count,
        main_peak_price=round(main_peak_price, 4) if main_peak_price == main_peak_price else float("nan"),
        main_peak_pct=round(main_peak_pct, 4),
        concentration=round(concentration, 4),
        peak_position=round(peak_pos, 4),
        bottom_band_pct=round(bottom_today, 4) if bottom_today == bottom_today else float("nan"),
        bottom_band_change_pct=round(bottom_change, 4),
        bottom_stable=bottom_stable,
        bottom_empty=bottom_empty,
        hard_filtered=hard_filtered,
        hard_filter_reason=hard_reason,
        main_rise_breakout=main_rise_breakout,
        volume_breakout=volume_breakout,
        volume_stagnation=volume_stagnation,
        pullback_main_peak_ok=pullback_main_peak_ok,
    )


def score_pullback_structure(
    *,
    signal_path: str,
    rise_60_pct: float,
    pullback_pct: float,
    pullback_swing_pct: float,
    box_position: float,
    ma_stack_ok: bool,
) -> float:
    base = 12.0
    if signal_path == "both":
        base = 28.0
    elif signal_path == "ma20_pullback":
        base = 24.0
    elif signal_path == "box_lower":
        base = 22.0
    if ma_stack_ok:
        base += 2.0
    if rise_60_pct == rise_60_pct and rise_60_pct >= 40.0:
        base += 2.0
    pb = pullback_swing_pct if pullback_swing_pct == pullback_swing_pct else pullback_pct
    if pb == pb and 6.0 <= pb <= 14.0:
        base += 2.0
    bp = box_position
    if bp == bp and bp < 0.25:
        base += 2.0
    return float(min(30.0, max(0.0, base)))


def score_chip_pullback_peak(chip: ChipAnalysis) -> float:
    if chip.hard_filtered:
        return 0.0
    score = 0.0
    if chip.pattern == "multi_peak_stable":
        score += 15.0
    if chip.bottom_stable:
        score += 5.0
    if chip.pullback_main_peak_ok:
        score += 8.0
    if chip.pattern == "low_single_peak" and not chip.main_rise_breakout:
        score += 4.0
    return float(min(25.0, score))


def score_chip_breakout(chip: ChipAnalysis) -> float:
    if chip.hard_filtered:
        return 0.0
    score = 0.0
    if chip.main_rise_breakout:
        score += 22.0
    elif chip.volume_breakout and chip.pattern in ("low_single_peak", "multi_peak_stable"):
        score += 12.0
    if chip.pattern == "low_single_peak":
        score += 3.0
    return float(min(25.0, score))


def score_chip_quality(chip: ChipAnalysis) -> float:
    if chip.hard_filtered:
        return 0.0
    score = 8.0
    if chip.concentration >= 0.15:
        score += 4.0
    elif chip.concentration >= 0.10:
        score += 2.0
    if chip.bottom_stable:
        score += 4.0
    if chip.pattern in ("low_single_peak", "multi_peak_stable"):
        score += 4.0
    if chip.peak_position <= 0.4:
        score += 2.0
    return float(min(20.0, score))


def compute_chip_scores(
    chip: ChipAnalysis,
    *,
    signal_path: str,
    rise_60_pct: float,
    pullback_pct: float,
    pullback_swing_pct: float,
    box_position: float,
    ma_stack_ok: bool,
    cfg: dict,
) -> ChipScores:
    s_struct = score_pullback_structure(
        signal_path=signal_path,
        rise_60_pct=rise_60_pct,
        pullback_pct=pullback_pct,
        pullback_swing_pct=pullback_swing_pct,
        box_position=box_position,
        ma_stack_ok=ma_stack_ok,
    )
    s_peak = score_chip_pullback_peak(chip)
    s_break = score_chip_breakout(chip)
    s_quality = score_chip_quality(chip)
    w_s = float(cfg.get("weight_structure", 0.30))
    w_p = float(cfg.get("weight_pullback_peak", 0.25))
    w_b = float(cfg.get("weight_breakout", 0.25))
    w_q = float(cfg.get("weight_chip_quality", 0.20))
    denom = w_s + w_p + w_b + w_q
    total = (
        s_struct / 30.0 * w_s
        + s_peak / 25.0 * w_p
        + s_break / 25.0 * w_b
        + s_quality / 20.0 * w_q
    ) / denom * 100.0
    return ChipScores(
        score_structure=round(s_struct, 2),
        score_pullback_peak=round(s_peak, 2),
        score_breakout=round(s_break, 2),
        score_chip_quality=round(s_quality, 2),
        score_total=round(float(min(100.0, max(0.0, total))), 2),
    )


def compute_chip_only_scores(chip: ChipAnalysis, cfg: dict) -> ChipScores:
    """简化模式（关闭下沿/接近买入层）：仅筹码三维度加权，用于 score_total 排序。"""
    s_peak = score_chip_pullback_peak(chip)
    s_break = score_chip_breakout(chip)
    s_quality = score_chip_quality(chip)
    w_p = float(cfg.get("weight_pullback_peak", 0.25))
    w_b = float(cfg.get("weight_breakout", 0.25))
    w_q = float(cfg.get("weight_chip_quality", 0.20))
    denom = w_p + w_b + w_q
    if denom <= 0:
        denom = 1.0
    total = (
        s_peak / 25.0 * w_p
        + s_break / 25.0 * w_b
        + s_quality / 20.0 * w_q
    ) / denom * 100.0
    return ChipScores(
        score_structure=0.0,
        score_pullback_peak=round(s_peak, 2),
        score_breakout=round(s_break, 2),
        score_chip_quality=round(s_quality, 2),
        score_total=round(float(min(100.0, max(0.0, total))), 2),
    )


def classify_signal_type(
    *,
    buy_signal: bool,
    new_uptrend_signal: bool,
    main_rise_breakout: bool,
) -> str:
    if main_rise_breakout:
        return "主升突破"
    if buy_signal:
        return "买入信号"
    if new_uptrend_signal:
        return "可能新主升"
    return ""


def fetch_chip_analysis_for_symbol(
    pro,
    symbol: str,
    trade_date: str,
    ohlc: pd.DataFrame,
    cfg: dict,
) -> Optional[ChipAnalysis]:
    ts_code = _to_ts_code(symbol)
    if not ts_code:
        return None
    compact = _date_compact(trade_date)
    chips_today = fetch_cyq_chips(pro, ts_code, trade_date)
    if chips_today is None or chips_today.empty:
        return None

    compare_days = int(cfg.get("chip_compare_days", 5))
    _, prev_perf_row = fetch_cyq_perf_near(pro, ts_code, trade_date, compare_days)

    chips_prev = None
    if prev_perf_row is not None:
        prev_date = str(prev_perf_row.get("trade_date", "")).replace("-", "")[:8]
        if prev_date and prev_date != compact:
            prev_fmt = f"{prev_date[:4]}-{prev_date[4:6]}-{prev_date[6:8]}"
            chips_prev = fetch_cyq_chips(pro, ts_code, prev_fmt)

    prepared = ohlc.sort_values("date").reset_index(drop=True)
    prepared["date"] = pd.to_datetime(prepared["date"])
    t = pd.Timestamp(trade_date)
    idx_rows = prepared[prepared["date"] == t]
    if idx_rows.empty:
        idx = len(prepared) - 1
        row = prepared.iloc[idx]
    else:
        idx = int(idx_rows.index[0])
        row = prepared.loc[idx]

    close = float(row["close"])
    open_ = float(row["open"])
    high = float(row["high"])
    volume = float(row["volume"])
    vol_ma5 = float(prepared["volume"].iloc[max(0, idx - 5) : idx].mean()) if idx >= 1 else volume

    lookback = int(cfg.get("breakout_lookback", 20))
    seg = prepared.iloc[max(0, idx - lookback + 1) : idx + 1]
    range_low_60 = float(seg["low"].min()) if len(seg) > 0 else close
    range_high_60 = float(seg["high"].max()) if len(seg) > 0 else close
    hhv_high_n = float(seg["high"].max()) if len(seg) > 0 else high

    long_seg = prepared.iloc[max(0, idx - 59) : idx + 1]
    if len(long_seg) >= 10:
        range_low_60 = float(long_seg["low"].min())
        range_high_60 = float(long_seg["high"].max())

    result = analyze_chips(
        chips_today,
        chips_prev,
        close=close,
        open_=open_,
        high=high,
        volume=volume,
        vol_ma5=vol_ma5,
        range_low_60=range_low_60,
        range_high_60=range_high_60,
        hhv_high_n=hhv_high_n,
        cfg=cfg,
    )
    return ChipAnalysis(
        trade_date=trade_date,
        pattern=result.pattern,
        pattern_label=result.pattern_label,
        peak_count=result.peak_count,
        main_peak_price=result.main_peak_price,
        main_peak_pct=result.main_peak_pct,
        concentration=result.concentration,
        peak_position=result.peak_position,
        bottom_band_pct=result.bottom_band_pct,
        bottom_band_change_pct=result.bottom_band_change_pct,
        bottom_stable=result.bottom_stable,
        bottom_empty=result.bottom_empty,
        hard_filtered=result.hard_filtered,
        hard_filter_reason=result.hard_filter_reason,
        main_rise_breakout=result.main_rise_breakout,
        volume_breakout=result.volume_breakout,
        volume_stagnation=result.volume_stagnation,
        pullback_main_peak_ok=result.pullback_main_peak_ok,
    )

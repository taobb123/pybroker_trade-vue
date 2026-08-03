#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从股票列表中扫描「MA10 下方末端缩量企稳 → 放量长阳反弹」候选（日线、前复权与项目 DataFetcher 一致）。

命中日 = 放量长阳当日；允许当日收盘站上 MA10。

前提（信号日前 1～3 根内至少一日满足）：
  - 量能：相对「前一波主升高点」锚定窗口内量能高点的 1/4～1/3，或当日量 ≤ 近 5 日均量 × 40%（萎缩≥60%），二者 OR；
  - 地量：当日量不超过近 60 日分布的给定分位；
  - K 线：十字星 / 锤子 / 小阴小阳（抛压枯竭近似）；
  - 乖离：(close−MA10)/MA10 ≥ −15%。

反弹日：量 ≥ 近 5 日均量×1.5（可选标记 ≥2×）；涨幅≥3%；阳线、收盘接近最高（短上影）；MA10 下跌放缓、MA5 拐头且接近/已金叉 MA10。

主升高点启发式：在 [信号日前 lookback] 至 [信号日前 4] 区间内取最高价所在 K 为锚点；锚点左侧取固定根数的成交量峰值作参照（默认 25 根，对应 20～30 根标准）。

数据：`backtest_sy_002028_threshold.fetch_ohlc_qfq`（需含 volume）。

用法（在 ma_strategy_project 目录下）：
    python pybroker_integration/fetch_a_low.py --symbols 002821,002378
    python pybroker_integration/fetch_a_low.py --pool config/fetch_a_low_symbols.txt

终端默认输出汇总、命中列表，以及池内未命中标的的单行 [未中] 摘要；--diagnose 时追加完整逐股诊断块。
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from backtest_sy_002028_threshold import fetch_ohlc_qfq, fetch_stock_name

DEFAULT_STOCKS_POOL_TXT = os.path.join(_SCRIPT_DIR, "stocks_pool.txt")
DEFAULT_SCAN_OUT_CSV = os.path.join(_SCRIPT_DIR, "rebound_support_scan.csv")

VOLUME_REBOUND_CONFIG = {
    "ma10_period": 10,
    "ma5_period": 5,
    "history_calendar_days": 250,
    "peak_lookback_bars": 90,
    "peak_left_volume_window": 25,
    "premise_max_offset": 3,
    "vol_path_a_min_ratio": 0.25,
    "vol_path_a_max_ratio": 1.0 / 3.0,
    "vol_path_b_ma5_remain": 0.4,
    "bias_ma10_floor": -0.15,
    "dim_vol_trailing": 60,
    "dim_vol_percentile": 35.0,
    "rebound_vol_mult": 1.5,
    "rebound_vol_mult_strong": 2.0,
    "rebound_min_pct": 0.03,
    "upper_shadow_max_ratio": 0.15,
    "ma10_slope_compare_bars": 5,
    "near_cross_max_gap_pct": 0.04,
}


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
    for col in ("open", "high", "low", "close", "volume"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if out["volume"].isna().all():
        return None
    out["volume"] = out["volume"].fillna(0.0)
    return out


def _is_stall_candle(o: float, h: float, l: float, c: float, prev_c: float) -> bool:
    if prev_c != prev_c or prev_c <= 0:
        return False
    rng = h - l
    if rng <= 1e-12:
        return False
    body = abs(c - o)
    body_ratio = body / rng
    pct = abs(c - prev_c) / prev_c
    if body_ratio <= 0.12 and rng / prev_c > 0.003:
        return True
    lo = min(o, c)
    hi = max(o, c)
    lower = lo - l
    upper = h - hi
    if lower >= 1.8 * max(body, rng * 0.04) and upper <= 0.55 * max(lower, 1e-12):
        return True
    if pct <= 0.012 and body_ratio <= 0.42:
        return True
    return False


def _find_uptrend_peak_idx(high: pd.Series, sig_idx: int, peak_lookback: int) -> Optional[int]:
    """信号日前 [4, peak_lookback] 区间内最高价所在索引（主升高点启发式）。"""
    left = max(0, sig_idx - int(peak_lookback))
    right_excl = sig_idx - 3
    if right_excl <= left:
        return None
    seg = high.iloc[left:right_excl]
    if seg.empty:
        return None
    rel = int(seg.argmax())
    return left + rel


def _volume_peak_before_anchor(vol: pd.Series, peak_idx: int, win: int) -> float:
    a = max(0, int(peak_idx) - int(win))
    b = int(peak_idx)
    if b <= a:
        return float("nan")
    seg = vol.iloc[a:b]
    if seg.empty:
        return float("nan")
    return float(seg.max())


def _premise_volume_path_a(vol_p: float, v_peak: float, lo_r: float, hi_r: float) -> bool:
    if v_peak != v_peak or v_peak <= 0 or vol_p != vol_p:
        return False
    lo_v = v_peak * float(lo_r)
    hi_v = v_peak * float(hi_r)
    return lo_v <= vol_p <= hi_v + 1e-9


def _premise_volume_path_b(vol: pd.Series, p_idx: int, remain: float) -> bool:
    if p_idx < 5:
        return False
    ma5v = float(vol.iloc[p_idx - 5 : p_idx].mean())
    if ma5v != ma5v or ma5v <= 0:
        return False
    return float(vol.iloc[p_idx]) <= ma5v * float(remain) + 1e-9


def _premise_dim_vol(vol: pd.Series, p_idx: int, trail: int, pct: float) -> bool:
    a = max(0, p_idx - int(trail))
    hist = vol.iloc[a:p_idx]
    if hist.empty or len(hist) < 10:
        return True
    q = float(np.percentile(hist.values, float(pct)))
    return float(vol.iloc[p_idx]) <= q + 1e-9


def _ma10_decelerating(ma10: pd.Series, idx: int, span: int) -> bool:
    if idx < 2 * int(span):
        return False
    late = float(ma10.iloc[idx] - ma10.iloc[idx - int(span)])
    early = float(ma10.iloc[idx - int(span)] - ma10.iloc[idx - 2 * int(span)])
    return late >= early - 1e-9


def _near_golden_cross(ma5: pd.Series, ma10: pd.Series, idx: int, max_gap: float) -> bool:
    m5 = float(ma5.iloc[idx])
    m10 = float(ma10.iloc[idx])
    if m10 <= 0 or m5 != m5 or m10 != m10:
        return False
    if m5 >= m10:
        return True
    gap = (m10 - m5) / m10
    return gap <= float(max_gap) + 1e-9


def _eval_premise_for_day(
    d: pd.DataFrame,
    p_idx: int,
    peak_idx: Optional[int],
    v_peak: float,
    cfg: dict,
) -> Tuple[bool, bool, bool, bool, bool]:
    vol = d["volume"]
    ma10 = d["ma10"]
    o, h, l, c = (
        float(d["open"].iloc[p_idx]),
        float(d["high"].iloc[p_idx]),
        float(d["low"].iloc[p_idx]),
        float(d["close"].iloc[p_idx]),
    )
    prev_c = float(d["close"].iloc[p_idx - 1]) if p_idx > 0 else float("nan")

    path_a = False
    if peak_idx is not None:
        path_a = _premise_volume_path_a(
            float(vol.iloc[p_idx]),
            v_peak,
            cfg["vol_path_a_min_ratio"],
            cfg["vol_path_a_max_ratio"],
        )
    path_b = _premise_volume_path_b(vol, p_idx, cfg["vol_path_b_ma5_remain"])
    vol_ok = path_a or path_b

    stall = _is_stall_candle(o, h, l, c, prev_c)
    m10v = float(ma10.iloc[p_idx])
    bias_ok = m10v == m10v and m10v > 0 and (c - m10v) / m10v >= float(cfg["bias_ma10_floor"]) - 1e-9
    dim_ok = _premise_dim_vol(
        vol,
        p_idx,
        cfg["dim_vol_trailing"],
        cfg["dim_vol_percentile"],
    )
    ok = bool(vol_ok and stall and bias_ok and dim_ok)
    return ok, path_a, path_b, stall, bias_ok


@dataclass(frozen=True)
class VolumeReboundSnapshot:
    symbol: str
    stock_name: str
    signal_date: str
    close: float
    ma5: float
    ma10: float
    vol: float
    vol_over_pre5mean: float
    rebound_pct: float
    upper_shadow_ratio: float
    premise_offset: int
    premise_path_a: bool
    premise_path_b: bool
    vol_strong_2x: bool
    ma10_slow: bool
    ma5_up: bool
    near_cross: bool
    rebound_yang: bool
    signal: bool
    diagnosis_zh: str


def _format_hit_diagnosis_zh(s: VolumeReboundSnapshot) -> str:
    """命中股票的简短中文诊断，供 CSV/终端阅读；未命中时返回空串。"""
    if not s.signal:
        return ""
    name = (s.stock_name or "").strip()
    who = f"{name}({s.symbol})" if name else s.symbol

    vol_bits: List[str] = []
    if s.premise_path_a:
        vol_bits.append("量能相对主升段参照高点落在约1/4～1/3")
    if s.premise_path_b:
        vol_bits.append("量能不高于近5日均量的四成（萎缩逾六成）")
    vol_premise = "、".join(vol_bits) if vol_bits else "量能前提满足"

    vr = s.vol_over_pre5mean
    vr_txt = f"{vr:.2f}倍" if vr == vr else "—"
    vol_day = (
        f"当日成交量为信号日前5日均量的{vr_txt}"
        + ("，达到「优选≥2倍」强度" if s.vol_strong_2x else "")
    )

    pos = "收于MA10上方" if s.close >= s.ma10 else "仍收在MA10下方"
    cross_txt = (
        "MA5已在MA10之上（金叉或延续多头）"
        if s.ma5 >= s.ma10
        else "MA5位于MA10下方但间距收窄，具备金叉预热形态"
    )

    shadow_txt = (
        "上影很短，未见放量长上影滞涨"
        if s.upper_shadow_ratio <= 0.08
        else "上影可控，收盘贴近当日高位"
    )

    return (
        f"{who} 于{s.signal_date}触发「下跌末端缩量企稳→放量长阳反弹」模型。"
        f"信号日前第{s.premise_offset}根K线满足前提：{vol_premise}，"
        f"并出现地量分位+十字星/锤子/小阴小阳类抛压衰竭形态，"
        f"且相对MA10的乖离未深跌逾阈值。"
        f"{vol_day}；实体涨幅约{s.rebound_pct:.2f}%，{shadow_txt}。"
        f"均线结构：MA10下跌速率放缓，MA5拐头向上；{cross_txt}；收盘{pos}（{s.close:.4f}，MA5={s.ma5:.4f}，MA10={s.ma10:.4f}）。"
        "以上为量价与均线规则下的技术摘要，不构成投资建议。"
    )


def _eval_volume_rebound_last(
    df: pd.DataFrame,
    cfg: dict,
) -> Optional[VolumeReboundSnapshot]:
    d = _prepare_ohlcv(df)
    if d is None:
        return None

    p10 = int(cfg["ma10_period"])
    p5 = int(cfg["ma5_period"])
    sig_idx = len(d) - 1
    need_left = max(
        int(cfg["peak_lookback_bars"]) + 5,
        int(cfg["dim_vol_trailing"]) + int(cfg["premise_max_offset"]) + 2,
        p10 + int(cfg["premise_max_offset"]) + 10,
    )
    if sig_idx < need_left:
        return None

    d["ma5"] = d["close"].rolling(p5, min_periods=p5).mean()
    d["ma10"] = d["close"].rolling(p10, min_periods=p10).mean()

    peak_idx = _find_uptrend_peak_idx(d["high"], sig_idx, int(cfg["peak_lookback_bars"]))
    v_peak = (
        _volume_peak_before_anchor(d["volume"], peak_idx, int(cfg["peak_left_volume_window"]))
        if peak_idx is not None
        else float("nan")
    )

    w = int(cfg["premise_max_offset"])
    premise_ok = False
    best_off = 0
    pa = pb = False
    for off in range(1, w + 1):
        p_idx = sig_idx - off
        if p_idx < 1:
            break
        ok, path_a, path_b, _, _ = _eval_premise_for_day(d, p_idx, peak_idx, v_peak, cfg)
        if ok:
            premise_ok = True
            best_off = off
            pa = path_a
            pb = path_b
            break

    vol = d["volume"]
    mean5 = float(vol.iloc[sig_idx - 5 : sig_idx].mean())
    v_sig = float(vol.iloc[sig_idx])
    vol_ratio = v_sig / mean5 if mean5 > 0 and mean5 == mean5 else float("nan")

    prev_c = float(d["close"].iloc[sig_idx - 1])
    o = float(d["open"].iloc[sig_idx])
    h = float(d["high"].iloc[sig_idx])
    l = float(d["low"].iloc[sig_idx])
    c = float(d["close"].iloc[sig_idx])
    reb_pct = (c - prev_c) / prev_c if prev_c > 0 else float("nan")
    rng = h - l
    up_ratio = (h - c) / rng if rng > 1e-12 else 0.0

    mult = float(cfg["rebound_vol_mult"])
    mult2 = float(cfg["rebound_vol_mult_strong"])
    vol_ok = mean5 > 0 and v_sig >= mult * mean5
    vol_strong = mean5 > 0 and v_sig >= mult2 * mean5
    yang = c > o
    pct_ok = reb_pct == reb_pct and reb_pct >= float(cfg["rebound_min_pct"])
    shadow_ok = up_ratio <= float(cfg["upper_shadow_max_ratio"]) + 1e-9
    rebound_ok = vol_ok and yang and pct_ok and shadow_ok

    ma5s, ma10s = d["ma5"], d["ma10"]
    ma5_up = float(ma5s.iloc[sig_idx]) > float(ma5s.iloc[sig_idx - 1])
    ma10_slow = _ma10_decelerating(ma10s, sig_idx, int(cfg["ma10_slope_compare_bars"]))
    near_x = _near_golden_cross(ma5s, ma10s, sig_idx, float(cfg["near_cross_max_gap_pct"]))

    structure_ok = ma10_slow and ma5_up and near_x

    sig = bool(premise_ok and rebound_ok and structure_ok)

    sym = str(d["symbol"].iloc[sig_idx] if "symbol" in d.columns else "").strip()
    nm = str(d["stock_name"].iloc[sig_idx] if "stock_name" in d.columns else "").strip()
    dt = d["date"].iloc[sig_idx]
    try:
        ds = pd.Timestamp(dt).strftime("%Y-%m-%d")
    except Exception:
        ds = str(dt)[:10]

    snap = VolumeReboundSnapshot(
        symbol=sym,
        stock_name=nm,
        signal_date=ds,
        close=round(c, 4),
        ma5=round(float(ma5s.iloc[sig_idx]), 4),
        ma10=round(float(ma10s.iloc[sig_idx]), 4),
        vol=round(v_sig, 2),
        vol_over_pre5mean=round(vol_ratio, 4) if vol_ratio == vol_ratio else float("nan"),
        rebound_pct=round(reb_pct * 100.0, 4) if reb_pct == reb_pct else float("nan"),
        upper_shadow_ratio=round(up_ratio, 4),
        premise_offset=best_off if premise_ok else 0,
        premise_path_a=pa,
        premise_path_b=pb,
        vol_strong_2x=vol_strong,
        ma10_slow=ma10_slow,
        ma5_up=ma5_up,
        near_cross=near_x,
        rebound_yang=yang,
        signal=sig,
        diagnosis_zh="",
    )
    if sig:
        snap = replace(snap, diagnosis_zh=_format_hit_diagnosis_zh(snap))
    return snap


def scan_volume_rebound(
    symbols: List[str],
    *,
    end_date: str,
    history_calendar_days: int,
    cfg: dict,
) -> tuple[List[VolumeReboundSnapshot], List[str], List[VolumeReboundSnapshot]]:
    end_dt = pd.to_datetime(end_date).to_pydatetime()
    start_dt = _calendar_start(end_dt, history_calendar_days)
    start_s = start_dt.strftime("%Y-%m-%d")
    end_s = pd.Timestamp(end_date).strftime("%Y-%m-%d")

    hits: List[VolumeReboundSnapshot] = []
    evaluated: List[VolumeReboundSnapshot] = []
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
        snap = _eval_volume_rebound_last(df, cfg)
        if snap is None:
            skipped.append(f"{sym}(数据不足或无volume)")
            continue
        evaluated.append(snap)
        if snap.signal:
            hits.append(snap)

    return hits, skipped, evaluated


def snapshots_to_dataframe(snaps: List[VolumeReboundSnapshot]) -> pd.DataFrame:
    rows = []
    for s in snaps:
        rows.append(
            {
                "symbol": s.symbol,
                "stock_name": s.stock_name,
                "signal_date": s.signal_date,
                "diagnosis_zh": s.diagnosis_zh,
                "close": s.close,
                "ma5": s.ma5,
                "ma10": s.ma10,
                "volume": s.vol,
                "vol_over_pre5mean": s.vol_over_pre5mean,
                "rebound_pct": s.rebound_pct,
                "upper_shadow_ratio": s.upper_shadow_ratio,
                "premise_offset": s.premise_offset,
                "premise_path_a": s.premise_path_a,
                "premise_path_b": s.premise_path_b,
                "vol_strong_2x": s.vol_strong_2x,
                "ma10_slow": s.ma10_slow,
                "ma5_up": s.ma5_up,
                "near_cross": s.near_cross,
                "signal": s.signal,
            }
        )
    return pd.DataFrame(rows)


def _failed_rebound_reasons(s: VolumeReboundSnapshot, cfg: dict) -> List[str]:
    """未命中时列出未满足的子条件（与 _eval_volume_rebound_last 判定一致）。"""
    failed: List[str] = []
    if s.premise_offset <= 0:
        failed.append("前1~3日无地量+企稳K+乖离等前提组合")

    mult = float(cfg["rebound_vol_mult"])
    vr = s.vol_over_pre5mean
    if vr != vr or vr < mult:
        failed.append(f"反弹日量未达{mult}×近5均")
    if not s.rebound_yang:
        failed.append("反弹日非阳线")
    min_pct = float(cfg["rebound_min_pct"]) * 100.0
    rp = s.rebound_pct
    if rp != rp or rp < min_pct:
        failed.append(f"涨幅不足{min_pct:.2f}%")
    max_sh = float(cfg["upper_shadow_max_ratio"])
    if s.upper_shadow_ratio > max_sh + 1e-9:
        failed.append("上影偏长")
    if not s.ma10_slow:
        failed.append("MA10下跌未放缓")
    if not s.ma5_up:
        failed.append("MA5未拐头向上")
    if not s.near_cross:
        failed.append("MA5与MA10未近金叉/未金叉")
    return failed


def _symbol_brief_line(s: VolumeReboundSnapshot, cfg: dict) -> str:
    """终端默认：单行结论（命中/未中 + 关键量价 + 未中原因）。"""
    label = f"{s.stock_name}({s.symbol})" if s.stock_name else s.symbol
    if s.signal:
        return (
            f"  [命中] {label}  {s.signal_date}  close={s.close:.4f}  "
            f"vol/5d={s.vol_over_pre5mean:.2f}x  +{s.rebound_pct:.2f}%  2x={s.vol_strong_2x}"
        )
    reason = "；".join(_failed_rebound_reasons(s, cfg)) or "未满足模型条件"
    return f"  [未中] {label}  {s.signal_date}  {reason}"


def _symbol_diagnosis_lines(s: VolumeReboundSnapshot) -> List[str]:
    label = f"{s.stock_name}({s.symbol})" if s.stock_name else s.symbol
    lines: List[str] = [f"—— {label}  截止 {s.signal_date} ——"]

    pos_ma = "站上MA10" if s.close >= s.ma10 else "仍在MA10下方"
    lines.append(
        f"  收盘 {s.close:.4f}  MA5={s.ma5:.4f}  MA10={s.ma10:.4f}  {pos_ma}"
    )
    lines.append(
        f"  反弹日: 量比前5均 {s.vol_over_pre5mean:.2f}x  涨幅 {s.rebound_pct:.2f}%  "
        f"上影占比 {s.upper_shadow_ratio:.2f}"
    )
    if s.premise_offset > 0:
        pa = "是" if s.premise_path_a else "否"
        pb = "是" if s.premise_path_b else "否"
        lines.append(
            f"  前提: 前{s.premise_offset}日满足 — 路径A(1/4~1/3峰量)={pa}  路径B(≤40%近5均)={pb}"
        )
    else:
        lines.append("  前提: 前1~3日内无一日满足地量+企稳K+乖离≥-15% 等组合")

    lines.append(
        f"  结构: MA10放缓={s.ma10_slow}  MA5拐头={s.ma5_up}  近金叉/已叉={s.near_cross}  量≥2x均={s.vol_strong_2x}"
    )

    if s.signal:
        lines.append("  **结论: 触发放量反弹模型。**")
        if s.diagnosis_zh:
            lines.append("  【摘要】" + s.diagnosis_zh)
    else:
        lines.append("  **结论: 未触发。**")
    lines.append("")
    return lines


def _merge_cfg(base: dict, overrides: dict) -> dict:
    out = dict(base)
    out.update({k: v for k, v in overrides.items() if v is not None})
    return out


def main() -> None:
    base_cfg = dict(VOLUME_REBOUND_CONFIG)
    parser = argparse.ArgumentParser(
        description="扫描：末端缩量企稳 + 放量长阳 + MA10 放缓 / MA5 拐头近金叉（允许突破 MA10）"
    )
    parser.add_argument("--pool", default=DEFAULT_STOCKS_POOL_TXT, help="股票池 txt")
    parser.add_argument("--symbols", default="", help="逗号分隔代码；非空则忽略 --pool")
    parser.add_argument("--diagnose", action="store_true", help="追加完整逐股诊断块")
    parser.add_argument("--end-date", default=datetime.now().strftime("%Y-%m-%d"), help="截止日（含）")
    parser.add_argument(
        "--days",
        type=int,
        default=int(base_cfg["history_calendar_days"]),
        help="向前拉取自然日长度",
    )
    parser.add_argument("--peak-lookback", type=int, default=None, help="主升高点搜索宽度（默认配置）")
    parser.add_argument(
        "--peak-vol-window",
        type=int,
        default=None,
        help="高点锚点左侧取量能参照的 K 根数（默认 25，对应约 20~30）",
    )
    parser.add_argument("--premise-window", type=int, default=None, help="前提在信号日前最多几根内（默认 3）")
    parser.add_argument("--rebound-mult", type=float, default=None, help="反弹量比近5均倍数下限（默认 1.5）")
    parser.add_argument("--rebound-pct", type=float, default=None, help="反弹涨幅下限，如 0.03")
    parser.add_argument("--upper-shadow-max", type=float, default=None, help="上影占振幅上限（默认 0.15）")
    parser.add_argument("--out-csv", default=DEFAULT_SCAN_OUT_CSV, help="命中 CSV 路径")
    args = parser.parse_args()

    cfg = _merge_cfg(
        base_cfg,
        {
            "history_calendar_days": int(args.days),
            "peak_lookback_bars": args.peak_lookback,
            "peak_left_volume_window": args.peak_vol_window,
            "premise_max_offset": args.premise_window,
            "rebound_vol_mult": args.rebound_mult,
            "rebound_min_pct": args.rebound_pct,
            "upper_shadow_max_ratio": args.upper_shadow_max,
        },
    )

    symbols_from_cli = bool(str(args.symbols).strip())
    if symbols_from_cli:
        syms = []
        for x in str(args.symbols).split(","):
            tok = x.strip()
            if not tok:
                continue
            sym = "".join(filter(str.isdigit, tok)).zfill(6)
            if len(sym) == 6:
                syms.append(sym)
        syms = list(dict.fromkeys(syms))
    else:
        pool_path = os.path.abspath(str(args.pool))
        syms = load_stocks_pool_txt(pool_path)
        if not syms:
            print(f"股票池为空或文件不存在: {pool_path}")
            sys.exit(2)

    hits, skipped, evaluated = scan_volume_rebound(
        syms,
        end_date=str(args.end_date),
        history_calendar_days=int(cfg["history_calendar_days"]),
        cfg=cfg,
    )

    out_df = snapshots_to_dataframe(hits)
    out_path = os.path.abspath(args.out_csv)
    ddir = os.path.dirname(out_path)
    if ddir:
        os.makedirs(ddir, exist_ok=True)
    out_df.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(
        "规则: 前1~3日前提(路径A峰量1/4~1/3 或 路径B≤40%近5均; 地量分位; 企稳K; 乖离≥-15%) + "
        f"反弹日量≥{cfg['rebound_vol_mult']}×前5均、涨幅≥{cfg['rebound_min_pct']:.2%}、短上影阳线 + "
        "MA10放缓、MA5拐头、近/已金叉。"
    )
    print(
        f"支撑反弹扫描 | 截止 {args.end_date} | 扫描 {len(syms)} 只 | 命中 {len(hits)} 只"
    )
    if not symbols_from_cli:
        print(f"股票池: {pool_path}")
    print(f"已写入: {out_path}")

    print("=" * 72)
    print("【扫描结果】")
    if hits:
        for s in sorted(hits, key=lambda x: x.symbol):
            print(_symbol_brief_line(s, cfg))
            if s.diagnosis_zh:
                print(f"    诊断: {s.diagnosis_zh}")
    else:
        print("  （无命中）")

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

    if bool(args.diagnose) and evaluated:
        print("=" * 72)
        print("【逐股诊断】（--diagnose，明细仅供参考）")
        print("=" * 72)
        for snap in sorted(evaluated, key=lambda x: x.symbol):
            for line in _symbol_diagnosis_lines(snap):
                print(line)


if __name__ == "__main__":
    main()

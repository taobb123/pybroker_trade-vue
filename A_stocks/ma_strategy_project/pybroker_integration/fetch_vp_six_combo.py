#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
量价六组合分类（Phase2 五维共振）——接在「沿 MA5 多头扫描」之后。

输入：默认取 ma5_trend_scan.csv 中 in_trend / signal 为真的命中股；
也可通过 --symbols 或 --pool 自定义列表覆盖。
输出：每票一个主标签，对应 docs/量价五维共振模型.md 第十二节六种组合：

  1 底部+缩量
  2 底部+放量上涨
  3 上涨途中+缩量整理
  4 上涨途中+放量突破
  5 高位+放量滞涨
  6 下跌途中+放量下跌

五维：股价位置 + 成交量（单日量比）+ 换手率 + 筹码结构 + 趋势（MA5 链 / 突破）。
Phase1 位置×量能定主标签；Phase2 换手+筹码修正匹配度、有限覆写标签，并给出共振分。

用法（在 ma_strategy_project 目录下）：
    python pybroker_integration/fetch_vp_six_combo.py
    python pybroker_integration/fetch_vp_six_combo.py --ma5-csv pybroker_integration/ma5_trend_scan.csv
    python pybroker_integration/fetch_vp_six_combo.py --symbols 002821,600519
    python pybroker_integration/fetch_vp_six_combo.py --diagnose
    python pybroker_integration/fetch_vp_six_combo.py --phase1-only
    python pybroker_integration/fetch_vp_six_combo.py --skip-chips

股票列表优先级：--symbols > 非空 --pool 自定义列表 > MA5 扫描命中股。

下游形态建仓：按 watch_combo_ids（默认 4、6）滚动合并 vp_combo_watch_{id}.csv
（最多 6 个交易日、同票只留最新）与 config/fetch_pattern_entry_symbols*.txt；
主表仍为当日截面，含 platform/breakout 锚点字段。
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
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

from backtest_sy_002028_threshold import (  # noqa: E402
    fetch_ohlc_qfq,
    fetch_stock_name,
    six_digit_to_ts_code,
)
from trend_pullback_chips import (  # noqa: E402
    CHIP_CONFIG,
    ChipAnalysis,
    fetch_chip_analysis_for_symbol,
    get_tushare_pro,
)

DEFAULT_MA5_CSV = os.path.join(_SCRIPT_DIR, "ma5_trend_scan.csv")
DEFAULT_OUT_CSV = os.path.join(_SCRIPT_DIR, "vp_six_combo_scan.csv")
DEFAULT_SYMBOLS_POOL_TXT = os.path.join(
    _SCRIPT_DIR, "config", "fetch_vp_six_combo_symbols.txt"
)
DEFAULT_PATTERN_ENTRY_SYMBOLS_TXT = os.path.join(
    _SCRIPT_DIR, "config", "fetch_pattern_entry_symbols.txt"
)

VP_SIX_CONFIG = {
    "history_calendar_days": 220,
    "min_bars": 65,
    "range_lookback_bars": 60,
    "vol_ma_bars": 20,
    "breakout_lookback_bars": 20,
    "vol_amplify_ratio": 1.5,
    "vol_shrink_ratio": 0.7,
    "stagnant_abs_pct": 1.0,
    "bottom_range_pct": 0.30,
    "high_range_pct": 0.80,
    "downtrend_ma20_lookback": 5,
    # Phase2 换手
    "turnover_ma_bars": 20,
    "turnover_high_pct": 5.0,
    "turnover_low_pct": 2.0,
    "turnover_amplify_ratio": 1.3,
    "turnover_shrink_ratio": 0.7,
    # Phase2 共振
    "resonance_pass_score": 60.0,
    # 下游形态建仓：按 combo 导出观察列表（4=上涨放量突破，6=下跌放量）
    "watch_combo_ids": [4, 6],
    # 观察池滚动：最多保留若干交易日；同代码只留最新 signal_date
    "watch_pool_max_trade_days": 6,
}

COMBO_META = {
    1: {
        "combo_name": "底部缩量",
        "meaning": "抛压减轻",
        "action_hint": "耐心观察，等待放量确认",
    },
    2: {
        "combo_name": "底部放量上涨",
        "meaning": "主力吸筹、启动概率增加",
        "action_hint": "可重点关注，等待回踩确认或突破跟进",
    },
    3: {
        "combo_name": "上涨缩量整理",
        "meaning": "惜售、趋势健康",
        "action_hint": "持股或寻找加仓机会",
    },
    4: {
        "combo_name": "上涨放量突破",
        "meaning": "趋势增强",
        "action_hint": "可顺势参与，但避免追高过度",
    },
    5: {
        "combo_name": "高位放量滞涨",
        "meaning": "分歧加大、可能派发",
        "action_hint": "减仓或提高警惕",
    },
    6: {
        "combo_name": "下跌放量",
        "meaning": "恐慌释放、风险较高",
        "action_hint": "一般不急于抄底，等待止跌信号",
    },
}

_CHIP_CONCENTRATED = {
    "low_single_peak",
    "single_peak",
    "multi_peak_stable",
    "multi_peak",
}
_CHIP_DISPERSED = {"scattered", "high_single_empty"}


@dataclass(frozen=True)
class VpSixSnapshot:
    symbol: str
    stock_name: str
    signal_date: str
    close: float
    prev_close: float
    pct_change: float
    ma20: float
    ma60: float
    ma20_prev: float
    range_low: float
    range_high: float
    range_pct: float
    close_vs_ma20_pct: float
    close_vs_ma60_pct: float
    volume: float
    vol_ma20: float
    vol_ratio: float
    vol_amplify: bool
    vol_shrink: bool
    price_up: bool
    price_down: bool
    is_breakout: bool
    is_stagnant: bool
    position_stage: str
    combo_id: int
    combo_name: str
    meaning: str
    action_hint: str
    match_exact: bool
    ma5_score_total: Optional[float]
    # Phase2
    turnover_today_pct: float
    turnover_ma20_pct: float
    turnover_ratio: float
    turnover_high: bool
    turnover_low: bool
    turnover_rising: bool
    chip_pattern: str
    chip_pattern_label: str
    chip_concentration: float
    chip_peak_position: float
    chip_bottom_stable: bool
    chip_bottom_empty: bool
    chip_state: str
    chip_available: bool
    resonance_score: float
    score_position: float
    score_volume: float
    score_turnover: float
    score_chip: float
    score_trend: float
    resonance_ok: bool
    resonance_note: str
    phase: int
    # 突破锚点（供形态建仓状态机）
    platform_level: float
    breakout_high: float
    breakout_close: float
    breakout_vol: float
    breakout_vol_ratio: float


def _calendar_start(end_dt: datetime, history_calendar_days: int) -> datetime:
    return end_dt - timedelta(days=max(30, int(history_calendar_days)))


def _norm_symbol(raw) -> str:
    return "".join(filter(str.isdigit, str(raw))).zfill(6)


def _truthy(val) -> bool:
    if isinstance(val, bool):
        return val
    if val is None or (isinstance(val, float) and val != val):
        return False
    s = str(val).strip().lower()
    return s in {"1", "true", "t", "yes", "y", "是"}


def _nan() -> float:
    return float("nan")


def _finite(x: float) -> bool:
    return x == x


def _try_tushare_pro():
    try:
        return get_tushare_pro()
    except Exception:
        return None


def _parse_symbols_text(raw: str) -> List[str]:
    """从粘贴文本解析 6 位代码（逗号/空白/换行分隔，去重保序）。"""
    out: List[str] = []
    seen: set[str] = set()
    for tok in str(raw or "").replace(",", " ").replace(";", " ").split():
        sym = _norm_symbol(tok)
        if len(sym) != 6 or not sym.isdigit():
            continue
        if sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


def load_symbols_pool_txt(path: str) -> List[str]:
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
    # 去掉整行注释后再解析
    lines: List[str] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        lines.append(s)
    return _parse_symbols_text("\n".join(lines))


def hits_from_symbols(symbols: List[str], *, source_note: str) -> Tuple[pd.DataFrame, List[str]]:
    rows = [{"symbol": _norm_symbol(s), "stock_name": ""} for s in symbols if _norm_symbol(s)]
    if not rows:
        return pd.DataFrame(columns=["symbol", "stock_name"]), [f"{source_note} → 0 只"]
    hits = pd.DataFrame(rows)
    hits["symbol"] = hits["symbol"].map(_norm_symbol)
    hits = hits.drop_duplicates(subset=["symbol"], keep="first").reset_index(drop=True)
    return hits, [f"{source_note} → {len(hits)} 只"]


def load_ma5_hits(ma5_csv: str) -> Tuple[pd.DataFrame, List[str]]:
    path = os.path.abspath(ma5_csv)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"找不到 MA5 扫描表: {path}")

    df = pd.read_csv(path, encoding="utf-8-sig")
    if df.empty:
        return df, [f"MA5 扫描表为空: {path}"]

    if "symbol" not in df.columns:
        raise ValueError(f"MA5 扫描表缺少 symbol 列: {path}")

    df = df.copy()
    df["symbol"] = df["symbol"].map(_norm_symbol)

    flag_col = None
    for c in ("in_trend", "signal"):
        if c in df.columns:
            flag_col = c
            break
    if flag_col is None:
        hits = df
        notes = [f"未找到 in_trend/signal 列，整表 {len(hits)} 行视为命中"]
    else:
        mask = df[flag_col].map(_truthy)
        hits = df.loc[mask].copy()
        notes = [f"自 {path} 筛选 {flag_col}=True → {len(hits)} 只"]

    hits = hits.drop_duplicates(subset=["symbol"], keep="first").reset_index(drop=True)
    return hits, notes


def resolve_hits(
    *,
    symbols_arg: str,
    pool_path: str,
    ma5_csv: str,
) -> Tuple[pd.DataFrame, List[str]]:
    """优先自定义列表，否则回退 MA5 链式命中股。"""
    cli_syms = _parse_symbols_text(symbols_arg)
    if cli_syms:
        return hits_from_symbols(cli_syms, source_note="自定义 --symbols")

    pool = str(pool_path or "").strip()
    if pool:
        pool_syms = load_symbols_pool_txt(pool)
        if pool_syms:
            return hits_from_symbols(
                pool_syms, source_note=f"自定义列表 {os.path.abspath(pool)}"
            )

    return load_ma5_hits(ma5_csv)


def fetch_bars_with_turnover(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """前复权 OHLCV + Tushare daily_basic.turnover_rate。"""
    ohlc = fetch_ohlc_qfq(symbol, start_date, end_date)
    out = ohlc.copy()
    out["turnover_rate"] = _nan()

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
        basic["date"] = pd.to_datetime(
            basic["trade_date"].astype(str), format="%Y%m%d", errors="coerce"
        )
        basic["turnover_rate"] = pd.to_numeric(basic["turnover_rate"], errors="coerce")
        out = out.drop(columns=["turnover_rate"], errors="ignore")
        out = out.merge(basic[["date", "turnover_rate"]], on="date", how="left")

    return out.sort_values("date").reset_index(drop=True)


def _ensure_volume_col(d: pd.DataFrame) -> pd.DataFrame:
    out = d.copy()
    if "volume" not in out.columns:
        for alt in ("vol", "amount"):
            if alt in out.columns:
                out["volume"] = out[alt]
                break
    if "volume" not in out.columns:
        raise ValueError("OHLC 缺少 volume 列")
    out["volume"] = pd.to_numeric(out["volume"], errors="coerce")
    return out


def _classify_position(
    *,
    close: float,
    ma20: float,
    ma60: float,
    ma20_prev_n: float,
    range_pct: float,
    bottom_range_pct: float,
    high_range_pct: float,
) -> str:
    ma20_falling = ma20 < ma20_prev_n

    if close < ma20 and ma20_falling:
        return "downtrend"
    if range_pct >= high_range_pct and close >= ma20:
        return "high"
    if range_pct <= bottom_range_pct and close <= ma60 * 1.08:
        return "bottom"
    if close >= ma20 and (ma20 >= ma20_prev_n or close >= ma60):
        return "uptrend"

    if range_pct >= high_range_pct:
        return "high"
    if range_pct <= bottom_range_pct:
        return "bottom"
    if close < ma20 and ma20_falling:
        return "downtrend"
    return "uptrend"


def _assign_combo_phase1(
    *,
    position_stage: str,
    vol_amplify: bool,
    vol_shrink: bool,
    price_up: bool,
    price_down: bool,
    is_breakout: bool,
    is_stagnant: bool,
) -> Tuple[int, bool]:
    if position_stage == "downtrend":
        return 6, bool(vol_amplify and price_down)
    if position_stage == "high":
        return 5, bool(vol_amplify and (is_stagnant or not price_up))
    if position_stage == "bottom":
        if vol_amplify and price_up:
            return 2, True
        return 1, bool(vol_shrink)
    if vol_amplify and (is_breakout or price_up):
        return 4, True
    return 3, bool(vol_shrink and not price_down)


def _eval_turnover(
    d: pd.DataFrame,
    *,
    ma_bars: int,
    high_pct: float,
    low_pct: float,
    amplify_ratio: float,
    shrink_ratio: float,
) -> Tuple[float, float, float, bool, bool, bool]:
    """返回 today, ma20, ratio, high, low, rising。缺数据时 ratio=nan。"""
    if "turnover_rate" not in d.columns:
        return _nan(), _nan(), _nan(), False, False, False

    tr = pd.to_numeric(d["turnover_rate"], errors="coerce")
    today = float(tr.iloc[-1]) if len(tr) else _nan()
    vb = max(5, int(ma_bars))
    prior = tr.iloc[-(vb + 1) : -1]
    ma20 = float(prior.mean()) if len(prior) and not prior.isna().all() else _nan()

    if not _finite(today):
        return today, ma20, _nan(), False, False, False

    high = today >= float(high_pct)
    low = today <= float(low_pct)
    if _finite(ma20) and ma20 > 0:
        ratio = today / ma20
        rising = ratio >= float(amplify_ratio)
        # shrink used only for scoring via ratio
        _ = ratio <= float(shrink_ratio)
    else:
        ratio = _nan()
        rising = False
    return today, ma20, ratio, high, low, rising


def _chip_state(chip: Optional[ChipAnalysis]) -> str:
    if chip is None:
        return "unknown"
    if chip.pattern in _CHIP_DISPERSED or chip.bottom_empty:
        return "dispersed"
    if chip.pattern in _CHIP_CONCENTRATED or chip.bottom_stable:
        return "concentrated"
    if _finite(chip.concentration) and chip.concentration >= 0.12:
        return "concentrated"
    if _finite(chip.concentration) and chip.concentration < 0.06:
        return "dispersed"
    return "unknown"


def _refine_combo_phase2(
    *,
    combo_id: int,
    match_exact: bool,
    position_stage: str,
    vol_amplify: bool,
    vol_shrink: bool,
    price_up: bool,
    price_down: bool,
    is_breakout: bool,
    is_stagnant: bool,
    turnover_high: bool,
    turnover_low: bool,
    chip: Optional[ChipAnalysis],
) -> Tuple[int, bool, str]:
    """
    有限覆写主标签；返回 (combo_id, match_exact, note)。
    """
    notes: List[str] = []
    cid = combo_id
    exact = match_exact

    # 放量但低换手：文档「意义有限」→ 降级精确匹配
    if vol_amplify and turnover_low:
        exact = False
        notes.append("放量+低换手，筹码交换不充分")
    if vol_amplify and turnover_high:
        if cid in (2, 4, 5, 6):
            exact = True
            notes.append("放量+高换手，换手充分")
    if vol_shrink and turnover_low and cid in (1, 3):
        exact = True
        notes.append("缩量+低换手，惜售一致")

    if chip is not None:
        if chip.pattern == "high_single_empty" or (
            chip.volume_stagnation and position_stage == "high"
        ):
            if cid != 5:
                notes.append(f"筹码覆写→高位派发({chip.pattern_label})")
            cid = 5
            exact = bool(vol_amplify or chip.volume_stagnation or turnover_high)
        elif chip.pattern == "scattered" and position_stage in ("high", "uptrend"):
            if position_stage == "high":
                cid = 5
                exact = False
                notes.append("多峰分散，高位警惕")
        elif chip.main_rise_breakout or (
            chip.pattern == "low_single_peak" and vol_amplify and price_up
        ):
            if position_stage == "bottom" or (
                position_stage == "uptrend" and chip.peak_position <= 0.40
            ):
                cid = 2
                exact = bool(turnover_high or not turnover_low)
                notes.append("低位单峰+放量，偏吸筹启动")
            elif position_stage == "uptrend" and (is_breakout or chip.volume_breakout):
                cid = 4
                exact = True
                notes.append("筹码支持放量突破")
        elif (
            chip.pattern in ("multi_peak_stable", "low_single_peak")
            and vol_shrink
            and position_stage == "uptrend"
            and not price_down
        ):
            cid = 3
            exact = True
            notes.append("底仓稳+缩量，健康整理")
        elif chip.bottom_empty and price_down and vol_amplify:
            cid = 6 if position_stage == "downtrend" else 5
            exact = True
            notes.append("底仓流失+放量下跌风险")

    # 下跌途中仍以位置优先
    if position_stage == "downtrend" and vol_amplify and price_down:
        cid = 6
        exact = True

    return cid, exact, "；".join(notes)


def _score_resonance(
    *,
    combo_id: int,
    position_stage: str,
    vol_amplify: bool,
    vol_shrink: bool,
    price_up: bool,
    is_breakout: bool,
    turnover_high: bool,
    turnover_low: bool,
    turnover_rising: bool,
    turnover_ratio: float,
    chip: Optional[ChipAnalysis],
    chip_state: str,
    ma5_score_total: Optional[float],
) -> Tuple[float, float, float, float, float, float, str]:
    """五维各 20 分，合计 100。"""
    notes: List[str] = []

    # 1 位置
    expect_pos = {
        1: "bottom",
        2: "bottom",
        3: "uptrend",
        4: "uptrend",
        5: "high",
        6: "downtrend",
    }[combo_id]
    if position_stage == expect_pos:
        s_pos = 20.0
    elif (combo_id in (1, 2) and position_stage == "uptrend") or (
        combo_id in (3, 4) and position_stage in ("bottom", "high")
    ):
        s_pos = 10.0
        notes.append("位置与组合部分偏离")
    else:
        s_pos = 4.0
        notes.append("位置与组合不一致")

    # 2 成交量
    want_amp = combo_id in (2, 4, 5, 6)
    want_shr = combo_id in (1, 3)
    if want_amp and vol_amplify:
        s_vol = 20.0
    elif want_shr and vol_shrink:
        s_vol = 20.0
    elif want_amp and not vol_shrink:
        s_vol = 10.0
    elif want_shr and not vol_amplify:
        s_vol = 10.0
    else:
        s_vol = 4.0
        notes.append("量能与组合方向相反")

    # 3 换手
    if not _finite(turnover_ratio) and not turnover_high and not turnover_low:
        s_turn = 8.0
        notes.append("换手数据缺失")
    elif want_amp:
        if turnover_high or turnover_rising:
            s_turn = 20.0
        elif turnover_low:
            s_turn = 4.0
            notes.append("放量组合但换手偏低")
        else:
            s_turn = 12.0
    else:  # shrink combos
        if turnover_low or (
            _finite(turnover_ratio) and turnover_ratio <= 0.7
        ):
            s_turn = 20.0
        elif turnover_high:
            s_turn = 6.0
            notes.append("缩量组合但换手偏高")
        else:
            s_turn = 12.0

    # 4 筹码
    if chip is None or chip_state == "unknown":
        s_chip = 8.0
        notes.append("筹码数据缺失")
    else:
        want_conc = combo_id in (1, 2, 3, 4)
        want_disp = combo_id in (5, 6)
        if want_conc and chip_state == "concentrated":
            s_chip = 20.0
            if chip.bottom_stable:
                s_chip = 20.0
        elif want_disp and chip_state == "dispersed":
            s_chip = 20.0
        elif want_conc and chip.pattern == "low_single_peak":
            s_chip = 20.0
        elif want_disp and chip.pattern in _CHIP_DISPERSED:
            s_chip = 20.0
        elif want_conc and chip_state == "dispersed":
            s_chip = 4.0
            notes.append("吸筹/持股组合但筹码发散")
        elif want_disp and chip_state == "concentrated":
            s_chip = 8.0
            notes.append("风险组合但筹码仍集中")
        else:
            s_chip = 10.0

        if combo_id == 5 and chip.volume_stagnation:
            s_chip = min(20.0, s_chip + 4.0)
        if combo_id == 2 and chip.main_rise_breakout:
            s_chip = 20.0

    # 5 趋势（MA5 链已通过）
    s_trend = 12.0
    if ma5_score_total is not None and _finite(float(ma5_score_total)):
        s_trend = 10.0 + min(6.0, float(ma5_score_total) / 100.0 * 6.0)
    if is_breakout and combo_id in (2, 4):
        s_trend = min(20.0, s_trend + 4.0)
    if price_up and combo_id in (2, 3, 4):
        s_trend = min(20.0, s_trend + 2.0)
    if combo_id in (5, 6) and (not price_up):
        s_trend = min(20.0, s_trend + 2.0)

    total = round(s_pos + s_vol + s_turn + s_chip + s_trend, 2)
    return (
        total,
        round(s_pos, 2),
        round(s_vol, 2),
        round(s_turn, 2),
        round(s_chip, 2),
        round(s_trend, 2),
        "；".join(notes),
    )


def evaluate_vp_six(
    df: pd.DataFrame,
    *,
    symbol: str,
    stock_name: str,
    ma5_score_total: Optional[float],
    range_lookback_bars: int,
    vol_ma_bars: int,
    breakout_lookback_bars: int,
    vol_amplify_ratio: float,
    vol_shrink_ratio: float,
    stagnant_abs_pct: float,
    bottom_range_pct: float,
    high_range_pct: float,
    downtrend_ma20_lookback: int,
    min_bars: int,
    turnover_ma_bars: int,
    turnover_high_pct: float,
    turnover_low_pct: float,
    turnover_amplify_ratio: float,
    turnover_shrink_ratio: float,
    resonance_pass_score: float,
    chip: Optional[ChipAnalysis],
    enable_phase2: bool,
) -> Optional[VpSixSnapshot]:
    need = max(int(min_bars), 60 + 2, int(range_lookback_bars) + 1, int(vol_ma_bars) + 2)
    if df is None or len(df) < need:
        return None

    d = df.sort_values("date").reset_index(drop=True)
    d = _ensure_volume_col(d)
    d["close"] = pd.to_numeric(d["close"], errors="coerce")
    d["high"] = pd.to_numeric(d["high"], errors="coerce")
    d["low"] = pd.to_numeric(d["low"], errors="coerce")

    d["ma20"] = d["close"].rolling(20, min_periods=20).mean()
    d["ma60"] = d["close"].rolling(60, min_periods=60).mean()

    last = d.iloc[-1]
    prev = d.iloc[-2]
    lb_ma = max(1, int(downtrend_ma20_lookback))
    ma20_prev_n = float(d.iloc[-1 - lb_ma]["ma20"]) if len(d) > lb_ma else float(prev["ma20"])

    c1 = float(last["close"])
    c0 = float(prev["close"])
    m20 = float(last["ma20"])
    m60 = float(last["ma60"])
    if not all(_finite(x) for x in (c1, c0, m20, m60, ma20_prev_n)):
        return None

    rb = max(5, int(range_lookback_bars))
    seg = d.iloc[-rb:]
    range_low = float(seg["low"].min())
    range_high = float(seg["high"].max())
    span = range_high - range_low
    range_pct = float((c1 - range_low) / span) if span > 1e-12 else 0.5
    range_pct = max(0.0, min(1.0, range_pct))

    vb = max(5, int(vol_ma_bars))
    prior_vol = d["volume"].iloc[-(vb + 1) : -1]
    vol_ma = float(prior_vol.mean()) if len(prior_vol) else _nan()
    vol_today = float(last["volume"])
    if not _finite(vol_ma) or vol_ma <= 0 or not _finite(vol_today):
        return None
    vol_ratio = vol_today / vol_ma
    vol_amplify = vol_ratio >= float(vol_amplify_ratio)
    vol_shrink = vol_ratio <= float(vol_shrink_ratio)

    pct_change = (c1 / c0 - 1.0) * 100.0 if c0 > 0 else 0.0
    price_up = c1 > c0
    price_down = c1 < c0
    is_stagnant = abs(pct_change) <= float(stagnant_abs_pct)

    bb = max(5, int(breakout_lookback_bars))
    prior_high = float(d["high"].iloc[-(bb + 1) : -1].max())
    is_breakout = c1 >= prior_high * 0.998
    h1 = float(last["high"]) if _finite(float(last["high"])) else c1
    platform_level = prior_high
    breakout_high = h1
    breakout_close = c1
    breakout_vol = vol_today
    breakout_vol_ratio = vol_ratio

    position_stage = _classify_position(
        close=c1,
        ma20=m20,
        ma60=m60,
        ma20_prev_n=ma20_prev_n,
        range_pct=range_pct,
        bottom_range_pct=float(bottom_range_pct),
        high_range_pct=float(high_range_pct),
    )
    combo_id, match_exact = _assign_combo_phase1(
        position_stage=position_stage,
        vol_amplify=vol_amplify,
        vol_shrink=vol_shrink,
        price_up=price_up,
        price_down=price_down,
        is_breakout=is_breakout,
        is_stagnant=is_stagnant,
    )

    tr_today, tr_ma, tr_ratio, tr_high, tr_low, tr_rising = _eval_turnover(
        d,
        ma_bars=int(turnover_ma_bars),
        high_pct=float(turnover_high_pct),
        low_pct=float(turnover_low_pct),
        amplify_ratio=float(turnover_amplify_ratio),
        shrink_ratio=float(turnover_shrink_ratio),
    )

    phase2_note = ""
    phase = 1
    chip_use = chip if enable_phase2 else None
    if enable_phase2:
        phase = 2
        combo_id, match_exact, phase2_note = _refine_combo_phase2(
            combo_id=combo_id,
            match_exact=match_exact,
            position_stage=position_stage,
            vol_amplify=vol_amplify,
            vol_shrink=vol_shrink,
            price_up=price_up,
            price_down=price_down,
            is_breakout=is_breakout,
            is_stagnant=is_stagnant,
            turnover_high=tr_high,
            turnover_low=tr_low,
            chip=chip_use,
        )

    cstate = _chip_state(chip_use)
    (
        resonance_score,
        s_pos,
        s_vol,
        s_turn,
        s_chip,
        s_trend,
        res_note,
    ) = _score_resonance(
        combo_id=combo_id,
        position_stage=position_stage,
        vol_amplify=vol_amplify,
        vol_shrink=vol_shrink,
        price_up=price_up,
        is_breakout=is_breakout,
        turnover_high=tr_high,
        turnover_low=tr_low,
        turnover_rising=tr_rising,
        turnover_ratio=tr_ratio,
        chip=chip_use,
        chip_state=cstate,
        ma5_score_total=ma5_score_total,
    )

    note_parts = [x for x in (phase2_note, res_note) if x]
    resonance_note = "；".join(note_parts)
    meta = COMBO_META[combo_id]
    ds = pd.Timestamp(last["date"]).strftime("%Y-%m-%d")

    return VpSixSnapshot(
        symbol=symbol,
        stock_name=stock_name or str(last.get("stock_name", "") or ""),
        signal_date=ds,
        close=c1,
        prev_close=c0,
        pct_change=round(pct_change, 4),
        ma20=m20,
        ma60=m60,
        ma20_prev=float(prev["ma20"]),
        range_low=range_low,
        range_high=range_high,
        range_pct=round(range_pct, 4),
        close_vs_ma20_pct=round((c1 / m20 - 1.0) * 100.0, 4),
        close_vs_ma60_pct=round((c1 / m60 - 1.0) * 100.0, 4),
        volume=vol_today,
        vol_ma20=vol_ma,
        vol_ratio=round(vol_ratio, 4),
        vol_amplify=vol_amplify,
        vol_shrink=vol_shrink,
        price_up=price_up,
        price_down=price_down,
        is_breakout=is_breakout,
        is_stagnant=is_stagnant,
        position_stage=position_stage,
        combo_id=combo_id,
        combo_name=meta["combo_name"],
        meaning=meta["meaning"],
        action_hint=meta["action_hint"],
        match_exact=match_exact,
        ma5_score_total=ma5_score_total,
        turnover_today_pct=round(tr_today, 4) if _finite(tr_today) else _nan(),
        turnover_ma20_pct=round(tr_ma, 4) if _finite(tr_ma) else _nan(),
        turnover_ratio=round(tr_ratio, 4) if _finite(tr_ratio) else _nan(),
        turnover_high=tr_high,
        turnover_low=tr_low,
        turnover_rising=tr_rising,
        chip_pattern=(chip_use.pattern if chip_use else ""),
        chip_pattern_label=(chip_use.pattern_label if chip_use else ""),
        chip_concentration=(
            float(chip_use.concentration) if chip_use else _nan()
        ),
        chip_peak_position=(float(chip_use.peak_position) if chip_use else _nan()),
        chip_bottom_stable=bool(chip_use.bottom_stable) if chip_use else False,
        chip_bottom_empty=bool(chip_use.bottom_empty) if chip_use else False,
        chip_state=cstate,
        chip_available=chip_use is not None,
        resonance_score=resonance_score,
        score_position=s_pos,
        score_volume=s_vol,
        score_turnover=s_turn,
        score_chip=s_chip,
        score_trend=s_trend,
        resonance_ok=resonance_score >= float(resonance_pass_score),
        resonance_note=resonance_note,
        phase=phase,
        platform_level=round(platform_level, 4),
        breakout_high=round(breakout_high, 4),
        breakout_close=round(breakout_close, 4),
        breakout_vol=breakout_vol,
        breakout_vol_ratio=round(breakout_vol_ratio, 4),
    )


def scan_vp_six(
    hits_df: pd.DataFrame,
    *,
    end_date: str,
    history_calendar_days: int,
    enable_phase2: bool,
    skip_chips: bool,
    **eval_kw,
) -> Tuple[List[VpSixSnapshot], List[str]]:
    end_dt = pd.to_datetime(end_date).to_pydatetime()
    start_dt = _calendar_start(end_dt, history_calendar_days)
    start_s = start_dt.strftime("%Y-%m-%d")
    end_s = pd.Timestamp(end_date).strftime("%Y-%m-%d")

    pro = None
    if enable_phase2 and not skip_chips:
        pro = _try_tushare_pro()
        if pro is None:
            print("警告: 无法初始化 Tushare，筹码维度将缺失（换手仍尝试拉取）")

    snaps: List[VpSixSnapshot] = []
    skipped: List[str] = []
    chip_cfg = dict(CHIP_CONFIG)

    for _, row in hits_df.iterrows():
        sym = _norm_symbol(row.get("symbol", ""))
        if len(sym) != 6:
            continue
        sname = str(row.get("stock_name", "") or "").strip()
        if not sname:
            sname = fetch_stock_name(sym)
        ma5_score = None
        if "score_total" in hits_df.columns:
            try:
                ma5_score = float(row["score_total"])
            except (TypeError, ValueError):
                ma5_score = None

        try:
            if enable_phase2:
                ohlc = fetch_bars_with_turnover(sym, start_s, end_s)
            else:
                ohlc = fetch_ohlc_qfq(sym, start_s, end_s)
        except Exception:
            skipped.append(f"{sym}(无日线)")
            continue

        chip: Optional[ChipAnalysis] = None
        if enable_phase2 and not skip_chips and pro is not None and not ohlc.empty:
            trade_date = pd.Timestamp(ohlc.iloc[-1]["date"]).strftime("%Y-%m-%d")
            try:
                chip = fetch_chip_analysis_for_symbol(
                    pro, sym, trade_date, ohlc, chip_cfg
                )
            except Exception:
                chip = None

        try:
            snap = evaluate_vp_six(
                ohlc,
                symbol=sym,
                stock_name=sname,
                ma5_score_total=ma5_score,
                chip=chip,
                enable_phase2=enable_phase2,
                **eval_kw,
            )
        except Exception as exc:
            skipped.append(f"{sym}({exc})")
            continue

        if snap is None:
            skipped.append(f"{sym}(数据不足)")
            continue
        snaps.append(snap)

    # 写入表按 combo_name（六类固定顺序=combo_id）分组，组内按共振分降序
    snaps.sort(
        key=lambda x: (
            x.combo_id,
            x.combo_name,
            -float(x.resonance_score),
            -(x.ma5_score_total or 0),
            x.symbol,
        )
    )
    return snaps, skipped


def snapshots_to_dataframe(snaps: List[VpSixSnapshot]) -> pd.DataFrame:
    rows = []
    for s in snaps:
        rows.append(
            {
                "symbol": s.symbol,
                "stock_name": s.stock_name,
                "signal_date": s.signal_date,
                "phase": s.phase,
                "combo_id": s.combo_id,
                "combo_name": s.combo_name,
                "position_stage": s.position_stage,
                "meaning": s.meaning,
                "action_hint": s.action_hint,
                "match_exact": s.match_exact,
                "resonance_score": s.resonance_score,
                "resonance_ok": s.resonance_ok,
                "score_position": s.score_position,
                "score_volume": s.score_volume,
                "score_turnover": s.score_turnover,
                "score_chip": s.score_chip,
                "score_trend": s.score_trend,
                "resonance_note": s.resonance_note,
                "close": s.close,
                "pct_change": s.pct_change,
                "ma20": s.ma20,
                "ma60": s.ma60,
                "range_low": s.range_low,
                "range_high": s.range_high,
                "range_pct": s.range_pct,
                "close_vs_ma20_pct": s.close_vs_ma20_pct,
                "close_vs_ma60_pct": s.close_vs_ma60_pct,
                "volume": s.volume,
                "vol_ma20": s.vol_ma20,
                "vol_ratio": s.vol_ratio,
                "vol_amplify": s.vol_amplify,
                "vol_shrink": s.vol_shrink,
                "price_up": s.price_up,
                "price_down": s.price_down,
                "is_breakout": s.is_breakout,
                "is_stagnant": s.is_stagnant,
                "platform_level": s.platform_level,
                "breakout_high": s.breakout_high,
                "breakout_close": s.breakout_close,
                "breakout_vol": s.breakout_vol,
                "breakout_vol_ratio": s.breakout_vol_ratio,
                "turnover_today_pct": s.turnover_today_pct,
                "turnover_ma20_pct": s.turnover_ma20_pct,
                "turnover_ratio": s.turnover_ratio,
                "turnover_high": s.turnover_high,
                "turnover_low": s.turnover_low,
                "turnover_rising": s.turnover_rising,
                "chip_available": s.chip_available,
                "chip_pattern": s.chip_pattern,
                "chip_pattern_label": s.chip_pattern_label,
                "chip_state": s.chip_state,
                "chip_concentration": s.chip_concentration,
                "chip_peak_position": s.chip_peak_position,
                "chip_bottom_stable": s.chip_bottom_stable,
                "chip_bottom_empty": s.chip_bottom_empty,
                "ma5_score_total": s.ma5_score_total,
            }
        )
    return pd.DataFrame(rows)


WATCH_CSV_COLUMNS = [
    "symbol",
    "stock_name",
    "signal_date",
    "combo_id",
    "combo_name",
    "close",
    "pct_change",
    "platform_level",
    "breakout_high",
    "breakout_close",
    "breakout_vol",
    "breakout_vol_ratio",
    "vol_ratio",
    "is_breakout",
    "resonance_score",
    "resonance_ok",
    "position_stage",
    "ma5_score_total",
]


def watch_csv_path(combo_id: int, *, out_dir: Optional[str] = None) -> str:
    base = out_dir or _SCRIPT_DIR
    return os.path.join(base, f"vp_combo_watch_{int(combo_id)}.csv")


def pattern_entry_symbols_path(combo_id: int) -> str:
    """combo 4 沿用历史路径；其它 combo 写独立 txt。"""
    cid = int(combo_id)
    if cid == 4:
        return DEFAULT_PATTERN_ENTRY_SYMBOLS_TXT
    return os.path.join(_SCRIPT_DIR, "config", f"fetch_pattern_entry_symbols_{cid}.txt")


def _load_watch_csv_file(path: str) -> pd.DataFrame:
    p = os.path.abspath(path)
    if not os.path.isfile(p):
        return pd.DataFrame(columns=WATCH_CSV_COLUMNS)
    try:
        df = pd.read_csv(p, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame(columns=WATCH_CSV_COLUMNS)
    if df is None or df.empty:
        return pd.DataFrame(columns=WATCH_CSV_COLUMNS)
    return df


def merge_rolling_watch_pool(
    existing: pd.DataFrame,
    today: pd.DataFrame,
    *,
    max_trade_days: int = 6,
) -> pd.DataFrame:
    """
    合并观察池：同 symbol 只留最新 signal_date；
    按交易日 signal_date 最多保留 max_trade_days 天（超出删最早一天整批）。
    """
    frames: List[pd.DataFrame] = []
    for part in (existing, today):
        if part is None or part.empty:
            continue
        frames.append(part.copy())
    if not frames:
        return pd.DataFrame(columns=WATCH_CSV_COLUMNS)

    df = pd.concat(frames, ignore_index=True)
    if "symbol" not in df.columns:
        return pd.DataFrame(columns=WATCH_CSV_COLUMNS)
    df["symbol"] = df["symbol"].map(_norm_symbol)
    df = df[df["symbol"].astype(str).str.len() == 6].copy()
    if df.empty:
        return pd.DataFrame(columns=WATCH_CSV_COLUMNS)

    if "signal_date" not in df.columns:
        df["signal_date"] = ""
    df["signal_date"] = (
        pd.to_datetime(df["signal_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    )
    # 无效日期排最后，优先保留有日期的新记录
    df["_sd_sort"] = pd.to_datetime(df["signal_date"], errors="coerce")
    df = df.sort_values(["_sd_sort", "symbol"], ascending=[False, True], na_position="last")
    df = df.drop_duplicates(subset=["symbol"], keep="first")

    valid_dates = [
        d
        for d in sorted(
            {str(x) for x in df["signal_date"].tolist() if str(x) not in ("", "nan", "NaT")},
            reverse=True,
        )
    ]
    keep_n = max(1, int(max_trade_days))
    keep_dates = set(valid_dates[:keep_n])
    if keep_dates:
        df = df[df["signal_date"].isin(keep_dates)].copy()

    df = df.drop(columns=["_sd_sort"], errors="ignore")
    for c in WATCH_CSV_COLUMNS:
        if c not in df.columns:
            df[c] = pd.NA
    df = (
        df[WATCH_CSV_COLUMNS]
        .sort_values(["signal_date", "symbol"], ascending=[False, True])
        .reset_index(drop=True)
    )
    return df


def export_combo_watch_lists(
    out_df: pd.DataFrame,
    *,
    combo_ids: List[int],
    out_dir: Optional[str] = None,
    pattern_entry_symbols_txt: str = DEFAULT_PATTERN_ENTRY_SYMBOLS_TXT,
    primary_combo_id: int = 4,
    max_trade_days: Optional[int] = None,
) -> List[str]:
    """
    按 combo_id 滚动合并观察池 CSV（默认最多 6 个交易日，同票只留最新），
    并同步写入对应 symbols txt。主表 out_df 仍为当日截面；观察池不整表清空。
    """
    notes: List[str] = []
    base = out_dir or _SCRIPT_DIR
    max_days = int(
        max_trade_days
        if max_trade_days is not None
        else VP_SIX_CONFIG.get("watch_pool_max_trade_days", 6)
    )
    has_today = out_df is not None and not out_df.empty and "combo_id" in out_df.columns

    for cid in combo_ids:
        path = watch_csv_path(cid, out_dir=base)
        existing = _load_watch_csv_file(path)
        if has_today:
            sub = out_df.loc[out_df["combo_id"].astype(int) == int(cid)].copy()
            cols = [c for c in WATCH_CSV_COLUMNS if c in sub.columns]
            today = sub[cols].copy() if cols else pd.DataFrame(columns=WATCH_CSV_COLUMNS)
        else:
            today = pd.DataFrame(columns=WATCH_CSV_COLUMNS)

        n_today = len(today) if not today.empty else 0
        watch = merge_rolling_watch_pool(existing, today, max_trade_days=max_days)
        ddir = os.path.dirname(os.path.abspath(path))
        if ddir:
            os.makedirs(ddir, exist_ok=True)
        watch.to_csv(path, index=False, encoding="utf-8-sig")

        dates = sorted(
            {str(x) for x in watch["signal_date"].tolist() if str(x) not in ("", "nan", "NaT")}
        ) if not watch.empty and "signal_date" in watch.columns else []
        notes.append(
            f"watch[{cid}] 今日+{n_today} → 池内 {len(watch)} 只 / "
            f"{len(dates)} 交易日(≤{max_days}) → {path}"
        )
        # 市场中性回测用：按 signal_date 归档观察池快照（同日覆盖）
        try:
            from market_neutral.data.pool_archive import save_watch_snapshot

            ap = save_watch_snapshot(watch, int(cid))
            notes.append(f"archive[{cid}] → {ap}")
        except Exception as exc:
            notes.append(f"archive[{cid}] 跳过: {exc}")

        syms = (
            [_norm_symbol(x) for x in watch["symbol"].tolist()]
            if not watch.empty and "symbol" in watch.columns
            else []
        )
        sp = pattern_entry_symbols_path(int(cid))
        _write_symbols_txt(sp, syms, header_combo_id=int(cid))
        notes.append(f"symbols txt[{cid}] {len(syms)} 只 → {sp}")
        if int(cid) == int(primary_combo_id) and os.path.abspath(sp) != os.path.abspath(
            pattern_entry_symbols_txt
        ):
            _write_symbols_txt(
                pattern_entry_symbols_txt, syms, header_combo_id=primary_combo_id
            )
            notes.append(
                f"symbols txt[{primary_combo_id}/compat] {len(syms)} 只 → {pattern_entry_symbols_txt}"
            )

    return notes


def remove_symbols_from_watch_pool(
    combo_id: int,
    symbols: List[str],
    *,
    out_dir: Optional[str] = None,
) -> Tuple[int, str]:
    """从观察池剔除指定代码，并重写 symbols txt。返回 (剔除数量, 说明)。"""
    cid = int(combo_id)
    drop = {_norm_symbol(s) for s in symbols if len(_norm_symbol(s)) == 6}
    if not drop:
        return 0, f"watch[{cid}] 无待剔除代码"
    path = watch_csv_path(cid, out_dir=out_dir)
    df = _load_watch_csv_file(path)
    if df.empty or "symbol" not in df.columns:
        return 0, f"watch[{cid}] 池空，跳过"
    df = df.copy()
    df["symbol"] = df["symbol"].map(_norm_symbol)
    before = len(df)
    df = df[~df["symbol"].isin(drop)].reset_index(drop=True)
    removed = before - len(df)
    ddir = os.path.dirname(os.path.abspath(path))
    if ddir:
        os.makedirs(ddir, exist_ok=True)
    cols = [c for c in WATCH_CSV_COLUMNS if c in df.columns]
    out = df[cols] if cols else df
    out.to_csv(path, index=False, encoding="utf-8-sig")
    syms = [_norm_symbol(x) for x in out["symbol"].tolist()] if not out.empty else []
    _write_symbols_txt(pattern_entry_symbols_path(cid), syms, header_combo_id=cid)
    if cid == 4:
        _write_symbols_txt(DEFAULT_PATTERN_ENTRY_SYMBOLS_TXT, syms, header_combo_id=4)
    return removed, f"watch[{cid}] 剔除作废 {removed} 只 → 剩 {len(out)} → {path}"


def _write_symbols_txt(
    path: str, symbols: List[str], *, header_combo_id: int
) -> None:
    p = os.path.abspath(path)
    ddir = os.path.dirname(p)
    if ddir:
        os.makedirs(ddir, exist_ok=True)
    name = COMBO_META.get(int(header_combo_id), {}).get("combo_name", str(header_combo_id))
    lines = [
        f"# 由 fetch_vp_six_combo 自动生成 · combo_id={header_combo_id} {name}",
        "# 供 fetch_pattern_entry 作为默认观察池；可手工增删。",
        "",
    ]
    for s in symbols:
        sym = _norm_symbol(s)
        if len(sym) == 6 and sym.isdigit():
            lines.append(sym)
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")


def _brief_line(s: VpSixSnapshot) -> str:
    label = f"{s.stock_name}({s.symbol})" if s.stock_name else s.symbol
    exact = "精确" if s.match_exact else "近邻"
    res = "共振" if s.resonance_ok else "未共振"
    tr = f"{s.turnover_today_pct:.2f}%" if _finite(s.turnover_today_pct) else "NA"
    chip = s.chip_pattern_label or s.chip_state
    return (
        f"  [{s.combo_id}] {label}  {s.combo_name}  ({exact}/{res} {s.resonance_score:.0f})  "
        f"位置={s.position_stage}  量比={s.vol_ratio:.2f}  换手={tr}  "
        f"筹码={chip}  → {s.action_hint}"
    )


def _diagnosis_lines(s: VpSixSnapshot) -> List[str]:
    label = f"{s.stock_name}({s.symbol})" if s.stock_name else s.symbol
    tr = (
        f"{s.turnover_today_pct:.4f}% (均 {s.turnover_ma20_pct:.4f}%, 比 {s.turnover_ratio:.2f})"
        if _finite(s.turnover_today_pct)
        else "缺失"
    )
    return [
        f"—— {label}  截止 {s.signal_date}  Phase{s.phase} ——",
        f"  主标签: [{s.combo_id}] {s.combo_name}  |  {s.meaning}  |  {s.action_hint}",
        f"  共振分 {s.resonance_score:.1f}/100  "
        f"({'通过' if s.resonance_ok else '未通过'})  "
        f"位置{s.score_position} 量{s.score_volume} 换手{s.score_turnover} "
        f"筹码{s.score_chip} 趋势{s.score_trend}",
        f"  位置: {s.position_stage}  近60日分位 {s.range_pct:.2%}  "
        f"(低 {s.range_low:.4f} ~ 高 {s.range_high:.4f})",
        f"  均线: close {s.close:.4f}  MA20 {s.ma20:.4f} ({s.close_vs_ma20_pct:+.2f}%)  "
        f"MA60 {s.ma60:.4f} ({s.close_vs_ma60_pct:+.2f}%)",
        f"  量价: 量比 {s.vol_ratio:.4f}  "
        f"{'放量' if s.vol_amplify else ('缩量' if s.vol_shrink else '中性')}  "
        f"涨跌 {s.pct_change:+.2f}%  "
        f"{'突破' if s.is_breakout else '未突破'}  "
        f"{'滞涨/窄幅' if s.is_stagnant else '非滞涨'}",
        f"  换手: {tr}  "
        f"{'高换手' if s.turnover_high else ('低换手' if s.turnover_low else '中性')}"
        f"{' 上升' if s.turnover_rising else ''}",
        f"  筹码: {s.chip_pattern_label or '无'}  state={s.chip_state}  "
        f"集中度={s.chip_concentration if _finite(s.chip_concentration) else 'NA'}  "
        f"峰位={s.chip_peak_position if _finite(s.chip_peak_position) else 'NA'}  "
        f"底仓稳={s.chip_bottom_stable} 底仓空={s.chip_bottom_empty}",
        f"  匹配: {'典型形态' if s.match_exact else '强制/近邻归类'}"
        + (f"  |  {s.resonance_note}" if s.resonance_note else ""),
    ]


def main() -> None:
    cfg = VP_SIX_CONFIG
    today = datetime.now().strftime("%Y-%m-%d")
    parser = argparse.ArgumentParser(
        description="量价六组合分类（MA5 命中股 Phase2 五维共振）"
    )
    parser.add_argument("--ma5-csv", default=DEFAULT_MA5_CSV, help="MA5 扫描 CSV")
    parser.add_argument(
        "--pool",
        default=DEFAULT_SYMBOLS_POOL_TXT,
        help="自定义股票列表 txt（非空则优先于 --ma5-csv；默认 config/fetch_vp_six_combo_symbols.txt）",
    )
    parser.add_argument(
        "--symbols",
        default="",
        help="自定义股票代码（逗号/空白分隔）；非空则忽略 --pool 与 --ma5-csv",
    )
    parser.add_argument("--end-date", default=today, help="截止日期 YYYY-MM-DD")
    parser.add_argument(
        "--days",
        type=int,
        default=int(cfg["history_calendar_days"]),
        help="回溯日历天数",
    )
    parser.add_argument(
        "--min-bars",
        type=int,
        default=int(cfg["min_bars"]),
        help="最少 K 线根数",
    )
    parser.add_argument(
        "--range-lookback",
        type=int,
        default=int(cfg["range_lookback_bars"]),
        help="高低点分位回看根数",
    )
    parser.add_argument(
        "--vol-ma",
        type=int,
        default=int(cfg["vol_ma_bars"]),
        help="单日量比分母：此前 N 日均量",
    )
    parser.add_argument(
        "--amplify",
        type=float,
        default=float(cfg["vol_amplify_ratio"]),
        help="放量阈值（量比≥）",
    )
    parser.add_argument(
        "--shrink",
        type=float,
        default=float(cfg["vol_shrink_ratio"]),
        help="缩量阈值（量比≤）",
    )
    parser.add_argument(
        "--phase1-only",
        action="store_true",
        help="仅 Phase1（不做换手/筹码）",
    )
    parser.add_argument(
        "--skip-chips",
        action="store_true",
        help="Phase2 跳过筹码（仍算换手）",
    )
    parser.add_argument("--out-csv", default=DEFAULT_OUT_CSV, help="输出 CSV")
    parser.add_argument("--diagnose", action="store_true", help="打印逐股诊断")
    args = parser.parse_args()

    enable_phase2 = not bool(args.phase1_only)
    hits_df, notes = resolve_hits(
        symbols_arg=str(args.symbols),
        pool_path=str(args.pool),
        ma5_csv=str(args.ma5_csv),
    )
    for n in notes:
        print(n)
    print(
        f"模式: {'Phase1' if not enable_phase2 else ('Phase2(无筹码)' if args.skip_chips else 'Phase2 五维共振')}"
    )

    if hits_df.empty:
        out_df = pd.DataFrame()
        out_path = os.path.abspath(args.out_csv)
        ddir = os.path.dirname(out_path)
        if ddir:
            os.makedirs(ddir, exist_ok=True)
        out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
        watch_notes = export_combo_watch_lists(
            out_df,
            combo_ids=[int(x) for x in cfg.get("watch_combo_ids", [4, 6])],
            out_dir=ddir or _SCRIPT_DIR,
            pattern_entry_symbols_txt=DEFAULT_PATTERN_ENTRY_SYMBOLS_TXT,
            primary_combo_id=int(cfg.get("watch_combo_ids", [4, 6])[0]),
            max_trade_days=int(cfg.get("watch_pool_max_trade_days", 6)),
        )
        print(f"无待分类股票，已写空表: {out_path}")
        print("【形态观察池】当日无命中，仍滚动保留既有 watch（不整表清空）")
        for wn in watch_notes:
            print(wn)
        sys.exit(0)

    snaps, skipped = scan_vp_six(
        hits_df,
        end_date=str(args.end_date),
        history_calendar_days=int(args.days),
        enable_phase2=enable_phase2,
        skip_chips=bool(args.skip_chips),
        range_lookback_bars=int(args.range_lookback),
        vol_ma_bars=int(args.vol_ma),
        breakout_lookback_bars=int(cfg["breakout_lookback_bars"]),
        vol_amplify_ratio=float(args.amplify),
        vol_shrink_ratio=float(args.shrink),
        stagnant_abs_pct=float(cfg["stagnant_abs_pct"]),
        bottom_range_pct=float(cfg["bottom_range_pct"]),
        high_range_pct=float(cfg["high_range_pct"]),
        downtrend_ma20_lookback=int(cfg["downtrend_ma20_lookback"]),
        min_bars=int(args.min_bars),
        turnover_ma_bars=int(cfg["turnover_ma_bars"]),
        turnover_high_pct=float(cfg["turnover_high_pct"]),
        turnover_low_pct=float(cfg["turnover_low_pct"]),
        turnover_amplify_ratio=float(cfg["turnover_amplify_ratio"]),
        turnover_shrink_ratio=float(cfg["turnover_shrink_ratio"]),
        resonance_pass_score=float(cfg["resonance_pass_score"]),
    )

    out_df = snapshots_to_dataframe(snaps)
    if not out_df.empty and "combo_name" in out_df.columns:
        sort_cols = ["combo_id", "combo_name"]
        asc = [True, True]
        if "resonance_score" in out_df.columns:
            sort_cols.append("resonance_score")
            asc.append(False)
        if "symbol" in out_df.columns:
            sort_cols.append("symbol")
            asc.append(True)
        out_df = out_df.sort_values(sort_cols, ascending=asc).reset_index(drop=True)
    out_path = os.path.abspath(args.out_csv)
    ddir = os.path.dirname(out_path)
    if ddir:
        os.makedirs(ddir, exist_ok=True)
    out_df.to_csv(out_path, index=False, encoding="utf-8-sig")

    watch_ids = [int(x) for x in cfg.get("watch_combo_ids", [4, 6])]
    watch_notes = export_combo_watch_lists(
        out_df,
        combo_ids=watch_ids,
        out_dir=ddir or _SCRIPT_DIR,
        pattern_entry_symbols_txt=DEFAULT_PATTERN_ENTRY_SYMBOLS_TXT,
        primary_combo_id=watch_ids[0] if watch_ids else 4,
        max_trade_days=int(cfg.get("watch_pool_max_trade_days", 6)),
    )

    phase_tag = f"P{snaps[0].phase}" if snaps else "P?"
    print(
        f"量价六组合[{phase_tag}] | 截止 {args.end_date} | 待分类 {len(hits_df)} | "
        f"分类 {len(snaps)} | CSV {out_path}"
    )
    print("=" * 72)
    print("【六组合分布】")
    if snaps:
        cnt = Counter(s.combo_id for s in snaps)
        for cid in range(1, 7):
            meta = COMBO_META[cid]
            print(f"  [{cid}] {meta['combo_name']}: {cnt.get(cid, 0)} 只")
        ok_n = sum(1 for s in snaps if s.resonance_ok)
        print(f"  五维共振通过: {ok_n}/{len(snaps)}")
        print("—— 明细（按 combo_name / 六类顺序）——")
        for s in snaps:
            print(_brief_line(s))
    else:
        print("  （无分类结果）")

    print("【形态观察导出】")
    for wn in watch_notes:
        print(f"  {wn}")

    if skipped:
        print(
            "跳过: "
            + ", ".join(skipped[:40])
            + (" ..." if len(skipped) > 40 else "")
        )

    if bool(args.diagnose) and snaps:
        print("=" * 72)
        print("【逐股诊断】")
        for s in snaps:
            for line in _diagnosis_lines(s):
                print(line)


if __name__ == "__main__":
    main()

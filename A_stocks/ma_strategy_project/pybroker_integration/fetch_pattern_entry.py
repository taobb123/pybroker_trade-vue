#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
形态建仓信号——接在「量价六组合分类」之后。

已实现形态：
  1) breakout_pullback_rebreak  ↔ combo 4 上涨放量突破
     严格主路径：缩量回踩后的再放量突破 → entry=True
  2) volume_dump_reversal       ↔ combo 6 下跌放量
     观察→止跌缩量→放量破压(试仓)→缩量回踩(加仓)→再放量创新高 → entry=True

输入优先级：
  --symbols > 非空 --pool > --watch-csv（默认按 combo 读 vp_combo_watch_{id}.csv）
  --combo-id 0 表示扫描全部已注册形态。

跑完后：仅「待选后通过」(entry) 自动推东财自选「量能」
（MX_APIKEY 或 config/mx_apikey.txt；--skip-mx-push 可关）。
同时对 combo4/6 全观察池计算估值 upside，排名前 N（默认 2）推东财自选「估值因子」；
以及 Q / M+ / M- 排名 Top2 分别推「Q」「M加」「M减」。
对「量能 / M加 / M减」推送票计算半凯利仓位（上限 20%）→ pattern_entry_kelly_positions.csv。

用法（在 ma_strategy_project 目录下）：
    python pybroker_integration/fetch_pattern_entry.py
    python pybroker_integration/fetch_pattern_entry.py --combo-id 6
    python pybroker_integration/fetch_pattern_entry.py --symbols 002709
"""

from __future__ import annotations

import argparse
import os
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple, Type

import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# 项目根优先，避免被 pybroker_integration/config 遮蔽 config.settings / db_config
for _p in (_SCRIPT_DIR, PROJECT_ROOT):
    if _p in sys.path:
        sys.path.remove(_p)
sys.path.insert(0, _SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

from backtest_sy_002028_threshold import (  # noqa: E402
    fetch_ohlc_qfq,
    fetch_stock_name,
)
from fetch_vp_six_combo import (  # noqa: E402
    DEFAULT_PATTERN_ENTRY_SYMBOLS_TXT,
    _norm_symbol,
    _parse_symbols_text,
    fetch_bars_with_turnover,
    load_symbols_pool_txt,
    pattern_entry_symbols_path,
    remove_symbols_from_watch_pool,
    watch_csv_path,
)
from mx_self_select import add_symbols_to_group  # noqa: E402
from kelly_position import (  # noqa: E402
    build_kelly_rows_for_symbols,
    write_kelly_position_csv,
)

DEFAULT_OUT_CSV = os.path.join(_SCRIPT_DIR, "pattern_entry_scan.csv")
DEFAULT_VALUE_OUT_CSV = os.path.join(_SCRIPT_DIR, "pattern_entry_valuation_rank.csv")
DEFAULT_Q_OUT_CSV = os.path.join(_SCRIPT_DIR, "pattern_entry_q_rank.csv")
DEFAULT_MPLUS_OUT_CSV = os.path.join(_SCRIPT_DIR, "pattern_entry_mplus_rank.csv")
DEFAULT_MMINUS_OUT_CSV = os.path.join(_SCRIPT_DIR, "pattern_entry_mminus_rank.csv")
DEFAULT_KELLY_OUT_CSV = os.path.join(_SCRIPT_DIR, "pattern_entry_kelly_positions.csv")

PATTERN_ENTRY_CONFIG = {
    "history_calendar_days": 220,
    "min_bars": 40,
    "vol_ma_bars": 20,
    # 回踩窗口：突破后第 2~5 根内完成缩量确认
    "min_pullback_bars": 2,
    "max_pullback_bars": 5,
    # 回踩确认后等待再突破的最长交易日
    "max_rebreak_wait_bars": 10,
    "vol_shrink_vs_breakout": 0.70,
    "vol_amplify_vs_pullback": 1.30,
    "vol_amplify_vs_ma": 1.20,
    "platform_break_tol": 0.005,
    "ma10_hold_tol": 0.02,
    # 爆量滞涨作废
    "stagnant_vol_mult": 2.5,
    "stagnant_abs_pct": 2.0,
    # 辅助评分权重（不触发 entry）
    "score_ma5_hold": 8.0,
    "score_macd_ok": 6.0,
    "score_turnover_fade": 6.0,
    "score_entry_bonus": 20.0,
    "score_confirm_bonus": 10.0,
    # —— 下跌放量反转（combo 6）——
    "dump_min_candidate_bars": 2,
    "dump_max_wait_break_bars": 40,
    "dump_vol_shrink_vs_panic": 0.70,
    "dump_break_vol_vs_ma5": 1.50,
    "dump_new_low_tol": 0.01,
    "dump_score_candidate": 6.0,
    "dump_score_trial": 12.0,
    "dump_score_add": 10.0,
}

# 内部 state 码 → 输出中文（CSV / 日志统一）
STATE_ZH = {
    "watch": "观察",
    "candidate": "止跌缩量候选",
    "trial": "试仓·放量破压",
    "confirming": "缩量回踩确认",
    "entry": "建仓",
    "invalid": "作废",
}
STATE_PRINT_ORDER = (
    "entry",
    "confirming",
    "trial",
    "candidate",
    "watch",
    "invalid",
)

# 推送东财自选「量能」：仅待选后通过（entry）；待选仍写入 CSV select_tag，但不推送
SELECT_TAG_BY_STATE = {
    "candidate": "待选",
    "trial": "待选",
    "confirming": "待选",
    "entry": "待选后通过",
}
MX_PUSH_GROUP_DEFAULT = "量能"
MX_VALUE_GROUP_DEFAULT = "估值因子"
MX_Q_GROUP_DEFAULT = "Q"
MX_MPLUS_GROUP_DEFAULT = "M加"
MX_MMINUS_GROUP_DEFAULT = "M减"
VALUE_TOP_N_DEFAULT = 2
QM_TOP_N_DEFAULT = 2


def state_label_zh(state: str) -> str:
    return STATE_ZH.get(str(state or ""), str(state or ""))


def select_tag_for_state(state: str) -> str:
    return SELECT_TAG_BY_STATE.get(str(state or ""), "")


def _finite(x: float) -> bool:
    return x == x and x is not None


def _nan() -> float:
    return float("nan")


def _calendar_start(end_dt: datetime, history_calendar_days: int) -> datetime:
    return end_dt - timedelta(days=max(30, int(history_calendar_days)))


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=int(span), adjust=False, min_periods=int(span)).mean()


def _macd_hist(close: pd.Series) -> pd.Series:
    ema12 = _ema(close, 12)
    ema26 = _ema(close, 26)
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False, min_periods=9).mean()
    return dif - dea


@dataclass
class WatchAnchor:
    symbol: str
    stock_name: str
    breakout_day: str
    platform_level: float
    breakout_high: float
    breakout_close: float
    breakout_vol: float
    breakout_vol_ratio: float
    combo_id: int = 4
    combo_name: str = "上涨放量突破"
    resonance_score: float = _nan()


@dataclass
class PatternResult:
    symbol: str
    stock_name: str
    pattern_id: str
    state: str
    entry: bool
    score: float
    signal_date: str
    breakout_day: str
    platform_level: float
    breakout_high: float
    breakout_close: float
    breakout_vol: float
    close: float
    pullback_bars: int
    bars_since_breakout: int
    pullback_ok: bool
    ma5_hold: bool
    macd_ok: bool
    turnover_fade: bool
    notes: str
    combo_id: int = 4
    combo_name: str = "上涨放量突破"
    # 下跌放量形态扩展（其它形态给默认）
    position_frac: float = 0.0
    trial_ok: bool = False
    add_ok: bool = False
    panic_low: float = field(default_factory=lambda: float("nan"))


class PatternBase(ABC):
    pattern_id: str = "base"
    trigger_combo_ids: Sequence[int] = ()

    @abstractmethod
    def evaluate(
        self,
        ohlc: pd.DataFrame,
        anchor: WatchAnchor,
        *,
        end_date: str,
        cfg: dict,
    ) -> PatternResult:
        raise NotImplementedError


class BreakoutPullbackRebreak(PatternBase):
    """放量突破 → 缩量回踩确认 → 再放量突破（唯一入场门闩）。"""

    pattern_id = "breakout_pullback_rebreak"
    trigger_combo_ids = (4,)

    def evaluate(
        self,
        ohlc: pd.DataFrame,
        anchor: WatchAnchor,
        *,
        end_date: str,
        cfg: dict,
    ) -> PatternResult:
        d = ohlc.sort_values("date").reset_index(drop=True).copy()
        d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
        for col in ("open", "high", "low", "close", "volume"):
            if col in d.columns:
                d[col] = pd.to_numeric(d[col], errors="coerce")
        if "turnover_rate" in d.columns:
            d["turnover_rate"] = pd.to_numeric(d["turnover_rate"], errors="coerce")

        end_s = str(end_date)[:10]
        d = d.loc[d["date"] <= end_s].reset_index(drop=True)

        notes: List[str] = []
        last = d.iloc[-1]
        close_now = float(last["close"])
        signal_date = str(last["date"])

        bi = d.index[d["date"] == str(anchor.breakout_day)[:10]]
        if len(bi) == 0:
            # 锚点日缺失：尝试用最近一根近似（仍保留锚点价量）
            notes.append("突破日K线缺失，按末根截面观察")
            return PatternResult(
                symbol=anchor.symbol,
                stock_name=anchor.stock_name,
                pattern_id=self.pattern_id,
                state="watch",
                entry=False,
                score=0.0,
                signal_date=signal_date,
                breakout_day=anchor.breakout_day,
                platform_level=anchor.platform_level,
                breakout_high=anchor.breakout_high,
                breakout_close=anchor.breakout_close,
                breakout_vol=anchor.breakout_vol,
                close=close_now,
                pullback_bars=0,
                bars_since_breakout=0,
                pullback_ok=False,
                ma5_hold=False,
                macd_ok=False,
                turnover_fade=False,
                notes="；".join(notes),
                combo_id=anchor.combo_id,
                combo_name=anchor.combo_name,
            )

        b_idx = int(bi[0])
        after = d.iloc[b_idx + 1 :].copy()
        bars_since = len(after)

        platform = float(anchor.platform_level)
        brk_high = float(anchor.breakout_high)
        brk_vol = float(anchor.breakout_vol)
        tol = float(cfg["platform_break_tol"])
        min_pb = int(cfg["min_pullback_bars"])
        max_pb = int(cfg["max_pullback_bars"])
        max_wait = int(cfg["max_rebreak_wait_bars"])
        shrink_ratio = float(cfg["vol_shrink_vs_breakout"])
        amp_pb = float(cfg["vol_amplify_vs_pullback"])
        amp_ma = float(cfg["vol_amplify_vs_ma"])
        stag_mult = float(cfg["stagnant_vol_mult"])
        stag_pct = float(cfg["stagnant_abs_pct"])
        ma10_tol = float(cfg["ma10_hold_tol"])

        d["ma5"] = d["close"].rolling(5, min_periods=5).mean()
        d["ma10"] = d["close"].rolling(10, min_periods=10).mean()
        vb = max(5, int(cfg["vol_ma_bars"]))
        d["vol_ma"] = d["volume"].rolling(vb, min_periods=max(3, vb // 2)).mean()
        d["macd_hist"] = _macd_hist(d["close"])

        if bars_since == 0:
            notes.append("突破当日，等待缩量回踩")
            return self._pack(
                anchor,
                state="watch",
                entry=False,
                score=0.0,
                signal_date=signal_date,
                close=close_now,
                pullback_bars=0,
                bars_since=0,
                pullback_ok=False,
                ma5_hold=False,
                macd_ok=False,
                turnover_fade=False,
                notes=notes,
            )

        pullback_ok = False
        pullback_bars = 0
        shrink_vols: List[float] = []
        state = "watch"
        entry = False
        invalid_reason = ""

        for i, row in after.iterrows():
            i = int(i)
            c = float(row["close"])
            lo = float(row["low"])
            vol = float(row["volume"])
            prev_c = float(d.iloc[i - 1]["close"]) if i > 0 else c
            pct = (c / prev_c - 1.0) * 100.0 if prev_c > 0 else 0.0
            days = i - b_idx  # 1-based since breakout

            # 作废：跌破平台
            if c < platform * (1.0 - tol):
                invalid_reason = f"收盘跌破平台 {platform:.4f}"
                state = "invalid"
                break

            # 作废：爆量滞涨
            if (
                _finite(brk_vol)
                and brk_vol > 0
                and vol >= brk_vol * stag_mult
                and abs(pct) <= stag_pct
            ):
                invalid_reason = f"爆量滞涨(量≥{stag_mult:.1f}x突破量且涨跌≤{stag_pct}%)"
                state = "invalid"
                break

            ma10 = float(row["ma10"]) if _finite(float(row.get("ma10", _nan()))) else _nan()
            hold_platform = lo >= platform * (1.0 - tol)
            hold_ma10 = (not _finite(ma10)) or (lo >= ma10 * (1.0 - ma10_tol))
            vol_shrink = (_finite(brk_vol) and brk_vol > 0 and vol <= brk_vol * shrink_ratio)

            if not pullback_ok:
                if days > max_pb:
                    invalid_reason = f"回踩超时(>{max_pb}日未确认)"
                    state = "invalid"
                    break
                if vol_shrink and hold_platform and hold_ma10:
                    pullback_bars += 1
                    shrink_vols.append(vol)
                if pullback_bars >= min_pb:
                    pullback_ok = True
                    state = "confirming"
                    notes.append(f"缩量回踩确认{pullback_bars}日")
                else:
                    state = "watch" if days < min_pb else "confirming"
            else:
                # 已确认回踩：等待再放量突破
                pb_vol_ref = (
                    float(sum(shrink_vols) / len(shrink_vols)) if shrink_vols else brk_vol
                )
                vol_ma = float(row["vol_ma"]) if _finite(float(row.get("vol_ma", _nan()))) else _nan()
                vol_amp = False
                if _finite(pb_vol_ref) and pb_vol_ref > 0 and vol >= pb_vol_ref * amp_pb:
                    vol_amp = True
                if _finite(vol_ma) and vol_ma > 0 and vol >= vol_ma * amp_ma:
                    vol_amp = True
                if c >= brk_high and vol_amp:
                    entry = True
                    state = "entry"
                    notes.append("再放量突破前高，主路径建仓")
                    # 切到当前行作为信号日
                    signal_date = str(row["date"])
                    close_now = c
                    break
                if days > max_pb + max_wait:
                    invalid_reason = f"再突破超时(确认后>{max_wait}日)"
                    state = "invalid"
                    break
                state = "confirming"

        if invalid_reason:
            notes.append(invalid_reason)

        # 辅助因子（仅评分）
        ma5_hold, macd_ok, turnover_fade = self._aux_flags(
            d, b_idx, after if bars_since else d.iloc[0:0], anchor, cfg
        )
        score = self._score(
            state=state,
            entry=entry,
            pullback_ok=pullback_ok,
            ma5_hold=ma5_hold,
            macd_ok=macd_ok,
            turnover_fade=turnover_fade,
            cfg=cfg,
        )
        if ma5_hold:
            notes.append("MA5强承接")
        if macd_ok:
            notes.append("MACD红柱健康")
        if turnover_fade:
            notes.append("换手递减站住")

        # 若循环结束仍在观察且未超时
        if state not in ("entry", "invalid"):
            if pullback_ok:
                state = "confirming"
            elif bars_since < min_pb:
                state = "watch"
            else:
                state = "confirming"

        return self._pack(
            anchor,
            state=state,
            entry=entry,
            score=score,
            signal_date=signal_date,
            close=close_now,
            pullback_bars=pullback_bars,
            bars_since=bars_since,
            pullback_ok=pullback_ok,
            ma5_hold=ma5_hold,
            macd_ok=macd_ok,
            turnover_fade=turnover_fade,
            notes=notes,
        )

    def _aux_flags(
        self,
        d: pd.DataFrame,
        b_idx: int,
        after: pd.DataFrame,
        anchor: WatchAnchor,
        cfg: dict,
    ) -> Tuple[bool, bool, bool]:
        if after is None or after.empty:
            return False, False, False

        # MA5：回踩段多数日 low 不低于 MA5*0.98 或 close 回到 MA5 上方
        ma5_hits = 0
        for _, row in after.iterrows():
            ma5 = float(row["ma5"]) if _finite(float(row.get("ma5", _nan()))) else _nan()
            if not _finite(ma5) or ma5 <= 0:
                continue
            lo = float(row["low"])
            c = float(row["close"])
            if lo >= ma5 * 0.98 or c >= ma5:
                ma5_hits += 1
        ma5_hold = ma5_hits >= max(1, len(after) // 2)

        # MACD：突破日红柱 vs 最新红柱，未明显萎缩
        h0 = float(d.iloc[b_idx]["macd_hist"]) if "macd_hist" in d.columns else _nan()
        h1 = float(d.iloc[-1]["macd_hist"]) if "macd_hist" in d.columns else _nan()
        macd_ok = _finite(h0) and _finite(h1) and h1 >= 0 and h1 >= h0 * 0.7

        # 换手：自突破日递减且股价站住平台
        turnover_fade = False
        if "turnover_rate" in d.columns:
            tr0 = float(d.iloc[b_idx]["turnover_rate"])
            recent = after["turnover_rate"].dropna()
            if _finite(tr0) and tr0 > 0 and len(recent) >= 2:
                declining = all(
                    float(recent.iloc[i]) <= float(recent.iloc[i - 1]) * 1.05
                    for i in range(1, len(recent))
                )
                last_c = float(d.iloc[-1]["close"])
                turnover_fade = declining and last_c >= float(anchor.platform_level)

        return ma5_hold, macd_ok, turnover_fade

    def _score(
        self,
        *,
        state: str,
        entry: bool,
        pullback_ok: bool,
        ma5_hold: bool,
        macd_ok: bool,
        turnover_fade: bool,
        cfg: dict,
    ) -> float:
        s = 0.0
        if entry:
            s += float(cfg["score_entry_bonus"])
        if pullback_ok or state == "confirming":
            s += float(cfg["score_confirm_bonus"])
        if ma5_hold:
            s += float(cfg["score_ma5_hold"])
        if macd_ok:
            s += float(cfg["score_macd_ok"])
        if turnover_fade:
            s += float(cfg["score_turnover_fade"])
        if state == "invalid":
            s = min(s, 5.0)
        return round(s, 2)

    def _pack(
        self,
        anchor: WatchAnchor,
        *,
        state: str,
        entry: bool,
        score: float,
        signal_date: str,
        close: float,
        pullback_bars: int,
        bars_since: int,
        pullback_ok: bool,
        ma5_hold: bool,
        macd_ok: bool,
        turnover_fade: bool,
        notes: List[str],
    ) -> PatternResult:
        return PatternResult(
            symbol=anchor.symbol,
            stock_name=anchor.stock_name,
            pattern_id=self.pattern_id,
            state=state,
            entry=bool(entry),
            score=float(score),
            signal_date=signal_date,
            breakout_day=anchor.breakout_day,
            platform_level=anchor.platform_level,
            breakout_high=anchor.breakout_high,
            breakout_close=anchor.breakout_close,
            breakout_vol=anchor.breakout_vol,
            close=close,
            pullback_bars=pullback_bars,
            bars_since_breakout=bars_since,
            pullback_ok=pullback_ok,
            ma5_hold=ma5_hold,
            macd_ok=macd_ok,
            turnover_fade=turnover_fade,
            notes="；".join([n for n in notes if n]),
            combo_id=anchor.combo_id,
            combo_name=anchor.combo_name,
            position_frac=1.0 if entry else (0.6 if pullback_ok else 0.0),
            trial_ok=False,
            add_ok=bool(pullback_ok and not entry),
            panic_low=_nan(),
        )


class VolumeDumpReversal(PatternBase):
    """
    下跌放量 → 止跌缩量 → 放量突破压力 → 缩量回踩 → 再放量创新高。

    entry=True 仅在最终「再放量创新高」；试仓/加仓以 trial_ok / add_ok + position_frac 标注。
    锚点语义：breakout_day=恐慌放量日，platform_level=压力位，breakout_vol=恐慌日成交量。
    """

    pattern_id = "volume_dump_reversal"
    trigger_combo_ids = (6,)

    def evaluate(
        self,
        ohlc: pd.DataFrame,
        anchor: WatchAnchor,
        *,
        end_date: str,
        cfg: dict,
    ) -> PatternResult:
        d = ohlc.sort_values("date").reset_index(drop=True).copy()
        d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
        for col in ("open", "high", "low", "close", "volume"):
            if col in d.columns:
                d[col] = pd.to_numeric(d[col], errors="coerce")
        if "turnover_rate" in d.columns:
            d["turnover_rate"] = pd.to_numeric(d["turnover_rate"], errors="coerce")

        end_s = str(end_date)[:10]
        d = d.loc[d["date"] <= end_s].reset_index(drop=True)

        notes: List[str] = []
        last = d.iloc[-1]
        close_now = float(last["close"])
        signal_date = str(last["date"])

        resistance = float(anchor.platform_level)
        panic_vol = float(anchor.breakout_vol)
        panic_day = str(anchor.breakout_day)[:10]

        bi = d.index[d["date"] == panic_day]
        if len(bi) == 0 or not _finite(resistance):
            notes.append("恐慌日或压力位缺失，仅观察")
            return self._pack(
                anchor,
                state="watch",
                entry=False,
                score=0.0,
                signal_date=signal_date,
                close=close_now,
                pullback_bars=0,
                bars_since=0,
                pullback_ok=False,
                ma5_hold=False,
                macd_ok=False,
                turnover_fade=False,
                notes=notes,
                position_frac=0.0,
                trial_ok=False,
                add_ok=False,
                panic_low=_nan(),
                rev_high=resistance if _finite(resistance) else _nan(),
                rev_close=anchor.breakout_close,
                rev_vol=panic_vol,
            )

        p_idx = int(bi[0])
        # 恐慌低点：恐慌日及随后若干日最低
        panic_window = d.iloc[p_idx : min(len(d), p_idx + 6)]
        panic_low = float(panic_window["low"].min())

        d["ma5"] = d["close"].rolling(5, min_periods=5).mean()
        d["ma10"] = d["close"].rolling(10, min_periods=10).mean()
        d["ma20"] = d["close"].rolling(20, min_periods=20).mean()
        d["vol_ma5"] = d["volume"].rolling(5, min_periods=3).mean()
        vb = max(5, int(cfg["vol_ma_bars"]))
        d["vol_ma"] = d["volume"].rolling(vb, min_periods=max(3, vb // 2)).mean()
        d["macd_hist"] = _macd_hist(d["close"])

        after = d.iloc[p_idx + 1 :]
        bars_since = len(after)
        if bars_since == 0:
            notes.append("下跌放量当日，只观察不买")
            return self._pack(
                anchor,
                state="watch",
                entry=False,
                score=0.0,
                signal_date=signal_date,
                close=close_now,
                pullback_bars=0,
                bars_since=0,
                pullback_ok=False,
                ma5_hold=False,
                macd_ok=False,
                turnover_fade=False,
                notes=notes,
                position_frac=0.0,
                trial_ok=False,
                add_ok=False,
                panic_low=panic_low,
                rev_high=resistance,
                rev_close=float(d.iloc[p_idx]["close"]),
                rev_vol=panic_vol,
            )

        shrink_ratio = float(cfg["dump_vol_shrink_vs_panic"])
        min_cand = int(cfg["dump_min_candidate_bars"])
        max_wait = int(cfg["dump_max_wait_break_bars"])
        break_vol_ratio = float(cfg["dump_break_vol_vs_ma5"])
        new_low_tol = float(cfg["dump_new_low_tol"])
        plat_tol = float(cfg["platform_break_tol"])
        min_pb = int(cfg["min_pullback_bars"])
        max_pb = int(cfg["max_pullback_bars"])
        max_rebreak = int(cfg["max_rebreak_wait_bars"])
        amp_pb = float(cfg["vol_amplify_vs_pullback"])
        amp_ma = float(cfg["vol_amplify_vs_ma"])

        candidate = False
        shrink_days = 0
        trial_ok = False
        add_ok = False
        pullback_ok = False
        pullback_bars = 0
        entry = False
        state = "watch"
        position_frac = 0.0
        invalid_reason = ""

        rev_day_idx: Optional[int] = None
        rev_high = resistance
        rev_close = resistance
        rev_vol = panic_vol
        shrink_vols: List[float] = []

        for i, row in after.iterrows():
            i = int(i)
            c = float(row["close"])
            lo = float(row["low"])
            hi = float(row["high"])
            vol = float(row["volume"])
            days = i - p_idx
            vol_ma5 = float(row["vol_ma5"]) if _finite(float(row.get("vol_ma5", _nan()))) else _nan()
            vol_ma = float(row["vol_ma"]) if _finite(float(row.get("vol_ma", _nan()))) else _nan()
            ma20 = float(row["ma20"]) if _finite(float(row.get("ma20", _nan()))) else _nan()
            ma20_prev = (
                float(d.iloc[i - 5]["ma20"])
                if i >= 5 and _finite(float(d.iloc[i - 5].get("ma20", _nan())))
                else _nan()
            )
            hist = float(row["macd_hist"]) if _finite(float(row.get("macd_hist", _nan()))) else _nan()

            # 再创新低 → 趋势未止，作废（已破压后也适用）
            if lo < panic_low * (1.0 - new_low_tol):
                invalid_reason = f"再创恐慌新低({lo:.4f}<{panic_low:.4f})"
                state = "invalid"
                break

            # —— 尚未破压：等待止跌缩量，再等放量突破压力 ——
            if not trial_ok:
                if days > max_wait:
                    invalid_reason = f"破压超时(>{max_wait}日)"
                    state = "invalid"
                    break

                vol_shrink = (
                    _finite(panic_vol)
                    and panic_vol > 0
                    and vol <= panic_vol * shrink_ratio
                )
                if vol_shrink and c > panic_low:
                    shrink_days += 1
                if shrink_days >= min_cand:
                    candidate = True
                    state = "candidate"
                    position_frac = max(position_frac, 0.0)

                # 无量靠近压力：保持观察/候选，不给试仓
                near_res = c >= resistance * 0.97
                weak_vol = _finite(vol_ma5) and vol_ma5 > 0 and vol < vol_ma5 * 1.0
                if near_res and weak_vol and c < resistance:
                    state = "candidate" if candidate else "watch"
                    continue

                # 放量突破压力位 → 试仓信号（非最终 entry）
                vol_break = (
                    (_finite(vol_ma5) and vol_ma5 > 0 and vol >= vol_ma5 * break_vol_ratio)
                    or (_finite(vol_ma) and vol_ma > 0 and vol >= vol_ma * break_vol_ratio)
                )
                if candidate and c >= resistance * (1.0 - plat_tol) and vol_break:
                    trial_ok = True
                    rev_day_idx = i
                    rev_high = hi
                    rev_close = c
                    rev_vol = vol
                    state = "trial"
                    position_frac = 0.2
                    notes.append(f"放量突破压力{resistance:.2f}·试仓20%")
                    signal_date = str(row["date"])
                    close_now = c
                elif candidate:
                    state = "candidate"
                else:
                    state = "watch"
                continue

            # —— 已试仓破压：缩量回踩确认 ——
            assert rev_day_idx is not None
            days_since_rev = i - rev_day_idx

            if c < resistance * (1.0 - plat_tol):
                invalid_reason = f"破压后跌回压力下({c:.4f}<{resistance:.4f})"
                state = "invalid"
                break

            if not pullback_ok:
                if days_since_rev > max_pb:
                    # 未完成回踩确认：仍可视为 trial，但超时标记
                    if days_since_rev > max_pb + max_rebreak:
                        invalid_reason = f"回踩确认超时(>{max_pb}日)"
                        state = "invalid"
                        break
                    state = "trial"
                    continue

                vol_shrink_pb = vol <= rev_vol * float(cfg["vol_shrink_vs_breakout"])
                hold = lo >= resistance * (1.0 - plat_tol)
                if vol_shrink_pb and hold and days_since_rev >= 1:
                    pullback_bars += 1
                    shrink_vols.append(vol)
                if pullback_bars >= min_pb:
                    pullback_ok = True
                    add_ok = True
                    state = "confirming"
                    position_frac = 0.6
                    notes.append(f"缩量回踩不破压力·加仓至60%")
                    signal_date = str(row["date"])
                    close_now = c
                else:
                    state = "trial"
                continue

            # —— 回踩完成：再放量创新高 = 系统建仓 entry ——
            pb_vol_ref = (
                float(sum(shrink_vols) / len(shrink_vols)) if shrink_vols else rev_vol
            )
            vol_amp = False
            if _finite(pb_vol_ref) and pb_vol_ref > 0 and vol >= pb_vol_ref * amp_pb:
                vol_amp = True
            if _finite(vol_ma) and vol_ma > 0 and vol >= vol_ma * amp_ma:
                vol_amp = True

            macd_ok_now = _finite(hist) and hist > 0
            if rev_day_idx is not None:
                h0 = float(d.iloc[rev_day_idx]["macd_hist"])
                if _finite(h0) and _finite(hist):
                    macd_ok_now = hist >= 0 and hist >= h0 * 0.85

            ma20_ok = True
            if _finite(ma20) and _finite(ma20_prev):
                ma20_ok = ma20 >= ma20_prev * 0.998  # 走平或上拐

            if c >= rev_high and vol_amp and macd_ok_now and ma20_ok:
                entry = True
                state = "entry"
                position_frac = 1.0
                notes.append("再放量创新高·加满建仓")
                signal_date = str(row["date"])
                close_now = c
                break

            if days_since_rev > max_pb + max_rebreak:
                invalid_reason = f"再突破超时(确认后>{max_rebreak}日)"
                state = "invalid"
                break
            state = "confirming"

        if invalid_reason:
            notes.append(invalid_reason)
            position_frac = 0.0

        if state not in ("entry", "invalid"):
            if entry:
                state = "entry"
            elif pullback_ok:
                state = "confirming"
                position_frac = max(position_frac, 0.6)
            elif trial_ok:
                state = "trial"
                position_frac = max(position_frac, 0.2)
            elif candidate:
                state = "candidate"
            else:
                state = "watch"

        # 辅助因子
        ma5_hold = False
        macd_ok = False
        turnover_fade = False
        if trial_ok and rev_day_idx is not None:
            seg = d.iloc[rev_day_idx:]
            hits = 0
            for _, rr in seg.iterrows():
                ma5 = float(rr["ma5"]) if _finite(float(rr.get("ma5", _nan()))) else _nan()
                if _finite(ma5) and (float(rr["low"]) >= ma5 * 0.98 or float(rr["close"]) >= ma5):
                    hits += 1
            ma5_hold = hits >= max(1, len(seg) // 2)
            h_now = float(d.iloc[-1]["macd_hist"])
            h_rev = float(d.iloc[rev_day_idx]["macd_hist"])
            macd_ok = _finite(h_now) and _finite(h_rev) and h_now >= 0 and h_now >= h_rev * 0.7
            if "turnover_rate" in d.columns:
                tr0 = float(d.iloc[rev_day_idx]["turnover_rate"])
                recent = seg["turnover_rate"].dropna()
                if _finite(tr0) and len(recent) >= 2:
                    declining = all(
                        float(recent.iloc[j]) <= float(recent.iloc[j - 1]) * 1.05
                        for j in range(1, len(recent))
                    )
                    turnover_fade = declining and close_now >= resistance

        if ma5_hold:
            notes.append("MA5强承接")
        if macd_ok:
            notes.append("MACD红柱健康")
        if turnover_fade:
            notes.append("换手递减站住")
        if candidate and "止跌缩量" not in "；".join(notes):
            notes.insert(0, "止跌缩量候选")

        score = 0.0
        if candidate:
            score += float(cfg["dump_score_candidate"])
        if trial_ok:
            score += float(cfg["dump_score_trial"])
        if add_ok or pullback_ok:
            score += float(cfg["dump_score_add"])
        if entry:
            score += float(cfg["score_entry_bonus"])
        if ma5_hold:
            score += float(cfg["score_ma5_hold"])
        if macd_ok:
            score += float(cfg["score_macd_ok"])
        if turnover_fade:
            score += float(cfg["score_turnover_fade"])
        if state == "invalid":
            score = min(score, 5.0)

        return self._pack(
            anchor,
            state=state,
            entry=entry,
            score=round(score, 2),
            signal_date=signal_date,
            close=close_now,
            pullback_bars=pullback_bars,
            bars_since=bars_since,
            pullback_ok=pullback_ok,
            ma5_hold=ma5_hold,
            macd_ok=macd_ok,
            turnover_fade=turnover_fade,
            notes=notes,
            position_frac=position_frac,
            trial_ok=trial_ok,
            add_ok=add_ok,
            panic_low=panic_low,
            rev_high=rev_high,
            rev_close=rev_close,
            rev_vol=rev_vol,
        )

    def _pack(
        self,
        anchor: WatchAnchor,
        *,
        state: str,
        entry: bool,
        score: float,
        signal_date: str,
        close: float,
        pullback_bars: int,
        bars_since: int,
        pullback_ok: bool,
        ma5_hold: bool,
        macd_ok: bool,
        turnover_fade: bool,
        notes: List[str],
        position_frac: float,
        trial_ok: bool,
        add_ok: bool,
        panic_low: float,
        rev_high: float,
        rev_close: float,
        rev_vol: float,
    ) -> PatternResult:
        return PatternResult(
            symbol=anchor.symbol,
            stock_name=anchor.stock_name,
            pattern_id=self.pattern_id,
            state=state,
            entry=bool(entry),
            score=float(score),
            signal_date=signal_date,
            breakout_day=anchor.breakout_day,
            platform_level=anchor.platform_level,
            breakout_high=rev_high if _finite(rev_high) else anchor.breakout_high,
            breakout_close=rev_close if _finite(rev_close) else anchor.breakout_close,
            breakout_vol=rev_vol if _finite(rev_vol) else anchor.breakout_vol,
            close=close,
            pullback_bars=pullback_bars,
            bars_since_breakout=bars_since,
            pullback_ok=pullback_ok,
            ma5_hold=ma5_hold,
            macd_ok=macd_ok,
            turnover_fade=turnover_fade,
            notes="；".join([n for n in notes if n]),
            combo_id=anchor.combo_id,
            combo_name=anchor.combo_name or "下跌放量",
            position_frac=float(position_frac),
            trial_ok=bool(trial_ok),
            add_ok=bool(add_ok),
            panic_low=panic_low,
        )


PATTERN_REGISTRY: Dict[str, Type[PatternBase]] = {
    BreakoutPullbackRebreak.pattern_id: BreakoutPullbackRebreak,
    VolumeDumpReversal.pattern_id: VolumeDumpReversal,
}

COMBO_DEFAULT_PATTERN: Dict[int, str] = {
    4: BreakoutPullbackRebreak.pattern_id,
    6: VolumeDumpReversal.pattern_id,
}


def get_pattern_for_combo(combo_id: int) -> PatternBase:
    pid = COMBO_DEFAULT_PATTERN.get(int(combo_id))
    if not pid or pid not in PATTERN_REGISTRY:
        raise KeyError(f"combo_id={combo_id} 尚无注册形态建仓模型")
    return PATTERN_REGISTRY[pid]()


def load_watch_csv(path: str) -> pd.DataFrame:
    p = os.path.abspath(path)
    if not os.path.isfile(p):
        return pd.DataFrame()
    df = pd.read_csv(p, encoding="utf-8-sig")
    if df.empty:
        return df
    if "symbol" in df.columns:
        df = df.copy()
        df["symbol"] = df["symbol"].map(_norm_symbol)
    return df


def anchors_from_watch_df(df: pd.DataFrame) -> List[WatchAnchor]:
    out: List[WatchAnchor] = []
    if df is None or df.empty:
        return out
    for _, row in df.iterrows():
        sym = _norm_symbol(row.get("symbol", ""))
        if len(sym) != 6:
            continue
        out.append(
            WatchAnchor(
                symbol=sym,
                stock_name=str(row.get("stock_name", "") or ""),
                breakout_day=str(row.get("signal_date", "") or "")[:10],
                platform_level=float(row.get("platform_level", _nan())),
                breakout_high=float(row.get("breakout_high", _nan())),
                breakout_close=float(row.get("breakout_close", row.get("close", _nan()))),
                breakout_vol=float(row.get("breakout_vol", row.get("volume", _nan()))),
                breakout_vol_ratio=float(row.get("breakout_vol_ratio", row.get("vol_ratio", _nan()))),
                combo_id=int(row.get("combo_id", 4) or 4),
                combo_name=str(row.get("combo_name", "上涨放量突破") or "上涨放量突破"),
                resonance_score=float(row.get("resonance_score", _nan())),
            )
        )
    return out


def resolve_anchors(
    *,
    symbols_arg: str,
    pool_path: str,
    watch_csv: str,
    combo_id: int,
) -> Tuple[List[WatchAnchor], List[str]]:
    notes: List[str] = []
    watch_df = load_watch_csv(watch_csv)
    watch_map: Dict[str, WatchAnchor] = {
        a.symbol: a for a in anchors_from_watch_df(watch_df)
    }

    cli = _parse_symbols_text(symbols_arg)
    if cli:
        notes.append(f"自定义 --symbols → {len(cli)} 只")
        return _anchors_for_symbols(cli, watch_map, combo_id), notes

    pool = str(pool_path or "").strip()
    if pool:
        pool_syms = load_symbols_pool_txt(pool)
        if pool_syms:
            notes.append(f"自定义列表 {os.path.abspath(pool)} → {len(pool_syms)} 只")
            return _anchors_for_symbols(pool_syms, watch_map, combo_id), notes

    anchors = [a for a in watch_map.values() if int(a.combo_id) == int(combo_id)]
    if not anchors and not watch_df.empty and "combo_id" not in watch_df.columns:
        anchors = list(watch_map.values())
    notes.append(f"watch CSV {os.path.abspath(watch_csv)} → {len(anchors)} 只")
    return anchors, notes


def _anchors_for_symbols(
    symbols: List[str],
    watch_map: Dict[str, WatchAnchor],
    combo_id: int,
) -> List[WatchAnchor]:
    out: List[WatchAnchor] = []
    cname = "下跌放量" if int(combo_id) == 6 else "上涨放量突破"
    for sym in symbols:
        s = _norm_symbol(sym)
        if s in watch_map:
            a = watch_map[s]
            out.append(
                WatchAnchor(
                    symbol=a.symbol,
                    stock_name=a.stock_name,
                    breakout_day=a.breakout_day,
                    platform_level=a.platform_level,
                    breakout_high=a.breakout_high,
                    breakout_close=a.breakout_close,
                    breakout_vol=a.breakout_vol,
                    breakout_vol_ratio=a.breakout_vol_ratio,
                    combo_id=int(combo_id),
                    combo_name=a.combo_name or cname,
                    resonance_score=a.resonance_score,
                )
            )
        else:
            out.append(
                WatchAnchor(
                    symbol=s,
                    stock_name="",
                    breakout_day="",
                    platform_level=_nan(),
                    breakout_high=_nan(),
                    breakout_close=_nan(),
                    breakout_vol=_nan(),
                    breakout_vol_ratio=_nan(),
                    combo_id=int(combo_id),
                    combo_name=cname,
                )
            )
    return out


def _infer_anchor_from_ohlc(
    ohlc: pd.DataFrame,
    *,
    symbol: str,
    stock_name: str,
    combo_id: int,
    breakout_lookback: int = 20,
    vol_ma_bars: int = 20,
    vol_amplify_ratio: float = 1.5,
) -> Optional[WatchAnchor]:
    """无 watch 锚点时：combo4 用最近放量突破；combo6 用最近放量下跌日。"""
    d = ohlc.sort_values("date").reset_index(drop=True).copy()
    if len(d) < breakout_lookback + 5:
        return None
    d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d")
    d["close"] = pd.to_numeric(d["close"], errors="coerce")
    d["high"] = pd.to_numeric(d["high"], errors="coerce")
    d["low"] = pd.to_numeric(d["low"], errors="coerce")
    d["volume"] = pd.to_numeric(d["volume"], errors="coerce")
    vb = max(5, int(vol_ma_bars))
    bb = max(5, int(breakout_lookback))
    cname = "下跌放量" if int(combo_id) == 6 else "上涨放量突破"

    if int(combo_id) == 6:
        # 近 lookback 内找量比最大的阴线作为恐慌日
        best_i = None
        best_score = -1.0
        for i in range(max(vb + 1, len(d) - 30), len(d)):
            prior_vol = d["volume"].iloc[i - vb : i]
            vol_ma = float(prior_vol.mean()) if len(prior_vol) else _nan()
            vol = float(d.iloc[i]["volume"])
            c0 = float(d.iloc[i - 1]["close"])
            c1 = float(d.iloc[i]["close"])
            if not (_finite(vol_ma) and vol_ma > 0 and _finite(vol) and c0 > 0):
                continue
            ratio = vol / vol_ma
            if c1 < c0 and ratio >= float(vol_amplify_ratio) and ratio > best_score:
                best_score = ratio
                best_i = i
        if best_i is None:
            best_i = len(d) - 1
            prior_vol = d["volume"].iloc[-(vb + 1) : -1]
            vol_ma = float(prior_vol.mean()) if len(prior_vol) else 1.0
            best_score = float(d.iloc[best_i]["volume"]) / vol_ma if vol_ma > 0 else 1.0
        row = d.iloc[best_i]
        # 压力位：恐慌日前 lookback 最高价
        start = max(0, best_i - bb)
        prior_high = float(d["high"].iloc[start:best_i].max()) if best_i > start else float(row["high"])
        return WatchAnchor(
            symbol=symbol,
            stock_name=stock_name,
            breakout_day=str(row["date"]),
            platform_level=prior_high,
            breakout_high=float(row["high"]),
            breakout_close=float(row["close"]),
            breakout_vol=float(row["volume"]),
            breakout_vol_ratio=round(float(best_score), 4),
            combo_id=int(combo_id),
            combo_name=cname,
        )

    last = d.iloc[-1]
    prior_high = float(d["high"].iloc[-(bb + 1) : -1].max())
    vol_ma = float(d["volume"].iloc[-(vb + 1) : -1].mean())
    vol = float(last["volume"])
    if not (_finite(vol_ma) and vol_ma > 0 and _finite(vol)):
        return None
    ratio = vol / vol_ma
    c1 = float(last["close"])
    return WatchAnchor(
        symbol=symbol,
        stock_name=stock_name,
        breakout_day=str(last["date"]),
        platform_level=prior_high,
        breakout_high=float(last["high"]),
        breakout_close=c1,
        breakout_vol=vol,
        breakout_vol_ratio=round(ratio, 4),
        combo_id=int(combo_id),
        combo_name=cname,
    )


def results_to_dataframe(rows: List[PatternResult]) -> pd.DataFrame:
    data = []
    for r in rows:
        data.append(
            {
                "symbol": r.symbol,
                "stock_name": r.stock_name,
                "pattern_id": r.pattern_id,
                "combo_id": r.combo_id,
                "combo_name": r.combo_name,
                "state": state_label_zh(r.state),
                "state_code": r.state,
                "select_tag": select_tag_for_state(r.state),
                "entry": r.entry,
                "position_frac": r.position_frac,
                "trial_ok": r.trial_ok,
                "add_ok": r.add_ok,
                "score": r.score,
                "signal_date": r.signal_date,
                "breakout_day": r.breakout_day,
                "platform_level": r.platform_level,
                "breakout_high": r.breakout_high,
                "breakout_close": r.breakout_close,
                "breakout_vol": r.breakout_vol,
                "panic_low": r.panic_low,
                "close": r.close,
                "pullback_bars": r.pullback_bars,
                "bars_since_breakout": r.bars_since_breakout,
                "pullback_ok": r.pullback_ok,
                "ma5_hold": r.ma5_hold,
                "macd_ok": r.macd_ok,
                "turnover_fade": r.turnover_fade,
                "notes": r.notes,
            }
        )
    return pd.DataFrame(data)


_STATE_RANK = {
    "entry": 0,
    "confirming": 1,
    "trial": 2,
    "candidate": 3,
    "watch": 4,
    "invalid": 5,
}


def scan_pattern_entry(
    anchors: List[WatchAnchor],
    *,
    end_date: str,
    history_calendar_days: int,
    cfg: dict,
) -> Tuple[List[PatternResult], List[str]]:
    results: List[PatternResult] = []
    skipped: List[str] = []
    end_dt = datetime.strptime(str(end_date)[:10], "%Y-%m-%d")
    start_dt = _calendar_start(end_dt, history_calendar_days)
    start_s = start_dt.strftime("%Y-%m-%d")
    end_s = end_dt.strftime("%Y-%m-%d")

    for anchor in anchors:
        sym = anchor.symbol
        try:
            name = anchor.stock_name or fetch_stock_name(sym) or ""
            ohlc = fetch_bars_with_turnover(sym, start_s, end_s)
            if ohlc is None or ohlc.empty or len(ohlc) < int(cfg["min_bars"]):
                skipped.append(f"{sym}(数据不足)")
                continue

            a = anchor
            if not a.breakout_day or not _finite(a.platform_level):
                inferred = _infer_anchor_from_ohlc(
                    ohlc,
                    symbol=sym,
                    stock_name=name,
                    combo_id=a.combo_id,
                )
                if inferred is None:
                    skipped.append(f"{sym}(无突破锚点)")
                    continue
                a = inferred
                a.stock_name = name or a.stock_name
            else:
                a.stock_name = name or a.stock_name

            if not a.combo_name:
                a.combo_name = (
                    "下跌放量" if int(a.combo_id) == 6 else "上涨放量突破"
                )

            pattern = get_pattern_for_combo(a.combo_id)
            res = pattern.evaluate(ohlc, a, end_date=end_s, cfg=cfg)
            results.append(res)
        except Exception as exc:
            skipped.append(f"{sym}({exc})")

    results.sort(
        key=lambda x: (
            0 if x.entry else 1,
            _STATE_RANK.get(x.state, 9),
            -float(x.position_frac),
            -float(x.score),
            x.symbol,
        )
    )
    return results, skipped


def _brief(r: PatternResult) -> str:
    label = f"{r.stock_name}({r.symbol})" if r.stock_name else r.symbol
    flag = state_label_zh(r.state)
    panic = f"  恐慌低={r.panic_low:.2f}" if _finite(r.panic_low) else ""
    path_hint = ""
    if r.state == "invalid" and (r.trial_ok or r.add_ok):
        path_hint = "  曾试仓" if r.trial_ok and not r.add_ok else "  曾加仓确认"
    return (
        f"  [{flag}] {label}  {r.pattern_id}  score={r.score:.0f}  "
        f"仓位={r.position_frac:.0%}  日={r.breakout_day}  "
        f"压力/平台={r.platform_level:.2f}  突破高={r.breakout_high:.2f}"
        f"{panic}  回踩={r.pullback_bars}日{path_hint}  → {r.notes or '-'}"
    )


def prune_invalid_watch_pools(results: List[PatternResult]) -> List[str]:
    """形态建仓判定为作废(invalid)的代码，从对应 combo 观察池剔除（可日后重新进池）。"""
    by_combo: Dict[int, List[str]] = {}
    for r in results:
        if r.state != "invalid":
            continue
        by_combo.setdefault(int(r.combo_id), []).append(r.symbol)
    notes: List[str] = []
    for cid, syms in sorted(by_combo.items()):
        _n, msg = remove_symbols_from_watch_pool(cid, syms)
        notes.append(msg)
    return notes


def collect_mx_push_symbols(results: List[PatternResult]) -> Tuple[List[str], List[str], List[str]]:
    """
    返回 (待选代码, 待选后通过代码, 实际推送列表)。
    待选 = candidate/trial/confirming（仅统计）；待选后通过 = entry。
    推送列表只含待选后通过。
    """
    dai: List[str] = []
    tong: List[str] = []
    seen_d: set = set()
    seen_t: set = set()
    for r in results:
        tag = select_tag_for_state(r.state)
        sym = _norm_symbol(r.symbol)
        if tag == "待选" and sym not in seen_d:
            seen_d.add(sym)
            dai.append(sym)
        elif tag == "待选后通过" and sym not in seen_t:
            seen_t.add(sym)
            tong.append(sym)
    return dai, tong, list(tong)


def push_selected_to_mx_group(
    results: List[PatternResult],
    *,
    group_name: str = MX_PUSH_GROUP_DEFAULT,
) -> List[str]:
    dai, tong, to_push = collect_mx_push_symbols(results)
    notes = [
        f"待选 {len(dai)} 只（不推送）· 待选后通过 {len(tong)} 只 · 推送 {len(to_push)} 只 →「{group_name}」"
    ]
    if not to_push:
        notes.append("无需推送（无待选后通过）")
        return notes
    _ok, push_notes = add_symbols_to_group(to_push, group_name=group_name)
    notes.extend(push_notes)
    return notes


def _fetch_daily_basic_asof(pro, end_date: str, *, max_back: int = 12) -> Tuple[pd.DataFrame, str]:
    """按交易日批量拉 daily_basic；若当日无数据则向前回溯。"""
    end_dt = datetime.strptime(str(end_date)[:10], "%Y-%m-%d")
    for i in range(max(1, int(max_back))):
        d = end_dt - timedelta(days=i)
        # 周末跳过
        if d.weekday() >= 5:
            continue
        ds = d.strftime("%Y%m%d")
        try:
            df = pro.daily_basic(
                trade_date=ds,
                fields="ts_code,trade_date,close,pe_ttm,pb",
            )
        except Exception:
            df = None
        if df is not None and not df.empty:
            return df, d.strftime("%Y-%m-%d")
    return pd.DataFrame(), ""


def rank_observation_pool_by_valuation(
    symbols: Sequence[str],
    *,
    end_date: str,
    name_map: Optional[Dict[str, str]] = None,
) -> Tuple[pd.DataFrame, List[str]]:
    """
    对观察池横截面算估值 upside 并降序排名。
    返回 (排名表, 说明)。
    """
    notes: List[str] = []
    uniq: List[str] = []
    seen = set()
    for s in symbols:
        sym = _norm_symbol(s)
        if len(sym) == 6 and sym not in seen:
            seen.add(sym)
            uniq.append(sym)
    if not uniq:
        return pd.DataFrame(), ["观察池为空，跳过估值排名"]

    try:
        from trend_pullback_chips import get_tushare_pro
        from backtest_sy_002028_threshold import six_digit_to_ts_code
        from market_neutral.factors.value import build_valuation_panel
        from market_neutral.data.prices import fetch_industry_map
    except Exception as exc:
        return pd.DataFrame(), [f"估值模块导入失败: {exc}"]

    try:
        pro = get_tushare_pro()
    except Exception as exc:
        return pd.DataFrame(), [f"Tushare 不可用: {exc}"]

    basic_all, asof = _fetch_daily_basic_asof(pro, end_date)
    if basic_all is None or basic_all.empty or not asof:
        return pd.DataFrame(), [f"无 daily_basic（截止 {end_date}）"]

    want_ts = {six_digit_to_ts_code(s): s for s in uniq}
    sub = basic_all[basic_all["ts_code"].astype(str).isin(want_ts.keys())].copy()
    if sub.empty:
        return pd.DataFrame(), [f"观察池股票在 {asof} 无估值行情"]

    sub["symbol"] = sub["ts_code"].map(lambda x: want_ts.get(str(x), ""))
    sub["date"] = pd.to_datetime(sub["trade_date"].astype(str))
    sub["pe_ttm"] = pd.to_numeric(sub["pe_ttm"], errors="coerce")
    sub["pb"] = pd.to_numeric(sub["pb"], errors="coerce")
    sub["close"] = pd.to_numeric(sub["close"], errors="coerce")
    basic = sub[["date", "symbol", "pe_ttm", "pb", "close"]]

    industry = fetch_industry_map(uniq)
    panel = build_valuation_panel(basic, industry)
    if panel.empty:
        return pd.DataFrame(), ["估值面板为空"]

    nm = name_map or {}
    # 取 asof 截面
    panel = panel.copy()
    panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()
    asof_ts = pd.Timestamp(asof).normalize()
    day = panel[panel["date"] == asof_ts]
    if day.empty:
        day = panel[panel["date"] == panel["date"].max()]
    day = day[day["upside"].notna()].copy()
    if day.empty:
        return pd.DataFrame(), [f"{asof} 无有效 upside（多为亏损无 PE）"]

    day = day.sort_values(["upside", "symbol"], ascending=[False, True]).reset_index(drop=True)
    day.insert(0, "rank", range(1, len(day) + 1))
    day["stock_name"] = day["symbol"].map(lambda s: nm.get(str(s), "") or "")
    day["asof"] = asof
    cols = [
        "rank",
        "asof",
        "symbol",
        "stock_name",
        "upside",
        "upside_raw",
        "fair_price",
        "close",
        "pe_ttm",
        "pe_ref",
        "industry",
        "undervalued",
    ]
    cols = [c for c in cols if c in day.columns]
    out = day[cols]
    notes.append(
        f"估值截面 {asof} · 有效 {len(out)}/{len(uniq)} 只 · 按 upside 降序"
    )
    return out, notes


def push_rank_top_to_mx_group(
    ranked: pd.DataFrame,
    *,
    top_n: int = VALUE_TOP_N_DEFAULT,
    group_name: str,
    score_col: str,
    label: str = "",
) -> Tuple[List[str], List[str]]:
    """推送任意排名表前 top_n 至东财自选分组。返回 (代码列表, 说明)。"""
    notes: List[str] = []
    n = max(1, int(top_n))
    tag = label or group_name
    if ranked is None or ranked.empty or "symbol" not in ranked.columns:
        notes.append(f"{tag} Top{n}：无排名结果，跳过推送「{group_name}」")
        return [], notes
    top = ranked.head(n)
    syms = [_norm_symbol(x) for x in top["symbol"].tolist()]
    syms = [s for s in syms if len(s) == 6]
    brief = []
    for _, r in top.iterrows():
        name = str(r.get("stock_name") or "")
        sc = r.get(score_col) if score_col in r.index else None
        if score_col == "upside" and sc is not None and sc == sc:
            sc_s = f"{100 * float(sc):.1f}%"
        elif sc is not None and sc == sc:
            sc_s = f"{float(sc):.3f}"
        else:
            sc_s = "-"
        brief.append(
            f"{r.get('symbol')}{(' ' + name) if name else ''} {score_col}={sc_s}"
        )
    notes.append(
        f"{tag} Top{n} →「{group_name}」: " + ("；".join(brief) if brief else "（空）")
    )
    if not syms:
        return [], notes
    _ok, push_notes = add_symbols_to_group(syms, group_name=group_name)
    notes.extend(push_notes)
    return syms, notes


def push_value_top_to_mx_group(
    ranked: pd.DataFrame,
    *,
    top_n: int = VALUE_TOP_N_DEFAULT,
    group_name: str = MX_VALUE_GROUP_DEFAULT,
) -> Tuple[List[str], List[str]]:
    """推送估值排名前 top_n 至东财自选「估值因子」。"""
    return push_rank_top_to_mx_group(
        ranked,
        top_n=top_n,
        group_name=group_name,
        score_col="upside",
        label="估值",
    )


def _write_rank_csv(path: str, df: pd.DataFrame, empty_cols: Sequence[str]) -> str:
    out = os.path.abspath(path)
    ddir = os.path.dirname(out)
    if ddir:
        os.makedirs(ddir, exist_ok=True)
    if df is not None and not df.empty:
        df.to_csv(out, index=False, encoding="utf-8-sig")
    else:
        pd.DataFrame(columns=list(empty_cols)).to_csv(
            out, index=False, encoding="utf-8-sig"
        )
    return out


def run_qm_rank_and_push(
    pool_syms: Sequence[str],
    *,
    end_date: str,
    name_map: Dict[str, str],
    top_n: int = QM_TOP_N_DEFAULT,
    skip_push: bool = False,
    skip_fina: bool = False,
    q_out_csv: str = DEFAULT_Q_OUT_CSV,
    mplus_out_csv: str = DEFAULT_MPLUS_OUT_CSV,
    mminus_out_csv: str = DEFAULT_MMINUS_OUT_CSV,
    q_group: str = MX_Q_GROUP_DEFAULT,
    mplus_group: str = MX_MPLUS_GROUP_DEFAULT,
    mminus_group: str = MX_MMINUS_GROUP_DEFAULT,
) -> List[str]:
    """观察池 Q/M+/M- 排名写 CSV，并 TopN 推东财自选「Q」「M加」「M减」。"""
    notes: List[str] = []
    try:
        from market_neutral.factors.daily_pool_rank import rank_observation_pool_qm
    except Exception as exc:
        return [f"Q/M 排名模块导入失败: {exc}"]

    ranked_map, rn = rank_observation_pool_qm(
        pool_syms,
        end_date=end_date,
        name_map=name_map,
        skip_fina=skip_fina,
    )
    notes.extend(rn)

    specs = [
        (
            "Q",
            ranked_map.get("Q"),
            q_out_csv,
            "company_q",
            q_group,
            ["rank", "asof", "symbol", "stock_name", "company_q", "roe", "ocf_to_or", "upside"],
        ),
        (
            "M+",
            ranked_map.get("M+"),
            mplus_out_csv,
            "mud_plus",
            mplus_group,
            ["rank", "asof", "symbol", "stock_name", "mud_plus", "r60", "vol_ratio"],
        ),
        (
            "M-",
            ranked_map.get("M-"),
            mminus_out_csv,
            "mud_minus",
            mminus_group,
            ["rank", "asof", "symbol", "stock_name", "mud_minus", "r20"],
        ),
    ]
    for label, df, path, score_col, group, empty_cols in specs:
        out = _write_rank_csv(path, df if df is not None else pd.DataFrame(), empty_cols)
        n_rows = 0 if df is None or df.empty else len(df)
        notes.append(f"{label} 排名表({n_rows}) → {out}")
        if skip_push:
            notes.append(f"已跳过「{group}」推送")
            continue
        _syms, pn = push_rank_top_to_mx_group(
            df if df is not None else pd.DataFrame(),
            top_n=top_n,
            group_name=group,
            score_col=score_col,
            label=label,
        )
        notes.extend(pn)
    return notes


def _top_symbols_from_rank_csv(path: str, top_n: int) -> List[str]:
    p = os.path.abspath(path)
    if not os.path.isfile(p):
        return []
    try:
        df = pd.read_csv(p, encoding="utf-8-sig")
    except Exception:
        return []
    if df is None or df.empty or "symbol" not in df.columns:
        return []
    n = max(1, int(top_n))
    out: List[str] = []
    seen = set()
    for raw in df["symbol"].head(n).tolist():
        s = _norm_symbol(raw)
        if len(s) == 6 and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def build_pattern_kelly_rows(
    results: List[PatternResult],
    *,
    name_map: Dict[str, str],
    mx_group: str = MX_PUSH_GROUP_DEFAULT,
    skip_mx_push: bool = False,
    mplus_csv: str = DEFAULT_MPLUS_OUT_CSV,
    mminus_csv: str = DEFAULT_MMINUS_OUT_CSV,
    qm_top_n: int = QM_TOP_N_DEFAULT,
    skip_qm: bool = False,
) -> Tuple[List[dict], List[str]]:
    """
    仅对「量能 / M加 / M减」推送池挂凯利（口径 A · 半凯利 · 上限 20%）。
    不包含估值因子、Q。
    """
    notes: List[str] = []
    rows: List[dict] = []

    # 量能：与推送一致，仅待选后通过
    if not skip_mx_push:
        _dai, tong, _ = collect_mx_push_symbols(results)
        r1, _st, n1 = build_kelly_rows_for_symbols(
            mx_group or MX_PUSH_GROUP_DEFAULT,
            tong,
            name_map=name_map,
        )
        rows.extend(r1)
        notes.extend(n1)
    else:
        notes.append("量能推送已跳过，不计算其凯利仓位")

    if not skip_qm:
        for group, path in (
            (MX_MPLUS_GROUP_DEFAULT, mplus_csv),
            (MX_MMINUS_GROUP_DEFAULT, mminus_csv),
        ):
            syms = _top_symbols_from_rank_csv(path, qm_top_n)
            r, _st, n = build_kelly_rows_for_symbols(group, syms, name_map=name_map)
            rows.extend(r)
            notes.extend(n)
    else:
        notes.append("Q/M 排名已跳过，不计算 M加/M减 凯利仓位")

    return rows, notes


def _combo_name_default(combo_id: int) -> str:
    return "下跌放量" if int(combo_id) == 6 else "上涨放量突破"


def resolve_all_anchors(
    *,
    symbols_arg: str,
    pool_path: str,
    watch_csv: str,
    combo_ids: List[int],
) -> Tuple[List[WatchAnchor], List[str]]:
    """按 combo 列表汇总观察锚点；--symbols/--pool 仅在单 combo 时覆盖。"""
    notes: List[str] = []
    cli = _parse_symbols_text(symbols_arg)
    if cli:
        if len(combo_ids) != 1:
            raise ValueError("--symbols 需同时指定单一 --combo-id（非 0）")
        cid = int(combo_ids[0])
        watch_df = load_watch_csv(watch_csv or watch_csv_path(cid))
        watch_map = {a.symbol: a for a in anchors_from_watch_df(watch_df)}
        notes.append(f"自定义 --symbols → {len(cli)} 只 · combo={cid}")
        return _anchors_for_symbols(cli, watch_map, cid), notes

    # 显式非空 pool 且单 combo
    pool = str(pool_path or "").strip()
    if pool and len(combo_ids) == 1:
        pool_syms = load_symbols_pool_txt(pool)
        if pool_syms:
            cid = int(combo_ids[0])
            wcsv = watch_csv or watch_csv_path(cid)
            watch_map = {a.symbol: a for a in anchors_from_watch_df(load_watch_csv(wcsv))}
            notes.append(f"自定义列表 {os.path.abspath(pool)} → {len(pool_syms)} 只 · combo={cid}")
            return _anchors_for_symbols(pool_syms, watch_map, cid), notes

    anchors: List[WatchAnchor] = []
    for cid in combo_ids:
        wcsv = watch_csv if (watch_csv and len(combo_ids) == 1) else watch_csv_path(cid)
        # 优先 per-combo symbols；空则用 watch csv
        sp = pattern_entry_symbols_path(cid)
        pool_syms = load_symbols_pool_txt(sp)
        watch_df = load_watch_csv(wcsv)
        watch_map = {a.symbol: a for a in anchors_from_watch_df(watch_df)}
        if pool_syms:
            part = _anchors_for_symbols(pool_syms, watch_map, cid)
            notes.append(f"combo[{cid}] symbols {sp} → {len(part)} 只")
        else:
            part = [a for a in watch_map.values() if int(a.combo_id) == int(cid)]
            if not part and not watch_df.empty and "combo_id" not in watch_df.columns:
                part = list(watch_map.values())
                for a in part:
                    a.combo_id = int(cid)
            notes.append(f"combo[{cid}] watch {os.path.abspath(wcsv)} → {len(part)} 只")
        for a in part:
            if not a.combo_name:
                a.combo_name = _combo_name_default(cid)
            a.combo_id = int(cid)
        anchors.extend(part)
    return anchors, notes


def main() -> None:
    cfg = dict(PATTERN_ENTRY_CONFIG)
    today = datetime.now().strftime("%Y-%m-%d")
    parser = argparse.ArgumentParser(
        description="形态建仓信号（上涨突破回踩 / 下跌放量反转）"
    )
    parser.add_argument(
        "--combo-id",
        type=int,
        default=0,
        help="上游六组合 id：4=上涨放量突破，6=下跌放量；0=全部已注册",
    )
    parser.add_argument(
        "--watch-csv",
        default="",
        help="观察列表 CSV（单 combo 时可覆盖；默认 vp_combo_watch_{id}.csv）",
    )
    parser.add_argument(
        "--pool",
        default="",
        help="股票列表 txt（单 combo 时非空则优先；默认按 combo 自动路径）",
    )
    parser.add_argument(
        "--symbols",
        default="",
        help="自定义代码（逗号/空白分隔）；需配合单一 --combo-id",
    )
    parser.add_argument("--end-date", default=today, help="截止日期 YYYY-MM-DD")
    parser.add_argument(
        "--days",
        type=int,
        default=int(cfg["history_calendar_days"]),
        help="回溯日历天数",
    )
    parser.add_argument("--out-csv", default=DEFAULT_OUT_CSV, help="输出 CSV")
    parser.add_argument(
        "--value-out-csv",
        default=DEFAULT_VALUE_OUT_CSV,
        help="观察池估值排名 CSV（默认 pattern_entry_valuation_rank.csv）",
    )
    parser.add_argument(
        "--mx-group",
        default=MX_PUSH_GROUP_DEFAULT,
        help="待选后通过推送的东财自选分组名（默认：量能）",
    )
    parser.add_argument(
        "--value-mx-group",
        default=MX_VALUE_GROUP_DEFAULT,
        help="估值 TopN 推送的东财自选分组名（默认：估值因子）",
    )
    parser.add_argument(
        "--value-top-n",
        type=int,
        default=VALUE_TOP_N_DEFAULT,
        help="估值排名推送只数（默认 2）",
    )
    parser.add_argument(
        "--skip-mx-push",
        action="store_true",
        help="不推送形态「待选后通过」到东财自选「量能」",
    )
    parser.add_argument(
        "--skip-value-rank",
        action="store_true",
        help="跳过观察池估值排名与「估值因子」推送",
    )
    parser.add_argument(
        "--skip-value-push",
        action="store_true",
        help="计算估值排名但不推送「估值因子」",
    )
    parser.add_argument(
        "--skip-qm-rank",
        action="store_true",
        help="跳过观察池 Q/M+/M- 排名与「Q」「M加」「M减」推送",
    )
    parser.add_argument(
        "--skip-qm-push",
        action="store_true",
        help="计算 Q/M 排名但不推送东财自选",
    )
    parser.add_argument(
        "--skip-qm-fina",
        action="store_true",
        help="Q 排名跳过财务拉取（仅用 upside 分位）",
    )
    parser.add_argument(
        "--qm-top-n",
        type=int,
        default=QM_TOP_N_DEFAULT,
        help="Q/M+/M- 各推送只数（默认 2）",
    )
    args = parser.parse_args()

    if int(args.combo_id) == 0:
        combo_ids = sorted(COMBO_DEFAULT_PATTERN.keys())
    else:
        combo_ids = [int(args.combo_id)]
        try:
            get_pattern_for_combo(combo_ids[0])
        except KeyError as exc:
            print(str(exc))
            sys.exit(2)

    try:
        anchors, notes = resolve_all_anchors(
            symbols_arg=str(args.symbols),
            pool_path=str(args.pool),
            watch_csv=str(args.watch_csv).strip(),
            combo_ids=combo_ids,
        )
    except ValueError as exc:
        print(str(exc))
        sys.exit(2)

    for n in notes:
        print(n)

    if not anchors:
        out_df = pd.DataFrame()
        out_path = os.path.abspath(args.out_csv)
        ddir = os.path.dirname(out_path)
        if ddir:
            os.makedirs(ddir, exist_ok=True)
        out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"无观察股票，已写空表: {out_path}")
        sys.exit(0)

    results, skipped = scan_pattern_entry(
        anchors,
        end_date=str(args.end_date),
        history_calendar_days=int(args.days),
        cfg=cfg,
    )
    out_df = results_to_dataframe(results)
    out_path = os.path.abspath(args.out_csv)
    ddir = os.path.dirname(out_path)
    if ddir:
        os.makedirs(ddir, exist_ok=True)
    out_df.to_csv(out_path, index=False, encoding="utf-8-sig")

    prune_notes = prune_invalid_watch_pools(results)
    mx_notes: List[str] = []
    if not bool(args.skip_mx_push):
        mx_notes = push_selected_to_mx_group(
            results, group_name=str(args.mx_group or MX_PUSH_GROUP_DEFAULT)
        )
    else:
        mx_notes = ["已跳过东财自选推送（--skip-mx-push）"]

    value_notes: List[str] = []
    value_path = ""
    name_map: Dict[str, str] = {}
    for a in anchors:
        if a.stock_name:
            name_map[_norm_symbol(a.symbol)] = str(a.stock_name)
    for r in results:
        if r.stock_name:
            name_map[_norm_symbol(r.symbol)] = str(r.stock_name)
    pool_syms = [_norm_symbol(a.symbol) for a in anchors]

    if not bool(args.skip_value_rank):
        ranked, vn = rank_observation_pool_by_valuation(
            pool_syms,
            end_date=str(args.end_date),
            name_map=name_map,
        )
        value_notes.extend(vn)
        value_path = os.path.abspath(str(args.value_out_csv or DEFAULT_VALUE_OUT_CSV))
        vdir = os.path.dirname(value_path)
        if vdir:
            os.makedirs(vdir, exist_ok=True)
        if ranked is not None and not ranked.empty:
            ranked.to_csv(value_path, index=False, encoding="utf-8-sig")
            value_notes.append(f"估值排名表 → {value_path}")
            if not bool(args.skip_value_push):
                _syms, pn = push_value_top_to_mx_group(
                    ranked,
                    top_n=int(args.value_top_n),
                    group_name=str(args.value_mx_group or MX_VALUE_GROUP_DEFAULT),
                )
                value_notes.extend(pn)
            else:
                value_notes.append("已跳过「估值因子」推送（--skip-value-push）")
        else:
            # 仍写空表，便于工作流「查看」
            pd.DataFrame(
                columns=[
                    "rank",
                    "asof",
                    "symbol",
                    "stock_name",
                    "upside",
                    "fair_price",
                    "close",
                    "pe_ttm",
                    "pe_ref",
                    "industry",
                ]
            ).to_csv(value_path, index=False, encoding="utf-8-sig")
            value_notes.append(f"估值排名空表 → {value_path}")
    else:
        value_notes = ["已跳过估值排名（--skip-value-rank）"]

    qm_notes: List[str] = []
    if not bool(args.skip_qm_rank):
        qm_notes = run_qm_rank_and_push(
            pool_syms,
            end_date=str(args.end_date),
            name_map=name_map,
            top_n=int(args.qm_top_n),
            skip_push=bool(args.skip_qm_push),
            skip_fina=bool(args.skip_qm_fina),
        )
    else:
        qm_notes = ["已跳过 Q/M 排名（--skip-qm-rank）"]

    kelly_notes: List[str] = []
    kelly_rows, kn = build_pattern_kelly_rows(
        results,
        name_map=name_map,
        mx_group=str(args.mx_group or MX_PUSH_GROUP_DEFAULT),
        skip_mx_push=bool(args.skip_mx_push),
        mplus_csv=DEFAULT_MPLUS_OUT_CSV,
        mminus_csv=DEFAULT_MMINUS_OUT_CSV,
        qm_top_n=int(args.qm_top_n),
        skip_qm=bool(args.skip_qm_rank),
    )
    kelly_notes.extend(kn)
    kelly_path = write_kelly_position_csv(kelly_rows, DEFAULT_KELLY_OUT_CSV)
    kelly_notes.append(f"凯利仓位表 → {kelly_path}")

    print("=" * 72)
    print(
        f"形态建仓 | combo={combo_ids} | 截止 {args.end_date} | "
        f"观察 {len(anchors)} | 结果 {len(results)} | CSV {out_path}"
    )
    print("【形态1】放量突破→缩量回踩→再放量突破")
    print("【形态2】下跌放量→止跌缩量→放量破压→缩量回踩→再放量创新高")
    if prune_notes:
        print("【观察池清理·仅作废】")
        for pn in prune_notes:
            print(f"  {pn}")
    if mx_notes:
        print("【东财自选·量能】")
        for pn in mx_notes:
            print(f"  {pn}")
    if value_notes:
        print("【估值因子】")
        for pn in value_notes:
            print(f"  {pn}")
    if qm_notes:
        print("【Q / M加 / M减】")
        for pn in qm_notes:
            print(f"  {pn}")
    if kelly_notes:
        print("【凯利仓位·量能/M加/M减】")
        for pn in kelly_notes:
            print(f"  {pn}")

    by_state: Dict[str, List[PatternResult]] = {}
    for r in results:
        by_state.setdefault(r.state, []).append(r)

    for st in STATE_PRINT_ORDER:
        group = by_state.get(st, [])
        print(f"—— {state_label_zh(st)}（{len(group)}）——")
        if not group:
            print("  （无）")
            continue
        for r in group:
            print(_brief(r))

    if skipped:
        print(
            "跳过: "
            + ", ".join(skipped[:40])
            + (" ..." if len(skipped) > 40 else "")
        )


if __name__ == "__main__":
    main()

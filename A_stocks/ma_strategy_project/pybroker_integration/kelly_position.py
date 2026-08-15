#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
凯利仓位（口径 A）：按因子/列表共用历史胜率 p 与盈亏比 b。

f* = p - (1-p)/b
建议仓位 = min(上限, 半凯利 × f*)

默认：半凯利 0.5、单票上限 20%。
p/b 来自市场中性仅多头净值曲线的月收益（*_L）。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MN_LATEST = os.path.join(_SCRIPT_DIR, "market_neutral", "output", "latest")
DEFAULT_COMBO23_LATEST = os.path.join(
    _SCRIPT_DIR, "market_neutral", "output", "combo23_latest"
)

HALF_KELLY = 0.5
KELLY_CAP = 0.20
MIN_MONTHS = 3

# 分组 → (仅多头变体, 默认 metrics 目录)
# 量能≈A、估值因子≈B；4+6 侧用 latest，2+3 侧用 combo23_latest
GROUP_VARIANT_MAP = {
    "量能": ("A_L", DEFAULT_MN_LATEST),
    "M加": ("M+_L", DEFAULT_MN_LATEST),
    "M减": ("M-_L", DEFAULT_MN_LATEST),
    "23M减": ("M-_L", DEFAULT_COMBO23_LATEST),
    "Q": ("Q_L", DEFAULT_COMBO23_LATEST),
    "估值因子": ("B_L", DEFAULT_COMBO23_LATEST),
}


@dataclass
class KellyStats:
    variant: str
    win_rate_p: float
    payoff_b: float
    kelly_full: float
    kelly_half: float
    kelly_pct: float
    n_months: int
    n_win: int
    n_loss: int
    source_dir: str
    ok: bool
    note: str = ""


def _norm_symbol(x) -> str:
    s = "".join(ch for ch in str(x) if ch.isdigit())
    return s.zfill(6) if s else ""


def kelly_fraction(p: float, b: float) -> float:
    """经典凯利：f* = p - (1-p)/b。无效输入返回 0。"""
    try:
        p_f = float(p)
        b_f = float(b)
    except Exception:
        return 0.0
    if not (0.0 <= p_f <= 1.0) or b_f <= 0 or p_f != p_f or b_f != b_f:
        return 0.0
    return max(0.0, p_f - (1.0 - p_f) / b_f)


def half_kelly_capped(
    p: float,
    b: float,
    *,
    half: float = HALF_KELLY,
    cap: float = KELLY_CAP,
) -> Tuple[float, float, float]:
    """返回 (kelly_full, kelly_half, kelly_pct 已封顶)。"""
    full = kelly_fraction(p, b)
    half_f = max(0.0, float(half) * full)
    capped = min(float(cap), half_f)
    return full, half_f, capped


def _monthly_returns_from_equity(eq: pd.DataFrame) -> pd.Series:
    work = eq.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work = work.dropna(subset=["date"])
    work["day_return"] = pd.to_numeric(work["day_return"], errors="coerce").fillna(0.0)
    work = work.sort_values("date")
    work["ym"] = work["date"].dt.to_period("M")
    return work.groupby("ym")["day_return"].apply(
        lambda x: float((1.0 + x).prod() - 1.0)
    )


def estimate_p_b_from_month_rets(
    month_ret: pd.Series,
) -> Tuple[float, float, int, int, int, str]:
    """
    p = 月胜率；b = 平均盈利月收益 / |平均亏损月收益|。
    样本不足或无法估 b 时 note 非空。
    """
    mr = pd.to_numeric(month_ret, errors="coerce").dropna()
    n = int(len(mr))
    if n < MIN_MONTHS:
        return 0.0, 0.0, n, 0, 0, f"月样本不足({n}<{MIN_MONTHS})"
    wins = mr[mr > 0]
    losses = mr[mr < 0]
    n_win = int(len(wins))
    n_loss = int(len(losses))
    p = float((mr > 0).mean())
    if n_loss <= 0:
        return p, 0.0, n, n_win, n_loss, "无亏损月，无法估盈亏比"
    if n_win <= 0:
        return p, 0.0, n, n_win, n_loss, "无盈利月，凯利为 0"
    avg_w = float(wins.mean())
    avg_l = abs(float(losses.mean()))
    if avg_l < 1e-12:
        return p, 0.0, n, n_win, n_loss, "平均亏损过小，无法估盈亏比"
    b = avg_w / avg_l
    return p, float(b), n, n_win, n_loss, ""


def load_kelly_stats(
    *,
    variant: str,
    source_dir: str,
    half: float = HALF_KELLY,
    cap: float = KELLY_CAP,
) -> KellyStats:
    src = os.path.abspath(source_dir)
    eq_path = os.path.join(src, "equity_curve.csv")
    if not os.path.isfile(eq_path):
        return KellyStats(
            variant=variant,
            win_rate_p=0.0,
            payoff_b=0.0,
            kelly_full=0.0,
            kelly_half=0.0,
            kelly_pct=0.0,
            n_months=0,
            n_win=0,
            n_loss=0,
            source_dir=src,
            ok=False,
            note=f"缺少净值曲线 {eq_path}",
        )
    try:
        eq = pd.read_csv(eq_path, encoding="utf-8-sig")
    except Exception as exc:
        return KellyStats(
            variant=variant,
            win_rate_p=0.0,
            payoff_b=0.0,
            kelly_full=0.0,
            kelly_half=0.0,
            kelly_pct=0.0,
            n_months=0,
            n_win=0,
            n_loss=0,
            source_dir=src,
            ok=False,
            note=f"读取净值失败: {exc}",
        )
    if eq.empty or "variant" not in eq.columns:
        return KellyStats(
            variant=variant,
            win_rate_p=0.0,
            payoff_b=0.0,
            kelly_full=0.0,
            kelly_half=0.0,
            kelly_pct=0.0,
            n_months=0,
            n_win=0,
            n_loss=0,
            source_dir=src,
            ok=False,
            note="净值表为空或无 variant 列",
        )
    sub = eq[eq["variant"].astype(str) == str(variant)].copy()
    if sub.empty:
        return KellyStats(
            variant=variant,
            win_rate_p=0.0,
            payoff_b=0.0,
            kelly_full=0.0,
            kelly_half=0.0,
            kelly_pct=0.0,
            n_months=0,
            n_win=0,
            n_loss=0,
            source_dir=src,
            ok=False,
            note=f"净值中无变体 {variant}",
        )
    month_ret = _monthly_returns_from_equity(sub)
    p, b, n, n_win, n_loss, note = estimate_p_b_from_month_rets(month_ret)
    if note:
        return KellyStats(
            variant=variant,
            win_rate_p=p,
            payoff_b=b,
            kelly_full=0.0,
            kelly_half=0.0,
            kelly_pct=0.0,
            n_months=n,
            n_win=n_win,
            n_loss=n_loss,
            source_dir=src,
            ok=False,
            note=note,
        )
    full, half_f, capped = half_kelly_capped(p, b, half=half, cap=cap)
    return KellyStats(
        variant=variant,
        win_rate_p=p,
        payoff_b=b,
        kelly_full=full,
        kelly_half=half_f,
        kelly_pct=capped,
        n_months=n,
        n_win=n_win,
        n_loss=n_loss,
        source_dir=src,
        ok=True,
        note=f"半凯利x{half:g} · 上限{100 * cap:.0f}%",
    )


def resolve_group_stats(
    group_name: str,
    *,
    source_dir_override: Optional[str] = None,
    half: float = HALF_KELLY,
    cap: float = KELLY_CAP,
) -> KellyStats:
    g = str(group_name or "").strip()
    mapped = GROUP_VARIANT_MAP.get(g)
    if not mapped:
        return KellyStats(
            variant="",
            win_rate_p=0.0,
            payoff_b=0.0,
            kelly_full=0.0,
            kelly_half=0.0,
            kelly_pct=0.0,
            n_months=0,
            n_win=0,
            n_loss=0,
            source_dir="",
            ok=False,
            note=f"分组「{g}」未配置凯利口径",
        )
    variant, default_dir = mapped
    src = source_dir_override or default_dir
    return load_kelly_stats(variant=variant, source_dir=src, half=half, cap=cap)


def build_kelly_rows_for_symbols(
    group_name: str,
    symbols: Sequence[str],
    *,
    name_map: Optional[Dict[str, str]] = None,
    source_dir_override: Optional[str] = None,
    half: float = HALF_KELLY,
    cap: float = KELLY_CAP,
) -> Tuple[List[dict], KellyStats, List[str]]:
    notes: List[str] = []
    stats = resolve_group_stats(
        group_name, source_dir_override=source_dir_override, half=half, cap=cap
    )
    names = name_map or {}
    rows: List[dict] = []
    syms: List[str] = []
    seen = set()
    for raw in symbols:
        s = _norm_symbol(raw)
        if len(s) != 6 or s in seen:
            continue
        seen.add(s)
        syms.append(s)

    if not stats.ok:
        notes.append(
            f"「{group_name}」凯利跳过：{stats.note}（variant={stats.variant or '-'}）"
        )
        for s in syms:
            rows.append(
                {
                    "group": group_name,
                    "symbol": s,
                    "stock_name": names.get(s, ""),
                    "variant": stats.variant,
                    "win_rate_p": stats.win_rate_p,
                    "payoff_b": stats.payoff_b,
                    "kelly_full": 0.0,
                    "kelly_half": 0.0,
                    "kelly_pct": 0.0,
                    "n_months": stats.n_months,
                    "source_dir": stats.source_dir,
                    "ok": False,
                    "note": stats.note,
                }
            )
        return rows, stats, notes

    notes.append(
        f"「{group_name}」p={100 * stats.win_rate_p:.1f}% b={stats.payoff_b:.2f} "
        f"f*={100 * stats.kelly_full:.1f}% 半凯利={100 * stats.kelly_half:.1f}% "
        f"建议={100 * stats.kelly_pct:.1f}% · {stats.variant} · 月样本{stats.n_months}"
    )
    for s in syms:
        rows.append(
            {
                "group": group_name,
                "symbol": s,
                "stock_name": names.get(s, ""),
                "variant": stats.variant,
                "win_rate_p": stats.win_rate_p,
                "payoff_b": stats.payoff_b,
                "kelly_full": stats.kelly_full,
                "kelly_half": stats.kelly_half,
                "kelly_pct": stats.kelly_pct,
                "n_months": stats.n_months,
                "source_dir": stats.source_dir,
                "ok": True,
                "note": stats.note,
            }
        )
        notes.append(
            f"  {s}{(' ' + names[s]) if names.get(s) else ''} "
            f"→ 建议仓位 {100 * stats.kelly_pct:.1f}%"
        )
    if not syms:
        notes.append(f"「{group_name}」无推送个股，仅记录因子凯利参数")
    return rows, stats, notes


def write_kelly_position_csv(
    rows: Iterable[dict],
    path: str,
) -> str:
    out = os.path.abspath(path)
    ddir = os.path.dirname(out)
    if ddir:
        os.makedirs(ddir, exist_ok=True)
    cols = [
        "group",
        "symbol",
        "stock_name",
        "variant",
        "win_rate_p",
        "payoff_b",
        "kelly_full",
        "kelly_half",
        "kelly_pct",
        "n_months",
        "source_dir",
        "ok",
        "note",
        "generated_at",
    ]
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data = []
    for r in rows:
        item = dict(r)
        item.setdefault("generated_at", ts)
        data.append(item)
    df = pd.DataFrame(data)
    if df.empty:
        df = pd.DataFrame(columns=cols)
    else:
        for c in cols:
            if c not in df.columns:
                df[c] = ""
        df = df[cols]
    df.to_csv(out, index=False, encoding="utf-8-sig")
    return out

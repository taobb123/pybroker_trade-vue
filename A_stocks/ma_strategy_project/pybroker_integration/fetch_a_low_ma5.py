#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
扫描「当前沿 MA5 多头运行」的持仓/观察名单（日线、前复权与项目 DataFetcher 一致）。

硬条件（同时满足才记为 in_trend / signal）：
1) 收盘不破 MA5：close >= MA5；
2) MA5 上翘：MA5[-1] > MA5[-2]；
3) MA10 翘头：MA10[-1] > MA10[-2]；
4) 量价：近窗内「上涨日」均量 > 「下跌日」均量（回踩缩量、上涨放量的日线近似）；
5) 收盘相对 MA5 的最大偏离率 |close−MA5|/close ≤ 5%（近 --hug-lookback 根 K）；
6) 阳多阴少：近 --volume-lookback 根 K 内，收涨天数 > 收跌天数（平盘不计）。

技术分（0–100，仅 OHLCV，不含板块/资金流）：贴线程度、5/10/20 多头、近窗量价结构、近几日收盘在 MA5 上方的持续性。
终端默认输出汇总、命中列表，以及池内 **未命中** 标的的单行摘要；`--diagnose` 时追加完整逐股诊断块。

数据：`backtest_sy_002028_threshold.fetch_ohlc_qfq`。

股票池：不传 `--symbols` 时默认读取本脚本同目录下的 `stocks_pool.txt`；`--pool` 可为绝对路径、相对路径或仅文件名（仅文件名时先 cwd 再回退脚本目录）。

用法（在 ma_strategy_project 目录下）：
    python pybroker_integration/fetch_a_low_ma5.py
    python pybroker_integration/fetch_a_low_ma5.py --symbols 002821,002378
    python pybroker_integration/fetch_a_low_ma5.py --diagnose
    python pybroker_integration/fetch_a_low_ma5.py --pool pybroker_integration/stocks_pool.txt --diagnose
    python pybroker_integration/fetch_a_low_ma5.py --all-rows --out-csv ma5_trend_all.csv
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

from backtest_sy_002028_threshold import fetch_ohlc_qfq, fetch_stock_name

STOCKS_POOL_TXT_BASENAME = "stocks_pool.txt"
DEFAULT_STOCKS_POOL_TXT = os.path.join(_SCRIPT_DIR, STOCKS_POOL_TXT_BASENAME)
DEFAULT_SCAN_OUT_CSV = os.path.join(_SCRIPT_DIR, "ma5_trend_scan.csv")

MA5_TREND_CONFIG = {
    "history_calendar_days": 200,
    "min_bars": 30,
    "hug_lookback_bars": 5,
    "volume_lookback_bars": 10,
    "persist_lookback_bars": 5,
    "max_deviation_pct": 5.0,
    "stocks_pool_txt": DEFAULT_STOCKS_POOL_TXT,
}


@dataclass(frozen=True)
class Ma5TrendSnapshot:
    symbol: str
    stock_name: str
    signal_date: str
    close: float
    ma5: float
    ma10: float
    ma20: float
    ma5_prev: float
    ma10_prev: float
    close_ge_ma5: bool
    ma5_up: bool
    ma10_up: bool
    vol_up_gt_down: bool
    ma5_max_deviation_pct: float
    deviation_ok: bool
    yang_gt_yin: bool
    yang_days: int
    yin_days: int
    vol_up_avg: float
    vol_down_avg: float
    vol_up_down_ratio: float
    signal: bool
    score_total: int
    score_hug: int
    score_stack: int
    score_volume: int
    score_persist: int
    days_close_ge_ma5_in_lookback: int


def _calendar_start(end_d: datetime, calendar_days: int) -> datetime:
    return end_d - timedelta(days=int(calendar_days))


def load_stocks_pool_txt(path: str) -> List[str]:
    """
    从文本文件读取股票代码：每行一个代码（可有前后空白），# 开头行为注释；
    兼容行内仅数字或逗号分隔时取第一段数字。
    编码依次尝试 utf-8-sig、utf-8、gbk。
    """
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


def resolve_stocks_pool_path(pool_arg: str) -> str:
    """
    解析股票池路径：默认同脚本目录下的 stocks_pool.txt。
    相对路径优先在当前工作目录查找；不存在时再尝试脚本所在目录（便于只写 stocks_pool.txt）。
    """
    raw = str(pool_arg or "").strip()
    if not raw:
        return os.path.abspath(DEFAULT_STOCKS_POOL_TXT)
    if os.path.isabs(raw):
        return os.path.abspath(raw)
    cwd_path = os.path.abspath(os.path.join(os.getcwd(), raw))
    if os.path.isfile(cwd_path):
        return cwd_path
    script_side = os.path.abspath(os.path.join(_SCRIPT_DIR, raw))
    if os.path.isfile(script_side):
        return script_side
    return cwd_path


def _score_hug_ma5(d: pd.DataFrame, lookback: int) -> Tuple[int, float]:
    """
    近 lookback 根 K（含当日）收盘相对 MA5 的平均偏离率 |close-ma5|/close，越小分越高。满分 30。
    """
    lb = max(1, int(lookback))
    if len(d) < lb:
        return 0, float("nan")
    seg = d.iloc[-lb:]
    c = pd.to_numeric(seg["close"], errors="coerce")
    m = pd.to_numeric(seg["ma5"], errors="coerce")
    ok = c.notna() & m.notna() & (c > 0)
    if not bool(ok.any()):
        return 0, float("nan")
    dev = ((c - m).abs() / c)[ok]
    mean_dev = float(dev.mean())
    if mean_dev != mean_dev:
        return 0, float("nan")
    # 0% -> 30 分；>=3% -> 0 分，之间线性
    cap = 0.03
    if mean_dev <= 0:
        return 30, mean_dev
    if mean_dev >= cap:
        return 0, mean_dev
    return int(round(30.0 * (1.0 - mean_dev / cap))), mean_dev


def _score_stack(ma5: float, ma10: float, ma20: float) -> int:
    """5>10>20 满分 25；仅 5>10 得 15；否则 0。"""
    if ma5 == ma5 and ma10 == ma10 and ma20 == ma20:
        if ma5 > ma10 > ma20:
            return 25
        if ma5 > ma10:
            return 15
    return 0


def _score_volume_structure(d: pd.DataFrame, lookback: int) -> Tuple[int, float]:
    """
    近 lookback 根 K：上涨日（close>昨收）均量 vs 下跌日均量，比值越大越好。满分 25。
    """
    lb = max(2, int(lookback))
    if len(d) < lb or "volume" not in d.columns:
        return 0, float("nan")
    seg = d.iloc[-lb:].copy()
    seg["prev_close"] = seg["close"].shift(1)
    seg["vol"] = pd.to_numeric(seg["volume"], errors="coerce")
    body = seg.iloc[1:]
    up = body[body["close"] > body["prev_close"]]
    down = body[body["close"] < body["prev_close"]]
    vu = float(up["vol"].mean()) if len(up) else float("nan")
    vd = float(down["vol"].mean()) if len(down) else float("nan")
    if vu != vu or vd != vd or vd <= 0:
        if vu != vu:
            return 0, float("nan")
        return 25, float("inf")
    ratio = vu / vd
    # ratio >= 1.5 -> 25；ratio <= 1 -> 0
    if ratio >= 1.5:
        return 25, ratio
    if ratio <= 1.0:
        return 0, ratio
    t = (ratio - 1.0) / 0.5
    return int(round(25.0 * t)), ratio


def _score_persist_close_ge_ma5(d: pd.DataFrame, lookback: int) -> Tuple[int, int]:
    """近 lookback 根 K 中收盘>=MA5 的天数：5/5->20 分，线性。满分 20。"""
    lb = max(1, int(lookback))
    if len(d) < lb:
        return 0, 0
    seg = d.iloc[-lb:]
    c = pd.to_numeric(seg["close"], errors="coerce")
    m = pd.to_numeric(seg["ma5"], errors="coerce")
    ok = c.notna() & m.notna()
    cnt = int(((c >= m) & ok).sum())
    score = int(round(20.0 * cnt / lb))
    return score, cnt


def _ma5_max_abs_deviation_pct(d: pd.DataFrame, lookback: int) -> float:
    """近 lookback 根 K（含当日）收盘相对 MA5 的最大偏离率 |close-ma5|/close，单位：百分比。"""
    lb = max(1, int(lookback))
    if len(d) < lb:
        return float("nan")
    seg = d.iloc[-lb:]
    c = pd.to_numeric(seg["close"], errors="coerce")
    m = pd.to_numeric(seg["ma5"], errors="coerce")
    ok = c.notna() & m.notna() & (c > 0)
    if not bool(ok.any()):
        return float("nan")
    dev_pct = ((c - m).abs() / c * 100.0)[ok]
    return float(dev_pct.max())


def _volume_up_down_means(d: pd.DataFrame, lookback: int) -> Tuple[float, float, float]:
    """
    近 lookback 根 K：上涨日（close>昨收）均量 vu、下跌日均量 vd、比值 vu/vd。
    若无下跌样本或 vd<=0，比值可为 nan；vu/vd 仍可能为 nan。
    """
    lb = max(2, int(lookback))
    if len(d) < lb or "volume" not in d.columns:
        return float("nan"), float("nan"), float("nan")
    seg = d.iloc[-lb:].copy()
    seg["prev_close"] = seg["close"].shift(1)
    seg["vol"] = pd.to_numeric(seg["volume"], errors="coerce")
    body = seg.iloc[1:]
    up = body[body["close"] > body["prev_close"]]
    down = body[body["close"] < body["prev_close"]]
    vu = float(up["vol"].mean()) if len(up) else float("nan")
    vd = float(down["vol"].mean()) if len(down) else float("nan")
    if vu != vu or vd != vd or vd <= 0:
        return vu, vd, float("nan")
    return vu, vd, vu / vd


def _yang_yin_counts(d: pd.DataFrame, lookback: int) -> Tuple[int, int]:
    """近 lookback 根 K 内：收涨天数、收跌天数（平盘不计；首根无昨收不参与）。"""
    lb = max(2, int(lookback))
    if len(d) < lb:
        return 0, 0
    seg = d.iloc[-lb:].copy()
    seg["prev_close"] = seg["close"].shift(1)
    body = seg.iloc[1:]
    yang = int((body["close"] > body["prev_close"]).sum())
    yin = int((body["close"] < body["prev_close"]).sum())
    return yang, yin


def _eval_ma5_trend(
    df: pd.DataFrame,
    *,
    min_bars: int,
    hug_lookback_bars: int,
    volume_lookback_bars: int,
    persist_lookback_bars: int,
    max_deviation_pct: float,
) -> Optional[Ma5TrendSnapshot]:
    need = max(
        int(min_bars),
        20 + 3,
        int(hug_lookback_bars) + 1,
        int(volume_lookback_bars) + 1,
        int(persist_lookback_bars) + 1,
    )
    if df is None or len(df) < need:
        return None

    d = df.sort_values("date").reset_index(drop=True).copy()
    d["ma5"] = d["close"].rolling(5, min_periods=5).mean()
    d["ma10"] = d["close"].rolling(10, min_periods=10).mean()
    d["ma20"] = d["close"].rolling(20, min_periods=20).mean()

    last = d.iloc[-1]
    prev = d.iloc[-2]

    c1 = float(last["close"])
    m5_1 = float(last["ma5"])
    m10_1 = float(last["ma10"])
    m20_1 = float(last["ma20"])
    m5_0 = float(prev["ma5"])
    m10_0 = float(prev["ma10"])

    if not all(x == x for x in (c1, m5_1, m10_1, m20_1, m5_0, m10_0)):
        return None

    close_ge_ma5 = c1 >= m5_1
    ma5_up = m5_1 > m5_0
    ma10_up = m10_1 > m10_0

    dev_max = _ma5_max_abs_deviation_pct(d, hug_lookback_bars)
    deviation_ok = (dev_max == dev_max) and (dev_max <= float(max_deviation_pct))

    vu, vd, v_ratio = _volume_up_down_means(d, volume_lookback_bars)
    vol_up_gt_down = (vu == vu) and (vd == vd) and vd > 0 and vu > vd

    yang_n, yin_n = _yang_yin_counts(d, volume_lookback_bars)
    yang_gt_yin = yang_n > yin_n

    signal = bool(
        close_ge_ma5
        and ma5_up
        and ma10_up
        and vol_up_gt_down
        and deviation_ok
        and yang_gt_yin
    )

    s_hug, _ = _score_hug_ma5(d, hug_lookback_bars)
    s_stack = _score_stack(m5_1, m10_1, m20_1)
    s_vol, _ = _score_volume_structure(d, volume_lookback_bars)
    s_persist, cnt_p = _score_persist_close_ge_ma5(d, persist_lookback_bars)
    total = int(max(0, min(100, s_hug + s_stack + s_vol + s_persist)))

    sym = str(last.get("symbol", "") or "").strip()
    nm = str(last.get("stock_name", "") or "").strip()
    dt = last["date"]
    try:
        ds = pd.Timestamp(dt).strftime("%Y-%m-%d")
    except Exception:
        ds = str(dt)[:10]

    return Ma5TrendSnapshot(
        symbol=sym,
        stock_name=nm,
        signal_date=ds,
        close=round(c1, 4),
        ma5=round(m5_1, 4),
        ma10=round(m10_1, 4),
        ma20=round(m20_1, 4),
        ma5_prev=round(m5_0, 4),
        ma10_prev=round(m10_0, 4),
        close_ge_ma5=close_ge_ma5,
        ma5_up=ma5_up,
        ma10_up=ma10_up,
        vol_up_gt_down=vol_up_gt_down,
        ma5_max_deviation_pct=round(dev_max, 4) if dev_max == dev_max else float("nan"),
        deviation_ok=deviation_ok,
        yang_gt_yin=yang_gt_yin,
        yang_days=yang_n,
        yin_days=yin_n,
        vol_up_avg=round(vu, 4) if vu == vu else float("nan"),
        vol_down_avg=round(vd, 4) if vd == vd else float("nan"),
        vol_up_down_ratio=round(v_ratio, 4) if v_ratio == v_ratio else float("nan"),
        signal=signal,
        score_total=total,
        score_hug=s_hug,
        score_stack=s_stack,
        score_volume=s_vol,
        score_persist=s_persist,
        days_close_ge_ma5_in_lookback=cnt_p,
    )


def _attach_symbol_meta(df: pd.DataFrame, symbol: str, stock_name: str) -> pd.DataFrame:
    out = df.copy()
    out["symbol"] = symbol
    out["stock_name"] = stock_name
    return out


def scan_ma5_trend(
    symbols: List[str],
    *,
    end_date: str,
    history_calendar_days: int,
    min_bars: int,
    hug_lookback_bars: int,
    volume_lookback_bars: int,
    persist_lookback_bars: int,
    max_deviation_pct: float,
) -> tuple[List[Ma5TrendSnapshot], List[str], List[Ma5TrendSnapshot]]:
    end_dt = pd.to_datetime(end_date).to_pydatetime()
    start_dt = _calendar_start(end_dt, history_calendar_days)
    start_s = start_dt.strftime("%Y-%m-%d")
    end_s = pd.Timestamp(end_date).strftime("%Y-%m-%d")

    hits: List[Ma5TrendSnapshot] = []
    evaluated: List[Ma5TrendSnapshot] = []
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
        snap = _eval_ma5_trend(
            df,
            min_bars=min_bars,
            hug_lookback_bars=hug_lookback_bars,
            volume_lookback_bars=volume_lookback_bars,
            persist_lookback_bars=persist_lookback_bars,
            max_deviation_pct=max_deviation_pct,
        )
        if snap is None:
            skipped.append(f"{sym}(数据不足)")
            continue
        evaluated.append(snap)
        if snap.signal:
            hits.append(snap)

    hits.sort(key=lambda x: (-x.score_total, x.symbol))
    return hits, skipped, evaluated


def snapshots_to_dataframe(snaps: List[Ma5TrendSnapshot]) -> pd.DataFrame:
    rows = []
    for s in snaps:
        rows.append(
            {
                "symbol": s.symbol,
                "stock_name": s.stock_name,
                "signal_date": s.signal_date,
                "close": s.close,
                "ma5": s.ma5,
                "ma10": s.ma10,
                "ma20": s.ma20,
                "ma5_prev": s.ma5_prev,
                "ma10_prev": s.ma10_prev,
                "close_ge_ma5": s.close_ge_ma5,
                "ma5_up": s.ma5_up,
                "ma10_up": s.ma10_up,
                "vol_up_gt_down": s.vol_up_gt_down,
                "ma5_max_deviation_pct": s.ma5_max_deviation_pct,
                "deviation_ok": s.deviation_ok,
                "yang_gt_yin": s.yang_gt_yin,
                "yang_days": s.yang_days,
                "yin_days": s.yin_days,
                "vol_up_avg": s.vol_up_avg,
                "vol_down_avg": s.vol_down_avg,
                "vol_up_down_ratio": s.vol_up_down_ratio,
                "in_trend": s.signal,
                "score_total": s.score_total,
                "score_hug": s.score_hug,
                "score_stack": s.score_stack,
                "score_volume": s.score_volume,
                "score_persist": s.score_persist,
                "days_close_ge_ma5": s.days_close_ge_ma5_in_lookback,
            }
        )
    return pd.DataFrame(rows)


def _failed_hard_reasons(s: Ma5TrendSnapshot) -> List[str]:
    failed: List[str] = []
    if not s.close_ge_ma5:
        failed.append("收盘跌破 MA5")
    if not s.ma5_up:
        failed.append("MA5 未上翘")
    if not s.ma10_up:
        failed.append("MA10 未上翘")
    if not s.vol_up_gt_down:
        failed.append("上涨未放量/回踩未缩量")
    if not s.deviation_ok:
        failed.append("收盘相对 MA5 最大偏离超过阈值")
    if not s.yang_gt_yin:
        failed.append("阳未多于阴")
    return failed


def _symbol_brief_line(s: Ma5TrendSnapshot) -> str:
    """终端默认：单行结论（命中/未中 + 技术分 + 简要原因）。"""
    label = f"{s.stock_name}({s.symbol})" if s.stock_name else s.symbol
    if s.signal:
        return (
            f"  [命中] {label}  {s.signal_date}  score={s.score_total}  "
            f"close={s.close:.4f}  ma5={s.ma5:.4f}"
        )
    reason = "；".join(_failed_hard_reasons(s)) or "未满足硬条件"
    return f"  [未中] {label}  {s.signal_date}  score={s.score_total}  {reason}"


def _symbol_diagnosis_lines(s: Ma5TrendSnapshot) -> List[str]:
    label = f"{s.stock_name}({s.symbol})" if s.stock_name else s.symbol
    lines: List[str] = [f"—— {label}  截止 {s.signal_date} ——"]
    lines.append(
        f"  收盘 {s.close:.4f}  MA5 {s.ma5:.4f}（昨 MA5 {s.ma5_prev:.4f}）  MA10 {s.ma10:.4f}（昨 {s.ma10_prev:.4f}）  MA20 {s.ma20:.4f}"
    )
    lines.append(
        "  硬条件: "
        + ("收盘≥MA5 " if s.close_ge_ma5 else "收盘<MA5 ")
        + ("；MA5 上翘 " if s.ma5_up else "；MA5 未上翘 ")
        + ("；MA10 上翘 " if s.ma10_up else "；MA10 未上翘 ")
        + ("；上涨放量/回踩缩量 " if s.vol_up_gt_down else "；量价结构未满足 ")
        + ("；偏离≤阈值 " if s.deviation_ok else "；偏离过大 ")
        + ("；阳>阴" if s.yang_gt_yin else "；阳未多于阴")
    )
    vr = (
        f"{s.vol_up_down_ratio:.4f}"
        if s.vol_up_down_ratio == s.vol_up_down_ratio
        else "-"
    )
    lines.append(
        f"  量价: 涨日均量/跌日均量≈{vr}  （阳 {s.yang_days} / 阴 {s.yin_days}）"
        f"  | 近窗收盘偏离 MA5 最大 {s.ma5_max_deviation_pct:.4f}%"
        if s.ma5_max_deviation_pct == s.ma5_max_deviation_pct
        else f"  量价: 涨日均量/跌日均量≈{vr}  （阳 {s.yang_days} / 阴 {s.yin_days}）  | 偏离 MA5 无法计算"
    )
    lines.append(
        f"  技术分: 合计 {s.score_total}（贴线 {s.score_hug} / 均线结构 {s.score_stack} / 量价 {s.score_volume} / 沿 MA5 持续性 {s.score_persist}；近窗收盘≥MA5 {s.days_close_ge_ma5_in_lookback} 天）"
    )
    if s.signal:
        lines.append("  **结论: 满足「沿 MA5 多头」硬条件。**")
    else:
        failed = _failed_hard_reasons(s)
        lines.append("  **结论: 未满足硬条件。** " + ("；".join(failed) if failed else ""))
    lines.append("")
    return lines


def natural_language_diagnosis_lines(
    s: Ma5TrendSnapshot,
    *,
    hug_lookback: int,
    volume_lookback: int,
    persist_lookback: int,
    max_deviation_pct: float,
) -> List[str]:
    """
    自然语言诊断：命中时为「沿 MA5 多头」可读说明；未命中时为未满足项摘要。
    供终端「满足硬条件」区块与 CSV 列 diagnosis_zh 使用。
    """
    label = f"{s.stock_name}({s.symbol})" if s.stock_name else s.symbol
    out: List[str] = []

    if s.signal:
        out.append(
            f"{label} 截至 {s.signal_date}：收盘价在五日线之上，五日线与十日线均较前一日抬高，"
            "短线呈现沿 MA5 运行的多头特征。"
        )
        if s.ma5 > s.ma10 > s.ma20:
            out.append(
                "均线结构为 5/10/20 多头排列，短中期趋势方向较为一致。"
            )
        elif s.ma5 > s.ma10:
            out.append(
                "五日线位于十日线之上，但中期均线尚未形成完整多头排列，需结合后续走势观察。"
            )
        else:
            out.append(
                "短期均线关系一般；本笔仍因其他硬条件与技术分项综合入选，宜谨慎看待均线结构。"
            )

        vr = (
            f"{s.vol_up_down_ratio:.2f}"
            if s.vol_up_down_ratio == s.vol_up_down_ratio
            else "无法计算"
        )
        out.append(
            f"量价上，近 {volume_lookback} 个交易日中阳线 {s.yang_days} 根、阴线 {s.yin_days} 根，阳多阴少；"
            f"上涨日平均成交量高于下跌日（相对约 {vr} 倍），符合「上涨放量、回踩缩量」的日线近似描述。"
        )

        if s.ma5_max_deviation_pct == s.ma5_max_deviation_pct:
            out.append(
                f"价格与五日线贴合度：近 {hug_lookback} 日收盘价相对 MA5 的最大偏离为 "
                f"{s.ma5_max_deviation_pct:.2f}%，未超过设定上限 {max_deviation_pct:g}%。"
            )
        else:
            out.append(
                f"价格与五日线偏离数据不足；硬条件已通过当日截面与其他项校验，近窗上限为 {max_deviation_pct:g}%。"
            )

        out.append(
            f"技术分 {s.score_total} 分（贴线 {s.score_hug}、均线结构 {s.score_stack}、量价 {s.score_volume}、"
            f"沿 MA5 持续性 {s.score_persist}）；近 {persist_lookback} 个交易日中 "
            f"{s.days_close_ge_ma5_in_lookback} 日收盘不低于 MA5。"
        )
    else:
        failed: List[str] = []
        if not s.close_ge_ma5:
            failed.append("收盘未站稳 MA5")
        if not s.ma5_up:
            failed.append("五日线未上翘")
        if not s.ma10_up:
            failed.append("十日线未上翘")
        if not s.vol_up_gt_down:
            failed.append("上涨日均量未大于下跌日均量")
        if not s.deviation_ok:
            failed.append(
                f"近 {hug_lookback} 日最大偏离超过 {max_deviation_pct:g}%"
            )
        if not s.yang_gt_yin:
            failed.append("阳线天数未多于阴线")
        out.append(
            f"{label} 截至 {s.signal_date}：未同时满足全部硬条件"
            + ("（" + "；".join(failed) + "）。" if failed else "。")
        )
        out.append(
            f"技术分 {s.score_total} 分（贴线 {s.score_hug}、结构 {s.score_stack}、量价 {s.score_volume}、"
            f"持续性 {s.score_persist}），仅作对照，不代表入选。"
        )

    return out


def _append_diagnosis_column(
    df: pd.DataFrame,
    snaps: List[Ma5TrendSnapshot],
    *,
    hug_lookback: int,
    volume_lookback: int,
    persist_lookback: int,
    max_deviation_pct: float,
) -> pd.DataFrame:
    if df.empty:
        return df
    texts = []
    for s in snaps:
        lines = natural_language_diagnosis_lines(
            s,
            hug_lookback=hug_lookback,
            volume_lookback=volume_lookback,
            persist_lookback=persist_lookback,
            max_deviation_pct=max_deviation_pct,
        )
        texts.append(" | ".join(lines))
    out = df.copy()
    out["diagnosis_zh"] = texts
    return out


def main() -> None:
    cfg = MA5_TREND_CONFIG
    parser = argparse.ArgumentParser(
        description="扫描：MA5 多头硬条件 + 量价/偏离/阳阴；输出技术分（无板块）"
    )
    parser.add_argument(
        "--pool",
        default=STOCKS_POOL_TXT_BASENAME,
        help=f"股票池文本；默认 {STOCKS_POOL_TXT_BASENAME}（解析为脚本同目录 {DEFAULT_STOCKS_POOL_TXT}）",
    )
    parser.add_argument(
        "--symbols",
        default="",
        help="逗号分隔 6 位代码；若非空则忽略 --pool，并对每只输出一行简要结果",
    )
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="输出完整逐股诊断块（收盘/均线/量价/技术分明细），置于终端末尾",
    )
    parser.add_argument(
        "--end-date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="评估截止日（含），默认今天",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=int(cfg.get("history_calendar_days", 200)),
        help="向前拉取的自然日长度",
    )
    parser.add_argument(
        "--min-bars",
        type=int,
        default=int(cfg.get("min_bars", 30)),
        help="至少需要多少根日线才评估",
    )
    parser.add_argument(
        "--hug-lookback",
        type=int,
        default=int(cfg.get("hug_lookback_bars", 5)),
        help="贴线评分用的近几根 K",
    )
    parser.add_argument(
        "--volume-lookback",
        type=int,
        default=int(cfg.get("volume_lookback_bars", 10)),
        help="量价评分用的近几根 K",
    )
    parser.add_argument(
        "--persist-lookback",
        type=int,
        default=int(cfg.get("persist_lookback_bars", 5)),
        help="沿 MA5 持续性评分用的近几根 K",
    )
    parser.add_argument(
        "--max-deviation-pct",
        type=float,
        default=float(cfg.get("max_deviation_pct", 5.0)),
        help="近 hug-lookback 根 K 内 |close-MA5|/close 最大偏离上限（%%），默认 5",
    )
    parser.add_argument(
        "--all-rows",
        action="store_true",
        help="CSV 输出池内全部股票（含未过硬条件），否则仅输出满足硬条件的标的",
    )
    parser.add_argument(
        "--out-csv",
        default=DEFAULT_SCAN_OUT_CSV,
        help=f"输出 CSV 路径（默认 {DEFAULT_SCAN_OUT_CSV}）",
    )
    args = parser.parse_args()

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
        pool_path = resolve_stocks_pool_path(str(args.pool))
        syms = load_stocks_pool_txt(pool_path)
        if not syms:
            print(f"股票池为空或文件不存在: {pool_path}")
            sys.exit(2)

    hits, skipped, evaluated = scan_ma5_trend(
        syms,
        end_date=str(args.end_date),
        history_calendar_days=int(args.days),
        min_bars=int(args.min_bars),
        hug_lookback_bars=int(args.hug_lookback),
        volume_lookback_bars=int(args.volume_lookback),
        persist_lookback_bars=int(args.persist_lookback),
        max_deviation_pct=float(args.max_deviation_pct),
    )

    if bool(args.all_rows):
        out_snaps = sorted(evaluated, key=lambda x: (-int(x.signal), -x.score_total, x.symbol))
    else:
        out_snaps = hits

    out_df = snapshots_to_dataframe(out_snaps)
    out_df = _append_diagnosis_column(
        out_df,
        out_snaps,
        hug_lookback=int(args.hug_lookback),
        volume_lookback=int(args.volume_lookback),
        persist_lookback=int(args.persist_lookback),
        max_deviation_pct=float(args.max_deviation_pct),
    )
    out_path = os.path.abspath(args.out_csv)
    ddir = os.path.dirname(out_path)
    if ddir:
        os.makedirs(ddir, exist_ok=True)
    out_df.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(
        f"MA5多头扫描 | 截止 {args.end_date} | 扫描 {len(syms)} 只 | 命中 {len(hits)} 只 | CSV {len(out_snaps)} 行"
    )
    if not symbols_from_cli:
        print(f"股票池: {pool_path}")
    print(f"已写入: {out_path}")

    print("=" * 72)
    print("【扫描结果】")
    if hits:
        for s in hits:
            print(_symbol_brief_line(s))
    else:
        print("  （无满足硬条件的标的）")

    misses = [x for x in evaluated if not x.signal]
    if misses:
        print("—— 未命中 ——")
        for snap in sorted(misses, key=lambda x: x.symbol):
            print(_symbol_brief_line(snap))

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

# -*- coding: utf-8 -*-
"""预测 K 线序列比较：真实 vs 预测红绿方向，生成 T+1 涨跌信号。"""

from __future__ import annotations

import json
import os
from typing import Any

import pandas as pd

from prediction_kline_chart import COMBINED_HIGHLOW_HISTORY_CSV
from stock_names import resolve_stock_names
from train_model_symbols import normalize_a_share_symbol

COMPARE_WINDOW_DAYS = 3
SIGNAL_CSV_NAME = "prediction_kline_signal.csv"
REGIME_SAME_BIAS = "same_bias"
REGIME_DIFF_BIAS = "diff_bias"


def kline_direction(open_p: float, close_p: float) -> str:
    """A 股习惯：close > open 为红柱，close < open 为绿柱。"""
    o = float(open_p)
    c = float(close_p)
    if c > o:
        return "red"
    if c < o:
        return "green"
    return "flat"


def bar_mid(row: dict[str, Any]) -> float:
    hi = float(row.get("high", row.get("close", 0)))
    lo = float(row.get("low", row.get("open", 0)))
    return (hi + lo) / 2.0


def kline_direction_open_close(open_p: float, close_p: float) -> str:
    """真实 K 线：close > open 为红柱，close < open 为绿柱。"""
    return kline_direction(open_p, close_p)


def predicted_sequence_direction(prev_mid: float | None, row: dict[str, Any]) -> str:
    """
    预测 K 线方向：与网页图表一致，用 (high+low)/2 相对前一根 mid 判断红/绿。
    综合高低模型 open=low、close=high，不能用 open/close 判断。
    """
    mid = bar_mid(row)
    if prev_mid is None:
        return "red"
    return "red" if mid >= prev_mid else "green"


def sequence_directions_for_rows(rows: list[dict[str, Any]]) -> list[str]:
    dirs: list[str] = []
    prev_mid: float | None = None
    for row in rows:
        dirs.append(predicted_sequence_direction(prev_mid, row))
        prev_mid = bar_mid(row)
    return dirs


def sequence_label(directions: list[str]) -> str:
    return "".join(direction_label(d)[0] for d in directions if d in ("red", "green"))


def direction_label(direction: str) -> str:
    return {"red": "红柱", "green": "绿柱", "flat": "平柱"}.get(direction, direction)


def prediction_label(direction: str) -> str:
    return {"up": "涨", "down": "跌", "flat": "平"}.get(direction, direction)


def directions_same(real_dir: str, pred_dir: str) -> bool:
    return real_dir == pred_dir and real_dir != "flat"


def predict_from_window(same_count: int, t1_pred_direction: str) -> tuple[str, str]:
    """
    根据 3 日相同数与 T+1 预测 K 线方向，返回 (predicted_direction, regime)。
    - same_count <= 1：赌后续继续相同 → 跟随 T+1 预测柱（红涨绿跌）
    - same_count > 1：赌后续转向不同 → 绿涨红跌
    """
    if t1_pred_direction == "flat":
        return "flat", REGIME_SAME_BIAS if same_count <= 1 else REGIME_DIFF_BIAS

    if same_count <= 1:
        regime = REGIME_SAME_BIAS
        if t1_pred_direction == "red":
            return "up", regime
        return "down", regime

    regime = REGIME_DIFF_BIAS
    if t1_pred_direction == "green":
        return "up", regime
    return "down", regime


def _load_combined_history(path: str) -> pd.DataFrame:
    if not os.path.isfile(path):
        return pd.DataFrame()
    df = pd.read_csv(path, encoding="utf-8-sig", dtype={"symbol": str})
    if df.empty:
        return df
    df = df.copy()
    df["symbol"] = df["symbol"].map(normalize_a_share_symbol)
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    if "anchor_t" in df.columns:
        df["anchor_t"] = pd.to_datetime(df["anchor_t"], errors="coerce").dt.strftime("%Y-%m-%d")
    if "is_future" in df.columns and df["is_future"].dtype != bool:
        df["is_future"] = (
            df["is_future"].astype(str).str.strip().str.lower().isin(["true", "1", "yes"])
        )
    return df.sort_values(["symbol", "date"])


def _real_directions_by_date(ohlc_df: pd.DataFrame) -> dict[str, str]:
    if ohlc_df is None or ohlc_df.empty:
        return {}
    out: dict[str, str] = {}
    for _, row in ohlc_df.iterrows():
        d = pd.to_datetime(row["date"], errors="coerce")
        if pd.isna(d):
            continue
        ds = d.strftime("%Y-%m-%d")
        if "open" not in row or "close" not in row:
            continue
        out[ds] = kline_direction(row["open"], row["close"])
    return out


def _fetch_real_directions(symbol: str, dates: list[str]) -> dict[str, str]:
    if not dates:
        return {}
    try:
        from backtest_sy_002028_threshold import fetch_ohlc_qfq
    except ImportError:
        return {}

    start = min(dates)
    end = max(dates)
    try:
        ohlc = fetch_ohlc_qfq(symbol, start, end)
    except Exception:
        return {}
    return _real_directions_by_date(ohlc)


def compute_signal_for_bars(
    hist_rows: list[dict[str, Any]],
    future_row: dict[str, Any] | None,
    real_dirs: dict[str, str],
    window_days: int = COMPARE_WINDOW_DAYS,
) -> dict[str, Any] | None:
    """对单只股票：取末 window_days 根历史 bar 比较，结合 T+1 预测 bar 出信号。"""
    if not hist_rows or future_row is None:
        return None
    window_rows = hist_rows[-window_days:]
    if len(window_rows) < window_days:
        return None

    all_pred_rows = hist_rows + [future_row]
    pred_dirs = sequence_directions_for_rows(all_pred_rows)
    window_start = len(hist_rows) - window_days

    day_details: list[dict[str, Any]] = []
    real_seq: list[str] = []
    pred_seq: list[str] = []
    same_count = 0
    for i, row in enumerate(window_rows):
        bar_date = str(row.get("date", ""))
        pred_dir = pred_dirs[window_start + i]
        real_dir = real_dirs.get(bar_date, "")
        is_same = directions_same(real_dir, pred_dir) if real_dir else False
        if is_same:
            same_count += 1
        if real_dir in ("red", "green"):
            real_seq.append(real_dir)
        if pred_dir in ("red", "green"):
            pred_seq.append(pred_dir)
        day_details.append(
            {
                "date": bar_date,
                "anchor_t": str(row.get("anchor_t", "")),
                "real_direction": real_dir,
                "pred_direction": pred_dir,
                "same": is_same,
            }
        )

    diff_count = window_days - same_count
    t1_date = str(future_row.get("date", ""))
    t1_pred_dir = pred_dirs[-1]
    predicted_direction, regime = predict_from_window(same_count, t1_pred_dir)
    anchor_t = str(future_row.get("anchor_t", ""))

    return {
        "symbol": normalize_a_share_symbol(str(future_row.get("symbol", ""))),
        "anchor_t": anchor_t,
        "t1_date": t1_date,
        "compare_dates": [d["date"] for d in day_details],
        "real_sequence": sequence_label(real_seq),
        "pred_sequence": sequence_label(pred_seq),
        "same_count": same_count,
        "diff_count": diff_count,
        "regime": regime,
        "regime_label": "后续相同概率偏高" if regime == REGIME_SAME_BIAS else "后续不同概率偏高",
        "day_details": day_details,
        "t1_pred_open": float(future_row.get("open", 0)),
        "t1_pred_close": float(future_row.get("close", 0)),
        "t1_pred_direction": t1_pred_dir,
        "t1_pred_direction_label": direction_label(t1_pred_dir),
        "predicted_direction": predicted_direction,
        "predicted_direction_label": prediction_label(predicted_direction),
    }


def build_signals_from_combined_csv(
    combined_csv_path: str,
    symbols: list[str] | None = None,
    fetch_real: bool = True,
) -> list[dict[str, Any]]:
    df = _load_combined_history(combined_csv_path)
    if df.empty:
        return []

    want = {normalize_a_share_symbol(s) for s in symbols} if symbols else None
    signals: list[dict[str, Any]] = []

    for sym, grp in df.groupby("symbol"):
        if want is not None and sym not in want:
            continue
        sub = grp.sort_values("date")
        if "is_future" in sub.columns:
            hist = sub[sub["is_future"] == False]  # noqa: E712
            fut = sub[sub["is_future"] == True]  # noqa: E712
        else:
            hist = sub.iloc[:-1]
            fut = sub.iloc[-1:]

        if hist.empty or fut.empty:
            continue

        hist_rows = hist.to_dict("records")
        future_row = fut.iloc[-1].to_dict()
        compare_dates = [str(r["date"]) for r in hist_rows[-COMPARE_WINDOW_DAYS:]]
        t1_date = str(future_row.get("date", ""))
        all_dates = sorted(set(compare_dates + ([t1_date] if t1_date else [])))

        real_dirs: dict[str, str] = {}
        if fetch_real:
            real_dirs = _fetch_real_directions(sym, all_dates)

        sig = compute_signal_for_bars(hist_rows, future_row, real_dirs)
        if sig:
            signals.append(sig)
    return signals


def attach_stock_names(
    signals: list[dict[str, Any]],
    names: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    name_map = names or {}
    for sig in signals:
        sym = normalize_a_share_symbol(str(sig.get("symbol", "")))
        sig["stock_name"] = name_map.get(sym, sym)
    return signals


def signals_to_csv_rows(signals: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for sig in signals:
        rows.append(
            {
                "stock_name": sig.get("stock_name", sig.get("symbol", "")),
                "t1_pred_direction_label": sig["t1_pred_direction_label"],
                "predicted_direction_label": sig["predicted_direction_label"],
                "anchor_t": sig["anchor_t"],
                "t1_date": sig["t1_date"],
                "compare_dates": "|".join(sig["compare_dates"]),
                "real_sequence": sig.get("real_sequence", ""),
                "pred_sequence": sig.get("pred_sequence", ""),
                "same_count": sig["same_count"],
                "diff_count": sig["diff_count"],
                "regime_label": sig["regime_label"],
                "predicted_direction": sig["predicted_direction"],
                "t1_pred_direction": sig["t1_pred_direction"],
                "regime": sig["regime"],
                "symbol": sig["symbol"],
            }
        )
    return pd.DataFrame(rows)


def write_signal_csv(
    signals: list[dict[str, Any]],
    out_path: str,
    names: dict[str, str] | None = None,
) -> int:
    attach_stock_names(signals, names)
    df = signals_to_csv_rows(signals)
    if df.empty:
        return 0
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    return len(df)


def enrich_charts_json_with_signals(
    payload: dict[str, Any],
    signals: list[dict[str, Any]],
) -> dict[str, Any]:
    by_symbol = {s["symbol"]: s for s in signals}
    for chart in payload.get("charts", []):
        sym = normalize_a_share_symbol(str(chart.get("symbol", "")))
        sig = by_symbol.get(sym)
        if sig:
            chart["symbol_name"] = sig.get("stock_name") or chart.get("symbol_name", sym)
            chart["signal"] = {
                k: sig[k]
                for k in (
                    "stock_name",
                    "anchor_t",
                    "t1_date",
                    "compare_dates",
                    "real_sequence",
                    "pred_sequence",
                    "same_count",
                    "diff_count",
                    "regime",
                    "regime_label",
                    "t1_pred_direction",
                    "t1_pred_direction_label",
                    "predicted_direction",
                    "predicted_direction_label",
                    "day_details",
                )
                if k in sig
            }
            if not chart["signal"].get("stock_name"):
                chart["signal"]["stock_name"] = chart.get("symbol_name", sym)
    payload["signal_rule"] = {
        "compare_window_days": COMPARE_WINDOW_DAYS,
        "real_direction": "真实 K 线：open/close 判断红/绿",
        "pred_direction": "预测 K 线：与图表一致，(high+low)/2 相对前一根 mid 判断红/绿",
        "t1_bar_source": "T+1 预测 K 线",
        "same_count_lte_1": "跟随 T+1 预测柱：红柱→涨，绿柱→跌",
        "same_count_gt_1": "反向解读 T+1 预测柱：绿柱→涨，红柱→跌",
        "output_primary": "predicted_direction_label（涨/跌）为最终预测，非 T+1 柱颜色本身",
    }
    return payload


def write_enriched_compare_json(
    compare_json_path: str,
    combined_csv_path: str,
    symbols: list[str] | None = None,
    fetch_real: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if not os.path.isfile(compare_json_path):
        return [], None
    with open(compare_json_path, encoding="utf-8") as f:
        payload = json.load(f)
    chart_symbols = [
        normalize_a_share_symbol(str(c.get("symbol", "")))
        for c in payload.get("charts", [])
    ]
    target = symbols or chart_symbols
    signals = build_signals_from_combined_csv(
        combined_csv_path,
        symbols=target,
        fetch_real=fetch_real,
    )
    payload = enrich_charts_json_with_signals(payload, signals)
    with open(compare_json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return signals, payload


def run_signal_pipeline(
    script_dir: str,
    symbols: list[str] | None = None,
    fetch_real: bool = True,
    stock_names: dict[str, str] | None = None,
) -> tuple[int, int, list[dict[str, Any]]]:
    combined = os.path.join(script_dir, COMBINED_HIGHLOW_HISTORY_CSV)
    compare_json = os.path.join(script_dir, "prediction_kline_compare.json")
    signal_csv = os.path.join(script_dir, SIGNAL_CSV_NAME)

    target_symbols = symbols
    if target_symbols is None and os.path.isfile(compare_json):
        with open(compare_json, encoding="utf-8") as f:
            payload = json.load(f)
        target_symbols = [
            normalize_a_share_symbol(str(c.get("symbol", "")))
            for c in payload.get("charts", [])
        ]

    names = dict(stock_names or {})
    if target_symbols and not names:
        names = resolve_stock_names(target_symbols)

    signals = build_signals_from_combined_csv(
        combined, symbols=target_symbols, fetch_real=fetch_real
    )
    attach_stock_names(signals, names)
    n_csv = write_signal_csv(signals, signal_csv, names=names)
    if os.path.isfile(compare_json):
        with open(compare_json, encoding="utf-8") as f:
            payload = json.load(f)
        payload = enrich_charts_json_with_signals(payload, signals)
        with open(compare_json, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    return n_csv, len(signals), signals

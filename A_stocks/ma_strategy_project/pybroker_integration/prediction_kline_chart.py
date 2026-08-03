# -*- coding: utf-8 -*-
"""预测 K 线：结果1+2 综合高低（四数排序）及 legacy 结果1/2 开收 K 线导出。"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

import pandas as pd

from train_model_symbols import normalize_a_share_symbol

HISTORY_DAYS = 20
FUTURE_BARS = 1
CHART_SYMBOL_COUNT = 4
COMPARE_JSON_NAME = "prediction_kline_compare.json"
MODEL_LABEL_RESULT1 = "结果1 · 预测下一交易日"
MODEL_LABEL_RESULT2 = "结果2 · 预测后两个交易日"
MODEL_LABEL_COMBINED = "结果1+2 · 综合预测高低"
MODEL_LABEL = MODEL_LABEL_COMBINED
COMBINED_HIGHLOW_HISTORY_CSV = "combined_highlow_history.csv"
RESULT1_WALKFORWARD_CSV = "result1_walkforward.csv"
RESULT2_WALKFORWARD_CSV = "result2_walkforward.csv"


def compute_high_low_from_preds(
    yesterday_price: float,
    result1_pred: float,
    result2_earlier_pred: float,
    result2_last_pred: float,
) -> tuple[float, float]:
    """四数排序：高价=两最大均值，低价=中间两数均值（与 compute_today_prices 一致）。"""
    computed1 = result2_last_pred + yesterday_price - result1_pred
    computed2 = result2_last_pred + yesterday_price - result2_earlier_pred
    arr = sorted([result1_pred, result2_earlier_pred, computed1, computed2])
    return (arr[2] + arr[3]) / 2.0, (arr[1] + arr[2]) / 2.0


def _pred_price(price: float, pred_return: float) -> float:
    return float(price) * (1.0 + float(pred_return)) if price else 0.0


def export_walkforward_csv(prediction_data: dict[str, dict[str, list]], csv_path: str) -> int:
    rows: list[dict[str, Any]] = []
    for sym, data in prediction_data.items():
        dates = data.get("dates") or []
        prices = data.get("prices") or []
        preds = data.get("predictions") or []
        n = min(len(dates), len(prices), len(preds))
        for i in range(n):
            p = float(prices[i])
            pr = float(preds[i])
            rows.append(
                {
                    "symbol": normalize_a_share_symbol(str(sym)),
                    "date": _format_date(dates[i]),
                    "current_price": round(p, 4),
                    "pred_return": round(pr, 6),
                    "predicted_price": round(_pred_price(p, pr), 4),
                }
            )
    if not rows:
        return 0
    os.makedirs(os.path.dirname(os.path.abspath(csv_path)) or ".", exist_ok=True)
    pd.DataFrame(rows).to_csv(csv_path, index=False, encoding="utf-8-sig")
    return len(rows)


def _load_walkforward_rows(path: str) -> dict[str, list[dict[str, Any]]]:
    if not os.path.isfile(path):
        return {}
    df = pd.read_csv(path, encoding="utf-8-sig", dtype={"symbol": str})
    if df.empty or "symbol" not in df.columns or "date" not in df.columns:
        return {}
    out: dict[str, list[dict[str, Any]]] = {}
    for sym, grp in df.groupby(df["symbol"].map(normalize_a_share_symbol)):
        rows = grp.sort_values("date").to_dict("records")
        out[str(sym)] = rows
    return out


def _bars_combined_highlow_for_symbol(
    r1_rows: list[dict[str, Any]],
    r2_rows: list[dict[str, Any]],
    symbol: str,
    trading_days_path: str | None = None,
) -> list[dict[str, Any]]:
    """锚定 T：四数综合高/低；K 线日=T+1；历史 walk-forward + 1 根未来。"""
    if len(r1_rows) < 2:
        return []
    r2_by_date = {_format_date(r["date"]): r for r in r2_rows}
    trading_cal = load_trading_dates(trading_days_path or "")
    sym = normalize_a_share_symbol(symbol)
    bars: list[dict[str, Any]] = []

    for j in range(1, len(r1_rows)):
        anchor = r1_rows[j]
        prev = r1_rows[j - 1]
        anchor_t = _format_date(anchor["date"])
        prev_t = _format_date(prev["date"])
        if prev_t not in r2_by_date or anchor_t not in r2_by_date:
            continue

        yesterday = float(anchor["current_price"])
        r1_pred = _pred_price(yesterday, float(anchor["pred_return"]))
        r2_earlier = _pred_price(
            float(r2_by_date[prev_t]["current_price"]),
            float(r2_by_date[prev_t]["pred_return"]),
        )
        r2_last = _pred_price(
            float(r2_by_date[anchor_t]["current_price"]),
            float(r2_by_date[anchor_t]["pred_return"]),
        )
        high, low = compute_high_low_from_preds(yesterday, r1_pred, r2_earlier, r2_last)

        is_future = j == len(r1_rows) - 1
        if is_future:
            bar_date = _date_plus_trading_days(anchor_t, 1, trading_cal)
        else:
            bar_date = _format_date(r1_rows[j + 1]["date"])

        bars.append(
            {
                "symbol": sym,
                "anchor_t": anchor_t,
                "date": bar_date,
                "high": round(high, 4),
                "low": round(low, 4),
                "open": round(low, 4),
                "close": round(high, 4),
                "result1_pred": round(r1_pred, 4),
                "result2_earlier_pred": round(r2_earlier, 4),
                "result2_last_pred": round(r2_last, 4),
                "is_future": is_future,
                "open_source": "综合高低",
            }
        )
    return bars


def build_combined_highlow_history_csv(
    result1_walkforward_csv: str,
    result2_walkforward_csv: str,
    out_csv_path: str,
    trading_days_path: str | None = None,
    today_high_low_csv: str | None = None,
    today_high_low_override: dict[str, tuple[float, float]] | None = None,
) -> int:
    """由两套 walk-forward CSV 生成综合高低 K 线历史；可选覆盖末根为未来当日高低。"""
    r1_map = _load_walkforward_rows(result1_walkforward_csv)
    r2_map = _load_walkforward_rows(result2_walkforward_csv)
    symbols = sorted(set(r1_map.keys()) & set(r2_map.keys()))
    all_rows: list[dict[str, Any]] = []

    override: dict[str, tuple[float, float]] = dict(today_high_low_override or {})
    if not override and today_high_low_csv and os.path.isfile(today_high_low_csv):
        try:
            th = pd.read_csv(today_high_low_csv, encoding="utf-8-sig", dtype={"symbol": str})
            if not th.empty and "today_high" in th.columns and "today_low" in th.columns:
                for _, row in th.iterrows():
                    sym = normalize_a_share_symbol(str(row["symbol"]))
                    override[sym] = (float(row["today_high"]), float(row["today_low"]))
        except Exception:
            pass

    for sym in symbols:
        bars = _bars_combined_highlow_for_symbol(
            r1_map[sym],
            r2_map[sym],
            sym,
            trading_days_path=trading_days_path,
        )
        if bars and sym in override:
            hi, lo = override[sym]
            bars[-1]["high"] = round(hi, 4)
            bars[-1]["low"] = round(lo, 4)
            bars[-1]["open"] = round(lo, 4)
            bars[-1]["close"] = round(hi, 4)
            bars[-1]["is_future"] = True
        all_rows.extend(bars)

    if not all_rows:
        return 0
    os.makedirs(os.path.dirname(os.path.abspath(out_csv_path)) or ".", exist_ok=True)
    pd.DataFrame(all_rows).to_csv(out_csv_path, index=False, encoding="utf-8-sig")
    return len(all_rows)


def _format_date(d: Any) -> str:
    if d is None:
        return ""
    if hasattr(d, "strftime"):
        return d.strftime("%Y-%m-%d")
    return str(d)


def load_trading_dates(path: str) -> list[str]:
    if not path or not os.path.isfile(path):
        return []
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        return []
    if "date" not in df.columns:
        return []
    return sorted(
        pd.to_datetime(df["date"], errors="coerce")
        .dropna()
        .dt.strftime("%Y-%m-%d")
        .astype(str)
        .tolist()
    )


def load_symbol_names(path: str) -> dict[str, str]:
    if not path or not os.path.isfile(path):
        return {}
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        return {}
    if "symbol" not in df.columns or "name" not in df.columns:
        return {}
    return dict(zip(df["symbol"].astype(str), df["name"].astype(str)))


def _date_plus_trading_days(
    t_date_str: str,
    steps: int,
    trading_cal: list[str],
) -> str:
    if steps <= 0:
        return t_date_str
    if trading_cal:
        try:
            idx = trading_cal.index(t_date_str)
            if idx + steps < len(trading_cal):
                return trading_cal[idx + steps]
        except ValueError:
            pass
        after = [d for d in trading_cal if d > t_date_str]
        if len(after) >= steps:
            return after[steps - 1]
    t_dt = pd.to_datetime(t_date_str, errors="coerce")
    if pd.isna(t_dt):
        return t_date_str
    return (t_dt + pd.tseries.offsets.BDay(steps)).strftime("%Y-%m-%d")


def _open_price_t_plus_1(
    prices: list,
    t_idx: int,
    t_date_str: str,
    symbol: str,
    result2_last2_csv: str | None,
) -> tuple[float, str]:
    """T+1 开价：优先数据内 T+1 收盘价，否则 result2 末行，否则 T 当前价。"""
    if t_idx + 1 < len(prices):
        return float(prices[t_idx + 1]), "T+1收盘价"
    if result2_last2_csv and os.path.isfile(result2_last2_csv):
        try:
            df = pd.read_csv(result2_last2_csv, encoding="utf-8-sig")
            sub = df[df["symbol"].astype(str) == str(symbol)].copy()
            if not sub.empty and "date" in sub.columns and "current_price" in sub.columns:
                sub["date_str"] = pd.to_datetime(sub["date"], errors="coerce").dt.strftime("%Y-%m-%d")
                sub = sub.sort_values("date_str")
                later = sub[sub["date_str"] > t_date_str]
                if not later.empty:
                    return float(later.iloc[0]["current_price"]), "T+1收盘价(结果2末表)"
                last_row = sub.iloc[-1]
                if str(last_row["date_str"]) > t_date_str:
                    return float(last_row["current_price"]), "T+1收盘价(结果2末表)"
        except Exception:
            pass
    return float(prices[t_idx]), "最新价(无T+1数据)"


def _bars_from_prediction_data_result1(
    prediction_data: dict[str, dict[str, list]],
    symbol: str,
    trading_days_path: str | None = None,
) -> list[dict[str, Any]]:
    """结果1：K 线日=T+1，开=T 价，收=T 预测价；历史 + 1 根未来。"""
    data = prediction_data.get(symbol)
    if not data:
        return []
    dates = data.get("dates") or []
    prices = data.get("prices") or []
    predictions = data.get("predictions") or []
    count = min(len(dates), len(prices), len(predictions))
    if count < 2:
        return []

    trading_cal = load_trading_dates(trading_days_path or "")
    bars: list[dict[str, Any]] = []

    for i in range(count - 1):
        anchor_t = _format_date(dates[i])
        bar_date = _format_date(dates[i + 1])
        open_p = float(prices[i])
        close_p = float(prices[i]) * (1 + float(predictions[i]))
        bars.append(
            {
                "symbol": normalize_a_share_symbol(symbol),
                "anchor_t": anchor_t,
                "date": bar_date,
                "open": round(open_p, 4),
                "close": round(close_p, 4),
                "pred_return": round(float(predictions[i]), 6),
                "is_future": False,
                "open_source": "T收盘价",
            }
        )

    t_idx = count - 1
    anchor_t = _format_date(dates[t_idx])
    open_p = float(prices[t_idx])
    close_p = float(prices[t_idx]) * (1 + float(predictions[t_idx]))
    if t_idx + 1 < count:
        bar_date = _format_date(dates[t_idx + 1])
    else:
        bar_date = _date_plus_trading_days(anchor_t, 1, trading_cal)

    bars.append(
        {
            "symbol": normalize_a_share_symbol(symbol),
            "anchor_t": anchor_t,
            "date": bar_date,
            "open": round(open_p, 4),
            "close": round(close_p, 4),
            "pred_return": round(float(predictions[t_idx]), 6),
            "is_future": True,
            "open_source": "T收盘价",
        }
    )
    return bars


def _bars_from_prediction_data_result2(
    prediction_data: dict[str, dict[str, list]],
    symbol: str,
    trading_days_path: str | None = None,
    result2_last2_csv: str | None = None,
) -> list[dict[str, Any]]:
    """结果2：K 线日=T+2，开=T+1 价，收=T 预测价；历史 + 1 根未来。"""
    data = prediction_data.get(symbol)
    if not data:
        return []
    dates = data.get("dates") or []
    prices = data.get("prices") or []
    predictions = data.get("predictions") or []
    count = min(len(dates), len(prices), len(predictions))
    if count < 2:
        return []

    trading_cal = load_trading_dates(trading_days_path or "")
    bars: list[dict[str, Any]] = []

    for i in range(count - 2):
        anchor_t = _format_date(dates[i])
        bar_date = _format_date(dates[i + 2])
        open_p = float(prices[i + 1])
        close_p = float(prices[i]) * (1 + float(predictions[i]))
        bars.append(
            {
                "symbol": normalize_a_share_symbol(symbol),
                "anchor_t": anchor_t,
                "date": bar_date,
                "open": round(open_p, 4),
                "close": round(close_p, 4),
                "pred_return": round(float(predictions[i]), 6),
                "is_future": False,
                "open_source": "T+1收盘价",
            }
        )

    t_idx = count - 1
    anchor_t = _format_date(dates[t_idx])
    open_p, open_src = _open_price_t_plus_1(
        prices, t_idx, anchor_t, symbol, result2_last2_csv
    )
    close_p = float(prices[t_idx]) * (1 + float(predictions[t_idx]))
    if t_idx + 2 < count:
        bar_date = _format_date(dates[t_idx + 2])
    else:
        bar_date = _date_plus_trading_days(anchor_t, 2, trading_cal)

    bars.append(
        {
            "symbol": normalize_a_share_symbol(symbol),
            "anchor_t": anchor_t,
            "date": bar_date,
            "open": round(open_p, 4),
            "close": round(close_p, 4),
            "pred_return": round(float(predictions[t_idx]), 6),
            "is_future": True,
            "open_source": open_src,
        }
    )
    return bars


# 兼容旧名
def _bars_from_prediction_data(
    prediction_data: dict[str, dict[str, list]],
    symbol: str,
    trading_days_path: str | None = None,
    result2_last2_csv: str | None = None,
) -> list[dict[str, Any]]:
    return _bars_from_prediction_data_result2(
        prediction_data,
        symbol,
        trading_days_path=trading_days_path,
        result2_last2_csv=result2_last2_csv,
    )


def export_result1_kline_csv(
    prediction_data: dict[str, dict[str, list]],
    csv_path: str,
    trading_days_path: str | None = None,
) -> int:
    all_rows: list[dict[str, Any]] = []
    for sym in prediction_data:
        all_rows.extend(
            _bars_from_prediction_data_result1(
                prediction_data,
                sym,
                trading_days_path=trading_days_path,
            )
        )
    if not all_rows:
        return 0
    os.makedirs(os.path.dirname(os.path.abspath(csv_path)) or ".", exist_ok=True)
    pd.DataFrame(all_rows).to_csv(csv_path, index=False, encoding="utf-8-sig")
    return len(all_rows)


def export_result2_kline_csv(
    prediction_data: dict[str, dict[str, list]],
    csv_path: str,
    trading_days_path: str | None = None,
    result2_last2_csv: str | None = None,
) -> int:
    all_rows: list[dict[str, Any]] = []
    for sym in prediction_data:
        all_rows.extend(
            _bars_from_prediction_data_result2(
                prediction_data,
                sym,
                trading_days_path=trading_days_path,
                result2_last2_csv=result2_last2_csv,
            )
        )
    if not all_rows:
        return 0
    os.makedirs(os.path.dirname(os.path.abspath(csv_path)) or ".", exist_ok=True)
    pd.DataFrame(all_rows).to_csv(csv_path, index=False, encoding="utf-8-sig")
    return len(all_rows)


def _read_kline_history_df(csv_path: str) -> pd.DataFrame:
    if not os.path.isfile(csv_path):
        return pd.DataFrame()
    df = pd.read_csv(csv_path, encoding="utf-8-sig", dtype={"symbol": str})
    if df.empty or "symbol" not in df.columns:
        return df
    df = df.copy()
    df["symbol"] = df["symbol"].map(normalize_a_share_symbol)
    if "is_future" in df.columns and df["is_future"].dtype != bool:
        df["is_future"] = (
            df["is_future"].astype(str).str.strip().str.lower().isin(["true", "1", "yes"])
        )
    return df


# 兼容旧名
def _read_result2_history_df(csv_path: str) -> pd.DataFrame:
    return _read_kline_history_df(csv_path)


def _chart_rows_for_symbol(
    csv_path: str,
    symbol: str,
    history_n: int = HISTORY_DAYS,
) -> list[dict[str, Any]]:
    df = _read_kline_history_df(csv_path)
    if df.empty:
        return []
    want = normalize_a_share_symbol(symbol)
    sub = df[df["symbol"] == want].copy()
    if sub.empty:
        return []
    if "is_future" in sub.columns:
        hist = sub[sub["is_future"] == False].sort_values("date")  # noqa: E712
        fut = sub[sub["is_future"] == True].sort_values("date")  # noqa: E712
    else:
        hist = sub.sort_values("date")
        fut = sub.iloc[0:0]
    hist = hist.tail(history_n)
    rows = hist.to_dict("records")
    if not fut.empty:
        rows.append(fut.iloc[-1].to_dict())
    return rows


def _chart_payload_from_rows(
    rows: list[dict[str, Any]],
    symbol: str,
    names: dict[str, str],
    history_n: int = HISTORY_DAYS,
    model_label: str = MODEL_LABEL,
) -> dict[str, Any]:
    dates: list[str] = []
    opens: list[float] = []
    closes: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    is_future: list[bool] = []
    anchor_ts: list[str] = []
    open_sources: list[str] = []

    for row in rows:
        dates.append(str(row.get("date", "")))
        hi = float(row.get("high", row.get("close", float("nan"))))
        lo = float(row.get("low", row.get("open", float("nan"))))
        highs.append(hi)
        lows.append(lo)
        opens.append(float(row.get("open", lo)))
        closes.append(float(row.get("close", hi)))
        is_future.append(bool(row.get("is_future", False)))
        anchor_ts.append(str(row.get("anchor_t", "")))
        open_sources.append(str(row.get("open_source", "")))

    return {
        "symbol": str(symbol),
        "symbol_name": names.get(str(symbol), str(symbol)),
        "history_days": history_n,
        "future_days": FUTURE_BARS,
        "model_label": model_label,
        "dates": dates,
        "opens": opens,
        "closes": closes,
        "highs": highs,
        "lows": lows,
        "is_future": is_future,
        "anchor_t": anchor_ts,
        "open_sources": open_sources,
    }


def build_charts_json(
    history_csv: str,
    symbols: list[str],
    out_json_path: str,
    symbol_names_path: str | None = None,
    symbol_names: dict[str, str] | None = None,
    history_n: int = HISTORY_DAYS,
    max_charts: int = CHART_SYMBOL_COUNT,
    model_label: str = MODEL_LABEL,
) -> dict[str, Any] | None:
    """为列表中前 max_charts 只股票生成单 JSON（charts 数组）。"""
    chart_syms = [normalize_a_share_symbol(s) for s in symbols[:max_charts]]
    names: dict[str, str] = {}
    if symbol_names:
        names = {
            normalize_a_share_symbol(str(k)): str(v)
            for k, v in symbol_names.items()
        }
    if not names:
        from stock_names import resolve_stock_names

        names = resolve_stock_names(chart_syms)
    csv_overrides = load_symbol_names(symbol_names_path or "")
    for sym, nm in csv_overrides.items():
        if nm and str(nm).strip():
            names[normalize_a_share_symbol(sym)] = str(nm).strip()
    charts: list[dict[str, Any]] = []
    for sym in symbols[:max_charts]:
        norm_sym = normalize_a_share_symbol(sym)
        rows = _chart_rows_for_symbol(history_csv, norm_sym, history_n=history_n)
        if not rows:
            continue
        charts.append(
            _chart_payload_from_rows(
                rows, norm_sym, names, history_n=history_n, model_label=model_label
            )
        )
    if not charts:
        return None

    payload: dict[str, Any] = {
        "chart_count": len(charts),
        "max_charts": max_charts,
        "history_days": history_n,
        "future_days": FUTURE_BARS,
        "model_label": model_label,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "charts": charts,
    }
    os.makedirs(os.path.dirname(os.path.abspath(out_json_path)) or ".", exist_ok=True)
    with open(out_json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return payload


def build_chart_json(
    history_csv: str,
    symbol: str,
    out_json_path: str,
    symbol_names_path: str | None = None,
    history_n: int = HISTORY_DAYS,
    model_label: str = MODEL_LABEL,
) -> dict[str, Any] | None:
    return build_charts_json(
        history_csv,
        [symbol],
        out_json_path,
        symbol_names_path=symbol_names_path,
        history_n=history_n,
        max_charts=1,
        model_label=model_label,
    )


# 兼容旧名
def build_compare_chart_json(
    result1_csv: str,
    result2_csv: str,
    symbol: str,
    out_json_path: str,
    symbol_names_path: str | None = None,
    n: int = HISTORY_DAYS,
) -> dict[str, Any] | None:
    return build_charts_json(
        result2_csv,
        [symbol],
        out_json_path,
        symbol_names_path=symbol_names_path,
        history_n=n,
        max_charts=1,
        model_label=MODEL_LABEL_RESULT2,
    )

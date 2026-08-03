#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
grid_buy 当日提示信号（不做回测、不算收益）。

- 只扫描「最近一个 SSE 交易日」（默认锚定今天；可用 --as-of / --end）。
- 买点基准 **仅** 使用 optimal_base_cost.csv 的 optimal_base_cost（表中有代码即用，与 start_date/end_date 无关；
  该两列仅表示表中基准的计算区间，可写入 detail 供对照，不参与过滤）。
  无表内记录的股票不参与。buy_price = round(base * (1 - BUY_OFFSET), 2) 仅作参考写入 detail。
- 触发判断：**现价 <= 基准**（基准为 optimal_base_cost）。现价优先取信号日 1 分钟线最后一根收盘
  （Tushare stk_mins，失败则 AkShare）；无分钟线时用信号日日线收盘价。detail 中的 intraday_* 有
  分钟则来自分钟聚合，否则用当日日线 low/high/close 填入以便对照。
- roc20_pct 仍由日线仅作参考（昨收相对 20 日前涨跌），不参与基准与触发。
- 申万一级与 sector_pct_day 需 tushare（可选）。

输出：UTF-8-SIG CSV（默认 rotation_trigger_buysingle_signals.csv）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import rotation_grid as rg  # noqa: E402
from backtest_sy_002028_threshold import fetch_ohlc_qfq, six_digit_to_ts_code  # noqa: E402
from rotation_trigger_history import (  # noqa: E402
    enrich_symbol_names,
    fetch_symbol_names,
    load_symbols,
)

DEFAULT_POOL = os.path.join(_SCRIPT_DIR, "stocks_pool.txt")
DEFAULT_OPTIMAL_CSV = os.path.join(_SCRIPT_DIR, "optimal_base_cost.csv")
DEFAULT_OUT = os.path.join(_SCRIPT_DIR, "rotation_trigger_buysingle_signals.csv")

# CSV 导出列顺序：在原先顺序上仅将「板块名称」sw_l1_name 挪到第 4 列（date,symbol,name 之后）
_SIGNAL_EXPORT_COLUMNS = (
    "date",
    "symbol",
    "name",
    "sw_l1_name",
    "strategy_id",
    "base_value",
    "base_source",
    "roc20_pct",
    "ma20_legacy",
    "sw_l1_code",
    "sector_pct_day",
    "buy_price",
    "intraday_low",
    "intraday_high",
    "intraday_last",
    "detail_json",
)


def reorder_signal_export_columns(df: pd.DataFrame) -> pd.DataFrame:
    """按固定列序导出；未知列排在末尾。"""
    full = list(_SIGNAL_EXPORT_COLUMNS)
    if df is None or df.empty:
        return pd.DataFrame(columns=full)
    ordered = [c for c in full if c in df.columns]
    extra = [c for c in df.columns if c not in ordered]
    return df[ordered + extra].copy()


def _write_csv(df: pd.DataFrame, path: str) -> str:
    try:
        df.to_csv(path, index=False, encoding="utf-8-sig")
        return path
    except PermissionError:
        base, ext = os.path.splitext(path)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        alt = f"{base}_{stamp}{ext if ext else '.csv'}"
        df.to_csv(alt, index=False, encoding="utf-8-sig")
        print(
            f"警告: 无法写入 \"{path}\"（文件可能被占用）。已改为: {alt}",
            file=sys.stderr,
        )
        return alt


def _parse_detail(detail_json: str) -> Dict[str, Any]:
    try:
        return json.loads(detail_json) if isinstance(detail_json, str) else {}
    except Exception:
        return {}


def last_sse_trade_on_or_before(anchor: pd.Timestamp, pro: Optional[Any]) -> pd.Timestamp:
    a = pd.Timestamp(anchor).normalize()
    if pro is not None:
        try:
            from rotation_trigger_buy_history import fetch_sse_trade_calendar  # noqa: E402

            start_c = (a - pd.Timedelta(days=60)).strftime("%Y%m%d")
            end_c = a.strftime("%Y%m%d")
            cal = fetch_sse_trade_calendar(pro, start_c, end_c)
            eligible = [d for d in cal if d <= a]
            if eligible:
                return eligible[-1]
        except Exception:
            pass
    return pd.bdate_range(end=a, periods=1)[0].normalize()


def _try_get_tushare_pro():
    try:
        from rotation_trigger_buy_history import (  # noqa: E402
            _get_pro,
            fetch_index_member_all,
            fetch_sw_l1_index_codes,
            load_sw_daily_pct_series,
            resolve_l1_on_date,
        )

        return (
            _get_pro(),
            fetch_sw_l1_index_codes,
            fetch_index_member_all,
            resolve_l1_on_date,
            load_sw_daily_pct_series,
        )
    except Exception as e:
        print(f"警告: 无法初始化 Tushare 申万映射（{e}），输出将不含行业指数列。", file=sys.stderr)
        return None, None, None, None, None


def load_optimal_base_by_symbol(csv_path: str) -> Dict[str, Dict[str, Any]]:
    """
    symbol(6位) -> {cost, csv_start_date, csv_end_date}，同代码多行取 updated_at 最新。
    csv_start_date / csv_end_date 仅写入 detail 说明用，不参与信号过滤。
    """
    if not os.path.isfile(csv_path):
        return {}
    try:
        df = pd.read_csv(csv_path, encoding="utf-8-sig")
    except Exception:
        return {}
    if df is None or df.empty or "symbol" not in df.columns or "optimal_base_cost" not in df.columns:
        return {}
    df = df.copy()
    df["symbol"] = df["symbol"].astype(str).map(lambda x: "".join(filter(str.isdigit, str(x))).zfill(6))
    if "updated_at" in df.columns:
        df["_ts"] = pd.to_datetime(df["updated_at"], errors="coerce")
    else:
        df["_ts"] = pd.Timestamp(0)
    df = df.sort_values("_ts").drop_duplicates("symbol", keep="last")
    out: Dict[str, Dict[str, Any]] = {}
    for _, r in df.iterrows():
        sym = str(r["symbol"]).zfill(6)
        try:
            cost = float(r["optimal_base_cost"])
        except Exception:
            continue
        if cost != cost or cost <= 0:
            continue
        def _cell_str(v: Any) -> str:
            if v is None:
                return ""
            try:
                if isinstance(v, float) and pd.isna(v):
                    return ""
            except Exception:
                pass
            s = str(v).strip()
            return "" if s.lower() in ("nan", "nat", "none") else s

        out[sym] = {
            "cost": cost,
            "csv_start_date": _cell_str(r.get("start_date")),
            "csv_end_date": _cell_str(r.get("end_date")),
        }
    return out


def _normalize_minute_df(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return None
    d = df.copy()
    cols = {c.lower(): c for c in d.columns}
    time_col = None
    for c in d.columns:
        cl = str(c).lower()
        if cl in ("trade_time", "time", "datetime") or str(c) in ("时间", "日期"):
            time_col = c
            break
    if time_col is None:
        time_col = d.columns[0]
    d["_t"] = pd.to_datetime(d[time_col], errors="coerce")
    d = d.dropna(subset=["_t"])
    if d.empty:
        return None

    def pick(*names: str) -> Optional[str]:
        lower = {str(x).lower(): x for x in d.columns}
        for n in names:
            if n in lower:
                return lower[n]
            if n.lower() in lower:
                return lower[n.lower()]
        return None

    oc = pick("open", "开盘")
    hc = pick("high", "最高")
    lc = pick("low", "最低")
    cc = pick("close", "收盘")
    if not all([oc, hc, lc, cc]):
        return None
    for c in (oc, hc, lc, cc):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=[oc, hc, lc, cc])
    if d.empty:
        return None
    d = d.sort_values("_t").reset_index(drop=True)
    d.rename(columns={oc: "open", hc: "high", lc: "low", cc: "close"}, inplace=True)
    return d[["open", "high", "low", "close"]]


def fetch_intraday_1min_bars(symbol6: str, trade_date: str, pro: Optional[Any]) -> Optional[pd.DataFrame]:
    """信号日 1 分钟 K 线（前复权口径由各源决定），列 open/high/low/close。"""
    ts_code = six_digit_to_ts_code(symbol6)
    ymd = trade_date.replace("-", "")
    if pro is not None:
        try:
            raw = pro.stk_mins(
                ts_code=ts_code,
                start_time=f"{ymd}093000",
                end_time=f"{ymd}150000",
                freq="1min",
            )
        except Exception:
            raw = None
        if raw is not None and not raw.empty:
            out = _normalize_minute_df(raw)
            if out is not None:
                return out
    try:
        import akshare as ak  # type: ignore

        start_s = f"{trade_date} 09:25:00"
        end_s = f"{trade_date} 15:05:00"
        raw = ak.stock_zh_a_hist_min_em(
            symbol=symbol6,
            period="1",
            start_date=start_s,
            end_date=end_s,
            adjust="qfq",
        )
    except Exception:
        return None
    return _normalize_minute_df(raw)


def intraday_ohlc_from_minutes(min_df: pd.DataFrame) -> Dict[str, float]:
    return {
        "intraday_low": float(min_df["low"].min()),
        "intraday_high": float(min_df["high"].max()),
        "intraday_last": float(min_df["close"].iloc[-1]),
    }


def scan_grid_buy_custom_base(
    symbols: List[str],
    signal_date: str,
    optimal_map: Dict[str, Dict[str, Any]],
    pro: Optional[Any],
) -> pd.DataFrame:
    """
    输出列与 scan_triggers 兼容：date, symbol, name, strategy_id, triggered, detail_json。
    """
    signal_ts = pd.Timestamp(signal_date).normalize()
    warm_start = (signal_ts - pd.Timedelta(days=90)).strftime("%Y-%m-%d")
    name_map = enrich_symbol_names(symbols, fetch_symbol_names(symbols))
    rows: List[Dict[str, Any]] = []

    for sym in symbols:
        sym = str(sym).zfill(6)
        rec = optimal_map.get(sym)
        if rec is None:
            continue
        base_val = float(rec["cost"])
        if not (base_val > 0) or base_val != base_val:
            continue
        base_source = "optimal_csv"

        try:
            raw = fetch_ohlc_qfq(sym, warm_start, signal_date)
        except Exception:
            continue
        if raw is None or raw.empty:
            continue
        prep = rg._prepare_frame(raw)
        prep = prep.dropna(subset=["ma20", "buy_price", "sell_price"])
        sub = prep[prep["date"] == signal_ts]
        if sub.empty:
            continue
        row = sub.iloc[0]
        ma_legacy = rg._to_float(row["ma20"])
        daily_low = rg._to_float(row["low"])
        daily_high = rg._to_float(row["high"])
        daily_close = rg._to_float(row["close"])

        hist = prep[prep["date"] <= signal_ts].sort_values("date").reset_index(drop=True)
        roc20_pct = float("nan")
        if len(hist) >= 22:
            prev_c = rg._to_float(hist.iloc[-2]["close"])
            c20 = rg._to_float(hist.iloc[-22]["close"])
            if c20 > 0 and prev_c == prev_c:
                roc20_pct = (prev_c / c20 - 1.0) * 100.0

        min_df = fetch_intraday_1min_bars(sym, signal_date, pro)
        spot_source = "daily_close"
        if min_df is not None and not min_df.empty:
            io = intraday_ohlc_from_minutes(min_df)
            ilo = io["intraday_low"]
            ihi = io["intraday_high"]
            ilast = io["intraday_last"]
            spot_px = ilast
            spot_source = "1min_last"
        else:
            ilo, ihi, ilast = daily_low, daily_high, daily_close
            spot_px = daily_close

        buy_p = round(base_val * (1.0 - rg.BUY_OFFSET), 2)
        sell_p = round(base_val * (1.0 + rg.SELL_OFFSET), 2)
        base_r = round(float(base_val), 2)
        spot_r = round(float(spot_px), 2)
        trig = base_val > 0 and spot_px == spot_px and spot_r <= base_r

        if not trig:
            continue

        detail = {
            "base_value": round(base_val, 4),
            "base_source": base_source,
            "optimal_csv_start_date": rec.get("csv_start_date") or None,
            "optimal_csv_end_date": rec.get("csv_end_date") or None,
            "roc20_pct": round(roc20_pct, 4) if roc20_pct == roc20_pct else None,
            "ma20_legacy": ma_legacy,
            "buy_price": buy_p,
            "sell_price": sell_p,
            "spot_price": round(spot_r, 4),
            "spot_source": spot_source,
            "intraday_low": round(ilo, 4),
            "intraday_high": round(ihi, 4),
            "intraday_last": round(ilast, 4),
            "daily_low": daily_low,
            "daily_high": daily_high,
            "daily_close": daily_close,
        }
        rows.append(
            {
                "date": signal_ts.strftime("%Y-%m-%d"),
                "symbol": sym,
                "name": name_map.get(sym, ""),
                "strategy_id": "grid_buy",
                "triggered": 1,
                "detail_json": json.dumps(detail, ensure_ascii=False),
            }
        )

    return pd.DataFrame(rows)


def build_buy_signals(
    trig: pd.DataFrame,
    pro,
    *,
    fetch_sw_l1_index_codes,
    fetch_index_member_all,
    resolve_l1_on_date,
    load_sw_daily_pct_series,
    signal_date_compact: str,
) -> pd.DataFrame:
    cols = list(_SIGNAL_EXPORT_COLUMNS)
    if trig is None or trig.empty:
        return pd.DataFrame(columns=cols)

    sw_l1_codes, sw_names = fetch_sw_l1_index_codes(pro)
    sym_mem: Dict[str, Any] = {}
    for sym in trig["symbol"].astype(str).map(lambda x: x.zfill(6)).unique():
        tc = six_digit_to_ts_code(sym)
        sym_mem[sym] = fetch_index_member_all(pro, tc, signal_date_compact)

    rows: List[Dict[str, Any]] = []
    l1_seen: Set[str] = set()
    for _, r in trig.iterrows():
        sym = str(r["symbol"]).zfill(6)
        dt = pd.to_datetime(r["date"], errors="coerce").normalize()
        if pd.isna(dt):
            continue
        d = _parse_detail(str(r.get("detail_json", "")))
        l1 = resolve_l1_on_date(sym_mem.get(sym), dt, sw_l1_codes)
        if l1:
            l1_seen.add(l1)
        rows.append(
            {
                "date": dt.strftime("%Y-%m-%d"),
                "symbol": sym,
                "name": str(r.get("name", "") or ""),
                "strategy_id": str(r.get("strategy_id", "grid_buy")),
                "base_value": d.get("base_value", ""),
                "base_source": d.get("base_source", ""),
                "roc20_pct": d.get("roc20_pct", ""),
                "ma20_legacy": d.get("ma20_legacy", ""),
                "sw_l1_code": l1 or "",
                "sw_l1_name": sw_names.get(l1, "") if l1 else "",
                "sector_pct_day": float("nan"),
                "buy_price": d.get("buy_price", ""),
                "intraday_low": d.get("intraday_low", ""),
                "intraday_high": d.get("intraday_high", ""),
                "intraday_last": d.get("intraday_last", ""),
                "detail_json": str(r.get("detail_json", "")),
            }
        )

    out = pd.DataFrame(rows)
    if l1_seen:
        pct_map = load_sw_daily_pct_series(pro, l1_seen, signal_date_compact, signal_date_compact)
        pcts: List[float] = []
        for _, rr in out.iterrows():
            code = str(rr.get("sw_l1_code", "") or "").strip()
            drow = pd.to_datetime(rr["date"], errors="coerce").normalize()
            if not code:
                pcts.append(float("nan"))
                continue
            s = pct_map.get(code, pd.Series(dtype=float))
            if drow in s.index and pd.notna(s.loc[drow]):
                pcts.append(round(float(s.loc[drow]), 4))
            else:
                pcts.append(float("nan"))
        out["sector_pct_day"] = pcts
    return reorder_signal_export_columns(out)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="grid_buy 当日提示：表内 optimal_base_cost，现价<=基准即提示 + 申万一级（不做回测）"
    )
    ap.add_argument("--pool", default=DEFAULT_POOL, help="股票列表文件")
    ap.add_argument(
        "--optimal-csv",
        default=DEFAULT_OPTIMAL_CSV,
        help="optimal_base_cost.csv 路径（仅表内有代码即用；start/end 列不参与过滤）",
    )
    ap.add_argument(
        "--as-of",
        default=None,
        metavar="YYYY-MM-DD",
        help="锚定日历日（默认今天）；取其及之前的最近开市日为信号日",
    )
    ap.add_argument(
        "--end",
        default=None,
        metavar="YYYY-MM-DD",
        help="与 --as-of 相同（兼容旧参数）",
    )
    ap.add_argument("--out", default=DEFAULT_OUT, help="输出 CSV")
    args = ap.parse_args()

    raw_anchor = args.as_of or args.end
    if raw_anchor:
        anchor = pd.Timestamp(raw_anchor).normalize()
    else:
        anchor = pd.Timestamp.today().normalize()

    pack = _try_get_tushare_pro()
    pro = pack[0]
    signal_day = last_sse_trade_on_or_before(anchor, pro)
    signal_str = signal_day.strftime("%Y-%m-%d")
    signal_c = signal_str.replace("-", "")

    syms = load_symbols(args.pool)
    if not syms:
        raise SystemExit(f"股票列表为空: {args.pool}")

    optimal_map = load_optimal_base_by_symbol(args.optimal_csv)
    if not optimal_map:
        print("提示: optimal_base_cost.csv 无有效数据，将不产生任何信号。", file=sys.stderr)
    trig = scan_grid_buy_custom_base(syms, signal_str, optimal_map, pro)

    if pro is not None and not trig.empty:
        out_df = build_buy_signals(
            trig,
            pro,
            fetch_sw_l1_index_codes=pack[1],
            fetch_index_member_all=pack[2],
            resolve_l1_on_date=pack[3],
            load_sw_daily_pct_series=pack[4],
            signal_date_compact=signal_c,
        )
    else:
        out_rows: List[Dict[str, Any]] = []
        for _, r in trig.iterrows():
            sym = str(r["symbol"]).zfill(6)
            d = _parse_detail(str(r.get("detail_json", "")))
            out_rows.append(
                {
                    "date": str(r.get("date", signal_str)),
                    "symbol": sym,
                    "name": str(r.get("name", "") or ""),
                    "strategy_id": str(r.get("strategy_id", "grid_buy")),
                    "base_value": d.get("base_value", ""),
                    "base_source": d.get("base_source", ""),
                    "roc20_pct": d.get("roc20_pct", ""),
                    "ma20_legacy": d.get("ma20_legacy", ""),
                    "sw_l1_code": "",
                    "sw_l1_name": "",
                    "sector_pct_day": float("nan"),
                    "buy_price": d.get("buy_price", ""),
                    "intraday_low": d.get("intraday_low", ""),
                    "intraday_high": d.get("intraday_high", ""),
                    "intraday_last": d.get("intraday_last", ""),
                    "detail_json": str(r.get("detail_json", "")),
                }
            )
        out_df = pd.DataFrame(out_rows)

    out_df = reorder_signal_export_columns(out_df)

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    path = _write_csv(out_df, args.out)
    print(f"信号交易日: {signal_str}（锚定 {anchor.strftime('%Y-%m-%d')}）")
    print(f"已写入 {path}，共 {len(out_df)} 条 grid_buy 提示信号")


if __name__ == "__main__":
    main()

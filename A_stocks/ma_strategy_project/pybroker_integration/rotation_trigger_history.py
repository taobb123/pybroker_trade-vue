#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多策略「纯条件」历史触发扫描（不做资金/持仓回测）。

- grid_buy / grid_sell：与 rotation_grid.py 一致的 MA20 网格触及（前复权、昨收 MA20）。
- grid5_buy / grid5_sell：grid5 买入 = 网格买入触及 + 日内涨跌幅带（rotation_grid_5pct.py）；
  卖出触及与 grid 相同。

输出：UTF-8-SIG CSV，默认仅输出行 triggered=1（可加 --all-rows 输出完整长表）。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from backtest_sy_002028_threshold import fetch_ohlc_qfq, fetch_stock_name  # noqa: E402

import rotation_grid as rg  # noqa: E402
import rotation_grid_5pct as rg5  # noqa: E402
from config.settings import DATA_CONFIG  # noqa: E402

DEFAULT_POOL = os.path.join(_SCRIPT_DIR, "stocks_pool.txt")
DEFAULT_OUT = os.path.join(_SCRIPT_DIR, "rotation_trigger_history.csv")
DEFAULT_MOMENTUM_OUT = os.path.join(_SCRIPT_DIR, "rotation_trigger_momentum_latest.csv")
DEFAULT_LOOKBACK_DAYS = 180

STRATEGY_IDS = (
    "grid_buy",
    "grid_sell",
    "grid5_buy",
    "grid5_sell",
)


def _symbol_six_digit(val: Any) -> str:
    """6 位数字证券代码（导出用）。"""
    return "".join(filter(str.isdigit, str(val))).zfill(6)


def _prepare_grid_base(raw: pd.DataFrame) -> pd.DataFrame:
    return rg._prepare_frame(raw)


def _prepare_grid5(raw: pd.DataFrame) -> pd.DataFrame:
    return rg5._prepare_frame(raw)


def load_symbols(path: str) -> List[str]:
    return rg.load_symbols_from_pool_file(path)


def fetch_symbol_names(symbols: List[str]) -> Dict[str, str]:
    """
    取股票名称映射（6位 code -> name）。
    依赖 Tushare stock_basic；若失败则返回空 dict（输出 name 置空）。
    """
    try:
        import tushare as ts  # type: ignore
    except Exception:
        return {}

    token = (DATA_CONFIG.get("tushare_token") or "").strip()
    if not token:
        return {}

    try:
        ts.set_token(token)
        pro = ts.pro_api()
        df = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
    except Exception:
        return {}

    if df is None or df.empty:
        return {}
    df = df.copy()
    df["symbol"] = df["ts_code"].map(lambda x: str(x).split(".")[0]).astype(str).str.zfill(6)
    m = dict(zip(df["symbol"].astype(str), df["name"].astype(str)))
    wanted = set(str(s).zfill(6) for s in symbols)
    return {s: m.get(s, "") for s in wanted}


def enrich_symbol_names(symbols: List[str], name_map: Dict[str, str]) -> Dict[str, str]:
    """在批量 Tushare 映射缺失时，用 fetch_stock_name（含 AkShare 回退）逐只补全。"""
    out = dict(name_map)
    for s in symbols:
        sym6 = str(s).zfill(6)
        if not (out.get(sym6) or "").strip():
            out[sym6] = fetch_stock_name(sym6)
    return out


def build_per_symbol_frames(
    symbols: List[str],
    start_date: str,
    end_date: str,
) -> Tuple[Dict[str, pd.DataFrame], Dict[str, pd.DataFrame], Set[pd.Timestamp]]:
    """返回 grid版、grid5 版（含 prev_close）日表，索引为 date。"""
    start_ts = pd.Timestamp(start_date)
    warm_start = (start_ts - pd.Timedelta(days=90)).strftime("%Y-%m-%d")

    per_g: Dict[str, pd.DataFrame] = {}
    per_g5: Dict[str, pd.DataFrame] = {}
    all_dates: Set[pd.Timestamp] = set()

    for sym in symbols:
        try:
            raw = fetch_ohlc_qfq(sym, warm_start, end_date)
        except Exception:
            continue
        if raw is None or raw.empty:
            continue
        g = _prepare_grid_base(raw)
        g5 = _prepare_grid5(raw)
        g = g.dropna(subset=["ma20", "buy_price", "sell_price"])
        g = g[(g["date"] >= start_ts) & (g["date"] <= pd.Timestamp(end_date))]
        g5 = g5.dropna(subset=["ma20", "buy_price", "sell_price"])
        g5 = g5[(g5["date"] >= start_ts) & (g5["date"] <= pd.Timestamp(end_date))]
        if g.empty or g5.empty:
            continue
        per_g[sym] = g.set_index("date")
        per_g5[sym] = g5.set_index("date")
        all_dates.update(g["date"].tolist())

    return per_g, per_g5, all_dates


def scan_triggers(
    symbols: List[str],
    start_date: str,
    end_date: str,
    *,
    strategies: Optional[Set[str]] = None,
    all_rows: bool = False,
) -> pd.DataFrame:
    name_map = enrich_symbol_names(symbols, fetch_symbol_names(symbols))
    strategies = strategies or set(STRATEGY_IDS)
    per_g, per_g5, all_dates = build_per_symbol_frames(symbols, start_date, end_date)
    if not per_g:
        return pd.DataFrame(
            columns=[
                "date",
                "symbol",
                "name",
                "strategy_id",
                "triggered",
                "detail_json",
            ]
        )

    dates = sorted(all_dates)
    rows: List[Dict[str, Any]] = []

    for dt in dates:
        for sym in symbols:
            sym = str(sym).zfill(6)
            if sym not in per_g:
                continue
            if dt not in per_g[sym].index:
                continue
            r = per_g[sym].loc[dt]
            if sym in per_g5 and dt in per_g5[sym].index:
                r5 = per_g5[sym].loc[dt]
            else:
                r5 = r
            low = rg._to_float(r["low"])
            high = rg._to_float(r["high"])
            buy_p = rg._to_float(r["buy_price"])
            sell_p = rg._to_float(r["sell_price"])
            ma = rg._to_float(r["ma20"])
            prev_close = rg._to_float(r5.get("prev_close", float("nan")))

            def emit(sid: str, trig: bool, detail: Dict[str, Any]) -> None:
                if not all_rows and not trig:
                    return
                rows.append(
                    {
                        "date": pd.Timestamp(dt).strftime("%Y-%m-%d"),
                        "symbol": sym,
                        "name": name_map.get(sym, ""),
                        "strategy_id": sid,
                        "triggered": int(bool(trig)),
                        "detail_json": json.dumps(detail, ensure_ascii=False),
                    }
                )

            if "grid_buy" in strategies:
                trig = ma > 0 and (low <= buy_p <= high)
                emit(
                    "grid_buy",
                    trig,
                    {
                        "ma20": ma,
                        "buy_price": buy_p,
                        "low": low,
                        "high": high,
                    },
                )

            if "grid_sell" in strategies:
                trig = high >= sell_p
                emit(
                    "grid_sell",
                    trig,
                    {
                        "sell_price": sell_p,
                        "high": high,
                    },
                )

            if "grid5_buy" in strategies:
                base_touch = ma > 0 and (low <= buy_p <= high)
                band = rg5._daily_pct_band_hit(
                    low,
                    high,
                    prev_close,
                    rg5.MORNING_PCT_MIN,
                    rg5.MORNING_PCT_MAX,
                )
                trig = base_touch and band
                emit(
                    "grid5_buy",
                    trig,
                    {
                        "ma20": ma,
                        "buy_price": buy_p,
                        "low": low,
                        "high": high,
                        "prev_close": prev_close,
                        "pct_band_min": rg5.MORNING_PCT_MIN,
                        "pct_band_max": rg5.MORNING_PCT_MAX,
                    },
                )

            if "grid5_sell" in strategies:
                trig = high >= sell_p
                emit(
                    "grid5_sell",
                    trig,
                    {
                        "sell_price": sell_p,
                        "high": high,
                    },
                )

    return pd.DataFrame(rows)


def build_latest_grid_sell_momentum(df: pd.DataFrame, last_n_trading_days: int = 2) -> pd.DataFrame:
    """
    基于输出结果中最近 N 个交易日的 grid_sell 触发记录（默认2），逐日计算动量：
    momentum = (high - sell_price) / sell_price
    并按动量降序排序；输出按日期升序拼接。
    另外，当最近交易日 >= 2 时，追加一段“今日-昨日 momentum_pct 差值”排序：
    diff = momentum_pct_today - momentum_pct_yesterday，且仅保留 diff > 0。
    """
    _mom_cols = [
        "rank",
        "date",
        "股票代码",
        "symbol",
        "name",
        "strategy_id",
        "sell_price",
        "high",
        "momentum",
        "momentum_pct",
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=_mom_cols)
    x = df.copy()
    x["date"] = pd.to_datetime(x["date"], errors="coerce")
    x = x[(x["strategy_id"] == "grid_sell") & (x["triggered"] == 1)]
    x = x.dropna(subset=["date"])
    if x.empty:
        return pd.DataFrame(columns=_mom_cols)

    n = max(1, int(last_n_trading_days))
    unique_dates = sorted(x["date"].unique())
    keep_dates = set(unique_dates[-n:])
    x = x[x["date"].isin(keep_dates)].copy()
    if x.empty:
        return pd.DataFrame(columns=_mom_cols)

    def _extract(detail_json: str) -> tuple[float, float]:
        try:
            d = json.loads(detail_json) if isinstance(detail_json, str) else {}
            sell_price = float(d.get("sell_price", float("nan")))
            high = float(d.get("high", float("nan")))
            return sell_price, high
        except Exception:
            return float("nan"), float("nan")

    def _one_day(sub: pd.DataFrame) -> pd.DataFrame:
        s = sub.copy()
        parsed = s["detail_json"].map(_extract)
        s["sell_price"] = parsed.map(lambda t: t[0])
        s["high"] = parsed.map(lambda t: t[1])
        s = s[(s["sell_price"] > 0) & (s["high"].notna())]
        s["momentum"] = (s["high"] - s["sell_price"]) / s["sell_price"]
        s["momentum_pct"] = s["momentum"] * 100.0
        s = s.sort_values("momentum", ascending=False).reset_index(drop=True)
        s["rank"] = s.index + 1
        s["date"] = s["date"].dt.strftime("%Y-%m-%d")
        s["symbol"] = s["symbol"].map(_symbol_six_digit)
        s["股票代码"] = s["symbol"]
        return s[_mom_cols]

    parts: List[pd.DataFrame] = []
    for d in sorted(keep_dates):
        sub = x[x["date"] == d]
        if not sub.empty:
            parts.append(_one_day(sub))
    if not parts:
        return pd.DataFrame(columns=_mom_cols)
    out = pd.concat(parts, ignore_index=True)

    # 追加“今日-昨日 momentum_pct 差值（仅正值）”排序段
    if len(unique_dates) >= 2:
        d_prev = unique_dates[-2]
        d_today = unique_dates[-1]
        prev_df = out[out["date"] == pd.Timestamp(d_prev).strftime("%Y-%m-%d")][["symbol", "momentum_pct"]].copy()
        prev_df = prev_df.rename(columns={"momentum_pct": "momentum_pct_prev"})
        today_df = out[out["date"] == pd.Timestamp(d_today).strftime("%Y-%m-%d")].copy()
        if not prev_df.empty and not today_df.empty:
            merged = today_df.merge(prev_df, on="symbol", how="inner")
            merged["momentum_pct_diff"] = merged["momentum_pct"] - merged["momentum_pct_prev"]
            merged = merged[merged["momentum_pct_diff"] > 0].copy()
            if not merged.empty:
                merged = merged.sort_values("momentum_pct_diff", ascending=False).reset_index(drop=True)
                merged["rank"] = merged.index + 1
                merged["strategy_id"] = "grid_sell_momentum_diff_pos"
                merged["momentum_pct"] = merged["momentum_pct_diff"]
                merged["momentum"] = merged["momentum_pct"] / 100.0
                merged["date"] = pd.Timestamp(d_today).strftime("%Y-%m-%d")
                out = pd.concat([out, merged[_mom_cols]], ignore_index=True)

    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="rotation多策略条件历史触发扫描 → CSV")
    ap.add_argument("--pool", default=DEFAULT_POOL, help="股票列表文件，一行一只代码")
    ap.add_argument("--start", default=None, help="YYYY-MM-DD；不传则按 end/lookback-days 推导")
    ap.add_argument("--end", default=None, help="YYYY-MM-DD；不传默认今天")
    ap.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS, help="回测天数（默认180）")
    ap.add_argument("--out", default=DEFAULT_OUT, help="输出 CSV 路径")
    ap.add_argument(
        "--momentum-out",
        default=DEFAULT_MOMENTUM_OUT,
        help="最近两个交易日 grid_sell 动量排序结果 CSV 路径",
    )
    ap.add_argument(
        "--strategies",
        default="all",
        help="逗号分隔：grid_buy,grid_sell,grid5_buy,grid5_sell 或 all",
    )
    ap.add_argument(
        "--all-rows",
        action="store_true",
        help="输出全部 (date,symbol,strategy) 含 triggered=0；默认仅 triggered=1",
    )
    args = ap.parse_args()
    if args.end:
        end_ts = pd.Timestamp(args.end).normalize()
    else:
        end_ts = pd.Timestamp.today().normalize()
    if args.start:
        start_ts = pd.Timestamp(args.start).normalize()
    else:
        start_ts = (end_ts - pd.Timedelta(days=max(1, int(args.lookback_days)))).normalize()
    if start_ts > end_ts:
        raise SystemExit("start 不能晚于 end")
    start_str = start_ts.strftime("%Y-%m-%d")
    end_str = end_ts.strftime("%Y-%m-%d")

    syms = load_symbols(args.pool)
    if not syms:
        raise SystemExit(f"股票列表为空: {args.pool}")

    if args.strategies.strip().lower() == "all":
        strat: Set[str] = set(STRATEGY_IDS)
    else:
        strat = {s.strip() for s in args.strategies.split(",") if s.strip()}
        bad = strat - set(STRATEGY_IDS)
        if bad:
            raise SystemExit(f"未知 strategy_id: {bad}，可选 {STRATEGY_IDS}")

    df = scan_triggers(
        syms,
        start_str,
        end_str,
        strategies=strat,
        all_rows=args.all_rows,
    )
    if not args.all_rows and not df.empty:
        df = df[df["triggered"] == 1].reset_index(drop=True)

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    df.to_csv(args.out, index=False, encoding="utf-8-sig")
    print(f"已写入 {args.out}，共 {len(df)} 行")
    if not df.empty:
        print(df["strategy_id"].value_counts().to_string())

    mom = build_latest_grid_sell_momentum(df)
    mo_dir = os.path.dirname(os.path.abspath(args.momentum_out))
    if mo_dir:
        os.makedirs(mo_dir, exist_ok=True)
    mom.to_csv(args.momentum_out, index=False, encoding="utf-8-sig")
    print(f"已写入 {args.momentum_out}，共 {len(mom)} 行")
    if not mom.empty:
        print("最近交易日 grid_sell 动量 Top5（按文件内顺序）:")
        print(mom.head(5).to_string(index=False))


if __name__ == "__main__":
    main()

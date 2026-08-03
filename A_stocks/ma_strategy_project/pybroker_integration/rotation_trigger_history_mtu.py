#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MTU：基准价触发 + 最新收盘日动量提示（不做资金回测）。

1) 按 optimal_base_cost 与阈值扫描触发；grid_sell 的触发价来自基准价×(1+加成)。
2) 动量（仅 grid_sell 触发标的）：momentum = (high - sell_price) / sell_price，sell_price 即触发价。
3) 「今天」= 全市场数据中出现的最新交易日（交易所最新一根日 K 的日期）；只输出该日的动量提示（控制台，可选 CSV）。
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

from rotation_trigger_history import build_latest_grid_sell_momentum  # noqa: E402

import rotation_grid as rg  # noqa: E402
import rotation_grid_5pct as rg5  # noqa: E402
from config.settings import DATA_CONFIG  # noqa: E402

DEFAULT_POOL = os.path.join(_SCRIPT_DIR, "stocks_pool.txt")
DEFAULT_OUT = os.path.join(_SCRIPT_DIR, "rotation_trigger_history.csv")
DEFAULT_MOMENTUM_OUT = os.path.join(_SCRIPT_DIR, "rotation_trigger_momentum_latest.csv")
DEFAULT_BASE_COST_FILE = os.path.join(_SCRIPT_DIR, "optimal_base_cost.csv")
# 仅需覆盖「最近交易日 + 昨日」触发与动量差分，默认用较短窗口即可
DEFAULT_LOOKBACK_DAYS = 60

STRATEGY_IDS = (
    "grid_buy",
    "grid_sell",
    "grid5_buy",
    "grid5_sell",
)
MOM_DIFF_STRATEGY_ID = "grid_sell_momentum_diff_pos"


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


def load_optimal_base_cost(path: str) -> Dict[str, float]:
    """
    读取 optimal_base_cost.csv，返回映射：symbol(6位) -> optimal_base_cost。
    """
    if not path or not os.path.exists(path):
        return {}
    try:
        df = pd.read_csv(path)
    except Exception:
        return {}
    if df is None or df.empty:
        return {}
    if "symbol" not in df.columns or "optimal_base_cost" not in df.columns:
        return {}

    x = df.copy()
    x["symbol"] = x["symbol"].astype(str).str.strip().str.zfill(6)
    x["optimal_base_cost"] = pd.to_numeric(x["optimal_base_cost"], errors="coerce")
    x = x.dropna(subset=["symbol", "optimal_base_cost"])
    x = x[x["optimal_base_cost"] > 0]
    if x.empty:
        return {}
    x = x.drop_duplicates(subset=["symbol"], keep="last")
    return dict(zip(x["symbol"], x["optimal_base_cost"].astype(float)))


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
        g = g.dropna(subset=["ma20"])
        g = g[(g["date"] >= start_ts) & (g["date"] <= pd.Timestamp(end_date))]
        g5 = g5.dropna(subset=["ma20"])
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
    base_cost_map: Optional[Dict[str, float]] = None,
    base_cost_markup: float = 0.05,
    strategies: Optional[Set[str]] = None,
    all_rows: bool = False,
) -> Tuple[pd.DataFrame, Optional[pd.Timestamp]]:
    name_map = enrich_symbol_names(symbols, fetch_symbol_names(symbols))
    base_cost_map = base_cost_map or {}
    strategies = strategies or set(STRATEGY_IDS)
    per_g, per_g5, all_dates = build_per_symbol_frames(symbols, start_date, end_date)
    _empty = pd.DataFrame(
        columns=[
            "date",
            "symbol",
            "name",
            "strategy_id",
            "triggered",
            "detail_json",
        ]
    )
    if not per_g:
        return _empty, None

    dates = sorted(all_dates)
    rows: List[Dict[str, Any]] = []

    for dt in dates:
        for sym in symbols:
            sym = str(sym).zfill(6)
            if sym not in per_g:
                continue
            base_cost = float(base_cost_map.get(sym, float("nan")))
            if not pd.notna(base_cost) or base_cost <= 0:
                continue
            trigger_price = float(base_cost * (1.0 + float(base_cost_markup)))
            if dt not in per_g[sym].index:
                continue
            r = per_g[sym].loc[dt]
            low = rg._to_float(r["low"])
            high = rg._to_float(r["high"])
            ma = rg._to_float(r["ma20"])

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
                trig = low <= trigger_price <= high
                emit(
                    "grid_buy",
                    trig,
                    {
                        "ma20": ma,
                        "trigger_price": trigger_price,
                        "buy_price": trigger_price,
                        "optimal_base_cost": base_cost,
                        "base_cost_markup": float(base_cost_markup),
                        "low": low,
                        "high": high,
                    },
                )

            if "grid_sell" in strategies:
                trig = high >= trigger_price
                emit(
                    "grid_sell",
                    trig,
                    {
                        "trigger_price": trigger_price,
                        "sell_price": trigger_price,
                        "optimal_base_cost": base_cost,
                        "base_cost_markup": float(base_cost_markup),
                        "high": high,
                    },
                )

            if "grid5_buy" in strategies:
                trig = low <= trigger_price <= high
                emit(
                    "grid5_buy",
                    trig,
                    {
                        "ma20": ma,
                        "trigger_price": trigger_price,
                        "buy_price": trigger_price,
                        "optimal_base_cost": base_cost,
                        "base_cost_markup": float(base_cost_markup),
                        "low": low,
                        "high": high,
                    },
                )

            if "grid5_sell" in strategies:
                trig = high >= trigger_price
                emit(
                    "grid5_sell",
                    trig,
                    {
                        "trigger_price": trigger_price,
                        "sell_price": trigger_price,
                        "optimal_base_cost": base_cost,
                        "base_cost_markup": float(base_cost_markup),
                        "high": high,
                    },
                )

    last_trading_day: Optional[pd.Timestamp] = None
    if dates:
        last_trading_day = pd.Timestamp(dates[-1]).normalize()
    return pd.DataFrame(rows), last_trading_day


def enrich_latest_momentum_with_diff(mom: pd.DataFrame) -> pd.DataFrame:
    """
    为 latest 动量结果追加列 momentum_pct_diff_2d（今日-昨日，单位：pct）。
    处理规则：
    - 新排序段（strategy_id=grid_sell_momentum_diff_pos）保留；
    - 原结果中与新排序段 symbol 重复的行删除；
    - 新排序段不做去重，保持原样。
    """
    diff_col = "momentum_pct_diff_2d"
    if mom is None or mom.empty:
        base_cols = [] if mom is None else list(mom.columns)
        if diff_col not in base_cols:
            base_cols.append(diff_col)
        return pd.DataFrame(columns=base_cols)

    out = mom.copy()
    out["symbol"] = out["symbol"].astype(str).str.zfill(6)
    out[diff_col] = pd.NA

    has_new_rank = "strategy_id" in out.columns and (out["strategy_id"] == MOM_DIFF_STRATEGY_ID).any()
    if has_new_rank:
        new_rank_df = out[out["strategy_id"] == MOM_DIFF_STRATEGY_ID].copy()
        old_df = out[out["strategy_id"] != MOM_DIFF_STRATEGY_ID].copy()
        if not new_rank_df.empty:
            dup_symbols = set(new_rank_df["symbol"].astype(str))
            old_df = old_df[~old_df["symbol"].astype(str).isin(dup_symbols)].copy()
            new_rank_df[diff_col] = pd.to_numeric(new_rank_df.get("momentum_pct"), errors="coerce")
            if old_df.empty:
                out = new_rank_df.copy()
            else:
                out = pd.concat([old_df, new_rank_df], ignore_index=True)
    else:
        tmp = out.copy()
        tmp["date"] = pd.to_datetime(tmp["date"], errors="coerce")
        tmp["momentum_pct"] = pd.to_numeric(tmp.get("momentum_pct"), errors="coerce")
        valid_dates = sorted(d for d in tmp["date"].dropna().unique())
        if len(valid_dates) >= 2:
            d_prev = valid_dates[-2]
            d_today = valid_dates[-1]
            prev_df = tmp[tmp["date"] == d_prev][["symbol", "momentum_pct"]].copy()
            prev_df = prev_df.rename(columns={"momentum_pct": "_momentum_pct_prev"})
            today_df = tmp[tmp["date"] == d_today].copy()
            merged = today_df.merge(prev_df, on="symbol", how="inner")
            merged[diff_col] = merged["momentum_pct"] - merged["_momentum_pct_prev"]
            new_rank_df = merged[merged[diff_col] > 0].copy()
            if not new_rank_df.empty:
                new_rank_df = new_rank_df.sort_values(diff_col, ascending=False).reset_index(drop=True)
                new_rank_df["rank"] = new_rank_df.index + 1
                new_rank_df["strategy_id"] = MOM_DIFF_STRATEGY_ID
                new_rank_df["date"] = pd.Timestamp(d_today).strftime("%Y-%m-%d")
                dup_symbols = set(new_rank_df["symbol"].astype(str))
                old_df = out[~out["symbol"].astype(str).isin(dup_symbols)].copy()
                for c in out.columns:
                    if c not in new_rank_df.columns:
                        new_rank_df[c] = pd.NA
                new_rank_df = new_rank_df[out.columns]
                if old_df.empty:
                    out = new_rank_df.copy()
                else:
                    out = pd.concat([old_df, new_rank_df], ignore_index=True)

    cols = [c for c in out.columns if c != diff_col] + [diff_col]
    return out[cols]


def format_latest_momentum_output(mom: pd.DataFrame) -> pd.DataFrame:
    """
    latest 输出格式化：
    - 移除 symbol 列；
    - 所有浮点数保留 1 位小数。
    """
    if mom is None or mom.empty:
        base_cols = [] if mom is None else list(mom.columns)
        out_cols = [c for c in base_cols if c != "symbol"]
        return pd.DataFrame(columns=out_cols)

    out = mom.copy()
    if "symbol" in out.columns:
        out = out.drop(columns=["symbol"])
    if "name" in out.columns and "个股名称" not in out.columns:
        out = out.rename(columns={"name": "个股名称"})

    float_cols = out.select_dtypes(include=["float", "float64", "float32"]).columns.tolist()
    if float_cols:
        out[float_cols] = out[float_cols].round(1)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(
        description="optimal_base_cost 基准触发扫描 → 仅输出最新收盘日 grid_sell 动量提示（无回测）",
    )
    ap.add_argument("--pool", default=DEFAULT_POOL, help="股票列表文件，一行一只代码")
    ap.add_argument("--base-cost-csv", default=DEFAULT_BASE_COST_FILE, help="基准成本 CSV（含 symbol,optimal_base_cost）")
    ap.add_argument("--base-cost-markup", type=float, default=0.05, help="触发阈值加成比例，默认 0.05 表示 +5%")
    ap.add_argument("--start", default=None, help="YYYY-MM-DD；不传则按 end/lookback-days 推导")
    ap.add_argument("--end", default=None, help="YYYY-MM-DD；不传默认今天")
    ap.add_argument(
        "--lookback-days",
        type=int,
        default=DEFAULT_LOOKBACK_DAYS,
        help="拉取日线窗口（自然日），需覆盖最近至少两个交易日，默认 60",
    )
    ap.add_argument(
        "--save-triggers",
        action="store_true",
        help="将当前窗口内触发扫描结果写入 --out（默认不写完整触发 CSV）",
    )
    ap.add_argument("--out", default=DEFAULT_OUT, help="与 --save-triggers 配合：触发结果 CSV 路径")
    ap.add_argument(
        "--momentum-out",
        default=DEFAULT_MOMENTUM_OUT,
        help="写入「最新收盘日」动量提示 CSV（仅该日相关行）",
    )
    ap.add_argument(
        "--strategies",
        default="all",
        help="逗号分隔：grid_buy,grid_sell,grid5_buy,grid5_sell 或 all",
    )
    ap.add_argument(
        "--all-rows",
        action="store_true",
        help="扫描时保留 triggered=0 行（仅与 --save-triggers 同用时有效）；动量仍只基于 grid_sell 触发",
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
    base_cost_map = load_optimal_base_cost(args.base_cost_csv)
    if not base_cost_map:
        raise SystemExit(f"基准成本映射为空或文件无效: {args.base_cost_csv}")

    if args.strategies.strip().lower() == "all":
        strat: Set[str] = set(STRATEGY_IDS)
    else:
        strat = {s.strip() for s in args.strategies.split(",") if s.strip()}
        bad = strat - set(STRATEGY_IDS)
        if bad:
            raise SystemExit(f"未知 strategy_id: {bad}，可选 {STRATEGY_IDS}")

    strategies = set(strat)
    strategies.add("grid_sell")
    df, last_td = scan_triggers(
        syms,
        start_str,
        end_str,
        base_cost_map=base_cost_map,
        base_cost_markup=args.base_cost_markup,
        strategies=strategies,
        all_rows=args.all_rows,
    )
    if last_td is None:
        raise SystemExit("未能确定最新交易日（无有效日线数据），请检查 pool 与网络拉取")
    last_str = last_td.strftime("%Y-%m-%d")
    print(f"最新收盘日（全池日线最大日期）: {last_str}")

    if not args.all_rows and not df.empty:
        df = df[df["triggered"] == 1].reset_index(drop=True)

    if args.save_triggers:
        out_dir = os.path.dirname(os.path.abspath(args.out))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        df.to_csv(args.out, index=False, encoding="utf-8-sig")
        print(f"已写入触发扫描 {args.out}，共 {len(df)} 行")

    mom = build_latest_grid_sell_momentum(df)
    mom = enrich_latest_momentum_with_diff(mom)
    if mom is None or mom.empty:
        print(f"=== {last_str} 动量提示：无 grid_sell 触发或数据不足（需至少约 2 个交易日触发样本）===")
        return

    if "date" not in mom.columns:
        mom["date"] = last_str
    mom_today = mom[mom["date"].astype(str) == last_str].copy()
    mom_out = format_latest_momentum_output(mom_today)

    mo_dir = os.path.dirname(os.path.abspath(args.momentum_out))
    if mo_dir:
        os.makedirs(mo_dir, exist_ok=True)
    mom_out.to_csv(args.momentum_out, index=False, encoding="utf-8-sig")
    print(f"已写入最新收盘日动量提示 {args.momentum_out}，共 {len(mom_out)} 行")

    print(f"=== {last_str} grid_sell 动量（momentum = (high - 触发价) / 触发价）===")
    if mom_out.empty:
        print("当日无触发标的或无有效 high/触发价，故无动量表。")
    else:
        print(mom_out.to_string(index=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
收费站模式（Toll / 申万一级「昨日最强」+ 固定持有）

规则：
- 仅使用 rotation_grid 的 grid_buy 触发（MA20 昨收基准、前复权；low<=buy_price<=high）。
- 申万一级（SW2021/SW2014，index_classify + index_member_all 的 l1_code）在「上一交易日」
  的全市场一级行业横向比较：用 sw_daily 的 pct_change，取涨幅最大的行业为「昨日收盘最强板块」
  （并列取指数代码较小者）。
- 触发当日 D：在所有 grid_buy 触发标的中，只保留所属 l1 等于「昨日最强板块」的股票；
  若多只符合，取股票代码较小者。
- 买入价：与 rotation_grid 一致，为当日 buy_price（网格价，见 detail_json）。
- 卖出：买入日 D 之后第 HOLD_TRADING_DAYS 个交易日（不含 D）的收盘价卖出（T+3）；
  卖出端按印花税 STAMP_DUTY_RATE。

输出：UTF-8-SIG CSV（默认 rotation_toll_booth_trades.csv），每行一笔独立交易（不做仓位叠加与资金曲线）。
"""

from __future__ import annotations

import argparse
import bisect
import json
import os
import sys
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from backtest_sy_002028_threshold import (  # noqa: E402
    STAMP_DUTY_RATE,
    fetch_ohlc_qfq,
    six_digit_to_ts_code,
)
from config.settings import DATA_CONFIG  # noqa: E402
from rotation_trigger_history import load_symbols, scan_triggers  # noqa: E402

DEFAULT_POOL = os.path.join(_SCRIPT_DIR, "stocks_pool.txt")
DEFAULT_OUT = os.path.join(_SCRIPT_DIR, "rotation_toll_booth_trades.csv")
DEFAULT_LOOKBACK_DAYS = 180
HOLD_TRADING_DAYS = 3  # 买入日后第 N 个交易日收盘卖出（T+N）


def _get_pro():
    import tushare as ts  # type: ignore

    token = (DATA_CONFIG.get("tushare_token") or "").strip()
    if not token:
        raise RuntimeError("未配置 tushare_token，无法拉取申万行业与 sw_daily。")
    ts.set_token(token)
    return ts.pro_api()


def fetch_sw_l1_index_codes(pro) -> Tuple[Set[str], Dict[str, str]]:
    """申万一级指数代码集合 + index_code -> industry_name。"""
    last_err: Optional[Exception] = None
    for src in ("SW2021", "SW2014"):
        try:
            df = pro.index_classify(level="L1", src=src)
        except Exception as e:
            last_err = e
            continue
        if df is None or df.empty or "index_code" not in df.columns:
            continue
        codes = set(df["index_code"].astype(str).tolist())
        name_map = dict(zip(df["index_code"].astype(str), df["industry_name"].astype(str)))
        return codes, name_map
    raise RuntimeError(f"index_classify 申万一级失败: {last_err}")


def fetch_index_member_all(pro, ts_code: str, end_date_compact: str) -> pd.DataFrame:
    """单只股票申万成分层级（含 l1_code）。"""
    try:
        df = pro.index_member_all(ts_code=ts_code, start_date="19900101", end_date=end_date_compact)
    except Exception:
        return pd.DataFrame()
    return df if df is not None else pd.DataFrame()


def _ymd_cell_to_ts(raw: object) -> pd.Timestamp:
    """Tushare 常见 YYYYMMDD 整型/浮点/字符串 → 日期。"""
    if raw is None:
        return pd.NaT
    try:
        if isinstance(raw, float) and pd.isna(raw):
            return pd.NaT
    except Exception:
        pass
    try:
        f = float(raw)
        if f != f:
            return pd.NaT
        si = int(f)
        s = str(si)
        if len(s) == 8 and s.isdigit():
            return pd.to_datetime(s, format="%Y%m%d", errors="coerce")
    except Exception:
        pass
    s = str(raw).strip().split(".")[0]
    if len(s) == 8 and s.isdigit():
        return pd.to_datetime(s, format="%Y%m%d", errors="coerce")
    return pd.to_datetime(s, errors="coerce")


def resolve_l1_on_date(
    mem: pd.DataFrame,
    trade_d: pd.Timestamp,
    sw_l1_codes: Set[str],
) -> Optional[str]:
    """在 trade_d 生效的申万一级 l1_code（取首条匹配）。"""
    if mem is None or mem.empty or "l1_code" not in mem.columns:
        return None
    td = pd.Timestamp(trade_d).normalize()
    for _, row in mem.iterrows():
        l1 = str(row.get("l1_code", "") or "").strip()
        if not l1 or l1 not in sw_l1_codes:
            continue
        in_d = _ymd_cell_to_ts(row.get("in_date"))
        if pd.isna(in_d) or in_d > td:
            continue
        out_raw = row.get("out_date")
        if out_raw is None or (isinstance(out_raw, float) and pd.isna(out_raw)):
            return l1
        s = str(out_raw).strip().lower()
        if s in ("", "none", "nan"):
            return l1
        out_d = _ymd_cell_to_ts(out_raw)
        if pd.isna(out_d) or out_d >= td:
            return l1
    return None


def load_sw_daily_pct_series(
    pro,
    codes: Set[str],
    start_compact: str,
    end_compact: str,
) -> Dict[str, pd.Series]:
    """l1_code -> Series(日期索引, pct_change 数值)。"""
    out: Dict[str, pd.Series] = {}
    for code in sorted(codes):
        try:
            df = pro.sw_daily(ts_code=code, start_date=start_compact, end_date=end_compact)
        except Exception:
            df = None
        if df is None or df.empty:
            out[code] = pd.Series(dtype=float)
            continue
        d = df.copy()
        d["trade_date"] = pd.to_datetime(d["trade_date"], errors="coerce")
        d = d.dropna(subset=["trade_date"]).set_index("trade_date").sort_index()
        pct = pd.to_numeric(d.get("pct_change"), errors="coerce")
        out[code] = pct
    return out


def fetch_sse_trade_calendar(pro, start_compact: str, end_compact: str) -> List[pd.Timestamp]:
    try:
        cal = pro.trade_cal(exchange="SSE", start_date=start_compact, end_date=end_compact, is_open="1")
    except Exception:
        return []
    if cal is None or cal.empty:
        return []
    dates = pd.to_datetime(cal["cal_date"].astype(str), format="%Y%m%d", errors="coerce")
    return sorted(dates.dropna().dt.normalize().unique().tolist())


def exit_date_after_n_sessions(
    cal: List[pd.Timestamp],
    entry: pd.Timestamp,
    n: int,
) -> Optional[pd.Timestamp]:
    """entry 所在交易日之后第 n 个交易日（不含 entry 当日）的日历日。"""
    if not cal:
        return None
    e = pd.Timestamp(entry).normalize()
    idx = bisect.bisect_left(cal, e)
    if idx >= len(cal) or cal[idx] != e:
        return None
    j = idx + n
    if j >= len(cal):
        return None
    return cal[j]


def prev_trading_day(cal: List[pd.Timestamp], d: pd.Timestamp) -> Optional[pd.Timestamp]:
    """d 为交易日时返回上一交易日，否则 None。"""
    if not cal:
        return None
    e = pd.Timestamp(d).normalize()
    i = bisect.bisect_left(cal, e)
    if i <= 0 or i >= len(cal) or cal[i] != e:
        return None
    return cal[i - 1]


def strongest_sw_l1_on_date(
    pct_by_code: Dict[str, pd.Series],
    sw_l1_codes: Set[str],
    day: pd.Timestamp,
) -> Tuple[Optional[str], float]:
    """在 day 当日各申万一级 pct_change 中取最强（并列取 l1 代码较小）。"""
    best: Optional[str] = None
    best_v = float("-inf")
    d = pd.Timestamp(day).normalize()
    for code in sorted(sw_l1_codes):
        s = pct_by_code.get(code, pd.Series(dtype=float))
        if d not in s.index:
            continue
        v = float(s.loc[d])
        if v != v:
            continue
        if v > best_v or (v == best_v and (best is None or code < best)):
            best_v = v
            best = code
    if best is None:
        return None, float("nan")
    return best, best_v


def _parse_buy_price(detail_json: str) -> float:
    try:
        d = json.loads(detail_json) if isinstance(detail_json, str) else {}
        return float(d.get("buy_price", float("nan")))
    except Exception:
        return float("nan")


def build_toll_booth_trades(
    triggers: pd.DataFrame,
    pro,
    *,
    sw_daily_start_compact: str,
    end_compact: str,
    trade_cal: List[pd.Timestamp],
) -> pd.DataFrame:
    """
    triggers: scan_triggers 输出，仅含 grid_buy 且 triggered=1。
    trade_cal: 须覆盖回测区间之前若干交易日，以便计算「上一交易日」最强板块。
    """
    if triggers is None or triggers.empty:
        return pd.DataFrame()

    sw_l1_codes, sw_names = fetch_sw_l1_index_codes(pro)

    sym_mem: Dict[str, pd.DataFrame] = {}
    for sym in triggers["symbol"].astype(str).map(lambda x: x.zfill(6)).unique():
        tc = six_digit_to_ts_code(sym)
        sym_mem[sym] = fetch_index_member_all(pro, tc, end_compact)

    rows: List[Dict] = []
    enriched: List[Dict] = []
    for _, r in triggers.iterrows():
        sym = str(r["symbol"]).zfill(6)
        dt = pd.to_datetime(r["date"], errors="coerce").normalize()
        if pd.isna(dt):
            continue
        l1 = resolve_l1_on_date(sym_mem.get(sym, pd.DataFrame()), dt, sw_l1_codes)
        buy_p = _parse_buy_price(str(r.get("detail_json", "")))
        enriched.append(
            {
                "date": dt,
                "symbol": sym,
                "name": str(r.get("name", "") or ""),
                "l1_code": l1,
                "buy_price": buy_p,
            }
        )

    ex = pd.DataFrame(enriched)
    ex = ex[ex["l1_code"].notna()].copy()
    if ex.empty:
        return pd.DataFrame()

    # 全市场申万一级日线涨幅（用于「上一交易日」横截面最强）
    pct_by_code = load_sw_daily_pct_series(pro, sw_l1_codes, sw_daily_start_compact, end_compact)

    for d0 in sorted(ex["date"].unique()):
        prev_d = prev_trading_day(trade_cal, d0)
        if prev_d is None:
            continue
        leader_l1, leader_pct = strongest_sw_l1_on_date(pct_by_code, sw_l1_codes, prev_d)
        if leader_l1 is None or leader_pct != leader_pct:
            continue
        g = ex[ex["date"] == d0]
        g2 = g[g["l1_code"].astype(str) == leader_l1].copy()
        if g2.empty:
            continue
        pick = g2.sort_values("symbol").iloc[0]
        sym = str(pick["symbol"])
        buy_price = float(pick["buy_price"])
        l1 = str(pick["l1_code"])
        if not (buy_price > 0) or not (buy_price == buy_price):
            continue
        xdt = exit_date_after_n_sessions(trade_cal, d0, HOLD_TRADING_DAYS)
        rows.append(
            {
                "strategy_id": "toll_booth_sw_l1_prev_leader",
                "entry_date": d0.strftime("%Y-%m-%d"),
                "exit_date": xdt.strftime("%Y-%m-%d") if xdt is not None else "",
                "symbol": sym,
                "name": str(pick.get("name", "") or ""),
                "sw_l1_code": l1,
                "sw_l1_name": sw_names.get(l1, ""),
                "prev_trade_date": prev_d.strftime("%Y-%m-%d"),
                "leader_sector_pct_prev_day": round(float(leader_pct), 4),
                "buy_price": round(buy_price, 4),
                "hold_trading_days": HOLD_TRADING_DAYS,
            }
        )

    if not rows:
        return pd.DataFrame()

    out_df = pd.DataFrame(rows)
    # 批量取卖出收盘价
    sym_to_exits: Dict[str, List[pd.Timestamp]] = {}
    for _, tr in out_df.iterrows():
        if not str(tr.get("exit_date", "")).strip():
            continue
        sym_to_exits.setdefault(str(tr["symbol"]).zfill(6), []).append(
            pd.to_datetime(tr["exit_date"]).normalize()
        )

    close_lookup: Dict[Tuple[str, pd.Timestamp], float] = {}
    for sym, dlist in sym_to_exits.items():
        mn = min(dlist).strftime("%Y-%m-%d")
        mx = max(dlist).strftime("%Y-%m-%d")
        try:
            ohlc = fetch_ohlc_qfq(sym, mn, mx)
        except Exception:
            ohlc = pd.DataFrame()
        if ohlc is None or ohlc.empty:
            continue
        ohlc = ohlc.copy()
        ohlc["date"] = pd.to_datetime(ohlc["date"]).dt.normalize()
        for _, bar in ohlc.iterrows():
            try:
                close_lookup[(sym, pd.Timestamp(bar["date"]).normalize())] = float(bar["close"])
            except Exception:
                continue

    sell_closes: List[float] = []
    pnl_g: List[float] = []
    pnl_n: List[float] = []
    for _, tr in out_df.iterrows():
        ed = str(tr.get("exit_date", "") or "").strip()
        if not ed:
            sell_closes.append(float("nan"))
            pnl_g.append(float("nan"))
            pnl_n.append(float("nan"))
            continue
        sym = str(tr["symbol"]).zfill(6)
        dt = pd.to_datetime(ed).normalize()
        c = close_lookup.get((sym, dt), float("nan"))
        sell_closes.append(c)
        bp = float(tr["buy_price"])
        if bp > 0 and c == c:
            gross = (c - bp) / bp * 100.0
            net = (c * (1.0 - STAMP_DUTY_RATE) - bp) / bp * 100.0
            pnl_g.append(round(gross, 4))
            pnl_n.append(round(net, 4))
        else:
            pnl_g.append(float("nan"))
            pnl_n.append(float("nan"))

    out_df["sell_close"] = sell_closes
    out_df["pnl_pct_gross"] = pnl_g
    out_df["pnl_pct_net"] = pnl_n
    return out_df


def main() -> None:
    ap = argparse.ArgumentParser(description="收费站模式：grid_buy + 申万一级昨日最强板块 + 网格价买 + T+3 收盘卖")
    ap.add_argument("--pool", default=DEFAULT_POOL, help="股票列表文件")
    ap.add_argument("--start", default=None, help="YYYY-MM-DD")
    ap.add_argument("--end", default=None, help="YYYY-MM-DD；默认今天")
    ap.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS, help="未传 start 时从 end 回溯自然日")
    ap.add_argument("--out", default=DEFAULT_OUT, help="输出 CSV")
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
    start_c = start_str.replace("-", "")
    end_c = end_str.replace("-", "")

    syms = load_symbols(args.pool)
    if not syms:
        raise SystemExit(f"股票列表为空: {args.pool}")

    pro = _get_pro()
    # 卖出日可能略晚于 end；日历与 sw_daily 需略早于 start，以便首日有「上一交易日」
    ext_end = (end_ts + pd.Timedelta(days=30)).strftime("%Y-%m-%d").replace("-", "")
    cal_start = (start_ts - pd.Timedelta(days=120)).strftime("%Y-%m-%d").replace("-", "")
    trade_cal_ext = fetch_sse_trade_calendar(pro, cal_start, ext_end)
    sw_daily_start = (start_ts - pd.Timedelta(days=60)).strftime("%Y-%m-%d").replace("-", "")

    trig = scan_triggers(
        syms,
        start_str,
        end_str,
        strategies={"grid_buy"},
        all_rows=False,
    )
    if not trig.empty:
        trig = trig[trig["triggered"] == 1].reset_index(drop=True)

    out_df = build_toll_booth_trades(
        trig,
        pro,
        sw_daily_start_compact=sw_daily_start,
        end_compact=end_c,
        trade_cal=trade_cal_ext,
    )

    out_dir = os.path.dirname(os.path.abspath(args.out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    out_df.to_csv(args.out, index=False, encoding="utf-8-sig")
    print(f"已写入 {args.out}，共 {len(out_df)} 笔收费站交易")
    if not out_df.empty:
        valid = out_df["pnl_pct_net"].dropna()
        if not valid.empty:
            print(f"含有效净值收益样本: {len(valid)} 笔，均值 pnl_pct_net: {valid.mean():.4f}%")


if __name__ == "__main__":
    main()

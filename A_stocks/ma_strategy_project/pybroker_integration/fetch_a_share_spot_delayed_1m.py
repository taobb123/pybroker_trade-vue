#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A 股参考现价（优先快照，其次约 1 分钟 K 线）

1) 优先：Tushare Pro `realtime_quote`（新浪 sina / 东财 dc），需 config/settings 中配置
   `DATA_CONFIG['tushare_token']`；为第三方网页快照，非交易所直连，延迟通常很短但仍非「法定实时」。
2) 回退：akshare 东方财富 1 分钟分时最后一根 K 的收盘价（约分钟级）。

用法（在 ma_strategy_project 目录下）：
    python pybroker_integration/fetch_a_share_spot_delayed_1m.py
    python pybroker_integration/fetch_a_share_spot_delayed_1m.py --symbol 002517
    python pybroker_integration/fetch_a_share_spot_delayed_1m.py --no-tushare
    python pybroker_integration/fetch_a_share_spot_delayed_1m.py --compare-table
    python pybroker_integration/fetch_a_share_spot_delayed_1m.py --compare-table --out-csv D:/out/prices.csv

对比模式会生成 UTF-8-SIG CSV（默认 pybroker_integration/fetch_a_share_spot_compare_prices.csv），
**仅包含**「参考价 <= 最优基准」的触发个股。「行业板块」为 Tushare `stock_basic` 的申万一级（或 industry）。
单股可加 --out-csv 写一行。

对比模式在配置 `tushare_token` 时还会自动生成第二张表：**申万一级全行业** `sw_daily` 涨跌幅
（与触发列表同一行情锚定日或最近交易日）+ **各行业触发家数**，默认路径为触发 CSV 同目录下
`*_sw_l1_sector_summary.csv`（可用 `--out-sector-csv` 指定；`--no-sector-summary` 关闭）。

默认用表 pybroker_integration/optimal_base_cost.csv（可先跑 backtest_sy_base_cost_search 写入）。
默认见 FETCH_A_SHARE_SPOT_CONFIG；命令行覆盖配置。
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from backtest_sy_002028_threshold import fetch_stock_name
from optimal_base_cost_store import DEFAULT_OPTIMAL_BASE_CSV, load_optimal_base_table

DEFAULT_COMPARE_OUT_CSV = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fetch_a_share_spot_compare_prices.csv",
)


def _sector_summary_path_from_trigger_csv(trigger_csv: str) -> str:
    base, ext = os.path.splitext(os.path.abspath(trigger_csv))
    return f"{base}_sw_l1_sector_summary{ext if ext else '.csv'}"


def _try_tushare_pro():
    try:
        from config.settings import DATA_CONFIG
    except ImportError:
        return None
    token = ((DATA_CONFIG or {}).get("tushare_token") or "").strip()
    if not token:
        return None
    try:
        import tushare as ts

        ts.set_token(token)
        return ts.pro_api()
    except Exception:
        return None


def _infer_signal_anchor_date(trig_df: pd.DataFrame) -> pd.Timestamp:
    """从触发行的 quote_date 推断对比锚定日；无则今天（自然日）。"""
    if trig_df is not None and not trig_df.empty and "quote_date" in trig_df.columns:
        s = pd.to_datetime(trig_df["quote_date"], errors="coerce").dropna()
        if not s.empty:
            return s.dt.normalize().max()
    return pd.Timestamp.today().normalize()


def _last_sw_pct_and_date(ser: pd.Series, anchor: pd.Timestamp) -> Tuple[float, str]:
    """取申万指数序列中 <= anchor 的最近一条 pct_change 与对应交易日。"""
    if ser is None or ser.empty:
        return float("nan"), ""
    a = anchor.normalize()
    ser = ser.sort_index()
    leq = ser[ser.index.normalize() <= a].dropna()
    if leq.empty:
        return float("nan"), ""
    last_idx = leq.index[-1]
    v = float(leq.iloc[-1])
    try:
        ds = pd.Timestamp(last_idx).strftime("%Y-%m-%d")
    except Exception:
        ds = str(last_idx)[:10]
    return v, ds


def write_sw_l1_sector_summary_csv(
    trig_df: pd.DataFrame,
    out_path: str,
) -> Optional[str]:
    """
    申万一级全行业横向表：涨跌排名、当日(最近可用) sw_daily 涨跌幅、触发家数。
    需 Tushare sw_daily + index_classify；失败返回 None。
    """
    pro = _try_tushare_pro()
    if pro is None:
        print("提示: 未配置 tushare_token，跳过申万一级行业汇总 CSV。", file=sys.stderr)
        return None
    try:
        from rotation_trigger_buy_history import (  # noqa: WPS433
            fetch_sw_l1_index_codes,
            load_sw_daily_pct_series,
        )
    except Exception as e:
        print(f"提示: 无法加载 rotation_trigger_buy_history（{e}），跳过行业汇总。", file=sys.stderr)
        return None

    anchor = _infer_signal_anchor_date(trig_df if trig_df is not None else pd.DataFrame())
    anchor_str = anchor.strftime("%Y-%m-%d")
    start_c = (anchor - pd.Timedelta(days=30)).strftime("%Y%m%d")
    end_c = anchor.strftime("%Y%m%d")

    try:
        codes, name_map = fetch_sw_l1_index_codes(pro)
    except Exception as e:
        print(f"提示: 申万一级 index_classify 失败（{e}），跳过行业汇总。", file=sys.stderr)
        return None

    try:
        pct_map = load_sw_daily_pct_series(pro, codes, start_c, end_c)
    except Exception as e:
        print(f"提示: sw_daily 批量拉取失败（{e}），跳过行业汇总。", file=sys.stderr)
        return None

    trig_counts: Dict[str, int] = {}
    if trig_df is not None and not trig_df.empty and "行业板块" in trig_df.columns:
        sub = trig_df["行业板块"].astype(str).str.strip()
        sub = sub[sub.ne("") & sub.str.lower().ne("nan")]
        if not sub.empty:
            vc = sub.value_counts()
            trig_counts = {str(k): int(v) for k, v in vc.items()}

    rows: List[Dict[str, Any]] = []
    for code in sorted(codes):
        nm = str(name_map.get(code, "") or "").strip()
        pct, td_used = _last_sw_pct_and_date(pct_map.get(code, pd.Series(dtype=float)), anchor)
        rows.append(
            {
                "对比锚定日": anchor_str,
                "申万一级": nm,
                "指数代码": code,
                "涨跌幅_pct": round(pct, 4) if pct == pct else "",
                "指数行情日": td_used,
                "触发家数": int(trig_counts.get(nm, 0)),
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return None
    out["_sort_pct"] = pd.to_numeric(out["涨跌幅_pct"], errors="coerce")
    out = out.sort_values("_sort_pct", ascending=False, na_position="last").reset_index(drop=True)
    out.insert(0, "涨跌排名", list(range(1, len(out) + 1)))
    out = out.drop(columns=["_sort_pct"], errors="ignore")

    p = os.path.abspath(out_path)
    d = os.path.dirname(p)
    if d:
        os.makedirs(d, exist_ok=True)
    out.to_csv(p, index=False, encoding="utf-8-sig")
    return p


# 对比模式 CSV 仅输出触发行（现价<=基准）时的列序
_COMPARE_TRIGGERED_CSV_COLUMNS = (
    "symbol",
    "stock_name",
    "行业板块",
    "optimal_base_cost",
    "ref_price",
    "quote_date",
    "quote_time",
    "price_source",
    "start_date",
    "end_date",
    "updated_at",
)

# ---------------------------------------------------------------------------
# 可在此修改默认行为（命令行参数会覆盖对应项）
# ---------------------------------------------------------------------------
FETCH_A_SHARE_SPOT_CONFIG = {
    "default_symbol": "002517",
    "fallback_bid_ask_by_default": False,
    # 若已配置 tushare_token，默认先请求 realtime_quote（需账号权限/积分）
    "prefer_tushare_realtime": True,
    # realtime_quote 数据源：'sina' 或 'dc'（东财单次单股）
    "tushare_realtime_src": "sina",
}


def _six_digit_to_ts_code(code: str) -> str:
    c = "".join(filter(str.isdigit, str(code))).zfill(6)
    if c.startswith("6"):
        return f"{c}.SH"
    if c.startswith(("8", "4")):
        return f"{c}.BJ"
    return f"{c}.SZ"


def _bid_ask_mid(symbol: str) -> Tuple[float, float, float]:
    import akshare as ak

    df = ak.stock_bid_ask_em(symbol=symbol)
    m = dict(zip(df["item"], df["value"]))
    buy1 = float(m["buy_1"])
    sell1 = float(m["sell_1"])
    return buy1, sell1, (buy1 + sell1) / 2.0


def fetch_tushare_realtime_quote(
    symbol_6: str,
    src: str = "sina",
) -> Optional[Tuple[str, str, float, str]]:
    """
    :return: (date_str, time_str, price, src_label) 或 None
    """
    try:
        from config.settings import DATA_CONFIG
    except ImportError:
        return None

    token = ((DATA_CONFIG or {}).get("tushare_token") or "").strip()
    if not token:
        return None

    try:
        import tushare as ts

        ts.set_token(token)
        ts_code = _six_digit_to_ts_code(symbol_6)
        df = ts.realtime_quote(ts_code=ts_code, src=src)
        if df is None or df.empty:
            return None
        row = df.iloc[0]
        price = float(row["PRICE"])
        if price <= 0 or price != price:  # NaN
            return None
        d = str(row["DATE"]).strip()
        t = str(row["TIME"]).strip()
        return d, t, price, f"tushare.realtime_quote({src})"
    except (requests.RequestException, TimeoutError, OSError, ImportError, Exception):
        return None


def fetch_delayed_1m_close(symbol: str) -> Optional[Tuple[Any, float]]:
    import akshare as ak

    today = datetime.now().strftime("%Y-%m-%d")
    try:
        df = ak.stock_zh_a_hist_min_em(
            symbol=symbol,
            period="1",
            adjust="",
            start_date=f"{today} 09:15:00",
            end_date=f"{today} 15:30:00",
        )
        if df is None or df.empty:
            return None
        last = df.iloc[-1]
        bar_time = last["时间"]
        close = float(last["收盘"])
        return bar_time, close
    except (requests.RequestException, TimeoutError, OSError) as e:
        print(f"1 分钟分时请求失败: {e}")
        return None
    except (TypeError, KeyError, ValueError, AttributeError):
        # 东财无当日分时、trends 为 None、或列名变化时 akshare 内部常抛 TypeError 等
        return None
    except Exception:
        return None


def _fetch_industry_name_map(symbols: List[str]) -> Dict[str, str]:
    """
    6 位代码 -> 申万一级/ industry（Tushare stock_basic：优先 industry_l1，否则 industry）。
    无 token 或失败时返回空串。
    """
    norm = list(
        dict.fromkeys(
            "".join(filter(str.isdigit, str(s))).zfill(6) for s in symbols if str(s).strip()
        )
    )
    out: Dict[str, str] = {s: "" for s in norm}
    if not norm:
        return out
    try:
        from config.settings import DATA_CONFIG
    except ImportError:
        return out
    token = ((DATA_CONFIG or {}).get("tushare_token") or "").strip()
    if not token:
        return out
    try:
        import tushare as ts

        ts.set_token(token)
        pro = ts.pro_api()
        df = None
        for fld in ("ts_code,industry,industry_l1", "ts_code,industry"):
            try:
                df = pro.stock_basic(exchange="", list_status="L", fields=fld)
                break
            except Exception:
                df = None
        if df is None or df.empty:
            return out
        code_to_name: Dict[str, str] = {}
        for _, row in df.iterrows():
            ts_code = str(row.get("ts_code", "") or "")
            code6 = ts_code.split(".")[0].zfill(6) if ts_code else ""
            if not code6:
                continue
            name = row.get("industry_l1") if "industry_l1" in df.columns else None
            if name is None or (isinstance(name, float) and pd.isna(name)) or str(name).strip() == "":
                name = row.get("industry") or ""
            if name is None or (isinstance(name, float) and pd.isna(name)):
                name = ""
            else:
                name = str(name).strip()
            code_to_name[code6] = name
        for s in norm:
            out[s] = code_to_name.get(s, "")
    except Exception:
        pass
    return out


def _industry_columns_for_symbol(sym: str) -> Dict[str, str]:
    """单只股票：行业板块（Tushare）。"""
    sw = _fetch_industry_name_map([sym]).get(sym, "")
    return {"行业板块": sw}


def fetch_reference_price(
    symbol: str,
    *,
    prefer_tushare: bool,
    tushare_src: str,
    use_bid_ask_fallback: bool,
) -> Optional[Tuple[float, str, str, str]]:
    """
    单只证券参考价：Tushare 快照 → akshare 1 分钟收盘 → 可选盘口中间价。
    :return: (price, source_label, quote_date, quote_time) 时间与日期若无则空字符串
    """
    sym = symbol.strip().zfill(6)
    if prefer_tushare:
        out_ts = fetch_tushare_realtime_quote(sym, src=tushare_src)
        if out_ts:
            d_s, t_s, price, label = out_ts
            return price, label, d_s, t_s
    out = fetch_delayed_1m_close(sym)
    if out:
        bar_time, close = out
        bt = str(bar_time)
        parts = bt.replace("T", " ").split()
        d_part = parts[0] if parts else ""
        t_part = parts[1] if len(parts) > 1 else bt
        return close, "akshare 1分钟分时收盘", d_part, t_part
    if use_bid_ask_fallback:
        try:
            b1, s1, mid = _bid_ask_mid(sym)
            return mid, "akshare 买卖一档中间价", "", ""
        except (requests.RequestException, TimeoutError, OSError, KeyError, ValueError):
            pass
    return None


def run_compare_to_optimal_table(
    table_path: str,
    *,
    prefer_tushare: bool,
    tushare_src: str,
    use_bid_ask_fallback: bool,
    out_csv: str,
    out_sector_csv: Optional[str] = None,
    no_sector_summary: bool = False,
) -> None:
    df = load_optimal_base_table(table_path)
    if df.empty:
        print(f"最优基准表为空或不存在: {table_path}")
        print("请先运行 backtest_sy_base_cost_search.py 写入至少一只股票。")
        return

    syms_for_ind = [str(row["symbol"]).strip() for _, row in df.iterrows()]
    sw_map = _fetch_industry_name_map(syms_for_ind)

    print(f"读取表: {table_path}  （共 {len(df)} 只股票）")
    print("规则: 最新价 <= 最优基准 时提示（与表中回测区间一并列出）")
    print("=" * 88)

    alerts: list[tuple] = []
    skipped: list[str] = []
    csv_rows: List[Dict[str, Any]] = []

    for _, row in df.iterrows():
        sym = str(row["symbol"]).strip().zfill(6)
        sw = sw_map.get(sym, "")
        try:
            base = float(str(row["optimal_base_cost"]).strip())
        except (TypeError, ValueError):
            skipped.append(f"{sym}(基准无效)")
            continue
        s_start = str(row.get("start_date", "")).strip()
        s_end = str(row.get("end_date", "")).strip()
        updated_at = str(row.get("updated_at", "")).strip()
        sname = str(row.get("stock_name", "") or "").strip()
        if not sname or sname.lower() == "nan":
            sname = fetch_stock_name(sym)

        ref = fetch_reference_price(
            sym,
            prefer_tushare=prefer_tushare,
            tushare_src=tushare_src,
            use_bid_ask_fallback=use_bid_ask_fallback,
        )
        if ref is None:
            skipped.append(f"{sym}(无行情)")
            continue
        price, src_lbl, qd, qt = ref
        below = round(price, 2) <= round(base, 2)
        if below:
            alerts.append((sym, sname, price, base, s_start, s_end, src_lbl, qd, qt, updated_at))
            csv_rows.append(
                {
                    "symbol": sym,
                    "stock_name": sname,
                    "行业板块": sw,
                    "optimal_base_cost": round(base, 4),
                    "ref_price": round(price, 4),
                    "quote_date": qd,
                    "quote_time": qt,
                    "price_source": src_lbl,
                    "start_date": s_start,
                    "end_date": s_end,
                    "updated_at": updated_at,
                }
            )

    out_path = os.path.abspath(out_csv)
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    out_df = pd.DataFrame(csv_rows, columns=list(_COMPARE_TRIGGERED_CSV_COLUMNS))
    out_df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"已写入触发个股 CSV（现价<=基准，共 {len(out_df)} 条，含行业板块）: {out_path}")

    if not no_sector_summary:
        sec_path = out_sector_csv or _sector_summary_path_from_trigger_csv(out_path)
        sec_written = write_sw_l1_sector_summary_csv(out_df, sec_path)
        if sec_written:
            print(f"已写入申万一级行业汇总 CSV（全行业涨跌+触发家数）: {sec_written}")

    if alerts:
        print("【提示】最新价 <= 最优基准：")
        for sym, sname, price, base, s_start, s_end, src_lbl, qd, qt, upd in alerts:
            rng = f"{s_start} ~ {s_end}" if s_start and s_end else "(表中未填区间)"
            qt_s = f"{qd} {qt}".strip() or "-"
            label = f"{sname}({sym})" if sname else sym
            print(
                f"  {label}  现价 {price:.2f} <= 基准 {base:.2f}  | 基准区间 {rng}  | 表更新时间 {upd or '-'}  | 行情 {src_lbl} {qt_s}"
            )
    else:
        print("无：当前列表中没有「现价 <= 最优基准」的标的（或均未取到价）。")

    if skipped:
        print("-" * 88)
        print(f"未参与比较或略过: {', '.join(skipped)}")

    print("=" * 88)


def main() -> None:
    cfg = FETCH_A_SHARE_SPOT_CONFIG
    d_sym = str(cfg.get("default_symbol", "002517")).strip()
    d_fb = bool(cfg.get("fallback_bid_ask_by_default", False))
    prefer_ts = bool(cfg.get("prefer_tushare_realtime", True))
    ts_src = str(cfg.get("tushare_realtime_src", "sina")).strip().lower()
    if ts_src not in ("sina", "dc"):
        ts_src = "sina"

    parser = argparse.ArgumentParser(description="A 股参考现价（优先 Tushare 快照）")
    parser.add_argument(
        "--symbol",
        default=d_sym,
        help=f"6 位股票代码，默认取自 FETCH_A_SHARE_SPOT_CONFIG['default_symbol']（当前 {d_sym!r}）",
    )
    parser.add_argument(
        "--no-tushare",
        action="store_true",
        help="跳过 Tushare realtime_quote，直接用 akshare 1 分钟线",
    )
    parser.add_argument(
        "--tushare-src",
        choices=("sina", "dc"),
        default=ts_src,
        help="Tushare realtime_quote 数据源（默认取配置）",
    )
    parser.add_argument(
        "--fallback-bid-ask",
        action=argparse.BooleanOptionalAction,
        default=d_fb,
        help="无快照且无 1 分钟线时，用 akshare 买卖一档中间价兜底",
    )
    parser.add_argument(
        "--compare-table",
        action="store_true",
        help="读取最优基准表 optimal_base_cost.csv，对表中股票取价并提示 现价<=基准",
    )
    parser.add_argument(
        "--table",
        default=DEFAULT_OPTIMAL_BASE_CSV,
        help=f"最优基准表路径（默认 {DEFAULT_OPTIMAL_BASE_CSV}）",
    )
    parser.add_argument(
        "--out-csv",
        default=None,
        metavar="PATH",
        help=(
            "对比模式（--compare-table）：仅将「现价<=基准」的触发股写入 CSV，默认 "
            f"{DEFAULT_COMPARE_OUT_CSV}；单股模式：若指定则写一行（含行业板块）"
        ),
    )
    parser.add_argument(
        "--out-sector-csv",
        default=None,
        metavar="PATH",
        help="对比模式：申万一级全行业汇总 CSV 路径；默认在触发 CSV 同目录下追加 _sw_l1_sector_summary",
    )
    parser.add_argument(
        "--no-sector-summary",
        action="store_true",
        help="对比模式：不生成申万一级行业汇总 CSV（不写 sw_daily）",
    )
    args = parser.parse_args()

    if args.compare_table:
        csv_path = args.out_csv if args.out_csv else DEFAULT_COMPARE_OUT_CSV
        run_compare_to_optimal_table(
            args.table,
            prefer_tushare=prefer_ts and not args.no_tushare,
            tushare_src=args.tushare_src,
            use_bid_ask_fallback=args.fallback_bid_ask,
            out_csv=csv_path,
            out_sector_csv=args.out_sector_csv,
            no_sector_summary=args.no_sector_summary,
        )
        return

    symbol = args.symbol.strip().zfill(6)
    _nm = fetch_stock_name(symbol)

    use_ts = prefer_ts and not args.no_tushare
    if use_ts:
        out_ts = fetch_tushare_realtime_quote(symbol, src=args.tushare_src)
        if out_ts:
            d_s, t_s, price, label = out_ts
            print(f"代码: {symbol}" + (f"  {_nm}" if _nm else ""))
            print(f"数据源: {label}")
            print(f"行情日期: {d_s}  时间: {t_s}")
            print(f"参考价(最新价): {price:.2f}")
            if args.out_csv:
                idc = _industry_columns_for_symbol(symbol)
                one = pd.DataFrame(
                    [
                        {
                            "symbol": symbol,
                            "stock_name": _nm,
                            **idc,
                            "ref_price": round(price, 4),
                            "quote_date": d_s,
                            "quote_time": t_s,
                            "price_source": label,
                        }
                    ]
                )
                p = os.path.abspath(args.out_csv)
                os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
                one.to_csv(p, index=False, encoding="utf-8-sig")
                print(f"已写入 CSV: {p}")
            return
        if not args.no_tushare:
            print("Tushare realtime_quote 不可用或未返回有效价（检查 token、积分/权限与网络），尝试 akshare 1 分钟线…")

    out = fetch_delayed_1m_close(symbol)
    if out:
        bar_time, close = out
        print(f"代码: {symbol}" + (f"  {_nm}" if _nm else ""))
        print(f"数据源: akshare 东方财富 1 分钟分时（最后一根 K 收盘价）")
        print(f"该根时间: {bar_time}")
        print(f"参考价(收盘): {close:.2f}")
        if args.out_csv:
            idc = _industry_columns_for_symbol(symbol)
            bt = str(bar_time)
            parts = bt.replace("T", " ").split()
            d_part = parts[0] if parts else ""
            t_part = parts[1] if len(parts) > 1 else bt
            one = pd.DataFrame(
                [
                    {
                        "symbol": symbol,
                        "stock_name": _nm,
                        **idc,
                        "ref_price": round(close, 4),
                        "quote_date": d_part,
                        "quote_time": t_part,
                        "price_source": "akshare 1分钟分时收盘",
                    }
                ]
            )
            p = os.path.abspath(args.out_csv)
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            one.to_csv(p, index=False, encoding="utf-8-sig")
            print(f"已写入 CSV: {p}")
        return

    print(f"代码: {symbol}" + (f"  {_nm}" if _nm else ""))
    print("暂无分时/快照数据（非交易时段、停牌、网络或接口异常）。")
    if args.fallback_bid_ask:
        try:
            b1, s1, mid = _bid_ask_mid(symbol)
            print("兜底: 买卖一档中间价（盘口，非 1 分钟 K 线）")
            print(f"买1: {b1:.2f}  卖1: {s1:.2f}  中间价: {mid:.2f}")
            if args.out_csv:
                idc = _industry_columns_for_symbol(symbol)
                one = pd.DataFrame(
                    [
                        {
                            "symbol": symbol,
                            "stock_name": _nm,
                            **idc,
                            "ref_price": round(mid, 4),
                            "quote_date": "",
                            "quote_time": "",
                            "price_source": "akshare 买卖一档中间价",
                        }
                    ]
                )
                p = os.path.abspath(args.out_csv)
                os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
                one.to_csv(p, index=False, encoding="utf-8-sig")
                print(f"已写入 CSV: {p}")
        except (requests.RequestException, TimeoutError, OSError, KeyError, ValueError) as e:
            print(f"买卖一档兜底也失败: {e}")
    else:
        print("可加 --fallback-bid-ask 尝试用买卖一档中间价兜底。")


if __name__ == "__main__":
    main()

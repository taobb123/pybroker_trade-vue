#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
券商公司业绩快报抓取与排名（tushare pro）

功能：
1) 用申万行业分类筛出“证券/券商”成分股（即券商公司股票代码）
2) 拉取最近若干个季度的“业绩快报”（express / express_vip）
3) 输出：
   - 每个券商公司“最新一条业绩快报”（按 ann_date）
   - “最新公布日期”对应的券商公司列表
   - 按指定指标（默认：yoy_net_profit）Top N 排名

说明：
- tushare 的 express 接口字段对应的是“业绩快报”，不是“业绩预告”。
- express_vip 需要更高权限；本脚本会在 express_vip 失败时回退到 express（并支持限制券商数量以避免调用过慢）。
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from config.settings import DATA_CONFIG  # type: ignore  # noqa: E402


def _get_pro():
    import tushare as ts  # type: ignore

    token = (DATA_CONFIG.get("tushare_token") or "").strip()
    if not token:
        raise RuntimeError("未配置 tushare_token：请检查 config/settings.py 里的 DATA_CONFIG['tushare_token']")

    ts.set_token(token)
    return ts.pro_api()


def _quarter_end(d: pd.Timestamp) -> pd.Timestamp:
    d = pd.Timestamp(d).normalize()
    y = int(d.year)
    m = int(d.month)
    q = (m - 1) // 3  # 0..3
    end_month = [3, 6, 9, 12][q]
    # 月末天数固定：3/31, 6/30, 9/30, 12/31
    end_day = 30 if end_month in (6, 9) else 31
    return pd.Timestamp(f"{y:04d}-{end_month:02d}-{end_day:02d}")


def _recent_quarter_ends(n_quarters: int, asof: Optional[pd.Timestamp] = None) -> List[str]:
    """
    返回最近 n_quarters 个季度的 period（tushare express 的 period 格式：YYYYMMDD）
    """
    if n_quarters <= 0:
        return []
    if asof is None:
        asof = pd.Timestamp.today()
    x = pd.Timestamp(asof).normalize()
    q_end = _quarter_end(x)

    out: List[str] = []
    cur = q_end
    for _ in range(n_quarters):
        out.append(cur.strftime("%Y%m%d"))
        # 往前退 3 个月，再重新对齐到所在季度的季度末
        cur = _quarter_end(cur - pd.DateOffset(months=3))
    return out


def _fetch_broker_ts_codes(
    pro,
    *,
    end_date_compact: str,
    src_list: Sequence[str] = ("SW2021", "SW2014"),
    name_keywords: Sequence[str] = ("证券", "券商"),
) -> Tuple[List[str], Dict[str, str]]:
    """
    基于申万行业分类筛出“证券/券商”成分股（券商公司）
    返回：
      broker_ts_codes: 去重后的股票代码（如 600000.SH）
      ts_to_name: ts_code -> 股票名称
    """
    found = pd.DataFrame()
    last_err: Optional[Exception] = None

    for src in src_list:
        try:
            df = pro.index_classify(level="L2", src=src)
            if df is None or df.empty:
                continue
            if "industry_name" not in df.columns or "index_code" not in df.columns:
                last_err = RuntimeError(f"index_classify 输出缺少列：{df.columns.tolist() if hasattr(df, 'columns') else 'unknown'}")
                continue
            # 行业名称里包含“证券/券商”的 L2 行业指数，作为券商行业入口
            kw_pattern = "|".join([k.replace("|", "") for k in name_keywords])
            mask = df["industry_name"].astype(str).str.contains(kw_pattern, na=False)
            tmp = df.loc[mask].copy()
            if tmp is None or tmp.empty:
                continue
            found = tmp
            break
        except Exception as e:
            last_err = e
            continue

    if found is None or found.empty:
        raise RuntimeError(f"未能筛到申万 L2 行业（证券/券商）。last_err={last_err}")

    ts_to_name: Dict[str, str] = {}
    broker_ts_codes_set = set()

    # index_member_all 的入参是 l2_code/l3_code（文档示例中 index_code 形如 801053.SI）
    # 因此将 index_classify 的 index_code 当作 l2_code 使用。
    l2_codes = sorted(set(found["index_code"].astype(str).tolist()))
    for l2_code in l2_codes:
        try:
            mem = pro.index_member_all(
                l2_code=l2_code,
                start_date="19900101",
                end_date=end_date_compact,
                is_new="Y",
            )
        except Exception:
            continue

        if mem is None or mem.empty or "ts_code" not in mem.columns:
            continue

        for _, row in mem.iterrows():
            ts_code = str(row.get("ts_code", "")).strip()
            if not ts_code:
                continue
            broker_ts_codes_set.add(ts_code)
            if ts_code not in ts_to_name:
                name = row.get("name")
                if name is not None and str(name).strip():
                    ts_to_name[ts_code] = str(name).strip()

    broker_ts_codes = sorted(broker_ts_codes_set)
    if not broker_ts_codes:
        raise RuntimeError("筛选到的券商成分股为空，请检查 tushare 权限或申万行业关键词。")

    return broker_ts_codes, ts_to_name


def _to_numeric_or_na(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _fetch_express_vip_for_period(
    pro,
    period: str,
    fields: str,
    broker_ts_codes: Iterable[str],
) -> pd.DataFrame:
    """
    express_vip：拉取某一报告期所有公司业绩快报，再过滤券商成分
    """
    df = pro.express_vip(period=period, fields=fields)
    if df is None or df.empty:
        return pd.DataFrame()
    broker_set = set(broker_ts_codes)
    if "ts_code" in df.columns:
        df = df[df["ts_code"].astype(str).isin(broker_set)].copy()
    df["period"] = period
    return df


def _fetch_express_fallback_for_period(
    pro,
    period: str,
    fields: str,
    broker_ts_codes: Sequence[str],
    *,
    max_brokers: int,
) -> pd.DataFrame:
    """
    express：按单只股票拉取（无 express_vip 权限时回退）
    """
    if max_brokers <= 0:
        max_brokers = len(broker_ts_codes)
    sub = list(broker_ts_codes[:max_brokers])

    rows: List[pd.DataFrame] = []
    for ts_code in sub:
        try:
            df1 = pro.express(ts_code=ts_code, period=period, fields=fields)
        except Exception:
            continue
        if df1 is None or df1.empty:
            continue
        df1 = df1.copy()
        df1["period"] = period
        rows.append(df1)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def _fetch_latest_express_for_brokers(
    pro,
    broker_ts_codes: Sequence[str],
    *,
    periods: Sequence[str],
    use_express_vip: bool,
    fields: str,
    max_brokers_for_fallback: int,
) -> pd.DataFrame:
    all_rows: List[pd.DataFrame] = []

    for period in periods:
        df_period = pd.DataFrame()
        if use_express_vip:
            try:
                df_period = _fetch_express_vip_for_period(pro, period, fields, broker_ts_codes)
            except Exception:
                # 回退到单只 express
                df_period = _fetch_express_fallback_for_period(
                    pro,
                    period,
                    fields,
                    broker_ts_codes,
                    max_brokers=max_brokers_for_fallback,
                )
        else:
            df_period = _fetch_express_fallback_for_period(
                pro,
                period,
                fields,
                broker_ts_codes,
                max_brokers=max_brokers_for_fallback,
            )

        if df_period is not None and not df_period.empty:
            all_rows.append(df_period)

    if not all_rows:
        return pd.DataFrame()
    return pd.concat(all_rows, ignore_index=True)


def _latest_row_per_company(df: pd.DataFrame) -> pd.DataFrame:
    """
    对每个券商公司（ts_code）取 ann_date 最新的一行
    """
    if df is None or df.empty:
        return pd.DataFrame()
    if "ts_code" not in df.columns or "ann_date" not in df.columns:
        return pd.DataFrame()

    dd = df.copy()
    dd["ann_date"] = dd["ann_date"].astype(str)
    # ann_date 通常是 YYYYMMDD
    dd["ann_dt"] = pd.to_datetime(dd["ann_date"], format="%Y%m%d", errors="coerce")
    dd = dd.dropna(subset=["ann_dt"])
    dd = dd.sort_values(["ts_code", "ann_dt"], ascending=[True, True])
    out = dd.groupby("ts_code", as_index=False).tail(1).drop(columns=["ann_dt"])
    return out


def main():
    ap = argparse.ArgumentParser(description="抓取券商公司最新业绩快报并排名（tushare pro）")
    ap.add_argument("--quarters", type=int, default=6, help="回看最近多少个季度（默认 6）")
    ap.add_argument("--topn", type=int, default=10, help="Top N（默认 10）")
    ap.add_argument(
        "--metric",
        type=str,
        default="n_income",
        help="排名指标：n_income / yoy_dedu_np / diluted_roe / yoy_sales / diluted_eps 等（默认 n_income）",
    )
    ap.add_argument("--use-vip", action="store_true", help="优先使用 express_vip（默认会尝试并在失败时回退）")
    ap.add_argument("--no-vip", action="store_true", help="强制不使用 express_vip，直接 express 回退")
    ap.add_argument(
        "--max-brokers",
        type=int,
        default=120,
        help="当 express_vip 不可用时，express 回退最多拉取前 N 个券商（默认 120）",
    )
    ap.add_argument("--out-dir", type=str, default=_SCRIPT_DIR, help="输出目录（默认脚本所在目录）")

    args = ap.parse_args()

    use_express_vip = True
    if args.no_vip:
        use_express_vip = False

    # fields：尽量控制字段数量，减少接口响应体
    fields = ",".join(
        [
            "ts_code",
            "ann_date",
            "end_date",
            "revenue",
            "yoy_sales",
            "operate_profit",
            "total_profit",
            "n_income",
            "yoy_net_profit",
            "yoy_dedu_np",
            "diluted_eps",
            "yoy_eps",
            "diluted_roe",
            "yoy_roe",
            "perf_summary",
            "is_audit",
            "remark",
        ]
    )

    pro = _get_pro()
    end_date_compact = pd.Timestamp.today().strftime("%Y%m%d")
    periods = _recent_quarter_ends(args.quarters, asof=pd.Timestamp.today())

    broker_ts_codes, ts_to_name = _fetch_broker_ts_codes(pro, end_date_compact=end_date_compact)
    print(f"筛到券商成分股数：{len(broker_ts_codes)}（示例：{broker_ts_codes[:5]}）")

    df_all = _fetch_latest_express_for_brokers(
        pro,
        broker_ts_codes,
        periods=periods,
        use_express_vip=use_express_vip,
        fields=fields,
        max_brokers_for_fallback=args.max_brokers,
    )

    if df_all is None or df_all.empty:
        raise SystemExit("未获取到任何业绩快报数据，请检查 tushare 权限/网络或调整 --quarters。")

    # 1) 每个券商公司最新一条
    df_latest = _latest_row_per_company(df_all)
    if df_latest is None or df_latest.empty:
        raise SystemExit("数据存在但无法按 ann_date 取每家公司最新行，请检查返回字段。")

    df_latest["name"] = df_latest["ts_code"].map(lambda x: ts_to_name.get(str(x), ""))
    df_latest = df_latest.sort_values("ann_date", ascending=False)

    latest_overall_ann_date = str(df_latest.iloc[0]["ann_date"])
    df_latest_overall = df_latest[df_latest["ann_date"].astype(str) == latest_overall_ann_date].copy()

    # 2) Top 排名（默认 yoy_net_profit）
    if args.metric not in df_latest.columns:
        raise SystemExit(f"metric={args.metric} 不在 express 输出字段中。当前字段：{df_latest.columns.tolist()}")

    df_rank = df_latest.copy()
    df_rank[args.metric] = _to_numeric_or_na(df_rank[args.metric])
    # tiebreak：yoy_net_profit 相同则按 n_income 再排
    if "n_income" in df_rank.columns:
        df_rank["n_income"] = _to_numeric_or_na(df_rank["n_income"])
        df_rank = df_rank.sort_values([args.metric, "n_income"], ascending=[False, False])
    else:
        df_rank = df_rank.sort_values([args.metric], ascending=False)
    df_top = df_rank.head(args.topn).copy()

    os.makedirs(args.out_dir, exist_ok=True)
    out_latest = os.path.join(args.out_dir, "broker_latest_express.csv")
    out_latest_overall = os.path.join(args.out_dir, "broker_latest_express_latest_date.csv")
    out_top = os.path.join(args.out_dir, "broker_express_topn.csv")

    df_latest.to_csv(out_latest, index=False, encoding="utf-8-sig")
    df_latest_overall.to_csv(out_latest_overall, index=False, encoding="utf-8-sig")
    df_top.to_csv(out_top, index=False, encoding="utf-8-sig")

    print(f"每家公司最新业绩快报：{out_latest}（行数 {len(df_latest)}）")
    print(f"最新公布日期={latest_overall_ann_date}的券商列表：{out_latest_overall}（行数 {len(df_latest_overall)}）")
    print(f"Top {args.topn} 排名（metric={args.metric}）：{out_top}（行数 {len(df_top)}）")


if __name__ == "__main__":
    main()


# -*- coding: utf-8 -*-
"""申万一级行业因子：互斥 0/1 暴露，市值权重之和为 1。"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def symbol6(value: object) -> str:
    text = str(value or "").strip().upper()
    if not text or text in {"NAN", "NONE", "NAT", "NULL"}:
        return ""
    head = text.split(".")[0]
    digits = "".join(ch for ch in head if ch.isdigit())
    if not digits:
        return ""
    return digits.zfill(6)[-6:]


def assign_unique_industry(members: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    每只股票只保留一个申万一级。

    同一股票出现在多个一级行业时，保留 in_date 较新的一条；日期相同则保留行业代码较小的一条。
    冲突明细原样返回，不把股票从分类里删掉。
    """
    empty_assigned = pd.DataFrame(
        columns=["symbol", "industry_code", "industry_name", "in_date", "exposure"]
    )
    empty_conflict = pd.DataFrame(
        columns=["symbol", "industry_code", "industry_name", "in_date"]
    )
    if members is None or members.empty:
        return empty_assigned, empty_conflict

    work = members.copy()
    work["symbol"] = work["symbol"].map(symbol6)
    work["industry_code"] = work["industry_code"].astype(str).str.strip()
    work["industry_name"] = work["industry_name"].astype(str).str.strip()
    work = work[(work["symbol"] != "") & (work["industry_code"] != "")]
    if "in_date" not in work.columns:
        work["in_date"] = ""
    work["in_date"] = work["in_date"].fillna("").astype(str)
    work = work.drop_duplicates(subset=["symbol", "industry_code"], keep="last")
    if work.empty:
        return empty_assigned, empty_conflict

    n_ind = work.groupby("symbol")["industry_code"].nunique()
    conflict_symbols = set(n_ind[n_ind > 1].index)
    conflicts = (
        work[work["symbol"].isin(conflict_symbols)]
        .loc[:, ["symbol", "industry_code", "industry_name", "in_date"]]
        .sort_values(["symbol", "in_date", "industry_code"], ascending=[True, False, True])
        .reset_index(drop=True)
    )
    ordered = work.sort_values(
        ["symbol", "in_date", "industry_code"],
        ascending=[True, False, True],
    )
    assigned = ordered.drop_duplicates(subset=["symbol"], keep="first").copy()
    assigned["exposure"] = 1
    assigned = assigned.loc[
        :, ["symbol", "industry_code", "industry_name", "in_date", "exposure"]
    ].reset_index(drop=True)
    return assigned, conflicts.reset_index(drop=True)


def industry_cap_weights(
    assigned: pd.DataFrame,
    market_value: pd.DataFrame,
) -> tuple[pd.DataFrame, dict]:
    """
    行业市值权重。权重分母是已分类且当日总市值为正的股票。

    返回 (行业覆盖表, 核对信息)。覆盖表的 cap_weight 之和等于 1。
    """
    columns = [
        "industry_code",
        "industry_name",
        "n_companies",
        "n_with_mv",
        "total_mv",
        "cap_weight",
    ]
    if assigned is None or assigned.empty:
        return pd.DataFrame(columns=columns), {
            "n_assigned": 0,
            "n_with_mv": 0,
            "classified_mv": 0.0,
            "cap_weight_sum": 0.0,
        }

    base = assigned.copy()
    base["symbol"] = base["symbol"].map(symbol6)
    counts = (
        base.groupby(["industry_code", "industry_name"], as_index=False)
        .agg(n_companies=("symbol", "nunique"))
    )

    mv = pd.DataFrame(columns=["symbol", "total_mv"])
    if market_value is not None and not market_value.empty:
        mv = market_value.copy()
        mv["symbol"] = mv["symbol"].map(symbol6)
        mv["total_mv"] = pd.to_numeric(mv["total_mv"], errors="coerce")
        mv = mv[(mv["symbol"] != "") & mv["total_mv"].notna() & (mv["total_mv"] > 0)]
        mv = mv.groupby("symbol", as_index=False)["total_mv"].sum()

    merged = base.merge(mv, on="symbol", how="left")
    valued = merged[merged["total_mv"].notna() & (merged["total_mv"] > 0)]
    if valued.empty:
        out = counts.copy()
        out["n_with_mv"] = 0
        out["total_mv"] = 0.0
        out["cap_weight"] = np.nan
        info = {
            "n_assigned": int(base["symbol"].nunique()),
            "n_with_mv": 0,
            "classified_mv": 0.0,
            "cap_weight_sum": 0.0,
        }
        return out.loc[:, columns], info

    cap = valued.groupby(["industry_code", "industry_name"], as_index=False).agg(
        n_with_mv=("symbol", "nunique"),
        total_mv=("total_mv", "sum"),
    )
    total = float(cap["total_mv"].sum())
    cap["cap_weight"] = cap["total_mv"] / total if total > 0 else np.nan
    out = counts.merge(cap, on=["industry_code", "industry_name"], how="left")
    out["n_with_mv"] = out["n_with_mv"].fillna(0).astype(int)
    out["total_mv"] = out["total_mv"].fillna(0.0)
    out = out.sort_values(["cap_weight", "industry_code"], ascending=[False, True])
    info = {
        "n_assigned": int(base["symbol"].nunique()),
        "n_with_mv": int(valued["symbol"].nunique()),
        "classified_mv": total,
        "cap_weight_sum": float(out["cap_weight"].sum()),
    }
    return out.loc[:, columns].reset_index(drop=True), info


def mplus_industry_behavior(
    pool: pd.DataFrame,
    assigned: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    把 M+ 池贴上申万一级，并用 mud_plus 观察行业之间的动量差异。

    不增删股票池成员。对不上行业的股票保留，暴露记 0。
    """
    stock_cols = [
        "rank",
        "asof",
        "symbol",
        "stock_name",
        "mud_plus",
        "industry_code",
        "industry_name",
        "exposure",
    ]
    group_cols = [
        "industry_code",
        "industry_name",
        "n",
        "mud_plus_mean",
        "mud_plus_median",
        "mud_plus_min",
        "mud_plus_max",
    ]
    if pool is None or pool.empty:
        return (
            pd.DataFrame(columns=stock_cols),
            pd.DataFrame(columns=group_cols),
            _behavior_info(pd.DataFrame(columns=["mud_plus", "industry_code", "exposure"])),
        )

    stocks = pool.copy()
    stocks["symbol"] = stocks["symbol"].map(symbol6)
    stocks["mud_plus"] = pd.to_numeric(stocks["mud_plus"], errors="coerce")
    if "stock_name" not in stocks.columns:
        stocks["stock_name"] = ""
    if "rank" not in stocks.columns:
        stocks["rank"] = np.arange(1, len(stocks) + 1)
    if "asof" not in stocks.columns:
        stocks["asof"] = ""

    ind = pd.DataFrame(columns=["symbol", "industry_code", "industry_name"])
    if assigned is not None and not assigned.empty:
        ind = assigned.loc[:, ["symbol", "industry_code", "industry_name"]].copy()
        ind["symbol"] = ind["symbol"].map(symbol6)
        ind = ind.drop_duplicates(subset=["symbol"], keep="first")

    merged = stocks.merge(ind, on="symbol", how="left")
    merged["exposure"] = np.where(merged["industry_code"].notna() & (merged["industry_code"] != ""), 1, 0)
    merged["industry_code"] = merged["industry_code"].fillna("")
    merged["industry_name"] = merged["industry_name"].fillna("")
    merged = merged.sort_values(["rank", "symbol"]).reset_index(drop=True)

    mapped = merged[merged["exposure"] == 1]
    if mapped.empty:
        grouped = pd.DataFrame(columns=group_cols)
    else:
        grouped = (
            mapped.groupby(["industry_code", "industry_name"], as_index=False)
            .agg(
                n=("symbol", "nunique"),
                mud_plus_mean=("mud_plus", "mean"),
                mud_plus_median=("mud_plus", "median"),
                mud_plus_min=("mud_plus", "min"),
                mud_plus_max=("mud_plus", "max"),
            )
            .sort_values(["mud_plus_mean", "industry_code"], ascending=[False, True])
            .reset_index(drop=True)
        )
    return merged.loc[:, stock_cols], grouped.loc[:, group_cols], _behavior_info(merged)


def _behavior_info(merged: pd.DataFrame) -> dict:
    mapped = merged[merged["exposure"] == 1] if "exposure" in merged.columns else merged.iloc[0:0]
    mud = pd.to_numeric(mapped["mud_plus"], errors="coerce") if "mud_plus" in mapped.columns else pd.Series(dtype=float)
    usable = mapped.loc[mud.notna(), ["industry_code"]].copy()
    usable["mud_plus"] = mud[mud.notna()].to_numpy()
    info = {
        "n_pool": int(len(merged)),
        "n_mapped": int((merged["exposure"] == 1).sum()) if "exposure" in merged.columns else 0,
        "n_unmapped": int((merged["exposure"] != 1).sum()) if "exposure" in merged.columns else int(len(merged)),
        "n_industries": int(usable["industry_code"].nunique()) if not usable.empty else 0,
        "pool_mud_mean": float(mud.mean()) if mud.notna().any() else None,
        "industry_mean_max": None,
        "industry_mean_min": None,
        "industry_mean_range": None,
        "eta_squared": None,
        "n_singleton_industries": 0,
        "eta_squared_n_ge_2": None,
    }
    if usable.empty:
        return info
    means = usable.groupby("industry_code")["mud_plus"].mean()
    counts = usable.groupby("industry_code")["mud_plus"].size()
    info["industry_mean_max"] = float(means.max())
    info["industry_mean_min"] = float(means.min())
    info["industry_mean_range"] = float(means.max() - means.min())
    info["eta_squared"] = _eta_squared(usable["mud_plus"], usable["industry_code"])
    info["n_singleton_industries"] = int((counts == 1).sum())
    multi = usable[usable["industry_code"].isin(counts[counts >= 2].index)]
    info["eta_squared_n_ge_2"] = _eta_squared(multi["mud_plus"], multi["industry_code"])
    return info


def _eta_squared(values: pd.Series, groups: pd.Series) -> Optional[float]:
    """行业均值能解释的 mud_plus 方差比例。组数不足时返回 None。"""
    frame = pd.DataFrame({"y": pd.to_numeric(values, errors="coerce"), "g": groups.astype(str)})
    frame = frame[frame["y"].notna() & (frame["g"] != "")]
    if frame["g"].nunique() < 2 or len(frame) < 3:
        return None
    grand = float(frame["y"].mean())
    ss_total = float(((frame["y"] - grand) ** 2).sum())
    if ss_total <= 0:
        return 0.0
    means = frame.groupby("g")["y"].transform("mean")
    ss_between = float(((means - grand) ** 2).sum())
    return ss_between / ss_total

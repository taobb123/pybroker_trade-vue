# -*- coding: utf-8 -*-
"""建立申万一级行业因子，并用 M+ 池的 mud_plus 观察行业行为差异。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pandas as pd

from industry_factor.build import assign_unique_industry, industry_cap_weights, mplus_industry_behavior, symbol6
from industry_factor.fetch import fetch_sw_l1_members, fetch_total_mv

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POOL = ROOT / "pattern_entry_mplus_rank.csv"
OUT_DIR = Path(__file__).resolve().parent / "output"


def load_mplus_pool(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"symbol": str}, encoding="utf-8-sig")
    frame["symbol"] = frame["symbol"].map(symbol6)
    frame["mud_plus"] = pd.to_numeric(frame["mud_plus"], errors="coerce")
    return frame


def build_report(
    *,
    pool_path: Path = DEFAULT_POOL,
    out_dir: Path = OUT_DIR,
    pro=None,
) -> dict:
    pool = load_mplus_pool(pool_path)
    if pool.empty or pool["mud_plus"].notna().sum() == 0:
        raise RuntimeError(f"M+ 池没有可用的 mud_plus: {pool_path}")
    asof = str(pool["asof"].iloc[0])[:10] if "asof" in pool.columns else ""

    if pro is None:
        from market_neutral.data.prices import get_tushare_pro

        pro = get_tushare_pro()

    members, src, notes = fetch_sw_l1_members(pro)
    if members.empty:
        detail = "；".join(notes) if notes else "无成分"
        raise RuntimeError(f"没有取到申万一级成分（{detail}）")
    assigned, conflicts = assign_unique_industry(members)
    market_value, mv_asof = fetch_total_mv(pro, asof or "2026-09-28")
    coverage, weight_info = industry_cap_weights(assigned, market_value)
    stocks, grouped, behavior = mplus_industry_behavior(pool, assigned)

    listed_mv = 0.0
    if not market_value.empty:
        listed_mv = float(pd.to_numeric(market_value["total_mv"], errors="coerce").fillna(0).clip(lower=0).sum())
    classified_mv = float(weight_info["classified_mv"])
    listed_exposure_sum = (classified_mv / listed_mv) if listed_mv > 0 else None

    report = {
        "classification": f"申万一级 {src}",
        "pool": str(pool_path),
        "pool_asof": asof,
        "mv_asof": mv_asof,
        "exposure": "0/1",
        "n_industries": int(coverage["industry_code"].nunique()) if not coverage.empty else 0,
        "n_assigned": int(weight_info["n_assigned"]),
        "n_conflicts": int(conflicts["symbol"].nunique()) if not conflicts.empty else 0,
        "cap_weight_sum": weight_info["cap_weight_sum"],
        "listed_exposure_sum": listed_exposure_sum,
        "company_count_min": int(coverage["n_companies"].min()) if not coverage.empty else 0,
        "company_count_max": int(coverage["n_companies"].max()) if not coverage.empty else 0,
        "cap_weight_min": float(coverage["cap_weight"].min()) if coverage["cap_weight"].notna().any() else None,
        "cap_weight_max": float(coverage["cap_weight"].max()) if coverage["cap_weight"].notna().any() else None,
        "mplus": behavior,
        "notes": notes,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    members.to_csv(out_dir / "sw_l1_members.csv", index=False, encoding="utf-8-sig")
    assigned.to_csv(out_dir / "sw_l1_exposure.csv", index=False, encoding="utf-8-sig")
    coverage.to_csv(out_dir / "sw_l1_coverage.csv", index=False, encoding="utf-8-sig")
    if not conflicts.empty:
        conflicts.to_csv(out_dir / "sw_l1_conflicts.csv", index=False, encoding="utf-8-sig")
    stocks.to_csv(out_dir / "mplus_industry_exposure.csv", index=False, encoding="utf-8-sig")
    grouped.to_csv(out_dir / "mplus_industry_mud.csv", index=False, encoding="utf-8-sig")
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main(pool_path: Optional[str] = None) -> int:
    path = Path(pool_path) if pool_path else DEFAULT_POOL
    report = build_report(pool_path=path)
    behavior = report["mplus"]
    print(
        f"申万一级 {report['n_industries']} 个行业，已分类 {report['n_assigned']} 只，"
        f"市值权重之和 {report['cap_weight_sum']:.6f}"
    )
    print(
        f"公司数 {report['company_count_min']}–{report['company_count_max']}，"
        f"市值占比 {report['cap_weight_min']:.2%}–{report['cap_weight_max']:.2%}"
    )
    print(
        f"M+ 池 {behavior['n_pool']} 只，对上行业 {behavior['n_mapped']} 只，"
        f"覆盖 {behavior['n_industries']} 个行业，"
        f"行业均值极差 {behavior['industry_mean_range']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

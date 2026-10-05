# -*- coding: utf-8 -*-
"""建立风险指数，并给出市场雷达自选股的暴露。"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from industry_factor.build import symbol6
from risk_index.fetch import fetch_daily_basic, fetch_fundamental, fetch_hs300_ret60, fetch_price_panel
from risk_index.fundamental import apply_market_value, fundamental_raw
from risk_index.price_descriptors import price_raw_frame
from risk_index.spec import DESCRIPTORS, INDEX_LABELS
from risk_index.standardize import compose_indices

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / "output"
INDUSTRY_PATH = ROOT / "industry_factor" / "output" / "sw_l1_exposure.csv"


def load_radar_picks() -> pd.DataFrame:
    from market_radar import load_radar_factor_picks

    picks, _, _ = load_radar_factor_picks()
    frame = pd.DataFrame(picks)
    if frame.empty:
        return pd.DataFrame(columns=["symbol", "name", "group", "rank"])
    frame["symbol"] = frame["symbol"].map(symbol6)
    return frame


def load_industry() -> pd.Series:
    if not INDUSTRY_PATH.is_file():
        return pd.Series(dtype=str)
    frame = pd.read_csv(INDUSTRY_PATH, dtype={"symbol": str}, encoding="utf-8-sig")
    frame["symbol"] = frame["symbol"].map(symbol6)
    return frame.drop_duplicates("symbol").set_index("symbol")["industry_name"]


def value_from_basic(basic: pd.DataFrame) -> pd.DataFrame:
    if basic is None or basic.empty:
        return pd.DataFrame()
    out = pd.DataFrame(index=basic.index)
    pe = pd.to_numeric(basic["pe_ttm"], errors="coerce")
    out["PE_TTM"] = pe.where(pe > 0)
    pb = pd.to_numeric(basic["pb"], errors="coerce")
    out["PB"] = pb.where(pb > 0)
    ps = pd.to_numeric(basic["ps_ttm"], errors="coerce")
    out["PS_TTM"] = ps.where(ps > 0)
    out["股息率"] = pd.to_numeric(basic["dv_ttm"], errors="coerce")
    out["E/P"] = 1.0 / out["PE_TTM"]
    return out


def build(asof: str | None = None) -> dict:
    from market_neutral.data.prices import get_tushare_pro

    day = asof or pd.Timestamp.today().strftime("%Y-%m-%d")
    pro = get_tushare_pro()
    print("[risk] 拉取全市场日线 …", flush=True)
    panel, used = fetch_price_panel(pro, day)
    if panel.empty:
        raise RuntimeError("没有拉到全市场日线，无法做风险指数标准化")
    print("[risk] 估值与沪深300 …", flush=True)
    basic = fetch_daily_basic(pro, used or day)
    hs300 = fetch_hs300_ret60(pro, used or day)
    print("[risk] 财务 …", flush=True)
    latest, annual, notes = fetch_fundamental(pro)
    if not basic.empty and "total_mv" in basic.columns and not latest.empty:
        latest = apply_market_value(latest, basic["total_mv"])
    price = price_raw_frame(
        panel,
        industry_name=load_industry(),
        hs300_ret60=hs300,
        circ_mv=basic["circ_mv"] if "circ_mv" in basic.columns else None,
    )
    blocks = [price, value_from_basic(basic), fundamental_raw(latest, annual)]
    raw = blocks[0]
    for block in blocks[1:]:
        if block is None or block.empty:
            continue
        raw = raw.join(block, how="left")
    print(f"[risk] 标准化 {len(raw)} 只 …", flush=True)
    indices, descriptors = compose_indices(raw)
    picks = load_radar_picks()
    if picks.empty:
        picked = indices.iloc[0:0].copy()
    else:
        keep = [c for c in ("symbol", "name", "group", "rank") if c in picks.columns]
        picked = picks[keep].merge(indices, left_on="symbol", right_index=True, how="left")
    coverage = {
        label: int(indices[label].notna().sum()) if label in indices.columns else 0
        for label in INDEX_LABELS.values()
    }
    used_names = [d.name for d in DESCRIPTORS if d.name in descriptors.columns]
    skipped = [d.name for d in DESCRIPTORS if d.sign is not None and d.name not in descriptors.columns]
    report = {
        "asof": used,
        "universe": int(len(raw)),
        "weight": "描述变量标准化后等权，指数再标准化为零均值、单位标准差",
        "winsor": "全市场 1% 与 99% 截断",
        "pick_count": int(len(picked)),
        "coverage": coverage,
        "descriptors_used": used_names,
        "descriptors_skipped": skipped,
        "value_direction": "估值倍数越高价值数值越高；股息率和 E/P 越高价值数值越低",
        "notes": notes
        + [
            "20日平均换手率方向为非单调，未纳入流动性指数。",
            "买卖价差、未来增长预期、浮动利率债务占比没有可用行情，未纳入。",
        ],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    picked.to_csv(OUT / "radar_exposure.csv", index=False, encoding="utf-8-sig")
    if not picked.empty and "group" in picked.columns:
        picked[picked["group"] == "M加"].to_csv(OUT / "mplus_radar_exposure.csv", index=False, encoding="utf-8-sig")
    indices.assign(symbol=indices.index).to_csv(OUT / "universe_exposure.csv", index=False, encoding="utf-8-sig")
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    report = build()
    print(
        f"截面 {report['asof']}，全市场 {report['universe']} 只，"
        f"雷达自选 {report['pick_count']} 只"
    )
    print("已纳入:", "、".join(report["descriptors_used"]))
    print("未纳入:", "、".join(report["descriptors_skipped"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

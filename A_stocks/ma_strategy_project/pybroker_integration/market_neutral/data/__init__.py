# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

import pandas as pd

from market_neutral.config import MNConfig, ensure_sys_path


@dataclass
class PoolMember:
    symbol: str
    combo_id: int
    stock_name: str = ""


def _norm_sym(x) -> str:
    s = "".join(c for c in str(x) if c.isdigit())
    return s.zfill(6) if s else ""


def load_observation_pool(cfg: MNConfig) -> Tuple[List[PoolMember], pd.DataFrame]:
    """
    合并 combo4/6 观察代码 txt + watch CSV。
    同一代码若分属两侧，保留两条（形态评估按各自 combo）。
    """
    ensure_sys_path()
    from fetch_vp_six_combo import (
        load_symbols_pool_txt,
        pattern_entry_symbols_path,
        watch_csv_path,
    )

    members: List[PoolMember] = []
    watch_frames: List[pd.DataFrame] = []
    seen: set = set()

    for cid in cfg.combo_ids:
        txt = pattern_entry_symbols_path(int(cid))
        csv_path = watch_csv_path(int(cid), out_dir=cfg.integration_root)
        syms = load_symbols_pool_txt(txt)
        name_map: Dict[str, str] = {}
        if os.path.isfile(csv_path):
            try:
                wdf = pd.read_csv(csv_path, encoding="utf-8-sig")
            except Exception:
                wdf = pd.DataFrame()
            if not wdf.empty and "symbol" in wdf.columns:
                wdf = wdf.copy()
                wdf["symbol"] = wdf["symbol"].map(_norm_sym)
                wdf["combo_id"] = int(cid)
                watch_frames.append(wdf)
                if "stock_name" in wdf.columns:
                    for _, r in wdf.iterrows():
                        name_map[_norm_sym(r["symbol"])] = str(r.get("stock_name") or "")
                for s in wdf["symbol"].tolist():
                    if s and s not in syms:
                        syms.append(s)
        for s in syms:
            sym = _norm_sym(s)
            if len(sym) != 6:
                continue
            key = (sym, int(cid))
            if key in seen:
                continue
            seen.add(key)
            members.append(
                PoolMember(symbol=sym, combo_id=int(cid), stock_name=name_map.get(sym, ""))
            )

    watch_all = (
        pd.concat(watch_frames, ignore_index=True) if watch_frames else pd.DataFrame()
    )
    return members, watch_all


def unique_symbols(members: Sequence[PoolMember]) -> List[str]:
    out: List[str] = []
    seen = set()
    for m in members:
        if m.symbol not in seen:
            seen.add(m.symbol)
            out.append(m.symbol)
    return out

# -*- coding: utf-8 -*-
"""
观察池历史快照归档。

由 fetch_vp_six_combo.export_combo_watch_lists 在写入当日 watch CSV 后调用；
market_neutral 回测按调仓日读取「≤该日」最近快照，降低存活者偏差。

目录结构（默认）:
  market_neutral/archive/watch_pool/
    watch_4_20260730.csv
    watch_6_20260730.csv
    index.csv   # archive_date, combo_id, path, n_symbols
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

_PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ARCHIVE_DIR = os.path.join(_PKG_DIR, "archive", "watch_pool")


def _norm_sym(x) -> str:
    s = "".join(c for c in str(x) if c.isdigit())
    return s.zfill(6) if s else ""


def _date_tag(asof: str) -> str:
    s = str(asof or "").strip()[:10].replace("-", "")
    if len(s) == 8 and s.isdigit():
        return s
    return datetime.now().strftime("%Y%m%d")


def archive_dir(root: Optional[str] = None) -> str:
    d = root or DEFAULT_ARCHIVE_DIR
    os.makedirs(d, exist_ok=True)
    return d


def snapshot_path(combo_id: int, asof: str, *, root: Optional[str] = None) -> str:
    return os.path.join(archive_dir(root), f"watch_{int(combo_id)}_{_date_tag(asof)}.csv")


def index_path(root: Optional[str] = None) -> str:
    return os.path.join(archive_dir(root), "index.csv")


def resolve_asof_from_watch(watch: pd.DataFrame, fallback: Optional[str] = None) -> str:
    """优先用 watch.signal_date 最大交易日，否则 fallback / 今天。"""
    if watch is not None and not watch.empty and "signal_date" in watch.columns:
        dates = pd.to_datetime(watch["signal_date"], errors="coerce").dropna()
        if len(dates):
            return pd.Timestamp(dates.max()).strftime("%Y-%m-%d")
    if fallback:
        return str(fallback)[:10]
    return datetime.now().strftime("%Y-%m-%d")


def save_watch_snapshot(
    watch: pd.DataFrame,
    combo_id: int,
    *,
    asof: Optional[str] = None,
    root: Optional[str] = None,
) -> str:
    """
    落盘单 combo 快照并更新 index.csv。
    同日同 combo 覆盖写入（每日多次跑六组合时保留最后一版）。
    """
    cid = int(combo_id)
    asof_s = resolve_asof_from_watch(watch, asof)
    path = snapshot_path(cid, asof_s, root=root)
    ddir = os.path.dirname(path)
    os.makedirs(ddir, exist_ok=True)
    if watch is None or watch.empty:
        df = pd.DataFrame(columns=["symbol", "combo_id", "signal_date", "stock_name"])
    else:
        df = watch.copy()
        if "symbol" in df.columns:
            df["symbol"] = df["symbol"].map(_norm_sym)
        if "combo_id" not in df.columns:
            df["combo_id"] = cid
    df.to_csv(path, index=False, encoding="utf-8-sig")
    _upsert_index(
        archive_date=asof_s,
        combo_id=cid,
        path=path,
        n_symbols=int(df["symbol"].nunique()) if "symbol" in df.columns and not df.empty else 0,
        root=root,
    )
    return path


def _upsert_index(
    *,
    archive_date: str,
    combo_id: int,
    path: str,
    n_symbols: int,
    root: Optional[str] = None,
) -> None:
    ip = index_path(root)
    row = {
        "archive_date": str(archive_date)[:10],
        "combo_id": int(combo_id),
        "path": os.path.abspath(path),
        "n_symbols": int(n_symbols),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    if os.path.isfile(ip):
        try:
            idx = pd.read_csv(ip, encoding="utf-8-sig")
        except Exception:
            idx = pd.DataFrame()
    else:
        idx = pd.DataFrame()
    if not idx.empty:
        mask = (idx["archive_date"].astype(str).str[:10] == row["archive_date"]) & (
            idx["combo_id"].astype(int) == int(combo_id)
        )
        idx = idx.loc[~mask].copy()
        idx = pd.concat([idx, pd.DataFrame([row])], ignore_index=True)
    else:
        idx = pd.DataFrame([row])
    idx = idx.sort_values(["archive_date", "combo_id"]).reset_index(drop=True)
    idx.to_csv(ip, index=False, encoding="utf-8-sig")


def seed_from_current_watch(
    *,
    integration_root: str,
    combo_ids: Sequence[int] = (4, 6),
    root: Optional[str] = None,
) -> List[str]:
    """
    对「尚无任何归档」的 combo，用当前 vp_combo_watch_{id}.csv 播种一版。
    已有其它 combo 归档时，仍可为缺失的 combo 单独播种（避免 4+6 有档却跳过 2+3）。
    """
    notes: List[str] = []
    archived: set = set()
    ip = index_path(root)
    if os.path.isfile(ip):
        try:
            idx = pd.read_csv(ip, encoding="utf-8-sig")
            if not idx.empty and "combo_id" in idx.columns:
                archived = {int(x) for x in idx["combo_id"].dropna().tolist()}
        except Exception:
            pass
    for cid in combo_ids:
        cid_i = int(cid)
        if cid_i in archived:
            notes.append(f"watch[{cid_i}] 已有归档，跳过播种")
            continue
        path = os.path.join(integration_root, f"vp_combo_watch_{cid_i}.csv")
        if not os.path.isfile(path):
            notes.append(f"无当前 watch[{cid_i}]，跳过")
            continue
        try:
            df = pd.read_csv(path, encoding="utf-8-sig")
        except Exception as exc:
            notes.append(f"读取 watch[{cid_i}] 失败: {exc}")
            continue
        out = save_watch_snapshot(df, cid_i, root=root)
        notes.append(f"播种 watch[{cid_i}] → {out}")
    return notes


def list_archive_dates(combo_id: int, *, root: Optional[str] = None) -> List[pd.Timestamp]:
    ip = index_path(root)
    if not os.path.isfile(ip):
        return []
    try:
        idx = pd.read_csv(ip, encoding="utf-8-sig")
    except Exception:
        return []
    if idx.empty:
        return []
    sub = idx[idx["combo_id"].astype(int) == int(combo_id)]
    dates = pd.to_datetime(sub["archive_date"], errors="coerce").dropna()
    return sorted({pd.Timestamp(d).normalize() for d in dates})


def load_snapshot_asof(
    combo_id: int,
    asof: str,
    *,
    root: Optional[str] = None,
) -> pd.DataFrame:
    """加载 ≤ asof 的最近一版快照；没有则空表。"""
    ip = index_path(root)
    if not os.path.isfile(ip):
        return pd.DataFrame()
    try:
        idx = pd.read_csv(ip, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame()
    if idx.empty:
        return pd.DataFrame()
    asof_ts = pd.Timestamp(str(asof)[:10]).normalize()
    sub = idx[idx["combo_id"].astype(int) == int(combo_id)].copy()
    if sub.empty:
        return pd.DataFrame()
    sub["archive_date"] = pd.to_datetime(sub["archive_date"], errors="coerce")
    sub = sub[sub["archive_date"].notna() & (sub["archive_date"] <= asof_ts)]
    if sub.empty:
        return pd.DataFrame()
    row = sub.sort_values("archive_date").iloc[-1]
    path = str(row["path"])
    if not os.path.isfile(path):
        # 兼容相对路径
        alt = os.path.join(archive_dir(root), os.path.basename(path))
        path = alt if os.path.isfile(alt) else path
    if not os.path.isfile(path):
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame()
    if not df.empty and "symbol" in df.columns:
        df = df.copy()
        df["symbol"] = df["symbol"].map(_norm_sym)
        df["combo_id"] = int(combo_id)
    return df


def collect_archived_symbols(
    combo_ids: Sequence[int],
    *,
    root: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> List[str]:
    """扫描归档快照，收集回测区间内出现过的全部代码（供拉行情）。"""
    ip = index_path(root)
    if not os.path.isfile(ip):
        return []
    try:
        idx = pd.read_csv(ip, encoding="utf-8-sig")
    except Exception:
        return []
    if idx.empty:
        return []
    idx = idx[idx["combo_id"].astype(int).isin([int(c) for c in combo_ids])].copy()
    if start:
        idx = idx[pd.to_datetime(idx["archive_date"], errors="coerce") >= pd.Timestamp(str(start)[:10])]
    if end:
        idx = idx[pd.to_datetime(idx["archive_date"], errors="coerce") <= pd.Timestamp(str(end)[:10])]
    syms: set = set()
    for path in idx["path"].astype(str).tolist():
        p = path
        if not os.path.isfile(p):
            alt = os.path.join(archive_dir(root), os.path.basename(p))
            p = alt if os.path.isfile(alt) else p
        if not os.path.isfile(p):
            continue
        try:
            df = pd.read_csv(p, encoding="utf-8-sig")
        except Exception:
            continue
        if "symbol" not in df.columns:
            continue
        for s in df["symbol"].tolist():
            ns = _norm_sym(s)
            if len(ns) == 6:
                syms.add(ns)
    return sorted(syms)


def members_asof(
    asof: str,
    combo_ids: Sequence[int],
    *,
    root: Optional[str] = None,
    fallback_members: Optional[Sequence] = None,
) -> Tuple[List, pd.DataFrame, str]:
    """
    返回 (PoolMember 列表, 合并 watch DF, 说明)。
    若归档无数据，使用 fallback_members。
    """
    from market_neutral.data import PoolMember

    frames: List[pd.DataFrame] = []
    notes: List[str] = []
    for cid in combo_ids:
        df = load_snapshot_asof(int(cid), asof, root=root)
        if df.empty:
            notes.append(f"combo{cid}:无≤{asof[:10]}快照")
            continue
        frames.append(df)
        notes.append(f"combo{cid}:{len(df)}只")

    if not frames:
        if fallback_members:
            return list(fallback_members), pd.DataFrame(), "归档未命中→当前池"
        return [], pd.DataFrame(), "归档未命中且无fallback"

    watch = pd.concat(frames, ignore_index=True)
    members: List = []
    seen = set()
    for _, r in watch.iterrows():
        sym = _norm_sym(r.get("symbol", ""))
        if len(sym) != 6:
            continue
        cid = int(r.get("combo_id") or 4)
        key = (sym, cid)
        if key in seen:
            continue
        seen.add(key)
        members.append(
            PoolMember(
                symbol=sym,
                combo_id=cid,
                stock_name=str(r.get("stock_name") or ""),
            )
        )
    return members, watch, "；".join(notes)

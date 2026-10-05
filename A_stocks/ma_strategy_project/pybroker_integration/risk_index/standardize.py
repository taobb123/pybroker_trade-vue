# -*- coding: utf-8 -*-
"""全市场标准化：先截断离群值，再变成零均值、单位标准差。指数内描述变量等权。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from risk_index.spec import DESCRIPTORS, INDEX_LABELS


WINSOR_P = 0.01
MIN_OBS = 30


def winsorize(values: pd.Series, p: float = WINSOR_P) -> pd.Series:
    number = pd.to_numeric(values, errors="coerce").astype(float)
    finite = number[np.isfinite(number)]
    if len(finite) < MIN_OBS:
        return number
    low = float(finite.quantile(p))
    high = float(finite.quantile(1.0 - p))
    return number.clip(lower=low, upper=high)


def zscore(values: pd.Series) -> pd.Series:
    """(x - 均值) / 标准差。均值和标准差在截断后的全样本上计算。"""
    clipped = winsorize(values)
    finite = clipped[np.isfinite(clipped)]
    if len(finite) < MIN_OBS:
        return pd.Series(np.nan, index=values.index, dtype=float)
    center = float(finite.mean())
    scale = float(finite.std(ddof=0))
    if not np.isfinite(scale) or scale < 1e-12:
        return pd.Series(np.nan, index=values.index, dtype=float)
    return (clipped - center) / scale


def compose_indices(raw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    每个描述变量先标准化，再按方向乘 +1 或 -1，指数内等权平均，最后再标准化一次。

    返回 (风险指数, 描述变量标准化暴露)。方向未定或整列缺失的描述变量不进入指数。
    """
    signed_parts: dict[str, list[pd.Series]] = {key: [] for key in INDEX_LABELS}
    z_columns: dict[str, pd.Series] = {}
    for item in DESCRIPTORS:
        if item.name not in raw.columns or item.sign is None:
            continue
        score = zscore(raw[item.name])
        if score.notna().sum() < MIN_OBS:
            continue
        z_columns[item.name] = score
        signed_parts[item.index].append(item.sign * score)

    indices: dict[str, pd.Series] = {}
    for key in INDEX_LABELS:
        parts = signed_parts[key]
        if not parts:
            indices[INDEX_LABELS[key]] = pd.Series(np.nan, index=raw.index, dtype=float)
            continue
        block = pd.concat(parts, axis=1)
        raw_index = block.mean(axis=1, skipna=True)
        raw_index = raw_index.where(block.notna().any(axis=1))
        indices[INDEX_LABELS[key]] = zscore(raw_index)
    index_frame = pd.DataFrame(indices, index=raw.index)
    descriptor_frame = pd.DataFrame(z_columns, index=raw.index) if z_columns else pd.DataFrame(index=raw.index)
    return index_frame, descriptor_frame

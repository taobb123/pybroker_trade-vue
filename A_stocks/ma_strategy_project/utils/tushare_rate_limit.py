#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tushare Pro 客户端限流参数：按官方积分档位推算「每分钟」请求上限。

说明：
- 官网对个人主页「总积分」有展示；SDK 的 ``pro.user(token=...)`` 返回的是各批次到期积分，
  本模块对「到期积分」列求和作为总积分近似值，用于档位判断（与常见账户一致）。
- 若需在本地强制覆盖（例如略低于官方值留余量），可在 ``DATA_CONFIG`` 中设置
  ``tushare_max_requests_per_minute``。
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import pandas as pd


def minute_limit_from_total_points(points: float) -> int:
    """按 Tushare 公开常见档位映射每分钟频次（常规数据）。"""
    try:
        p = float(points)
    except (TypeError, ValueError):
        return 50
    if p >= 5000:
        return 500
    if p >= 2000:
        return 200
    return 50


def _sum_expiring_points(df: Optional[pd.DataFrame]) -> float:
    if df is None or df.empty:
        return 0.0
    for c in df.columns:
        if "积分" in str(c):
            return float(pd.to_numeric(df[c], errors="coerce").fillna(0).sum())
    return float(pd.to_numeric(df.iloc[:, -1], errors="coerce").fillna(0).sum())


def resolve_tushare_rate_limit(
    data_config: Optional[Dict[str, Any]] = None,
) -> Tuple[int, int, str]:
    """
    解析每分钟窗口内允许的最大请求次数。

    Returns:
        (max_requests_per_window, window_seconds, reason_tag)
    """
    data_config = data_config or {}
    window = int(data_config.get("tushare_rate_window_seconds") or 60)
    window = max(1, window)

    explicit = data_config.get("tushare_max_requests_per_minute")
    if explicit is not None:
        try:
            n = int(explicit)
            if n > 0:
                return n, window, "config"
        except (TypeError, ValueError):
            pass

    token = (data_config.get("tushare_token") or "").strip()
    if not token:
        return 50, window, "fallback_no_token"

    try:
        import tushare as ts

        pro = ts.pro_api(token)
        df = pro.user(token=token)
        total = _sum_expiring_points(df)
        if total <= 0:
            return 50, window, "fallback_user_empty"
        limit = minute_limit_from_total_points(total)
        return limit, window, f"points~{total:.0f}"
    except Exception:
        return 50, window, "fallback_user_error"

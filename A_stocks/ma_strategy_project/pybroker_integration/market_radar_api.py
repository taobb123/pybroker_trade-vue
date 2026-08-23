#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盘中市场雷达 API：POST /api/market-radar，服务端 60s 缓存。"""

from __future__ import annotations

import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from market_radar import (
    GROWTH_UNIVERSE_LABEL,
    MAX_SYMBOLS,
    MarketRadarError,
    build_market_radar,
    growth_ranking_mtime,
    load_growth_factor_picks,
    session_state,
    six_digit,
    universe_payload,
)

router = APIRouter(tags=["market-radar"])

_CACHE_TTL_SEC = 60.0
_ERROR_TTL_SEC = 15.0
_lock = threading.Lock()
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


class RadarBody(BaseModel):
    """默认忽略前端自选，改用成长因子 M加/Q 前三；symbols 仅作调试覆盖。"""

    symbols: list[str] = Field(default_factory=list, max_length=MAX_SYMBOLS)
    use_watchlist: bool = False


def _placeholder_stocks(picks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in picks:
        out.append(
            {
                "symbol": p["symbol"],
                "ts_code": "",
                "name": p.get("name") or p["symbol"],
                "group": p.get("group"),
                "rank": p.get("rank"),
                "industry": p.get("industry") or None,
                "pct": None,
                "sector_code": None,
                "sector_name": None,
                "sector_level": None,
                "sector_pct": None,
                "rs_index": None,
                "rs_sector": None,
                "strength": None,
                "lamp": "unknown",
                "quote_kind": "missing",
            }
        )
    return out


def _error_payload(message: str) -> dict[str, Any]:
    picks, hint = load_growth_factor_picks()
    return {
        "ok": False,
        "error": message,
        "as_of": None,
        "session": session_state(None),
        "cached": False,
        "sector_stale": None,
        "source": GROWTH_UNIVERSE_LABEL,
        "universe": universe_payload(picks, hint),
        "indexes": [],
        "sectors": [],
        "stocks": _placeholder_stocks(picks),
        "alerts": [],
    }


def _cache_key(body: RadarBody) -> str:
    mtime = growth_ranking_mtime()
    if body.use_watchlist:
        uniq: list[str] = []
        seen: set[str] = set()
        for raw in body.symbols:
            s = six_digit(raw)
            if s and s not in seen:
                seen.add(s)
                uniq.append(s)
        return f"watch:{mtime}:{','.join(sorted(uniq))}"
    return f"growth:{mtime}"


def _get_cached(key: str) -> dict[str, Any] | None:
    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if not hit:
            return None
        ts, payload = hit
        ttl = _ERROR_TTL_SEC if not payload.get("ok", True) else _CACHE_TTL_SEC
        if now - ts >= ttl:
            return None
        out = dict(payload)
        out["cached"] = True
        return out


def _put_cache(key: str, payload: dict[str, Any]) -> None:
    with _lock:
        _cache[key] = (time.time(), dict(payload))


@router.post("/api/market-radar")
def market_radar(body: RadarBody | None = None) -> dict[str, Any]:
    body = body or RadarBody()
    key = _cache_key(body)
    cached = _get_cached(key)
    if cached is not None:
        return cached
    try:
        symbols = body.symbols if body.use_watchlist else []
        payload = build_market_radar(symbols)
    except MarketRadarError as exc:
        err = _error_payload(str(exc))
        _put_cache(key, err)
        return err
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"市场雷达暂不可用：{exc}") from exc
    payload["cached"] = False
    _put_cache(key, payload)
    return payload

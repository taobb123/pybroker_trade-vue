#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盘中市场雷达：大盘 / 申万板块 / 观察池个股相对强弱（准实时，非 Level-2）。"""

from __future__ import annotations

import importlib.util
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

# 与 workflow-platform/src/config/marketRadarRules.ts 对齐
RS_STRONG_INDEX = 0.5
RS_WEAK_INDEX = -1.0
VOLUME_SURGE = 0.30
LAG_SECTOR = -2.0
INDEX_PCT_SANITY = 12.0
SECTOR_PCT_SANITY = 20.0
STOCK_PCT_SANITY = 22.0
INDEX_LAMP_BAND = 0.3
MAX_SYMBOLS = 40

INDEX_SPECS = (
    {"ts_code": "000001.SH", "label": "上证"},
    {"ts_code": "000300.SH", "label": "沪深300"},
    {"ts_code": "399006.SZ", "label": "创业板"},
)
HS300_CODE = "000300.SH"

_SCRIPT_DIR = Path(__file__).resolve().parent
_MA_PROJECT_ROOT = _SCRIPT_DIR.parent
_CACHE_PATH = _SCRIPT_DIR / ".cache" / "market_radar_sw_map.json"
GROWTH_RANKING_CSV = _SCRIPT_DIR / "factor_growth_ranking.csv"
GROWTH_GROUPS = ("M加", "Q")
GROWTH_TOP_N = 3
GROWTH_UNIVERSE_LABEL = "按成长因子排序 · M加前3 + Q前3"


class MarketRadarError(RuntimeError):
    """配置或数据源不可用。"""


def _cn_now() -> datetime:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Shanghai"))
    except Exception:
        return datetime.now(timezone(timedelta(hours=8)))


def _ymd(dt: Optional[datetime] = None) -> str:
    return (dt or _cn_now()).strftime("%Y%m%d")


def six_digit(raw: str) -> str:
    s = str(raw or "").strip().upper()
    if "." in s:
        s = s.split(".", 1)[0]
    digits = "".join(c for c in s if c.isdigit())
    return digits.zfill(6) if digits else ""


def to_ts_code(symbol_6: str) -> str:
    c = six_digit(symbol_6)
    if not c:
        return ""
    if c.startswith("6"):
        return f"{c}.SH"
    if c.startswith(("8", "4")):
        return f"{c}.BJ"
    return f"{c}.SZ"


def _sw_ts(code: Any) -> str:
    c = str(code or "").strip()
    if not c or c.lower() in {"nan", "none"}:
        return ""
    if "." not in c:
        return f"{c}.SI"
    return c


def _finite(v: Any) -> Optional[float]:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n != n:  # NaN
        return None
    return n


def _cell(row: Any, *names: str) -> Any:
    for name in names:
        if hasattr(row, "index") and name in row.index:
            val = row[name]
            if val is not None and str(val).strip().lower() not in {"", "nan", "none"}:
                return val
        if isinstance(row, dict) and name in row:
            val = row[name]
            if val is not None and str(val).strip().lower() not in {"", "nan", "none"}:
                return val
    return None


def _pct_from_row(row: Any, *, sanity_abs: Optional[float] = None) -> Optional[float]:
    """涨跌幅（百分点）。Tushare daily / sw_daily / rt_sw_k 的 pct_change、pct_chg 已是百分数。

    禁止把 |x|<1 的值再乘 100，否则 +0.64% 会显示成 +64%。
    """
    close = _finite(_cell(row, "close", "price"))
    pre = _finite(_cell(row, "pre_close", "preclose"))
    named = _finite(_cell(row, "pct_change", "pct_chg"))

    from_px = None
    if close is not None and pre is not None and abs(pre) > 1e-6:
        from_px = (close / pre - 1.0) * 100.0

    def _ok(p: Optional[float]) -> bool:
        if p is None or p != p:
            return False
        if sanity_abs is None:
            return True
        return abs(p) <= sanity_abs

    if from_px is not None and pre is not None and pre >= 10 and _ok(from_px):
        return round(from_px, 4)
    if _ok(named):
        return round(float(named), 4)
    if _ok(from_px):
        return round(float(from_px), 4)

    if named is not None and sanity_abs is not None and abs(named) > sanity_abs:
        scaled = named / 100.0
        if _ok(scaled):
            return round(scaled, 4)
    if from_px is not None and sanity_abs is not None and abs(from_px) > sanity_abs:
        scaled = from_px / 100.0
        if _ok(scaled):
            return round(scaled, 4)
    return None


def _token_from_settings_file(path: Path) -> str:
    """按文件路径加载 DATA_CONFIG，避免 import config 命中 pybroker_integration/config。"""
    if not path.is_file():
        return ""
    spec = importlib.util.spec_from_file_location("_market_radar_settings", path)
    if spec is None or spec.loader is None:
        return ""
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cfg = getattr(mod, "DATA_CONFIG", None) or {}
    return str(cfg.get("tushare_token") or "").strip()


def _token_from_workflow_yaml() -> str:
    path = _SCRIPT_DIR / "config" / "workflow_runner.yaml"
    if not path.is_file():
        return ""
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        extra = (data.get("data_sources") or {}).get("extra_env") or {}
        return str(extra.get("TUSHARE_TOKEN") or "").strip()
    except Exception:
        return ""


def resolve_tushare_token() -> str:
    for candidate in (
        (os.getenv("TUSHARE_TOKEN") or "").strip(),
        _token_from_workflow_yaml(),
        _token_from_settings_file(_MA_PROJECT_ROOT / "config" / "settings.py"),
        _token_from_settings_file(_SCRIPT_DIR / "config" / "settings.py"),
    ):
        if candidate:
            return candidate
    return ""


def get_tushare_bundle() -> tuple[Any, Any]:
    """返回 (ts 模块, pro_api)。"""
    token = resolve_tushare_token()
    if not token:
        raise MarketRadarError(
            "未配置 Tushare Token：请在上级目录 config/settings.py 的 DATA_CONFIG['tushare_token'] "
            "填写，或设置环境变量 TUSHARE_TOKEN（不要把空的 YAML extra_env 当成已配置）"
        )
    try:
        import tushare as ts
    except ImportError as exc:
        raise MarketRadarError("未安装 tushare") from exc
    ts.set_token(token)
    return ts, ts.pro_api()


def growth_ranking_mtime() -> str:
    if GROWTH_RANKING_CSV.is_file():
        return str(int(GROWTH_RANKING_CSV.stat().st_mtime))
    return "missing"


def load_growth_factor_picks(top_n: int = GROWTH_TOP_N) -> tuple[list[dict[str, Any]], str | None]:
    """工作流「按成长因子排序」产物：M加前 N + Q 前 N。"""
    if not GROWTH_RANKING_CSV.is_file():
        return [], "未找到 factor_growth_ranking.csv，请先运行工作流「按成长因子排序」。"
    try:
        df = pd.read_csv(GROWTH_RANKING_CSV, encoding="utf-8-sig")
    except Exception:
        df = pd.read_csv(GROWTH_RANKING_CSV, encoding="gbk")
    if df is None or df.empty:
        return [], "成长因子排序表为空，请重新运行「按成长因子排序」。"
    cols = {str(c).strip(): c for c in df.columns}
    group_col = cols.get("分组")
    rank_col = cols.get("排名")
    code_col = cols.get("股票代码") or cols.get("代码")
    name_col = cols.get("股票名称") or cols.get("名称")
    ind_col = cols.get("行业")
    if group_col is None or code_col is None:
        return [], "成长因子排序表缺少「分组」或「股票代码」列。"

    picks: list[dict[str, Any]] = []
    seen: set[str] = set()
    missing_groups: list[str] = []
    for group in GROWTH_GROUPS:
        sub = df[df[group_col].astype(str).str.strip() == group]
        if sub.empty:
            missing_groups.append(group)
            continue
        work = sub.copy()
        if rank_col is not None:
            work["_rank"] = pd.to_numeric(work[rank_col], errors="coerce")
            work = work.sort_values("_rank", ascending=True, na_position="last")
        taken = 0
        for _, row in work.iterrows():
            if taken >= top_n:
                break
            sym = six_digit(row.get(code_col))
            if not sym or sym in seen:
                continue
            seen.add(sym)
            rank_val = row.get("_rank") if "_rank" in work.columns else None
            try:
                rank_n = int(rank_val) if rank_val is not None and rank_val == rank_val else taken + 1
            except (TypeError, ValueError):
                rank_n = taken + 1
            picks.append(
                {
                    "symbol": sym,
                    "name": str(row.get(name_col) or "").strip() if name_col else "",
                    "group": group,
                    "rank": rank_n,
                    "industry": str(row.get(ind_col) or "").strip() if ind_col else "",
                }
            )
            taken += 1
    hint = None
    if not picks:
        hint = "成长因子排序表中没有可用的 M加 / Q 标的。"
    elif missing_groups:
        hint = f"排序表缺少分组：{'、'.join(missing_groups)}"
    return picks, hint


def universe_payload(picks: list[dict[str, Any]], hint: str | None) -> dict[str, Any]:
    return {
        "source": "growth_factor",
        "label": GROWTH_UNIVERSE_LABEL,
        "file": "factor_growth_ranking.csv",
        "hint": hint,
        "count": len(picks),
        "picks": picks,
    }


def session_state(pro: Any | None = None, now: Optional[datetime] = None) -> str:
    now = now or _cn_now()
    if now.weekday() >= 5:
        return "closed"
    if pro is not None:
        try:
            ymd = _ymd(now)
            cal = pro.trade_cal(exchange="SSE", start_date=ymd, end_date=ymd)
            if cal is not None and not cal.empty:
                flag = str(cal.iloc[0].get("is_open", "1")).strip()
                if flag != "1":
                    return "closed"
        except Exception:
            pass
    t = now.time()
    morning = datetime.strptime("09:15", "%H:%M").time() <= t <= datetime.strptime("11:30", "%H:%M").time()
    afternoon = datetime.strptime("13:00", "%H:%M").time() <= t <= datetime.strptime("15:00", "%H:%M").time()
    return "open" if (morning or afternoon) else "closed"


def index_lamp(pct: Optional[float]) -> str:
    if pct is None:
        return "unknown"
    if pct > INDEX_LAMP_BAND:
        return "strong"
    if pct < -INDEX_LAMP_BAND:
        return "weak"
    return "watch"


def stock_lamp(
    stock_pct: Optional[float],
    sector_pct: Optional[float],
    rs_index: Optional[float],
    rs_sector: Optional[float],
) -> str:
    if rs_index is None:
        return "unknown"
    if rs_index < RS_WEAK_INDEX or (
        sector_pct is not None and sector_pct > 0 and stock_pct is not None and stock_pct < 0
    ):
        return "weak"
    if rs_index > RS_STRONG_INDEX and (rs_sector is None or rs_sector >= 0):
        return "strong"
    return "watch"


def strength_score(rs_index: Optional[float], rs_sector: Optional[float]) -> Optional[int]:
    if rs_index is None and rs_sector is None:
        return None
    raw = 50.0 + 10.0 * (rs_index or 0.0) + 8.0 * (rs_sector or 0.0)
    return int(max(0, min(100, round(raw))))


def _load_sw_cache() -> dict[str, Any]:
    try:
        if not _CACHE_PATH.is_file():
            return {"date": "", "items": {}}
        data = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, dict):
            return {"date": "", "items": {}}
        return {"date": str(data.get("date") or ""), "items": items}
    except Exception:
        return {"date": "", "items": {}}


def _save_sw_cache(payload: dict[str, Any]) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _row_to_sw(row: Any) -> dict[str, str]:
    return {
        "l1_code": _sw_ts(_cell(row, "l1_code")),
        "l1_name": str(_cell(row, "l1_name") or "").strip(),
        "l2_code": _sw_ts(_cell(row, "l2_code")),
        "l2_name": str(_cell(row, "l2_name") or "").strip(),
        "l3_code": _sw_ts(_cell(row, "l3_code")),
        "l3_name": str(_cell(row, "l3_name") or "").strip(),
    }


def _pick_member_row(df: pd.DataFrame) -> Optional[pd.Series]:
    if df is None or df.empty:
        return None
    work = df
    if "is_new" in work.columns:
        fresh = work[work["is_new"].astype(str).str.upper() == "Y"]
        if not fresh.empty:
            work = fresh
    return work.iloc[-1]


def resolve_sw_map(pro: Any, ts_codes: list[str]) -> dict[str, dict[str, str]]:
    """ts_code -> 申万层级。优先读日缓存。"""
    cache = _load_sw_cache()
    today = _ymd()
    items: dict[str, dict[str, str]] = dict(cache.get("items") or {})
    missing = [c for c in ts_codes if c not in items or cache.get("date") != today]
    for i, code in enumerate(missing):
        try:
            df = pro.index_member_all(ts_code=code, start_date="19900101", end_date=today, is_new="Y")
        except Exception:
            df = None
        if df is None or (hasattr(df, "empty") and df.empty):
            try:
                df = pro.index_member_all(ts_code=code, start_date="19900101", end_date=today)
            except Exception:
                df = None
        row = _pick_member_row(df) if df is not None else None
        if row is not None:
            items[code] = _row_to_sw(row)
        if i + 1 < len(missing):
            time.sleep(0.12)
    _save_sw_cache({"date": today, "items": items})
    return {c: items[c] for c in ts_codes if c in items}


def _sector_display(sw: dict[str, str]) -> tuple[str, str, str]:
    """返回 (code, name, level)，二级优先。"""
    if sw.get("l2_code") and sw.get("l2_name"):
        return sw["l2_code"], sw["l2_name"], "L2"
    if sw.get("l1_code") and sw.get("l1_name"):
        return sw["l1_code"], sw["l1_name"], "L1"
    if sw.get("l3_code") and sw.get("l3_name"):
        return sw["l3_code"], sw["l3_name"], "L3"
    return "", "", ""


def _lower_df(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return df
    out = df.copy()
    out.columns = [str(c).strip().lower() for c in out.columns]
    return out


def _match_code_rows(df: pd.DataFrame, ts_code: str, *, exact: bool) -> pd.DataFrame:
    codes = df["ts_code"].astype(str).str.strip()
    target = str(ts_code).strip()
    hit = df[codes.str.upper() == target.upper()]
    if not hit.empty:
        return hit
    base = target.split(".")[0]
    bases = codes.str.split(".").str[0]
    hit = df[bases == base]
    if not hit.empty:
        return hit
    if exact:
        return hit
    return df[codes.str.startswith(base)]


def _quote_from_rt_df(
    df: Optional[pd.DataFrame],
    ts_code: str,
    *,
    exact: bool = False,
    sanity_abs: Optional[float] = None,
) -> Optional[dict[str, Any]]:
    df = _lower_df(df)
    if df is None or df.empty:
        return None
    if "ts_code" not in df.columns:
        for alt in ("code", "symbol"):
            if alt in df.columns:
                df = df.rename(columns={alt: "ts_code"})
                break
    if "ts_code" not in df.columns:
        return None
    hit = _match_code_rows(df, ts_code, exact=exact)
    if hit.empty:
        return None
    row = hit.iloc[0]
    pct = _pct_from_row(row, sanity_abs=sanity_abs)
    return {
        "ts_code": ts_code,
        "name": str(_cell(row, "name") or "").strip(),
        "pct": pct,
        "close": _finite(_cell(row, "close", "price")),
        "pre_close": _finite(_cell(row, "pre_close", "preclose")),
        "amount": _finite(_cell(row, "amount")),
        "vol": _finite(_cell(row, "vol", "volume")),
        "trade_time": str(_cell(row, "trade_time", "time", "date", "trade_date") or "").strip(),
        "quote_kind": "realtime",
    }


def fetch_index_quotes(ts_mod: Any, pro: Any) -> list[dict[str, Any]]:
    codes = [s["ts_code"] for s in INDEX_SPECS]
    rt_df = None
    try:
        rt_df = pro.rt_idx_k(ts_code=",".join(codes))
    except Exception:
        rt_df = None
    if rt_df is None or (hasattr(rt_df, "empty") and rt_df.empty):
        try:
            rt_df = ts_mod.realtime_quote(ts_code=",".join(codes), src="sina")
        except Exception:
            rt_df = None

    out: list[dict[str, Any]] = []
    for spec in INDEX_SPECS:
        q = _quote_from_rt_df(rt_df, spec["ts_code"], exact=True, sanity_abs=INDEX_PCT_SANITY)
        if q is None:
            try:
                start = (_cn_now() - timedelta(days=10)).strftime("%Y%m%d")
                daily = pro.index_daily(ts_code=spec["ts_code"], start_date=start, end_date=_ymd())
                if daily is not None and not daily.empty:
                    if "trade_date" in daily.columns:
                        daily = daily.sort_values("trade_date")
                    row = daily.iloc[-1]
                    q = {
                        "ts_code": spec["ts_code"],
                        "name": spec["label"],
                        "pct": _pct_from_row(row, sanity_abs=INDEX_PCT_SANITY),
                        "close": _finite(_cell(row, "close")),
                        "pre_close": _finite(_cell(row, "pre_close")),
                        "amount": _finite(_cell(row, "amount")),
                        "vol": _finite(_cell(row, "vol")),
                        "trade_time": str(_cell(row, "trade_date") or "").strip(),
                        "quote_kind": "daily",
                    }
            except Exception:
                q = None
        item = {
            "ts_code": spec["ts_code"],
            "label": spec["label"],
            "pct": q["pct"] if q else None,
            "close": q["close"] if q else None,
            "lamp": index_lamp(q["pct"] if q else None),
            "quote_kind": q["quote_kind"] if q else "missing",
        }
        out.append(item)
    return out


def fetch_stock_quotes(ts_mod: Any, pro: Any, ts_codes: list[str]) -> dict[str, dict[str, Any]]:
    if not ts_codes:
        return {}
    joined = ",".join(ts_codes)
    rt_df = None
    try:
        rt_df = ts_mod.realtime_quote(ts_code=joined, src="sina")
    except Exception:
        rt_df = None
    if rt_df is None or (hasattr(rt_df, "empty") and rt_df.empty):
        try:
            rt_df = pro.rt_k(ts_code=joined)
        except Exception:
            rt_df = None

    found: dict[str, dict[str, Any]] = {}
    for code in ts_codes:
        q = _quote_from_rt_df(rt_df, code, sanity_abs=STOCK_PCT_SANITY)
        if q:
            found[code] = q

    missing = [c for c in ts_codes if c not in found]
    if missing:
        start = (_cn_now() - timedelta(days=10)).strftime("%Y%m%d")
        try:
            daily = pro.daily(ts_code=",".join(missing), start_date=start, end_date=_ymd())
        except Exception:
            daily = None
        if daily is not None and not daily.empty:
            daily = _lower_df(daily)
            daily = daily.sort_values("trade_date") if daily is not None and "trade_date" in daily.columns else daily
            for code in missing:
                sub = daily[daily["ts_code"].astype(str) == code] if "ts_code" in daily.columns else daily
                if sub is None or sub.empty:
                    continue
                q = _quote_from_rt_df(sub, code, sanity_abs=STOCK_PCT_SANITY)
                if q:
                    q["quote_kind"] = "daily"
                    found[code] = q
    return found


def fetch_sector_quotes(pro: Any, sector_codes: list[str]) -> dict[str, dict[str, Any]]:
    if not sector_codes:
        return {}
    rt_df = None
    try:
        rt_df = pro.rt_sw_k()
    except Exception:
        rt_df = None
    if rt_df is None or (hasattr(rt_df, "empty") and rt_df.empty):
        try:
            rt_df = pro.rt_sw_k(ts_code=",".join(sector_codes))
        except Exception:
            rt_df = None

    found: dict[str, dict[str, Any]] = {}
    for code in sector_codes:
        q = _quote_from_rt_df(rt_df, code, exact=True, sanity_abs=SECTOR_PCT_SANITY)
        if q and q.get("pct") is not None and abs(float(q["pct"])) <= SECTOR_PCT_SANITY:
            found[code] = q

    missing = [c for c in sector_codes if c not in found]
    start = (_cn_now() - timedelta(days=12)).strftime("%Y%m%d")
    end = _ymd()
    today = end
    for code in list(dict.fromkeys([*found.keys(), *missing])):
        prev_amount = None
        today_daily_amount = None
        daily_q = None
        try:
            daily = pro.sw_daily(ts_code=code, start_date=start, end_date=end)
        except Exception:
            daily = None
        if daily is not None and not daily.empty:
            if "trade_date" in daily.columns:
                daily = daily.sort_values("trade_date")
            last = daily.iloc[-1]
            last_date = str(_cell(last, "trade_date") or "").strip()
            daily_q = {
                "ts_code": code,
                "name": str(_cell(last, "name") or "").strip(),
                "pct": _pct_from_row(last, sanity_abs=SECTOR_PCT_SANITY),
                "close": _finite(_cell(last, "close")),
                "pre_close": _finite(_cell(last, "pre_close")),
                "amount": _finite(_cell(last, "amount")),
                "vol": _finite(_cell(last, "vol")),
                "trade_time": last_date,
                "quote_kind": "daily",
            }
            if last_date == today:
                today_daily_amount = daily_q.get("amount")
                if len(daily) >= 2:
                    prev_amount = _finite(_cell(daily.iloc[-2], "amount"))
            else:
                prev_amount = daily_q.get("amount")
            rt_amt = found[code].get("amount") if code in found else None
            if rt_amt is not None and prev_amount:
                yday = prev_amount * 1000.0
                if yday > 0:
                    ratio = rt_amt / yday - 1.0
                    if -0.95 <= ratio <= 12:
                        found[code]["amount_change"] = ratio
            elif today_daily_amount is not None and prev_amount:
                ratio = today_daily_amount / prev_amount - 1.0
                if code in found:
                    found[code]["amount_change"] = ratio
                elif daily_q is not None:
                    daily_q["amount_change"] = ratio
        if code not in found and daily_q:
            found[code] = daily_q
        elif code in found and daily_q:
            rt_pct = found[code].get("pct")
            daily_pct = daily_q.get("pct")
            if daily_pct is not None and (
                rt_pct is None or abs(float(rt_pct)) > SECTOR_PCT_SANITY
            ):
                found[code]["pct"] = daily_pct
                found[code]["quote_kind"] = "daily"
    return found


def build_market_radar(symbols: list[str] | None = None) -> dict[str, Any]:
    now = _cn_now()
    as_of = now.strftime("%Y-%m-%d %H:%M:%S")
    picks, universe_hint = load_growth_factor_picks()
    meta = {p["symbol"]: p for p in picks}
    requested = [six_digit(s) for s in (symbols or [])]
    requested = [s for s in requested if s]
    uniq = requested if requested else [p["symbol"] for p in picks]
    seen: set[str] = set()
    ordered: list[str] = []
    for s in uniq:
        if s and s not in seen:
            seen.add(s)
            ordered.append(s)
        if len(ordered) >= MAX_SYMBOLS:
            break
    uniq = ordered
    universe = universe_payload(picks, universe_hint)

    ts_mod, pro = get_tushare_bundle()
    session = session_state(pro, now)
    indexes = fetch_index_quotes(ts_mod, pro)
    hs300_pct = next((i["pct"] for i in indexes if i["ts_code"] == HS300_CODE), None)

    pairs = [(s, to_ts_code(s)) for s in uniq if to_ts_code(s)]
    ts_codes = [c for _, c in pairs]
    sw_map = resolve_sw_map(pro, ts_codes) if ts_codes else {}
    stock_quotes = fetch_stock_quotes(ts_mod, pro, ts_codes) if ts_codes else {}

    sector_of: dict[str, tuple[str, str, str]] = {}
    sector_codes: list[str] = []
    for code in ts_codes:
        sw = sw_map.get(code) or {}
        sc, sn, lv = _sector_display(sw)
        sector_of[code] = (sc, sn, lv)
        if sc and sc not in sector_codes:
            sector_codes.append(sc)

    sector_quotes = fetch_sector_quotes(pro, sector_codes) if sector_codes else {}
    sector_stale = None
    if sector_quotes and all(q.get("quote_kind") == "daily" for q in sector_quotes.values()):
        sector_stale = "daily"
    elif any(q.get("quote_kind") == "daily" for q in sector_quotes.values()):
        sector_stale = "daily"

    stocks_out: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []
    sector_count: dict[str, int] = {}

    for sym, ts_code in pairs:
        q = stock_quotes.get(ts_code) or {}
        sc, sn, lv = sector_of.get(ts_code, ("", "", ""))
        sq = sector_quotes.get(sc) or {}
        stock_pct = q.get("pct")
        sector_pct = sq.get("pct")
        rs_index = None if stock_pct is None or hs300_pct is None else round(stock_pct - hs300_pct, 4)
        rs_sector = None if stock_pct is None or sector_pct is None else round(stock_pct - sector_pct, 4)
        lamp = stock_lamp(stock_pct, sector_pct, rs_index, rs_sector)
        pick = meta.get(sym) or {}
        name = str(pick.get("name") or q.get("name") or "").strip() or ts_code
        if sc:
            sector_count[sc] = sector_count.get(sc, 0) + 1
        stocks_out.append(
            {
                "symbol": sym,
                "ts_code": ts_code,
                "name": name,
                "group": pick.get("group"),
                "rank": pick.get("rank"),
                "industry": pick.get("industry") or None,
                "pct": stock_pct,
                "sector_code": sc or None,
                "sector_name": sn or None,
                "sector_level": lv or None,
                "sector_pct": sector_pct,
                "rs_index": rs_index,
                "rs_sector": rs_sector,
                "strength": strength_score(rs_index, rs_sector),
                "lamp": lamp,
                "quote_kind": q.get("quote_kind") or "missing",
            }
        )
        if rs_sector is not None and rs_sector < LAG_SECTOR:
            alerts.append(
                {
                    "kind": "lag_sector",
                    "level": "stock",
                    "code": sym,
                    "name": name,
                    "message": f"{name} 跑输板块 {abs(rs_sector):.2f}%",
                    "value": rs_sector,
                }
            )

    sectors_out: list[dict[str, Any]] = []
    for code in sector_codes:
        q = sector_quotes.get(code) or {}
        name = str(q.get("name") or "").strip()
        if not name:
            name = next((sn for sc, sn, _ in sector_of.values() if sc == code and sn), code)
        pct = q.get("pct")
        rs_index = None if pct is None or hs300_pct is None else round(pct - hs300_pct, 4)
        amount_change = q.get("amount_change")
        sectors_out.append(
            {
                "code": code,
                "name": name,
                "level": next((lv for sc, _, lv in sector_of.values() if sc == code), "L2"),
                "pct": pct,
                "amount_change": amount_change,
                "rs_index": rs_index,
                "quote_kind": q.get("quote_kind") or "missing",
                "stock_count": sector_count.get(code, 0),
                "lamp": index_lamp(pct),
            }
        )
        if amount_change is not None and amount_change >= VOLUME_SURGE:
            alerts.append(
                {
                    "kind": "volume_surge",
                    "level": "sector",
                    "code": code,
                    "name": name,
                    "message": f"{name} 成交额 {amount_change * 100:+.0f}%",
                    "value": amount_change,
                }
            )

    sources = [GROWTH_UNIVERSE_LABEL, "tushare"]
    if sector_stale:
        sources.append("sw_daily")
    if any(i.get("quote_kind") == "realtime" for i in indexes):
        sources.append("rt_idx/realtime_quote")

    return {
        "ok": True,
        "as_of": as_of,
        "session": session,
        "cached": False,
        "sector_stale": sector_stale,
        "source": " · ".join(sources),
        "universe": universe,
        "indexes": indexes,
        "sectors": sectors_out,
        "stocks": stocks_out,
        "alerts": alerts,
    }

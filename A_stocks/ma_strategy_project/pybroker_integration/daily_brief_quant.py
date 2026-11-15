# -*- coding: utf-8 -*-
"""每日复盘的量化段落。

研究口径，权重和阶段规则未经验证，不构成交易指令。
缺数据时写「无法计算」，不用估算值代替实测。
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parent
CACHE = ROOT / ".cache" / "daily_brief"
CROSS = CACHE / "cross"
FEATURES = CACHE / "features.csv"
TZ = ZoneInfo("Asia/Shanghai")

FORMULA_VERSION = 1
PERCENTILE_WINDOW = 250
MIN_OBS = 60
LISTING_MIN_DAYS = 60
LISTING_CERTAIN_GAP = 120
TOP_N = 5
CHASE_N = 20
WEIGHTS = {"chase": 0.40, "structure": 0.35, "risk": 0.25}
WINDOWS = (5, 20, 60)

FEATURE_COLUMNS = [
    "date",
    "version",
    "n",
    "chase_mean",
    "chase_median",
    "chase_up",
    "chase_limit",
    "chase_drop5",
    "struct_overlap",
    "struct_spread",
    "struct_up",
    "risk_up",
    "risk_up_n",
    "risk_down_n",
    "risk_flat_n",
    "risk_limit_up",
    "risk_limit_down",
    "risk_amount",
]


def _log(logger, message: str) -> None:
    if logger is not None:
        logger(message)
    else:
        print(message)


def _ok(value) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return number == number and number not in (float("inf"), float("-inf"))


def _iso(ymd: str) -> str:
    digits = re.sub(r"\D", "", str(ymd or ""))
    if len(digits) < 8:
        return ""
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"


def _ymd(iso: str) -> str:
    return str(iso or "").replace("-", "")[:8]


def _finite_count(values) -> int:
    return sum(1 for value in values if _ok(value))


def is_hs_ashare(ts_code: str) -> bool:
    """沪深 A 股。不含北交所、B 股。"""
    code = str(ts_code or "")
    if not (code.endswith(".SH") or code.endswith(".SZ")):
        return False
    symbol = code[:6]
    return not symbol.startswith(("900", "200"))


def is_st_name(name: str) -> bool:
    return "ST" in str(name or "").upper()


def listing_days(list_date: str, rank_day: str, open_days: list[str]) -> int | None:
    """上市至排名日的交易日数。日历跨度已超过 120 天时，交易日必不少于 60。"""
    listed = _iso(list_date)
    rank = _iso(rank_day)
    if not listed or not rank or listed > rank:
        return None
    span = (datetime.strptime(rank, "%Y-%m-%d") - datetime.strptime(listed, "%Y-%m-%d")).days
    if span >= LISTING_CERTAIN_GAP:
        return 10_000
    if not open_days:
        return None
    return sum(1 for day in open_days if listed <= day <= rank)


def resolve_brief_day(
    explicit: str | None,
    now: datetime,
    open_days: list[str],
) -> tuple[str | None, str]:
    """决定本次要复盘的交易日。非交易日返回空日期，调用方应结束且不写行情结论。"""
    opens = [day for day in open_days if day]
    if explicit:
        if explicit not in opens:
            return None, f"{explicit} 不是上交所交易日，本次结束"
        return explicit, ""
    today = now.strftime("%Y-%m-%d")
    if today not in opens:
        return None, f"{today} 不是上交所交易日，本次结束"
    cutoff = now.replace(hour=15, minute=5, second=0, microsecond=0)
    if now < cutoff:
        prior = [day for day in opens if day < today]
        if not prior:
            return None, f"{today} 尚未收盘，且没有更早的交易日，本次结束"
        return prior[-1], f"{today} 尚未收盘，改用最近已收盘交易日 {prior[-1]}"
    return today, ""


def previous_open(open_days: list[str], day: str) -> str | None:
    prior = [item for item in open_days if item < day]
    return prior[-1] if prior else None


def shift_open(open_days: list[str], day: str, offset: int) -> str | None:
    if day not in open_days:
        return None
    index = open_days.index(day) + offset
    if index < 0 or index >= len(open_days):
        return None
    return open_days[index]


def session_closed(day: str, now: datetime) -> bool:
    current = now.date()
    target = datetime.strptime(day, "%Y-%m-%d").date()
    if target < current:
        return True
    if target > current:
        return False
    return now >= now.replace(hour=15, minute=5, second=0, microsecond=0)


def pct_of(values, window: int = PERCENTILE_WINDOW, min_obs: int = MIN_OBS) -> float | None:
    """最后一个值在窗口内的分位数（0–100）。窗口含当日。有效值不足则无法计算。"""
    seq = list(values)[-window:]
    if not seq or not _ok(seq[-1]):
        return None
    finite = [float(item) for item in seq if _ok(item)]
    if len(finite) < min_obs:
        return None
    today = float(seq[-1])
    return sum(item <= today for item in finite) / len(finite) * 100.0


def reversed_pct(values, window: int = PERCENTILE_WINDOW, min_obs: int = MIN_OBS) -> float | None:
    rank = pct_of(values, window=window, min_obs=min_obs)
    if rank is None:
        return None
    return 100.0 - rank


def pillar_score(parts: list[tuple[str, float | None, bool]]) -> tuple[float | None, str]:
    """必需成分缺一则整支柱无法计算。可选成分缺失时不补估，只对其余已有成分等权。"""
    missing = [name for name, value, required in parts if required and not _ok(value)]
    if missing:
        return None, "无法计算：" + "、".join(missing)
    used = [(name, float(value)) for name, value, _required in parts if _ok(value)]
    if not used:
        return None, "无法计算"
    score = sum(value for _name, value in used) / len(used)
    return score, "、".join(name for name, _value in used)


def composite_score(chase, structure, risk) -> float | None:
    if not (_ok(chase) and _ok(structure) and _ok(risk)):
        return None
    return (
        WEIGHTS["chase"] * float(chase)
        + WEIGHTS["structure"] * float(structure)
        + WEIGHTS["risk"] * float(risk)
    )


def ranks_from_returns(returns: dict[str, float]) -> dict[str, int]:
    ordered = sorted(returns.items(), key=lambda item: (-float(item[1]), item[0]))
    return {name: index for index, (name, _ret) in enumerate(ordered, 1)}


def top_names(returns: dict[str, float], count: int = TOP_N) -> list[str]:
    ordered = sorted(returns.items(), key=lambda item: (-float(item[1]), item[0]))
    return [name for name, _ret in ordered[:count]]


def bottom_names(returns: dict[str, float], count: int = TOP_N) -> list[str]:
    ordered = sorted(returns.items(), key=lambda item: (float(item[1]), item[0]))
    return [name for name, _ret in ordered[:count]]


def structure_labels(
    ret5: dict[str, float],
    ret20: dict[str, float],
    ret60: dict[str, float],
    rank20_five_days_ago: dict[str, int] | None,
    up_ratio: dict[str, float],
) -> dict:
    """多周期标签可以并列。缺排名或上涨占比时，不把该条件当成成立。"""
    top5 = top_names(ret5, TOP_N) if len(ret5) >= TOP_N else []
    top20 = top_names(ret20, TOP_N) if len(ret20) >= TOP_N else []
    rank5 = ranks_from_returns(ret5)
    rank20 = ranks_from_returns(ret20)
    rank60 = ranks_from_returns(ret60)
    old = rank20_five_days_ago or {}
    overlap = [name for name in top5 if name in set(top20)]
    notes: list[str] = []
    if rank20_five_days_ago is None:
        notes.append("缺少 5 个交易日前的 20 日排名，延续与轮动不使用这项")

    continued = []
    for name in overlap:
        old_rank = old.get(name)
        if old_rank is not None and old_rank <= 10:
            continued.append(name)

    worse = 0
    compared = 0
    for name in top20:
        old_rank = old.get(name)
        new_rank = rank20.get(name)
        if old_rank is None or new_rank is None:
            continue
        compared += 1
        if new_rank > old_rank:
            worse += 1
    rotation = len(overlap) <= 1 and worse >= 2 and rank20_five_days_ago is not None
    if rank20_five_days_ago is not None and compared < len(top20):
        notes.append("部分 20 日领涨板块缺少 5 日前排名，只统计能对照的板块")

    ebb = []
    for name in set(top20) | set(top_names(ret60, TOP_N) if len(ret60) >= TOP_N else []):
        weak = (name in ret5 and float(ret5[name]) < 0) or (name in rank5 and rank5[name] > 10)
        if not weak or name not in up_ratio or not _ok(up_ratio[name]):
            continue
        if float(up_ratio[name]) < 0.50:
            ebb.append(name)

    fresh = []
    for name in top5:
        if name not in rank20 or name not in rank60:
            continue
        if rank20[name] > 10 and rank60[name] > 10:
            fresh.append(name)

    return {
        "continue": continued,
        "rotation": rotation,
        "rotation_overlap": len(overlap),
        "rotation_names": overlap,
        "ebb": ebb,
        "new": fresh,
        "notes": notes,
    }


def stance_of(phase: str, confidence: str) -> str:
    if phase in ("冰点", "退潮"):
        return "防守"
    if phase in ("分化", "高潮"):
        return "精选"
    if phase in ("回暖", "上升"):
        return "进攻" if confidence != "低" else "精选"
    return "无法给出"


def judge_phase(
    score,
    velocity,
    up_ratio,
    chase_mean,
    drop5,
    labels: dict,
    limit_up,
    limit_down,
) -> dict:
    """按披露的顺序匹配。综合分无法计算时不推测阶段。"""
    labels = labels or {}
    continued = list(labels.get("continue") or [])
    ebb = list(labels.get("ebb") or [])
    rotation = bool(labels.get("rotation"))
    if not _ok(score):
        return {
            "phase": "无法判断",
            "confidence": "无法评估",
            "stance": "无法给出",
            "support": ["综合分无法计算"],
            "counter": [],
        }

    def pack(phase: str, support: list[str], counter: list[str]) -> dict:
        support_n = len(support)
        counter_n = len(counter)
        if support_n >= 3 and counter_n == 0:
            confidence = "高"
        elif support_n >= 2 and counter_n <= 1:
            confidence = "中"
        else:
            confidence = "低"
        return {
            "phase": phase,
            "confidence": confidence,
            "stance": stance_of(phase, confidence),
            "support": support,
            "counter": counter,
        }

    counters_ice = []
    if _ok(chase_mean) and float(chase_mean) > 0:
        counters_ice.append("柏拉爱空平均收益为正")
    if continued:
        counters_ice.append("存在延续板块")
    if _ok(limit_up) and _ok(limit_down) and float(limit_up) > float(limit_down):
        counters_ice.append("涨停家数多于跌停家数")
    if _ok(velocity) and float(velocity) <= 0 and _ok(up_ratio) and float(up_ratio) < 0.40 and float(score) < 25:
        return pack(
            "冰点",
            ["综合分低于 25", "情绪速度不高于 0", "上涨家数占比低于 40%"],
            counters_ice,
        )

    counters_hot = []
    if _ok(velocity) and float(velocity) < 0:
        counters_hot.append("情绪速度为负")
    if ebb:
        counters_hot.append("存在退潮板块")
    if _ok(drop5) and float(drop5) >= 0.20:
        counters_hot.append("收益率≤-5%的比例不低于 20%")
    if float(score) >= 75 and _ok(up_ratio) and float(up_ratio) >= 0.55 and _ok(chase_mean) and float(chase_mean) > 0:
        return pack(
            "高潮",
            ["综合分不低于 75", "上涨家数占比不低于 55%", "柏拉爱空平均收益为正"],
            counters_hot,
        )

    ebb_clause = bool(ebb) or (
        _ok(chase_mean) and float(chase_mean) < 0 and _ok(velocity) and float(velocity) < 0
    )
    if float(score) < 60 and ebb_clause:
        support = ["综合分低于 60"]
        if ebb:
            support.append("存在退潮板块")
        if _ok(chase_mean) and float(chase_mean) < 0 and _ok(velocity) and float(velocity) < 0:
            support.append("柏拉爱空平均收益为负且情绪速度为负")
        counter = []
        if _ok(velocity) and float(velocity) > 0:
            counter.append("情绪速度为正")
        if labels.get("new"):
            counter.append("存在新方向")
        if _ok(up_ratio) and float(up_ratio) >= 0.55:
            counter.append("上涨家数占比不低于 55%")
        if rotation:
            counter.append("同时出现轮动")
        return pack("退潮", support, counter)

    score_band = 40 <= float(score) <= 70
    breadth_band = _ok(up_ratio) and 0.45 <= float(up_ratio) <= 0.58
    if rotation or (score_band and breadth_band):
        support = []
        if rotation:
            support.append("5 日与 20 日领涨明显错位")
        if score_band:
            support.append("综合分位于 40–70")
        if breadth_band:
            support.append("上涨家数占比位于 45%–58%")
        counter = []
        if len(continued) >= 3:
            counter.append("延续板块不少于 3 个")
        if _ok(velocity) and float(velocity) >= 5:
            counter.append("情绪速度不低于 5")
        return pack("分化", support, counter)

    if float(score) >= 55 and _ok(velocity) and float(velocity) >= 0 and _ok(up_ratio) and float(up_ratio) >= 0.50:
        counter = []
        if ebb:
            counter.append("存在退潮板块")
        if _ok(chase_mean) and float(chase_mean) < 0:
            counter.append("柏拉爱空平均收益为负")
        return pack(
            "上升",
            ["综合分不低于 55", "情绪速度不低于 0", "上涨家数占比不低于 50%"],
            counter,
        )

    if float(score) >= 30 and _ok(velocity) and float(velocity) > 0 and _ok(up_ratio) and float(up_ratio) >= 0.40:
        counter = []
        if _ok(chase_mean) and float(chase_mean) < 0:
            counter.append("柏拉爱空平均收益为负")
        if ebb:
            counter.append("存在退潮板块")
        return pack(
            "回暖",
            ["综合分不低于 30", "情绪速度为正", "上涨家数占比不低于 40%"],
            counter,
        )

    if not _ok(velocity):
        return {
            "phase": "无法判断",
            "confidence": "无法评估",
            "stance": "无法给出",
            "support": ["速度无法计算，未套用依赖速度的兜底规则"],
            "counter": [],
        }
    if float(score) < 40 and float(velocity) <= 0:
        return pack("退潮", ["综合分低于 40 且情绪速度不高于 0"], [])
    return pack("分化", ["未命中前面的阶段条件"], [])


def intraday_max_drawdown(highs: list[float], lows: list[float]) -> float | None:
    """当日最高价首次出现之后（含该分钟最低价）的回撤，相对该最高价。"""
    pairs = [(float(high), float(low)) for high, low in zip(highs, lows) if _ok(high) and _ok(low)]
    if not pairs:
        return None
    peak = max(high for high, _low in pairs)
    if peak <= 0:
        return None
    index = next(pos for pos, (high, _low) in enumerate(pairs) if high == peak)
    trough = min(low for _high, low in pairs[index:])
    if trough < 0:
        return None
    return (peak - trough) / peak


def window_return_on(series: pd.Series, day: str, periods: int) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty or str(values.index[-1]) != day or len(values) <= periods:
        return None
    last = float(values.iloc[-1])
    base = float(values.iloc[-1 - periods])
    if base <= 0:
        return None
    return (last / base - 1.0) * 100.0


def amount_stats(series: pd.Series, day: str) -> tuple[float | None, float | None, float | None]:
    """返回当日成交额（亿元）、相对前一日变化、当日/近 20 日均额。申万 amount 按万元折算。"""
    values = pd.to_numeric(series, errors="coerce").dropna()
    values = values[values.index.astype(str) <= day]
    if values.empty or str(values.index[-1]) != day:
        return None, None, None
    today = float(values.iloc[-1])
    today_yi = today / 10000.0
    change = None
    if len(values) >= 2 and float(values.iloc[-2]) > 0:
        change = today / float(values.iloc[-2]) - 1.0
    activity = None
    base = values.iloc[-21:-1]
    if len(base) >= 20 and float(base.mean()) > 0:
        activity = today / float(base.mean())
    return today_yi, change, activity


def returns_asof(close_df: pd.DataFrame, day: str, windows=WINDOWS) -> dict[int, dict[str, float]]:
    if close_df is None or close_df.empty or day not in set(map(str, close_df.index)):
        return {item: {} for item in windows}
    sliced = close_df.loc[:day]
    out: dict[int, dict[str, float]] = {}
    for periods in windows:
        column = {}
        for name in sliced.columns:
            value = window_return_on(sliced[name], day, periods)
            if value is not None:
                column[str(name)] = value
        out[periods] = column
    return out


def _prepare_bar(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["ts_code", "pct_chg", "vol", "amount", "close", "up_limit", "down_limit"])
    work = frame.copy()
    work["ts_code"] = work["ts_code"].astype(str)
    for column in ("pct_chg", "vol", "amount", "close", "up_limit", "down_limit"):
        if column not in work.columns:
            work[column] = pd.NA
        work[column] = pd.to_numeric(work[column], errors="coerce")
    return work


def chase_observation(
    rank_df: pd.DataFrame | None,
    obs_df: pd.DataFrame | None,
    basic: pd.DataFrame,
    suspend_rank: set[str],
    suspend_obs: set[str],
    open_days: list[str],
    rank_day: str,
    with_sample: bool = False,
) -> dict | None:
    rank = _prepare_bar(rank_df)
    obs = _prepare_bar(obs_df)
    if rank.empty or obs.empty:
        return None
    rank = rank[rank["ts_code"].map(is_hs_ashare)].copy()
    info = basic.copy() if basic is not None else pd.DataFrame(columns=["ts_code", "name", "list_date"])
    if "ts_code" not in info.columns:
        info = pd.DataFrame(columns=["ts_code", "name", "list_date"])
    info["ts_code"] = info["ts_code"].astype(str)
    merged = rank.merge(info[["ts_code", "name", "list_date"]], on="ts_code", how="left")
    counts = {"st": 0, "new": 0, "missing_basic": 0, "halt_rank": 0, "bad_pct": 0}
    kept = []
    for row in merged.itertuples(index=False):
        code = str(row.ts_code)
        if not _ok(row.pct_chg):
            counts["bad_pct"] += 1
            continue
        if code in suspend_rank or not _ok(row.vol) or float(row.vol) <= 0:
            counts["halt_rank"] += 1
            continue
        name = "" if pd.isna(row.name) else str(row.name).strip()
        if not name:
            counts["missing_basic"] += 1
            continue
        if is_st_name(name):
            counts["st"] += 1
            continue
        days = listing_days(getattr(row, "list_date", ""), rank_day, open_days)
        if days is None or days < LISTING_MIN_DAYS:
            counts["new"] += 1
            continue
        kept.append((float(row.pct_chg), float(row.amount) if _ok(row.amount) else 0.0, code, name))
    kept.sort(key=lambda item: (-item[0], -item[1], item[2]))
    chosen = kept[:CHASE_N]
    obs_ix = obs.drop_duplicates("ts_code").set_index("ts_code")
    sample = []
    dropped = 0
    for rank_pct, _amount, code, name in chosen:
        if code in suspend_obs or code not in obs_ix.index:
            dropped += 1
            continue
        bar = obs_ix.loc[code]
        if not _ok(bar["pct_chg"]) or not _ok(bar["vol"]) or float(bar["vol"]) <= 0:
            dropped += 1
            continue
        limit_up = None
        limit_down = None
        if _ok(bar["close"]) and _ok(bar["up_limit"]):
            limit_up = float(bar["close"]) + 1e-4 >= float(bar["up_limit"])
        if _ok(bar["close"]) and _ok(bar["down_limit"]):
            limit_down = float(bar["close"]) - 1e-4 <= float(bar["down_limit"])
        sample.append(
            {
                "ts_code": code,
                "name": name,
                "rank_pct": rank_pct,
                "pct": float(bar["pct_chg"]),
                "limit_up": limit_up,
                "limit_down": limit_down,
            }
        )
    if not sample:
        stats = {
            "n": 0,
            "mean": None,
            "median": None,
            "up": None,
            "limit_up": None,
            "drop5": None,
        }
    else:
        pcts = [float(item["pct"]) for item in sample]
        known = [item for item in sample if item["limit_up"] is not None]
        ordered = sorted(pcts)
        mid = ordered[len(ordered) // 2]
        if len(ordered) % 2 == 0:
            mid = (ordered[len(ordered) // 2 - 1] + mid) / 2.0
        stats = {
            "n": len(sample),
            "mean": sum(pcts) / len(pcts),
            "median": mid,
            "up": sum(1 for item in pcts if item > 0) / len(pcts),
            "limit_up": (sum(1 for item in known if item["limit_up"]) / len(known)) if known else None,
            "drop5": sum(1 for item in pcts if item <= -5.0) / len(pcts),
        }
    stats["dropped_obs"] = dropped
    stats["excluded"] = counts
    stats["pool"] = len(kept)
    if with_sample:
        stats["sample"] = sample
    return stats


def breadth_of(frame: pd.DataFrame | None) -> dict:
    empty = {
        "up": None,
        "down": None,
        "flat": None,
        "up_ratio": None,
        "limit_up": None,
        "limit_down": None,
        "amount": None,
    }
    work = _prepare_bar(frame)
    if work.empty:
        return empty
    work = work[work["ts_code"].map(is_hs_ashare)]
    valid = work["pct_chg"].notna()
    pct = work.loc[valid, "pct_chg"]
    if pct.empty:
        return empty
    up = int((pct > 0).sum())
    down = int((pct < 0).sum())
    flat = int((pct == 0).sum())
    total = up + down + flat
    amount = pd.to_numeric(work.loc[valid, "amount"], errors="coerce").sum()
    limit_up = limit_down = None
    if work["up_limit"].notna().any() or work["down_limit"].notna().any():
        close = work["close"]
        limit_up = int(((close + 1e-4) >= work["up_limit"]).fillna(False).sum())
        limit_down = int(((close - 1e-4) <= work["down_limit"]).fillna(False).sum())
    return {
        "up": up,
        "down": down,
        "flat": flat,
        "up_ratio": (up / total) if total else None,
        "limit_up": limit_up,
        "limit_down": limit_down,
        "amount": (float(amount) / 1e5) if _ok(amount) else None,
    }


def sector_up_map(frame: pd.DataFrame | None, members: pd.DataFrame | None) -> dict[str, float]:
    if frame is None or members is None or members.empty or "symbol" not in members.columns:
        return {}
    work = _prepare_bar(frame)
    work = work[(work["vol"] > 0) & work["pct_chg"].notna()].copy()
    if work.empty:
        return {}
    work["symbol"] = work["ts_code"].str.slice(0, 6)
    merged = work.merge(members[["symbol", "industry_name"]], on="symbol", how="inner")
    ratios = {}
    for name, part in merged.groupby("industry_name"):
        if len(part) == 0:
            continue
        ratios[str(name)] = float((part["pct_chg"] > 0).mean())
    return ratios


def structure_features(ret5: dict[str, float], ret20: dict[str, float], up_map: dict[str, float]) -> dict:
    if len(ret5) < TOP_N or len(ret20) < TOP_N:
        return {"overlap": None, "spread": None, "up": None}
    leaders = top_names(ret5, TOP_N)
    overlap = len(set(leaders) & set(top_names(ret20, TOP_N)))
    lead_ret = [float(ret5[name]) for name in leaders]
    lag_names = [name for name in bottom_names(ret5, TOP_N) if name not in set(leaders)]
    if len(lag_names) < 1:
        spread = None
    else:
        spread = sum(lead_ret) / len(lead_ret) - sum(float(ret5[name]) for name in lag_names) / len(lag_names)
    ups = [float(up_map[name]) for name in leaders if name in up_map and _ok(up_map[name])]
    return {
        "overlap": overlap,
        "spread": spread,
        "up": (sum(ups) / len(ups)) if len(ups) >= 3 else None,
    }


def _amount_ratio_series(amounts) -> list[float | None]:
    values = list(amounts)
    ratios: list[float | None] = []
    for index, today in enumerate(values):
        window = [item for item in values[max(0, index - 5) : index] if _ok(item)]
        if len(window) < 5 or not _ok(today) or sum(window) <= 0:
            ratios.append(None)
        else:
            ratios.append(float(today) / (sum(float(item) for item in window) / len(window)))
    return ratios


def _limit_spread_series(frame: pd.DataFrame) -> list[float | None]:
    spreads = []
    for up, down in zip(frame["risk_limit_up"], frame["risk_limit_down"]):
        if _ok(up) and _ok(down):
            spreads.append(float(up) - float(down))
        else:
            spreads.append(None)
    return spreads


def score_asof(frame: pd.DataFrame, index: int) -> dict:
    sub = frame.iloc[: index + 1]
    chase, chase_text = pillar_score(
        [
            ("平均收益", pct_of(sub["chase_mean"]), True),
            ("上涨比例", pct_of(sub["chase_up"]), True),
            ("涨停比例", pct_of(sub["chase_limit"]), False),
            ("收益率≤-5%比例（反向）", reversed_pct(sub["chase_drop5"]), False),
        ]
    )
    structure, structure_text = pillar_score(
        [
            ("5日与20日领涨重合度", pct_of(sub["struct_overlap"]), True),
            ("领涨与领跌收益差", pct_of(sub["struct_spread"]), True),
            ("领涨内部上涨占比", pct_of(sub["struct_up"]), False),
        ]
    )
    risk, risk_text = pillar_score(
        [
            ("上涨家数占比", pct_of(sub["risk_up"]), True),
            ("涨停减跌停", pct_of(_limit_spread_series(sub)), False),
            ("成交额相对近5日", pct_of(_amount_ratio_series(sub["risk_amount"])), False),
        ]
    )
    total = composite_score(chase, structure, risk)
    return {
        "chase": chase,
        "structure": structure,
        "risk": risk,
        "total": total,
        "chase_parts": chase_text,
        "structure_parts": structure_text,
        "risk_parts": risk_text,
        "history_chase": _finite_count(list(sub["chase_mean"])[-PERCENTILE_WINDOW:]),
        "history_struct": _finite_count(list(sub["struct_overlap"])[-PERCENTILE_WINDOW:]),
        "history_risk": _finite_count(list(sub["risk_up"])[-PERCENTILE_WINDOW:]),
    }


def velocity_pair(scores: list[dict]) -> tuple[float | None, float | None]:
    totals = [item.get("total") for item in scores]
    if len(totals) < 2 or not (_ok(totals[-1]) and _ok(totals[-2])):
        velocity = None
    else:
        velocity = float(totals[-1]) - float(totals[-2])
    if len(totals) < 3 or not (_ok(totals[-2]) and _ok(totals[-3])) or velocity is None:
        return velocity, None
    previous = float(totals[-2]) - float(totals[-3])
    return velocity, velocity - previous


def _fmt_pct(value, digits: int = 2, signed: bool = True) -> str:
    if not _ok(value):
        return "无法计算"
    number = float(value)
    sign = "+" if signed and number > 0 else ""
    return f"{sign}{number:.{digits}f}%"


def _fmt_ratio(value) -> str:
    if not _ok(value):
        return "无法计算"
    return f"{float(value) * 100:.1f}%"


def _fmt_num(value, digits: int = 1) -> str:
    if not _ok(value):
        return "无法计算"
    return f"{float(value):.{digits}f}"


def _fmt_score(value) -> str:
    if not _ok(value):
        return "无法计算"
    return f"{float(value):.1f}"


def _fmt_yi(value) -> str:
    if not _ok(value):
        return "无法计算"
    number = float(value)
    if abs(number) >= 10000:
        return f"{number / 10000:.2f}万亿"
    return f"{number:.0f}亿"


def _fmt_change(value) -> str:
    if not _ok(value):
        return "无法计算"
    return f"{float(value) * 100:+.1f}%"


def _names(items: list[str]) -> str:
    return "、".join(items) if items else "无"


def _promotion_text(levels: list | None) -> str:
    rows = []
    for level in levels or []:
        src = level.get("from_board")
        dst = level.get("to_board")
        pct = level.get("pct")
        if src is None or dst is None or not _ok(pct):
            continue
        rows.append(f"{src}进{dst} {float(pct):.0f}%")
    if not rows:
        return "无法计算"
    return "；".join(rows)


def failure_ctx(day: str, reason: str, lianban_phase: str, calendar_note: str) -> dict:
    phase = judge_phase(None, None, None, None, None, {}, None, None)
    return {
        "day": day,
        "prev_day": None,
        "calendar_note": calendar_note,
        "lianban_phase": lianban_phase,
        "error": reason,
        "chase_history": [],
        "chase_sample": [],
        "chase_excluded": {},
        "chase_dropped": None,
        "chase_pool": None,
        "drawdown": None,
        "drawdown_note": "无法计算",
        "next_drawdown": None,
        "next_drawdown_note": "无法计算",
        "sectors": [],
        "labels": {},
        "breadth": {},
        "promotion": "无法计算",
        "sentiment": {},
        "phase": phase,
        "conclusion": "量化数据不足，无法与前一交易日比较。",
        "missing": [reason] if reason else ["量化段落无法计算"],
        "history_note": "",
    }


def render_markdown(ctx: dict) -> str:
    day = ctx.get("day") or ""
    lines = [
        "## 柏拉爱空",
        "",
        f"数据日期：{day}。来源：Tushare Pro。交易日历：上交所 trade_cal。",
    ]
    if ctx.get("calendar_note"):
        lines.append(str(ctx["calendar_note"]))
    if ctx.get("error"):
        lines.append(f"计算中断：{ctx['error']}")
    lines.extend(
        [
            "",
            "样本是前一交易日涨跌幅前 20 的沪深 A 股。先剔除 ST、上市不足 60 个交易日、基础资料缺失、排名日停牌或无成交；涨跌幅相同则成交额大者优先。观察日停牌或无行情的再剔除，不把收益记为 0。涨停和跌停的收益保留在平均、中位数和上涨比例里。涨停比例只在有涨跌停价的样本中计算。收益率≤-5%按当日涨跌幅不高于 -5% 统计。ST 用生成时的 stock_basic 名称，不回溯更名。",
            "",
        ]
    )
    history = list(ctx.get("chase_history") or [])
    lines.extend(
        [
            "| 日期 | 样本数 | 平均收益 | 中位数 | 上涨比例 | 涨停比例 | 收益率≤-5% | 当日盘中回撤 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    if not history:
        lines.append("| 无法计算 | 无法计算 | 无法计算 | 无法计算 | 无法计算 | 无法计算 | 无法计算 | 无法计算 |")
    for row in history:
        draw = "无法计算"
        if row.get("date") == day:
            draw = _fmt_ratio(ctx.get("drawdown"))
        lines.append(
            "| {date} | {n} | {mean} | {median} | {up} | {limit} | {drop5} | {draw} |".format(
                date=row.get("date") or "无法计算",
                n=row["n"] if _ok(row.get("n")) else "无法计算",
                mean=_fmt_pct(row.get("mean")),
                median=_fmt_pct(row.get("median")),
                up=_fmt_ratio(row.get("up")),
                limit=_fmt_ratio(row.get("limit")),
                drop5=_fmt_ratio(row.get("drop5")),
                draw=draw,
            )
        )
    lines.append("")
    lines.append(_chase_trend(history))
    excluded = ctx.get("chase_excluded") or {}
    if excluded or ctx.get("chase_pool") is not None:
        lines.append(
            "排名池 {pool} 只。剔除只记一次：ST {st}，上市不足 60 日或上市日缺失 {new}，基础资料缺失 {missing}，排名日停牌或无成交 {halt}，无涨跌幅 {bad}。观察日再剔除 {drop} 只。".format(
                pool=ctx.get("chase_pool") if ctx.get("chase_pool") is not None else "无法计算",
                st=excluded.get("st", "无法计算"),
                new=excluded.get("new", "无法计算"),
                missing=excluded.get("missing_basic", "无法计算"),
                halt=excluded.get("halt_rank", "无法计算"),
                bad=excluded.get("bad_pct", "无法计算"),
                drop=ctx.get("chase_dropped") if ctx.get("chase_dropped") is not None else "无法计算",
            )
        )
    lines.append(f"当日盘中最大回撤：{_fmt_ratio(ctx.get('drawdown'))}。{ctx.get('drawdown_note') or ''}".rstrip())
    lines.append(f"次日盘中最大回撤：{_fmt_ratio(ctx.get('next_drawdown'))}。{ctx.get('next_drawdown_note') or ''}".rstrip())
    sample = list(ctx.get("chase_sample") or [])
    if sample:
        lines.extend(
            [
                "",
                "| 代码 | 名称 | 前一交易日涨幅 | 当日涨幅 | 涨停 | 跌停 |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for item in sample:
            lines.append(
                "| {code} | {name} | {rank} | {pct} | {up} | {down} |".format(
                    code=str(item.get("ts_code") or "")[:6],
                    name=item.get("name") or "无法计算",
                    rank=_fmt_pct(item.get("rank_pct")),
                    pct=_fmt_pct(item.get("pct")),
                    up=_yes_no(item.get("limit_up")),
                    down=_yes_no(item.get("limit_down")),
                )
            )
    lines.extend(["", "## 板块强弱", ""])
    lines.append(
        "申万一级。区间收益率 = 当日收盘 / N 个交易日前收盘 - 1，且最后一根收盘必须落在数据日。名次 1 为区间涨幅最高。名次变化相对前一交易日同窗口，正数表示名次上升。内部上涨占比、当日成交额、活跃度（当日成交额 / 近 20 日均额）都是当日值。成分用当前申万一级，未按历史调样回溯。单日涨跌不单独作为主线结论。"
    )
    lines.append("")
    sectors = list(ctx.get("sectors") or [])
    if not sectors:
        lines.append("板块区间收益无法计算。")
        lines.append("")
    for block in sectors:
        lines.append(f"### {block.get('window')} 日")
        lines.append("")
        lines.extend(
            [
                "| 分组 | 板块 | 区间收益率 | 名次 | 名次变化 | 当日成交额 | 活跃度 | 内部上涨占比 |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        rows = list(block.get("rows") or [])
        if not rows:
            lines.append("| 无法计算 | 无法计算 | 无法计算 | 无法计算 | 无法计算 | 无法计算 | 无法计算 | 无法计算 |")
        for row in rows:
            lines.append(
                "| {group} | {name} | {ret} | {rank} | {change} | {amount} | {activity} | {up} |".format(
                    group=row.get("group") or "无法计算",
                    name=row.get("name") or "无法计算",
                    ret=_fmt_pct(row.get("ret")),
                    rank=row.get("rank") if row.get("rank") else "无法计算",
                    change=row.get("change") or "无法计算",
                    amount=_fmt_yi(row.get("amount")),
                    activity=_fmt_num(row.get("activity"), 2) if _ok(row.get("activity")) else "无法计算",
                    up=_fmt_ratio(row.get("up")),
                )
            )
        lines.append("")
    labels = ctx.get("labels") or {}
    lines.extend(
        [
            "| 标签 | 结果 |",
            "| --- | --- |",
            f"| 延续 | {_names(labels.get('continue') or [])} |",
            "| 轮动 | {flag}{extra} |".format(
                flag="是" if labels.get("rotation") else "否" if labels else "无法计算",
                extra=(
                    f"，5 日与 20 日领涨重合 {labels.get('rotation_overlap')} 个"
                    + (f"（{'、'.join(labels.get('rotation_names') or [])}）" if labels.get("rotation_names") else "")
                    if labels.get("rotation_overlap") is not None
                    else ""
                ),
            ),
            f"| 退潮 | {_names(labels.get('ebb') or [])} |",
            f"| 新方向 | {_names(labels.get('new') or [])} |",
            "",
        ]
    )
    for note in labels.get("notes") or []:
        lines.append(note)
    if labels.get("notes"):
        lines.append("")
    lines.append("标签按多周期重合并列列出，不合成一个主线名称。")
    lines.extend(["", "## 市场广度与风险偏好", ""])
    lines.append("涨跌家数来自沪深 A 股日线，平盘单列，北交所和 B 股不计入。涨停、跌停用收盘价对照涨跌停价，不用涨跌幅是否等于 10%。成交额是这些股票日线成交额合计（Tushare 千元折算为亿元），与交易所公布的两市总额可能不一致。")
    lines.append("")
    breadth = ctx.get("breadth") or {}
    lines.extend(
        [
            "| 指标 | 数值 |",
            "| --- | --- |",
            f"| 上涨 | {_int_or_missing(breadth.get('up'))} |",
            f"| 下跌 | {_int_or_missing(breadth.get('down'))} |",
            f"| 平盘 | {_int_or_missing(breadth.get('flat'))} |",
            f"| 上涨家数占比 | {_fmt_ratio(breadth.get('up_ratio'))} |",
            f"| 涨停 | {_int_or_missing(breadth.get('limit_up'))} |",
            f"| 跌停 | {_int_or_missing(breadth.get('limit_down'))} |",
            f"| 连板晋级率 | {ctx.get('promotion') or '无法计算'} |",
            f"| 成交额 | {_fmt_yi(breadth.get('amount'))} |",
            f"| 成交额较前一交易日 | {_fmt_change(breadth.get('amount_prev'))} |",
            f"| 成交额较近 5 日均值 | {_fmt_change(breadth.get('amount_ma5'))} |",
            "",
            "晋级率来自连板网天梯行头，不纳入下面的情绪指数。近 5 日均值不含当日。",
            "",
            "## 情绪指数",
            "",
            "权重是研究参数，不代表已经验证有效：追涨赚钱效应 40%，板块强弱结构 35%，市场风险偏好 25%。支柱内部对已有成分等权。标准化用滚动分位数，窗口最多 250 个交易日且含当日，至少 60 个有效值。任一支柱无法计算时，综合分记为无法计算，不把剩余权重重新归一。速度 = 当日综合分 − 前一交易日综合分；加速度 = 当日速度 − 前一交易日速度。速度用未四舍五入的分数相减。",
            "",
        ]
    )
    sentiment = ctx.get("sentiment") or {}
    lines.extend(
        [
            "| 项目 | 权重 | 分数 | 纳入成分 |",
            "| --- | --- | --- | --- |",
            f"| 追涨赚钱效应 | 40% | {_fmt_score(sentiment.get('chase'))} | {sentiment.get('chase_parts') or '无法计算'} |",
            f"| 板块强弱结构 | 35% | {_fmt_score(sentiment.get('structure'))} | {sentiment.get('structure_parts') or '无法计算'} |",
            f"| 市场风险偏好 | 25% | {_fmt_score(sentiment.get('risk'))} | {sentiment.get('risk_parts') or '无法计算'} |",
            f"| 综合分 | 100% | {_fmt_score(sentiment.get('total'))} | 三支柱均需可计算 |",
            f"| 速度 |  | {_fmt_score(sentiment.get('velocity'))} | 相对前一交易日 |",
            f"| 加速度 |  | {_fmt_score(sentiment.get('accel'))} | 速度的变化 |",
            "",
            "本次窗口有效天数：追涨平均收益 {chase}，领涨重合度 {struct}，上涨家数占比 {risk}。".format(
                chase=sentiment.get("history_chase", "无法计算"),
                struct=sentiment.get("history_struct", "无法计算"),
                risk=sentiment.get("history_risk", "无法计算"),
            ),
            "",
            "## 市场阶段",
            "",
            "阶段规则是研究启发式，按顺序命中即停止：冰点（综合分<25、速度≤0、上涨占比<40%）；高潮（综合分≥75、上涨占比≥55%、柏拉爱空平均收益>0）；退潮（综合分<60，且有退潮板块，或柏拉爱空转负且速度为负）；分化（轮动，或综合分在 40–70 且上涨占比在 45%–58%）；上升（综合分≥55、速度≥0、上涨占比≥50%）；回暖（综合分≥30、速度>0、上涨占比≥40%）。再剩下时，综合分<40 且速度≤0 记为退潮，否则记为分化。综合分无法计算则阶段为无法判断。置信度：支持不少于 3 条且无反证为高，支持不少于 2 条且反证不超过 1 条为中，其余为低。",
            "",
        ]
    )
    phase = ctx.get("phase") or {}
    lines.extend(
        [
            "| 项目 | 内容 |",
            "| --- | --- |",
            f"| 阶段 | {phase.get('phase') or '无法判断'} |",
            f"| 置信度 | {phase.get('confidence') or '无法评估'} |",
            f"| 支持 | {_join_notes(phase.get('support'))} |",
            f"| 反证 | {_join_notes(phase.get('counter')) or '无'} |",
            f"| 连板网对照 | {ctx.get('lianban_phase') or '无法计算'} |",
            "",
            "连板网阶段只作对照，不覆盖上表。",
            "",
            "## 明日观察",
            "",
            "| 项目 | 内容 |",
            "| --- | --- |",
        ]
    )
    for label, text in ctx.get("plan") or _default_plan(phase):
        lines.append(f"| {label} | {text} |")
    lines.extend(
        [
            "",
            "以上为研究观察，不构成收益承诺。情绪指数和阶段都不是买卖指令。",
            "",
            "## 简短复盘结论",
            "",
            ctx.get("conclusion") or "无法与前一交易日比较。",
            "",
            "## 数据口径与缺失",
            "",
        ]
    )
    missing = [item for item in (ctx.get("missing") or []) if item]
    if missing:
        for item in missing:
            lines.append(f"- {item}")
    else:
        lines.append("- 本次列出的实测项没有用估算值填空。")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _yes_no(value) -> str:
    if value is True:
        return "是"
    if value is False:
        return "否"
    return "无法计算"


def _int_or_missing(value) -> str:
    if not _ok(value):
        return "无法计算"
    return str(int(value))


def _join_notes(items) -> str:
    rows = [str(item) for item in (items or []) if str(item).strip()]
    return "；".join(rows) if rows else "无"


def _chase_trend(history: list[dict]) -> str:
    if len(history) < 2:
        return "近 3 至 5 个交易日对照：无法计算。"
    today = history[-1].get("mean")
    prev = [row.get("mean") for row in history[:-1] if _ok(row.get("mean"))]
    if not _ok(today) or len(prev) < 3:
        return "近 3 至 5 个交易日对照：有效天数不足，无法计算。"
    base = sum(float(item) for item in prev) / len(prev)
    return (
        f"当日平均收益 {float(today):+.2f}%，此前 {len(prev)} 个交易日均值 {base:+.2f}%，"
        f"差额 {float(today) - base:+.2f} 个百分点。"
    )


def _default_plan(phase: dict) -> list[tuple[str, str]]:
    stance = (phase or {}).get("stance") or "无法给出"
    return [
        ("重点板块", "无法计算"),
        ("代表性信号", "无法计算"),
        ("规避", "无法计算"),
        ("仓位倾向", f"{stance}。这是研究启发式，不是下单指令。"),
    ]


def _call(fn, retries: int = 3, **kwargs):
    last = None
    for attempt in range(retries):
        try:
            return fn(**kwargs)
        except TypeError:
            raise
        except Exception as exc:
            last = exc
            time.sleep(1.2 * (attempt + 1))
    if last:
        raise last
    return None


def sse_open_days(now: datetime, explicit: str | None = None, lookback_days: int = 80) -> list[str]:
    from market_radar import get_tushare_bundle

    _ts, pro = get_tushare_bundle()
    end_point = now
    if explicit:
        explicit_day = datetime.strptime(explicit, "%Y-%m-%d")
        span = (now.date() - explicit_day.date()).days
        if span + 40 > lookback_days:
            lookback_days = span + 40
        if explicit_day.date() > now.date():
            end_point = explicit_day
    end_point = end_point + timedelta(days=15)
    start = (end_point - timedelta(days=lookback_days + 15)).strftime("%Y%m%d")
    frame = _call(
        pro.trade_cal,
        exchange="SSE",
        start_date=start,
        end_date=end_point.strftime("%Y%m%d"),
        is_open="1",
    )
    if frame is None or frame.empty or "cal_date" not in frame.columns:
        raise RuntimeError("上交所交易日历为空")
    days = sorted({_iso(item) for item in frame["cal_date"].tolist() if _iso(item)})
    if not days:
        raise RuntimeError("上交所交易日历为空")
    return days


def _cross_path(day: str) -> Path:
    return CROSS / f"{_ymd(day)}.csv"


def _cross_ready(day: str) -> bool:
    path = _cross_path(day)
    if not path.is_file() or path.stat().st_size < 50_000:
        return False
    try:
        header = pd.read_csv(path, nrows=2)
    except Exception:
        return False
    return {"ts_code", "pct_chg", "close"}.issubset(header.columns)


def read_cross(day: str) -> pd.DataFrame | None:
    path = _cross_path(day)
    if not path.is_file():
        return None
    try:
        frame = pd.read_csv(path, dtype={"ts_code": str})
    except Exception:
        return None
    if frame.empty or "ts_code" not in frame.columns:
        return None
    return frame


def _write_frame(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False, encoding="utf-8")
    temporary.replace(path)


def _fetch_cross(pro, day: str, use_limits: list[bool]) -> pd.DataFrame | None:
    ymd = _ymd(day)
    try:
        daily = _call(pro.daily, trade_date=ymd, fields="ts_code,pct_chg,vol,amount,close")
    except TypeError:
        daily = _call(pro.daily, trade_date=ymd)
    time.sleep(0.12)
    if daily is None or daily.empty or "ts_code" not in daily.columns:
        return None
    frame = daily.copy()
    frame["up_limit"] = pd.NA
    frame["down_limit"] = pd.NA
    limits = _limit_frame(pro, ymd, use_limits)
    if limits is not None and not limits.empty and "ts_code" in limits.columns:
        keep = [column for column in ("ts_code", "up_limit", "down_limit") if column in limits.columns]
        frame = frame.drop(columns=["up_limit", "down_limit"], errors="ignore").merge(
            limits[keep], on="ts_code", how="left"
        )
    return frame


def _limit_frame(pro, ymd: str, state: list[bool]) -> pd.DataFrame | None:
    """涨跌停价失败时只跳过当天。权限类错误才停止后续请求。"""
    if not state[0]:
        return None
    fn = getattr(pro, "stk_limit", None)
    if fn is None:
        state[0] = False
        return None
    try:
        frame = _call(fn, trade_date=ymd, fields="ts_code,up_limit,down_limit")
    except TypeError:
        try:
            frame = _call(fn, trade_date=ymd)
        except Exception as exc:
            if _minute_denied(exc):
                state[0] = False
            return None
    except Exception as exc:
        if _minute_denied(exc):
            state[0] = False
        return None
    time.sleep(0.12)
    return frame


def ensure_crosses(pro, days: list[str], logger) -> list[str]:
    missing_notes = []
    use_limits = [True]
    pending = [day for day in days if not _cross_ready(day)]
    for index, day in enumerate(pending, 1):
        if index == 1 or index % 20 == 0 or index == len(pending):
            _log(logger, f"量化复盘补齐日线 {index}/{len(pending)} {day}")
        try:
            frame = _fetch_cross(pro, day, use_limits)
        except Exception as exc:
            missing_notes.append(f"{day} 日线获取失败：{exc}")
            continue
        if frame is None or frame.empty:
            missing_notes.append(f"{day} 日线为空")
            continue
        _write_frame(_cross_path(day), frame)
    if not use_limits[0]:
        missing_notes.append("涨跌停价接口不可用，涨停、跌停和涨停比例无法计算")
    return missing_notes


def _load_basic(pro) -> pd.DataFrame:
    frame = _call(
        pro.stock_basic,
        exchange="",
        list_status="L",
        fields="ts_code,name,list_date,market",
    )
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["ts_code", "name", "list_date", "market"])
    frame = frame.copy()
    frame["ts_code"] = frame["ts_code"].astype(str)
    frame["name"] = frame["name"].fillna("").astype(str).str.strip()
    frame["list_date"] = frame["list_date"].map(_iso)
    return frame


def _load_suspend(pro, start: str, end: str) -> tuple[dict[str, set[str]], str]:
    fn = getattr(pro, "suspend_d", None)
    if fn is None:
        return {}, "停牌接口不可用，仅用成交量为 0 或无行情剔除"
    found: dict[str, set[str]] = {}
    cursor = datetime.strptime(start, "%Y-%m-%d")
    last = datetime.strptime(end, "%Y-%m-%d")
    failed = False
    while cursor <= last:
        chunk_end = min(last, cursor + timedelta(days=80))
        try:
            frame = _call(
                fn,
                start_date=cursor.strftime("%Y%m%d"),
                end_date=chunk_end.strftime("%Y%m%d"),
                suspend_type="S",
            )
        except TypeError:
            try:
                frame = _call(
                    fn,
                    start_date=cursor.strftime("%Y%m%d"),
                    end_date=chunk_end.strftime("%Y%m%d"),
                )
            except Exception:
                frame = None
                failed = True
        except Exception:
            frame = None
            failed = True
        time.sleep(0.12)
        if frame is not None and not frame.empty and "ts_code" in frame.columns and "trade_date" in frame.columns:
            for code, trade_date in zip(frame["ts_code"], frame["trade_date"]):
                day = _iso(trade_date)
                if day:
                    found.setdefault(day, set()).add(str(code))
        cursor = chunk_end + timedelta(days=1)
    if failed and not found:
        return {}, "停牌列表获取失败，仅用成交量为 0 或无行情剔除"
    return found, ""


def _load_sw(pro, start: str, end: str, logger) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    notes = []
    meta = None
    for src in ("SW2021", "SW2014"):
        try:
            meta = _call(pro.index_classify, level="L1", src=src)
        except Exception as exc:
            notes.append(f"申万行业列表 {src} 失败：{exc}")
            meta = None
        if meta is not None and not meta.empty and "index_code" in meta.columns:
            break
    empty = pd.DataFrame()
    if meta is None or meta.empty:
        notes.append("申万一级行业列表为空")
        return empty, empty, empty, notes
    closes = {}
    amounts = {}
    member_rows = []
    for record in meta.itertuples(index=False):
        code = str(getattr(record, "index_code", "") or "").strip()
        name = str(getattr(record, "industry_name", "") or "").strip() or code
        if not code:
            continue
        try:
            daily = _call(pro.sw_daily, ts_code=code, start_date=_ymd(start), end_date=_ymd(end))
        except Exception as exc:
            notes.append(f"{name} 行情失败：{exc}")
            daily = None
        time.sleep(0.12)
        if daily is not None and not daily.empty and "trade_date" in daily.columns and "close" in daily.columns:
            piece = daily.copy()
            piece["date"] = piece["trade_date"].map(_iso)
            piece = piece[piece["date"] != ""].drop_duplicates("date", keep="last").set_index("date").sort_index()
            closes[name] = pd.to_numeric(piece["close"], errors="coerce")
            if "amount" in piece.columns:
                amounts[name] = pd.to_numeric(piece["amount"], errors="coerce")
        else:
            notes.append(f"{name} 无收盘价")
        members = _members(pro, code)
        time.sleep(0.12)
        if members is None or members.empty:
            notes.append(f"{name} 无成分")
            continue
        symbol_col = "con_code" if "con_code" in members.columns else "ts_code" if "ts_code" in members.columns else ""
        if not symbol_col:
            notes.append(f"{name} 成分缺少代码")
            continue
        for raw in members[symbol_col].astype(str):
            symbol = re.sub(r"\D", "", raw)[:6]
            if len(symbol) == 6:
                member_rows.append({"symbol": symbol, "industry_name": name})
    close_df = pd.DataFrame(closes).sort_index() if closes else empty
    amount_df = pd.DataFrame(amounts).sort_index() if amounts else empty
    member_df = pd.DataFrame(member_rows)
    if not member_df.empty:
        duplicated = int(member_df["symbol"].duplicated().sum())
        if duplicated:
            notes.append(f"{duplicated} 只股票落在多个一级行业，保留先出现的行业")
            member_df = member_df.drop_duplicates("symbol", keep="first")
    return close_df, amount_df, member_df, notes


def _members(pro, index_code: str) -> pd.DataFrame | None:
    loaders = []
    if hasattr(pro, "index_member"):
        loaders.append(lambda: pro.index_member(index_code=index_code, is_new="Y"))
    if hasattr(pro, "index_member_all"):
        loaders.append(lambda: pro.index_member_all(l1_code=index_code, is_new="Y"))
    for loader in loaders:
        try:
            frame = loader()
        except Exception:
            frame = None
        if frame is None or frame.empty:
            continue
        return frame
    return None


def _read_features() -> pd.DataFrame:
    if not FEATURES.is_file():
        return pd.DataFrame(columns=FEATURE_COLUMNS)
    try:
        frame = pd.read_csv(FEATURES, dtype={"date": str})
    except Exception:
        return pd.DataFrame(columns=FEATURE_COLUMNS)
    for column in FEATURE_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA
    return frame


def _feature_targets(existing: pd.DataFrame, days: list[str]) -> list[str]:
    if existing.empty or "version" not in existing.columns or (pd.to_numeric(existing["version"], errors="coerce") != FORMULA_VERSION).any():
        if not existing.empty and "version" in existing.columns and (pd.to_numeric(existing["version"], errors="coerce") != FORMULA_VERSION).any():
            return list(days)
        if existing.empty:
            return list(days)
    have = set(existing["date"].astype(str))
    if (pd.to_numeric(existing.get("version", pd.Series(dtype=float)), errors="coerce") != FORMULA_VERSION).any():
        return list(days)
    missing = [day for day in days if day not in have]
    refresh = days[-3:]
    return list(dict.fromkeys([*missing, *refresh]))


def _build_feature_row(
    day: str,
    prev: str,
    close_df: pd.DataFrame,
    members: pd.DataFrame,
    basic: pd.DataFrame,
    suspend: dict[str, set[str]],
    open_days: list[str],
) -> dict | None:
    chase = chase_observation(
        read_cross(prev),
        read_cross(day),
        basic,
        suspend.get(prev, set()),
        suspend.get(day, set()),
        open_days,
        prev,
        with_sample=False,
    )
    rets = returns_asof(close_df, day, (5, 20))
    struct = structure_features(rets.get(5, {}), rets.get(20, {}), sector_up_map(read_cross(day), members))
    bread = breadth_of(read_cross(day))
    if chase is None and not _ok(bread.get("up")) and struct.get("overlap") is None:
        return None
    chase = chase or {}
    return {
        "date": day,
        "version": FORMULA_VERSION,
        "n": chase.get("n"),
        "chase_mean": chase.get("mean"),
        "chase_median": chase.get("median"),
        "chase_up": chase.get("up"),
        "chase_limit": chase.get("limit_up"),
        "chase_drop5": chase.get("drop5"),
        "struct_overlap": struct.get("overlap"),
        "struct_spread": struct.get("spread"),
        "struct_up": struct.get("up"),
        "risk_up": bread.get("up_ratio"),
        "risk_up_n": bread.get("up"),
        "risk_down_n": bread.get("down"),
        "risk_flat_n": bread.get("flat"),
        "risk_limit_up": bread.get("limit_up"),
        "risk_limit_down": bread.get("limit_down"),
        "risk_amount": bread.get("amount"),
    }


def ensure_features(
    days: list[str],
    open_days: list[str],
    close_df: pd.DataFrame,
    members: pd.DataFrame,
    basic: pd.DataFrame,
    suspend: dict[str, set[str]],
    logger,
) -> pd.DataFrame:
    existing = _read_features()
    targets = _feature_targets(existing, days)
    rows = []
    for day in targets:
        prev = previous_open(open_days, day)
        if not prev:
            continue
        row = _build_feature_row(day, prev, close_df, members, basic, suspend, open_days)
        if row:
            rows.append(row)
    if rows:
        fresh = pd.DataFrame(rows)
        if not existing.empty:
            keep = existing[pd.to_numeric(existing["version"], errors="coerce") == FORMULA_VERSION]
            keep = keep[~keep["date"].astype(str).isin(set(fresh["date"].astype(str)))]
            existing = pd.concat([keep, fresh], ignore_index=True)
        else:
            existing = fresh
        existing = existing.sort_values("date").drop_duplicates("date", keep="last")
        _write_frame(FEATURES, existing[FEATURE_COLUMNS])
        _log(logger, f"量化复盘更新特征 {len(rows)} 日")
    elif not existing.empty:
        existing = existing[pd.to_numeric(existing["version"], errors="coerce") == FORMULA_VERSION]
    return existing.sort_values("date") if not existing.empty else existing


def _sector_block(window: int, rets: dict[str, float], prev_ranks: dict[str, int] | None, amount_map, up_map) -> dict:
    if len(rets) < 2:
        return {"window": window, "rows": []}
    ranks = ranks_from_returns(rets)
    leaders = top_names(rets, TOP_N)
    laggards = [name for name in bottom_names(rets, TOP_N + len(leaders)) if name not in set(leaders)][:TOP_N]
    rows = []
    for group, names in (("领涨", leaders), ("领跌", laggards)):
        for name in names:
            amount, _change, activity = amount_map.get(name, (None, None, None))
            if prev_ranks is None:
                change = "无法计算"
            elif name not in prev_ranks:
                change = "新进"
            else:
                change = f"{prev_ranks[name] - ranks[name]:+d}"
            rows.append(
                {
                    "group": group,
                    "name": name,
                    "ret": rets[name],
                    "rank": ranks[name],
                    "change": change,
                    "amount": amount,
                    "activity": activity,
                    "up": up_map.get(name),
                }
            )
    return {"window": window, "rows": rows}


def _amount_change(frame: pd.DataFrame, index: int) -> tuple[float | None, float | None]:
    if frame.empty or index < 0 or index >= len(frame):
        return None, None
    today = frame.iloc[index]["risk_amount"]
    if not _ok(today):
        return None, None
    prev = None
    if index >= 1 and _ok(frame.iloc[index - 1]["risk_amount"]) and float(frame.iloc[index - 1]["risk_amount"]) > 0:
        prev = float(today) / float(frame.iloc[index - 1]["risk_amount"]) - 1.0
    window = [item for item in frame.iloc[max(0, index - 5) : index]["risk_amount"] if _ok(item)]
    ma5 = None
    if len(window) >= 5 and sum(float(item) for item in window) > 0:
        ma5 = float(today) / (sum(float(item) for item in window) / len(window)) - 1.0
    return prev, ma5


def _minute_denied(exc: Exception) -> bool:
    text = str(exc)
    return any(word in text for word in ("权限", "积分", "无权限", "没有访问", "not permit"))


def _minute_limited(exc: Exception) -> bool:
    text = str(exc)
    return any(word in text for word in ("频率超限", "每分钟", "访问过于频繁"))


def summarize_drawdowns(values: list[float], expected: int, blocked: str = "") -> tuple[float | None, str]:
    """覆盖不足时不把少数股票的回撤写成全样本结果。"""
    if blocked:
        return None, blocked
    if expected <= 0 or not values or len(values) * 5 < expected * 4:
        return None, f"分钟线只覆盖 {len(values)}/{expected} 只，不把少数股票当成全样本回撤，也未用日线高低点代替"
    mean = sum(values) / len(values)
    return mean, f"按 1 分钟线计算，覆盖 {len(values)}/{expected} 只；高点在该分钟内的先后顺序无法拆开"


def _drawdown_from_minutes(raw: pd.DataFrame | None) -> float | None:
    if raw is None or raw.empty:
        return None
    columns = {str(column).lower(): column for column in raw.columns}
    high_col = columns.get("high")
    low_col = columns.get("low")
    time_col = columns.get("trade_time") or columns.get("time")
    if not high_col or not low_col:
        return None
    work = raw.copy()
    if time_col:
        work = work.sort_values(time_col)
    return intraday_max_drawdown(work[high_col].tolist(), work[low_col].tolist())


def fetch_drawdowns(pro, codes: list[str], day: str) -> tuple[float | None, str]:
    if pro is None or not codes or not hasattr(pro, "stk_mins"):
        return None, "分钟线接口不可用"
    ymd = _ymd(day)
    values = []
    blocked = ""
    for code in codes:
        try:
            raw = pro.stk_mins(
                ts_code=code,
                freq="1min",
                start_time=f"{ymd}093000",
                end_time=f"{ymd}150000",
            )
        except Exception as exc:
            if _minute_denied(exc):
                blocked = "分钟线无权限，未用日线高低点代替"
                break
            if _minute_limited(exc):
                blocked = "分钟线频率超限，样本回撤无法计算，未用日线高低点或个别股票代替"
                break
            continue
        time.sleep(0.12)
        value = _drawdown_from_minutes(raw)
        if value is not None:
            values.append(value)
    return summarize_drawdowns(values, len(codes), blocked)


def _leader_name(rets: dict[str, float]) -> str | None:
    names = top_names(rets, 1) if rets else []
    return names[0] if names else None


def _plan(labels: dict, sectors: list[dict], chase: dict | None, breadth: dict, phase: dict) -> list[tuple[str, str]]:
    labels = labels or {}
    focus = list(labels.get("continue") or []) + [name for name in (labels.get("new") or []) if name not in set(labels.get("continue") or [])]
    focus_text = "、".join(focus[:5]) if focus else "没有同时满足多周期条件的重点板块"
    leader = ""
    rows = []
    for block in sectors:
        if block.get("window") == 5:
            rows = [row for row in block.get("rows") or [] if row.get("group") == "领涨"]
    if rows:
        first = rows[0]
        leader = f"5 日领涨第一 {first.get('name')}，区间收益 {_fmt_pct(first.get('ret'))}，内部上涨占比 {_fmt_ratio(first.get('up'))}。"
    else:
        leader = "5 日领涨第一无法计算。"
    chase = chase or {}
    signal = (
        leader
        + f"柏拉爱空平均收益 {_fmt_pct(chase.get('mean'))}，上涨比例 {_fmt_ratio(chase.get('up'))}。"
    )
    risks = []
    if labels.get("ebb"):
        risks.append("退潮板块：" + "、".join(labels["ebb"]))
    if _ok(chase.get("drop5")):
        risks.append(f"柏拉爱空样本收益率≤-5%的比例 {_fmt_ratio(chase.get('drop5'))}")
    if _ok(breadth.get("limit_down")):
        risks.append(f"跌停 {_int_or_missing(breadth.get('limit_down'))} 家")
    if _ok(breadth.get("amount_prev")) and float(breadth["amount_prev"]) <= -0.10:
        risks.append(f"成交额较前一交易日 {_fmt_change(breadth.get('amount_prev'))}")
    risk_text = "；".join(risks) if risks else "没有额外可计算的风险项"
    stance = (phase or {}).get("stance") or "无法给出"
    return [
        ("重点板块", focus_text),
        ("代表性信号", signal),
        ("规避", risk_text),
        ("仓位倾向", f"{stance}。冰点或退潮对应防守，分化或高潮对应精选，回暖或上升且置信度不是低才对应进攻。"),
    ]


def _conclusion(day: str, prev: str | None, sentiment: dict, prev_sentiment: dict | None, phase: dict, prev_phase: str | None, breadth: dict, prev_breadth: dict | None, leader: str | None, prev_leader: str | None) -> str:
    if not prev:
        return f"{day} 没有前一交易日的同类计算结果。"
    bits = []
    total = (sentiment or {}).get("total")
    prev_total = (prev_sentiment or {}).get("total")
    if _ok(total) and _ok(prev_total):
        bits.append(f"情绪指数 {float(prev_total):.1f} → {float(total):.1f}（{float(total) - float(prev_total):+.1f}）")
    else:
        bits.append("情绪指数无法与前一交易日比较")
    current_phase = (phase or {}).get("phase") or "无法判断"
    if current_phase == "无法判断" or not prev_phase or prev_phase == "无法判断":
        bits.append("阶段无法与前一交易日比较")
    elif current_phase == prev_phase:
        bits.append(f"阶段仍为{current_phase}")
    else:
        bits.append(f"阶段 {prev_phase} → {current_phase}")
    up = (breadth or {}).get("up_ratio")
    prev_up = (prev_breadth or {}).get("up_ratio")
    if _ok(up) and _ok(prev_up):
        bits.append(f"上涨家数占比 {_fmt_ratio(prev_up)} → {_fmt_ratio(up)}")
    else:
        bits.append("上涨家数占比无法比较")
    if leader and prev_leader:
        if leader == prev_leader:
            bits.append(f"5 日领涨第一仍为{leader}")
        else:
            bits.append(f"5 日领涨第一由{prev_leader}变为{leader}")
    else:
        bits.append("5 日领涨第一无法比较")
    return f"相对 {prev}：" + "；".join(bits) + "。"


def _history_rows(frame: pd.DataFrame, day: str) -> list[dict]:
    if frame is None or frame.empty:
        return []
    work = frame[frame["date"].astype(str) <= day].tail(5)
    rows = []
    for record in work.itertuples(index=False):
        rows.append(
            {
                "date": str(record.date),
                "n": None if not _ok(record.n) else int(record.n),
                "mean": None if not _ok(record.chase_mean) else float(record.chase_mean),
                "median": None if not _ok(record.chase_median) else float(record.chase_median),
                "up": None if not _ok(record.chase_up) else float(record.chase_up),
                "limit": None if not _ok(record.chase_limit) else float(record.chase_limit),
                "drop5": None if not _ok(record.chase_drop5) else float(record.chase_drop5),
            }
        )
    return rows


def _view_labels(day: str, open_days: list[str], close_df: pd.DataFrame, members: pd.DataFrame) -> dict:
    prev5 = shift_open(open_days, day, -5)
    rets = returns_asof(close_df, day)
    old = None
    if prev5:
        old_rets = returns_asof(close_df, prev5, (20,))
        old = ranks_from_returns(old_rets.get(20, {})) if old_rets.get(20) else {}
    return structure_labels(
        rets.get(5, {}),
        rets.get(20, {}),
        rets.get(60, {}),
        old,
        sector_up_map(read_cross(day), members),
    )


def assemble(
    day: str,
    *,
    promotion_levels: list | None = None,
    lianban_phase: str = "",
    calendar_note: str = "",
    prev_day_hint: str | None = None,
    log=None,
    now: datetime | None = None,
) -> dict:
    moment = now or datetime.now(TZ)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=TZ)
    open_days = sse_open_days(moment, day, lookback_days=560)
    if day not in open_days:
        raise RuntimeError(f"{day} 不是上交所交易日")
    from market_radar import get_tushare_bundle

    _ts, pro = get_tushare_bundle()
    missing = []
    if calendar_note:
        missing.append(calendar_note)
    if prev_day_hint and prev_day_hint != previous_open(open_days, day):
        missing.append(f"连板网上一交易日为 {prev_day_hint}，量化对照用上交所上一交易日 {previous_open(open_days, day) or '无法计算'}")
    basic = _load_basic(pro)
    if basic.empty:
        missing.append("stock_basic 为空，柏拉爱空样本无法剔除 ST 和次新")
    feature_days = [item for item in open_days if item <= day][-PERCENTILE_WINDOW:]
    first = feature_days[0]
    prev_of_first = previous_open(open_days, first)
    cross_days = ([prev_of_first] if prev_of_first else []) + feature_days
    start = open_days[0]
    missing.extend(ensure_crosses(pro, cross_days, log))
    suspend, suspend_note = _load_suspend(pro, start, day)
    if suspend_note:
        missing.append(suspend_note)
    close_df, amount_df, members, sw_notes = _load_sw(pro, start, day, log)
    missing.extend(sw_notes)
    features = ensure_features(feature_days, open_days, close_df, members, basic, suspend, log)
    features = features[features["date"].astype(str) <= day] if not features.empty else features
    prev = previous_open(open_days, day)
    today_chase = None
    if prev:
        today_chase = chase_observation(
            read_cross(prev),
            read_cross(day),
            basic,
            suspend.get(prev, set()),
            suspend.get(day, set()),
            open_days,
            prev,
            with_sample=True,
        )
    if today_chase is None:
        missing.append("当日或前一交易日日线不足，柏拉爱空无法计算")
        today_chase = {"n": None, "mean": None, "median": None, "up": None, "limit_up": None, "drop5": None, "sample": [], "excluded": {}, "dropped_obs": None, "pool": None}
    breadth = breadth_of(read_cross(day))
    if not _ok(breadth.get("up")):
        missing.append("当日涨跌家数无法计算")
    if breadth.get("limit_up") is None:
        missing.append("当日涨跌停价缺失，涨停和跌停家数无法计算")
    rets = returns_asof(close_df, day)
    prev_rets = returns_asof(close_df, prev) if prev else {}
    up_map = sector_up_map(read_cross(day), members)
    if not up_map:
        missing.append("板块成分或当日行情不足，内部上涨占比无法计算")
    amount_map = {}
    if amount_df is not None and not amount_df.empty:
        for name in amount_df.columns:
            amount_map[str(name)] = amount_stats(amount_df[name], day)
    else:
        missing.append("申万成交额无法计算")
    sectors = []
    for window in WINDOWS:
        current = rets.get(window) or {}
        previous_map = prev_rets.get(window) if prev else None
        prev_ranks = ranks_from_returns(previous_map) if previous_map else None
        if not current:
            missing.append(f"{window} 日板块收益率无法计算")
        sectors.append(_sector_block(window, current, prev_ranks, amount_map, up_map))
    labels = _view_labels(day, open_days, close_df, members) if not close_df.empty else {}
    if not labels:
        missing.append("板块标签无法计算")
        labels = {}
    scores = []
    score_index = []
    if not features.empty:
        features = features.reset_index(drop=True)
        positions = [pos for pos, value in enumerate(features["date"].astype(str)) if value in set(feature_days)]
        for pos in positions[-3:]:
            scores.append(score_asof(features, pos))
            score_index.append(pos)
    sentiment = scores[-1] if scores else {}
    velocity, accel = velocity_pair(scores) if scores else (None, None)
    sentiment = dict(sentiment)
    sentiment["velocity"] = velocity
    sentiment["accel"] = accel
    if not _ok(sentiment.get("total")):
        missing.append("情绪综合分无法计算")
    prev_sentiment = scores[-2] if len(scores) >= 2 else None
    amount_prev, amount_ma5 = (None, None)
    if not features.empty and score_index:
        amount_prev, amount_ma5 = _amount_change(features, score_index[-1])
    breadth = dict(breadth)
    breadth["amount_prev"] = amount_prev
    breadth["amount_ma5"] = amount_ma5
    sample = list(today_chase.get("sample") or [])
    codes = [item["ts_code"] for item in sample]
    drawdown, draw_note = (None, "样本为空")
    if codes:
        drawdown, draw_note = fetch_drawdowns(pro, codes, day)
    if drawdown is None:
        missing.append(draw_note or "当日盘中最大回撤无法计算")
    next_day = shift_open(open_days, day, 1)
    if not next_day:
        next_draw, next_note = None, "日历中没有下一交易日"
    elif not session_closed(next_day, moment):
        next_draw, next_note = None, f"下一交易日 {next_day} 尚未收盘"
    elif not codes:
        next_draw, next_note = None, "样本为空"
    else:
        next_draw, next_note = fetch_drawdowns(pro, codes, next_day)
        next_note = f"{next_day}。" + next_note
    if next_draw is None:
        missing.append("次日盘中最大回撤无法计算：" + next_note)
    row = features[features["date"].astype(str) == day] if not features.empty else pd.DataFrame()
    chase_mean = float(row.iloc[-1]["chase_mean"]) if not row.empty and _ok(row.iloc[-1]["chase_mean"]) else today_chase.get("mean")
    drop5 = float(row.iloc[-1]["chase_drop5"]) if not row.empty and _ok(row.iloc[-1]["chase_drop5"]) else today_chase.get("drop5")
    phase = judge_phase(
        sentiment.get("total"),
        velocity,
        breadth.get("up_ratio"),
        chase_mean,
        drop5,
        labels,
        breadth.get("limit_up"),
        breadth.get("limit_down"),
    )
    prev_phase = None
    prev_leader = None
    prev_breadth = None
    if prev and len(scores) >= 2 and not features.empty:
        prev_labels = _view_labels(prev, open_days, close_df, members)
        prev_row = features[features["date"].astype(str) == prev]
        prev_velocity = None
        if len(scores) >= 3 and _ok(scores[-2].get("total")) and _ok(scores[-3].get("total")):
            prev_velocity = float(scores[-2]["total"]) - float(scores[-3]["total"])
        prev_mean = float(prev_row.iloc[-1]["chase_mean"]) if not prev_row.empty and _ok(prev_row.iloc[-1]["chase_mean"]) else None
        prev_drop = float(prev_row.iloc[-1]["chase_drop5"]) if not prev_row.empty and _ok(prev_row.iloc[-1]["chase_drop5"]) else None
        prev_breadth = breadth_of(read_cross(prev))
        prev_phase = judge_phase(
            scores[-2].get("total"),
            prev_velocity,
            prev_breadth.get("up_ratio"),
            prev_mean,
            prev_drop,
            prev_labels,
            prev_breadth.get("limit_up"),
            prev_breadth.get("limit_down"),
        )["phase"]
        prev_leader = _leader_name(returns_asof(close_df, prev, (5,)).get(5, {}))
    leader = _leader_name(rets.get(5, {}))
    history = _history_rows(features, day)
    ctx = {
        "day": day,
        "prev_day": prev,
        "calendar_note": calendar_note,
        "lianban_phase": lianban_phase,
        "error": "",
        "chase_history": history,
        "chase_sample": sample,
        "chase_excluded": today_chase.get("excluded") or {},
        "chase_dropped": today_chase.get("dropped_obs"),
        "chase_pool": today_chase.get("pool"),
        "drawdown": drawdown,
        "drawdown_note": draw_note,
        "next_drawdown": next_draw,
        "next_drawdown_note": next_note,
        "sectors": sectors,
        "labels": labels,
        "breadth": breadth,
        "promotion": _promotion_text(promotion_levels),
        "sentiment": sentiment,
        "phase": phase,
        "missing": _unique(missing),
        "conclusion": _conclusion(
            day,
            prev,
            sentiment,
            prev_sentiment,
            phase,
            prev_phase,
            breadth,
            prev_breadth,
            leader,
            prev_leader,
        ),
    }
    ctx["plan"] = _plan(labels, sectors, {"mean": chase_mean, "up": today_chase.get("up"), "drop5": drop5}, breadth, phase)
    return ctx


def _unique(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def render_quant_report(
    day: str,
    *,
    promotion_levels: list | None = None,
    lianban_phase: str = "",
    calendar_note: str = "",
    prev_day_hint: str | None = None,
    log=None,
    now: datetime | None = None,
) -> str:
    try:
        ctx = assemble(
            day,
            promotion_levels=promotion_levels,
            lianban_phase=lianban_phase,
            calendar_note=calendar_note,
            prev_day_hint=prev_day_hint,
            log=log,
            now=now,
        )
    except Exception as exc:
        _log(log, f"量化复盘失败：{exc}")
        ctx = failure_ctx(day, str(exc), lianban_phase, calendar_note)
    return render_markdown(ctx)


def self_test() -> None:
    opens = ["2026-11-12", "2026-11-13", "2026-11-16"]
    saturday = datetime(2026, 11, 14, 22, 0, tzinfo=TZ)
    assert resolve_brief_day(None, saturday, opens)[0] is None
    morning = datetime(2026, 11, 16, 10, 0, tzinfo=TZ)
    assert resolve_brief_day(None, morning, opens)[0] == "2026-11-13"
    evening = datetime(2026, 11, 16, 17, 30, tzinfo=TZ)
    assert resolve_brief_day(None, evening, opens)[0] == "2026-11-16"
    assert resolve_brief_day(None, evening.replace(hour=15, minute=5), opens)[0] == "2026-11-16"
    assert resolve_brief_day("2026-11-14", evening, opens)[0] is None
    assert resolve_brief_day("2026-11-13", saturday, opens)[0] == "2026-11-13"

    assert listing_days("2020-01-02", "2026-11-13", opens) == 10_000
    short = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06", "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"]
    assert listing_days("2026-11-01", "2026-11-13", short) == 10
    assert listing_days("", "2026-11-13", short) is None

    assert pct_of(list(range(70))) == 100
    assert pct_of([1] * 59) is None
    assert reversed_pct(list(range(70))) == 0
    assert composite_score(80, None, 70) is None
    assert abs(composite_score(80, 50, 70) - (0.4 * 80 + 0.35 * 50 + 0.25 * 70)) < 1e-9
    assert stance_of("回暖", "低") == "精选"
    assert stance_of("回暖", "中") == "进攻"
    assert stance_of("高潮", "高") == "精选"
    assert stance_of("无法判断", "无法评估") == "无法给出"

    ice = judge_phase(10, -2, 0.30, -1, 0.30, {}, 10, 30)
    assert ice["phase"] == "冰点" and ice["confidence"] == "高" and ice["stance"] == "防守"
    hot = judge_phase(80, -1, 0.60, 1.2, 0.05, {}, 40, 5)
    assert hot["phase"] == "高潮" and any("速度" in item for item in hot["counter"])
    assert judge_phase(None, 1, 0.5, 1, 0.1, {"rotation": True}, 1, 1)["phase"] == "无法判断"
    split = judge_phase(
        20,
        0,
        0.70,
        1,
        0.05,
        {"continue": [], "rotation": True, "ebb": [], "new": [], "rotation_overlap": 1},
        10,
        10,
    )
    assert split["phase"] == "分化" and split["stance"] == "精选" and split["confidence"] == "低"

    ret5 = {
        "延续甲": 10, "新方向": 9, "延续乙": 8, "普通丙": 7, "普通丁": 6,
        "填充1": 5, "填充2": 4, "填充3": 3, "填充4": 2, "填充5": 1, "退潮": -1, "填充6": -2,
    }
    ret20 = {
        "延续甲": 10, "延续乙": 9, "普通丙": 8, "普通丁": 7, "填充1": 6,
        "填充2": 5, "填充3": 4, "填充4": 3, "填充5": 2, "退潮": 1, "填充6": 0, "新方向": -1,
    }
    ret60 = {
        "延续甲": 10, "延续乙": 9, "普通丙": 8, "退潮": 7, "填充1": 6,
        "普通丁": 5, "填充2": 4, "填充3": 3, "填充4": 2, "填充5": 1, "填充6": 0, "新方向": -1,
    }
    old = {"延续甲": 2, "延续乙": 11, "普通丙": 4, "普通丁": 5}
    ups = {name: 0.8 for name in ret5}
    ups["退潮"] = 0.2
    labels = structure_labels(ret5, ret20, ret60, old, ups)
    assert labels["continue"] == ["延续甲", "普通丙", "普通丁"], labels
    assert labels["new"] == ["新方向"], labels
    assert labels["ebb"] == ["退潮"], labels
    assert labels["rotation"] is False
    hidden = structure_labels(ret5, ret20, ret60, old, {name: 0.8 for name in ret5})
    assert hidden["ebb"] == []
    rot5 = {"A": 12, "B": 11, "C": 10, "D": 9, "E": 8, "F": 1, "G": 1, "H": 1, "I": 1, "J": 0, "K": 0, "L": 0}
    rot20 = {"A": 10, "F": 9, "G": 8, "H": 7, "I": 6, "B": 5, "C": 4, "D": 3, "E": 2, "J": 1, "K": 0, "L": -1}
    rotation = structure_labels(rot5, rot20, rot20, {"A": 4, "F": 1, "G": 1, "H": 8, "I": 9}, {})
    assert rotation["rotation"] is True and rotation["rotation_overlap"] == 1
    assert rotation["continue"] == ["A"]

    highs = [10, 12, 11]
    lows = [9, 11, 8]
    assert abs(intraday_max_drawdown(highs, lows) - (12 - 8) / 12) < 1e-9
    assert intraday_max_drawdown([], []) is None
    partial, note = summarize_drawdowns([0.01], 20, "")
    assert partial is None and "1/20" in note
    blocked, blocked_note = summarize_drawdowns([0.01], 20, "分钟线频率超限")
    assert blocked is None and blocked_note == "分钟线频率超限"
    covered, covered_note = summarize_drawdowns([0.02] * 16, 20, "")
    assert abs(covered - 0.02) < 1e-9 and "16/20" in covered_note

    days = pd.bdate_range("2026-01-01", periods=80).strftime("%Y-%m-%d").tolist()
    basic = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "name": "平安银行", "list_date": "1991-04-03"},
            {"ts_code": "000002.SZ", "name": "*ST华塑", "list_date": "1991-04-03"},
            {"ts_code": "600001.SH", "name": "次新股份", "list_date": days[-5]},
            {"ts_code": "900901.SH", "name": "B股", "list_date": "1991-04-03"},
            {"ts_code": "300001.SZ", "name": "停牌股份", "list_date": "1991-04-03"},
            {"ts_code": "002001.SZ", "name": "观察停牌", "list_date": "1991-04-03"},
        ]
    )
    rank_rows = [
        ("000002.SZ", 20, 100, 10),
        ("600001.SH", 19, 100, 10),
        ("900901.SH", 18, 100, 10),
        ("300001.SZ", 17, 0, 10),
        ("000001.SZ", 9, 100, 10),
        ("002001.SZ", 8, 100, 10),
    ]
    rank = pd.DataFrame(
        [{"ts_code": code, "pct_chg": pct, "vol": vol, "amount": amount, "close": 10, "up_limit": 11, "down_limit": 9} for code, pct, vol, amount in rank_rows]
    )
    obs = rank.copy()
    obs.loc[obs["ts_code"] == "000001.SZ", "pct_chg"] = 3
    obs.loc[obs["ts_code"] == "000001.SZ", "close"] = 11
    obs.loc[obs["ts_code"] == "002001.SZ", "vol"] = 0
    found = chase_observation(rank, obs, basic, set(), set(), days, days[-2], with_sample=True)
    assert found["n"] == 1, found
    assert found["sample"][0]["name"] == "平安银行"
    assert found["sample"][0]["limit_up"] is True
    assert abs(found["mean"] - 3) < 1e-9
    assert found["excluded"]["st"] == 1
    assert found["excluded"]["new"] >= 1
    assert found["dropped_obs"] == 1
    no_limit = obs.drop(columns=["up_limit", "down_limit"])
    unknown = chase_observation(rank, no_limit, basic, set(), set(), days, days[-2], with_sample=True)
    assert unknown["limit_up"] is None
    assert unknown["mean"] is not None

    text = render_markdown(failure_ctx("2026-11-13", "测试中断", "冰点期", ""))
    for title in ("## 柏拉爱空", "## 板块强弱", "## 市场广度与风险偏好", "## 情绪指数", "## 市场阶段", "## 明日观察", "## 简短复盘结论"):
        assert title in text
    assert "无法计算" in text
    assert "研究参数" in text
    assert "不构成收益承诺" in text
    assert "40%" in text
    assert "nan" not in text.lower()
    print("quant self-test ok")


if __name__ == "__main__":
    self_test()

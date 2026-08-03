#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
市场温度计（Market Temperature）仓位管理模型 V2.3

V2.3 回测验证温度分 vs 上证未来 N 日收益，校准仓位映射（见 market_temperature_backtest.py）
V2.2 涨跌停情绪因子组 + 风险信号百分位化
V2.1 市场广度因子组
V2   资金活跃度因子组
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

# 主要宽基指数：上证为主，深证/创业板为辅
INDEX_CODES = ("000001.SH", "399001.SZ", "399006.SZ")
PRIMARY_INDEX = "000001.SH"
INDEX_WEIGHTS: Dict[str, float] = {
    "000001.SH": 0.60,
    "399001.SZ": 0.20,
    "399006.SZ": 0.20,
}
INDEX_LABELS: Dict[str, str] = {
    "000001.SH": "上证",
    "399001.SZ": "深证",
    "399006.SZ": "创业板",
}

CORE_FACTOR_WEIGHT = 20
PERCENTILE_WINDOW = 250
PERCENTILE_WINDOW_LONG = 500
INDEX_LOOKBACK_CAL_DAYS = 420
MAX_MISSING_FETCH_PER_RUN = 40
WARM_CACHE_MAX_FETCH = 280

# 资金因子组内权重（占 20 分）
VOL_SUB_WEIGHTS = {
    "vol_ratio": 0.35,
    "consecutive_vol": 0.25,
    "vol_price": 0.25,
    "amount_pct": 0.15,
}

# 广度因子组内权重（占 20 分）— V2.1
BREADTH_SUB_WEIGHTS = {
    "up_ratio_pct": 0.40,
    "up_count_pct": 0.25,
    "spread_pct": 0.20,
    "persistence": 0.15,
}
BREADTH_PERSISTENCE_MIN_RATIO = 0.50

# 涨跌停情绪因子组（辅助 10 分）— V2.2
SENTIMENT_MAX_SCORE = 10.0
SENTIMENT_SUB_WEIGHTS = {
    "limit_up_pct": 0.35,
    "limit_down_inv": 0.25,
    "limit_spread_pct": 0.25,
    "limit_ratio_pct": 0.15,
}

# 风险信号百分位阈值 — V2.2（无固定家数门槛）
RISK_PCT_THRESHOLDS = {
    "limit_down_high": 85.0,
    "limit_up_low": 15.0,
    "up_ratio_low": 10.0,
    "limit_spread_low": 15.0,
    "limit_ratio_low": 20.0,
    "market_amount_high": 92.0,
    "upper_shadow_high": 88.0,
}

HOT_SECTOR_TOP_N = 3
HOT_SECTOR_STREAK_DAYS = 3

DEFAULT_OUT_CSV = os.path.join(_SCRIPT_DIR, "market_temperature_latest.csv")
METRICS_CACHE_PATH = os.path.join(_SCRIPT_DIR, "market_metrics_cache.csv")
CALIBRATION_JSON_PATH = os.path.join(_SCRIPT_DIR, "config", "market_temperature_calibration.json")

# 默认阶梯仓位映射（可被回测校准 JSON 覆盖）
DEFAULT_POSITION_BUCKETS: List[Dict[str, Any]] = [
    {"max_score": 20, "position_pct": 0, "label": "空仓"},
    {"max_score": 40, "position_pct": 20, "label": "轻仓 20%"},
    {"max_score": 60, "position_pct": 40, "label": "中仓 40%"},
    {"max_score": 80, "position_pct": 70, "label": "重仓 70%"},
    {"max_score": 101, "position_pct": 100, "label": "满仓 100%"},
]


@dataclass
class FactorScore:
    name: str
    score: float
    max_score: float
    passed: bool
    detail: str = ""


@dataclass
class TemperatureResult:
    trade_date: str
    total_score: float
    position_pct: float
    position_label: str
    factors: List[FactorScore] = field(default_factory=list)
    risk_signals: List[str] = field(default_factory=list)
    risk_penalty: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PlainDiagnosis:
    """通俗诊断摘要。"""

    headline: str
    market_snapshot: List[str]
    action_hints: List[str]
    factor_plain: Dict[str, str]
    mood: str = ""


def _level_word(score: float, max_score: float) -> str:
    if max_score <= 0:
        return "暂无"
    r = score / max_score
    if r >= 0.8:
        return "很好"
    if r >= 0.6:
        return "偏好"
    if r >= 0.4:
        return "一般"
    if r >= 0.2:
        return "偏弱"
    return "较差"


def _pct_plain(pct: float) -> str:
    if np.isnan(pct):
        return "暂无法与历史对比"
    if pct >= 85:
        return "处于近一年极高水平"
    if pct >= 70:
        return "明显高于近期常态"
    if pct >= 55:
        return "略高于近期常态"
    if pct >= 45:
        return "接近近期常态"
    if pct >= 30:
        return "略低于近期常态"
    if pct >= 15:
        return "明显低于近期常态"
    return "处于近一年极低水平"


def _plain_ma_factor(f: FactorScore) -> str:
    name = "短期" if "20" in f.name else "中期"
    if f.score >= f.max_score * 0.8:
        return f"大盘{name}趋势向上，指数多数站在均线之上，适合顺势参与。"
    if f.passed or f.score >= f.max_score * 0.5:
        return f"大盘{name}趋势中性偏强，上证与部分指数仍在均线附近，可精选个股。"
    if f.score > 0:
        return f"大盘{name}趋势偏弱，指数多在均线下方，宜控制节奏、不急于加仓。"
    return f"大盘{name}趋势偏弱，三大指数均未有效站上均线，整体仍处调整格局。"


def _plain_volume_factor(f: FactorScore) -> str:
    d = f.detail
    if f.score >= f.max_score * 0.7:
        base = "资金活跃，成交处于相对高位，市场并不缺流动性。"
    elif f.score >= f.max_score * 0.4:
        base = "资金活跃度中等，有增量但不构成全面进攻信号。"
    else:
        base = "资金偏谨慎，成交与量比均未明显放大，增量资金有限。"
    if "P250=" in d:
        try:
            p250 = float(d.split("P250=")[1].split()[0])
            base += f" 成交额{_pct_plain(p250)}。"
        except Exception:
            pass
    return base


def _plain_breadth_factor(f: FactorScore) -> str:
    d = f.detail
    up = down = 0
    ratio_txt = ""
    if "上涨" in d and "下跌" in d:
        try:
            head = d.split("|")[0]
            m_up = re.search(r"上涨(\d+)", head)
            m_down = re.search(r"下跌(\d+)", head)
            if m_up:
                up = int(m_up.group(1))
            if m_down:
                down = int(m_down.group(1))
            m_ratio = re.search(r"上涨比例=([\d.]+%)", d)
            if m_ratio:
                ratio_txt = m_ratio.group(1)
        except Exception:
            pass
    if up and down:
        if up > down * 1.2:
            spread = "涨家数明显多于跌家数，赚钱效应较好，多数个股在赚钱。"
        elif up > down:
            spread = "涨家数略多于跌家数，个股层面略偏暖。"
        elif down > up * 1.2:
            spread = "跌家数明显多于涨家数，赚钱效应偏差，需防个股普跌风险。"
        elif down > up:
            spread = "跌家数略多于涨家数，市场分化，选股难度上升。"
        else:
            spread = "涨跌家数接近，个股分化明显。"
        if ratio_txt:
            spread += f" 约 {ratio_txt} 的股票收涨。"
    else:
        spread = "个股涨跌互现，需结合板块与个股质量判断。"
    level = _level_word(f.score, f.max_score)
    return f"{spread} 整体广度评价：{level}。"


def _plain_hot_sector_factor(f: FactorScore) -> str:
    d = f.detail
    if f.score >= f.max_score * 0.8:
        return "主线清晰且已连续多日走强，板块有持续性，适合围绕热点做波段。"
    if f.score > 0:
        leaders = ""
        if "涨幅前3:" in d:
            leaders = d.split("涨幅前3:")[1].split(";")[0].strip()
        msg = "有部分板块领涨"
        if leaders:
            msg += f"（如 {leaders}）"
        msg += "，但主线尚未连续三天确认，热点切换较快，不宜盲目追高。"
        return msg
    return "缺乏持续性强的大主线，板块轮动快，更适合低吸而非追涨。"


def _plain_sentiment(sent: Optional[FactorScore]) -> str:
    if sent is None:
        return ""
    if sent.score >= sent.max_score * 0.7:
        return "涨跌停情绪偏暖，短线资金愿意进攻，可参与强势方向。"
    if sent.score >= sent.max_score * 0.4:
        return "涨跌停情绪中性，涨停与跌停都不算极端，宜控制仓位精选标的。"
    return "涨跌停情绪偏弱，涨停不多或跌停偏多，短线博弈需更谨慎。"


def build_plain_diagnosis(result: TemperatureResult) -> PlainDiagnosis:
    """生成非专业人士可读的诊断摘要。"""
    score = result.total_score
    pos = result.position_pct

    if score >= 80:
        headline = f"市场偏强，可考虑接近满仓运作（建议约 {pos:.0f}%）。"
        mood = "进攻"
    elif score >= 60:
        headline = f"市场中性偏强，适合积极但留有余地（建议约 {pos:.0f}%）。"
        mood = "偏进攻"
    elif score >= 40:
        headline = f"市场震荡分化，宜中性仓位、精选个股（建议约 {pos:.0f}%）。"
        mood = "平衡"
    elif score >= 20:
        headline = f"市场偏弱，宜轻仓观望、减少新开仓（建议约 {pos:.0f}%）。"
        mood = "防守"
    else:
        headline = f"市场较弱，建议空仓或仅极小仓位观察（建议约 {pos:.0f}%）。"
        mood = "极度防守"

    if result.risk_penalty > 0:
        headline += f" 另有多项风险信号，已下调评分。"

    factor_plain: Dict[str, str] = {}
    snapshot: List[str] = []
    for f in result.factors:
        if "20日线" in f.name:
            plain = _plain_ma_factor(f)
            label = "短期趋势"
        elif "60日线" in f.name:
            plain = _plain_ma_factor(f)
            label = "中期趋势"
        elif f.name == "资金活跃度":
            plain = _plain_volume_factor(f)
            label = "资金与成交"
        elif f.name == "市场广度":
            plain = _plain_breadth_factor(f)
            label = "赚钱效应"
        elif f.name == "热点持续性":
            plain = _plain_hot_sector_factor(f)
            label = "主线板块"
        else:
            plain = f.detail
            label = f.name
        factor_plain[f.name] = plain
        snapshot.append(f"  {label}：{plain}（{f.score:.0f}/{f.max_score:.0f}分）")

    sent = result.extra.get("sentiment")
    sent_plain = _plain_sentiment(sent if isinstance(sent, FactorScore) else None)
    if sent_plain:
        snapshot.append(f"  短线情绪：{sent_plain}（{sent.score:.0f}/{sent.max_score:.0f}分）" if isinstance(sent, FactorScore) else f"  短线情绪：{sent_plain}")

    action_hints: List[str] = []
    if pos >= 70:
        action_hints.append("可积极加仓，优先强势板块与龙头，但仍需设好止损。")
    elif pos >= 40:
        action_hints.append("维持中等仓位，多做确定性高的个股，避免一次性打满。")
    elif pos >= 20:
        action_hints.append("以轻仓为主，仅小仓试探，不宜追涨。")
    else:
        action_hints.append("以观望为主，减少新开仓，保住现金等待更好时机。")

    ma20 = next((f for f in result.factors if "20日线" in f.name), None)
    ma60 = next((f for f in result.factors if "60日线" in f.name), None)
    hot = next((f for f in result.factors if f.name == "热点持续性"), None)
    breadth = next((f for f in result.factors if f.name == "市场广度"), None)

    if ma20 and ma20.score < ma20.max_score * 0.3:
        action_hints.append("指数短期趋势不佳：不猜底、不重仓抄底，等均线重新走好再加。")
    if ma60 and ma60.score < ma60.max_score * 0.3:
        action_hints.append("中期趋势尚未完全扭转，更适合波段而非长持满仓。")
    if hot and hot.score < hot.max_score * 0.5:
        action_hints.append("热点不持续：少追当日涨幅榜，多等回踩或换到稳健标的。")
    if breadth and breadth.score >= breadth.max_score * 0.6:
        action_hints.append("个股层面仍有一定赚钱效应，可重选股、轻指数。")
    elif breadth and breadth.score < breadth.max_score * 0.3:
        action_hints.append("普跌风险偏高，即使持有也要控制单票仓位。")

    if result.risk_signals:
        plain_risks = result.extra.get("risk_signals_plain") or []
        if plain_risks:
            action_hints.append("风险提示：" + "；".join(plain_risks))
        else:
            action_hints.append(f"风险提示：{'；'.join(result.risk_signals)}")

    return PlainDiagnosis(
        headline=headline,
        market_snapshot=snapshot,
        action_hints=action_hints,
        factor_plain=factor_plain,
        mood=mood,
    )


def _get_tushare_token() -> str:
    try:
        from config.settings import DATA_CONFIG

        return (DATA_CONFIG or {}).get("tushare_token", "") or ""
    except Exception:
        return os.environ.get("TUSHARE_TOKEN", "")


_PROXY_BYPASS_DONE = False


def _bypass_local_proxy() -> None:
    """
    绕过本机 Clash/系统代理（常见 127.0.0.1:7897），避免 TuShare 读超时。
    Windows 即使未设 HTTP_PROXY，requests 也会走 IE/系统代理。
    """
    global _PROXY_BYPASS_DONE
    if _PROXY_BYPASS_DONE:
        return
    for key in (
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "all_proxy",
    ):
        os.environ.pop(key, None)
    os.environ["NO_PROXY"] = "*"
    os.environ["no_proxy"] = "*"
    try:
        import urllib.request

        urllib.request.getproxies = lambda: {}  # type: ignore[assignment,return-value]
    except Exception:
        pass
    try:
        import requests

        _orig_init = requests.Session.__init__

        def _session_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            _orig_init(self, *args, **kwargs)
            self.trust_env = False

        requests.Session.__init__ = _session_init  # type: ignore[method-assign]
    except Exception:
        pass
    _PROXY_BYPASS_DONE = True


def _get_tushare_pro():
    _bypass_local_proxy()
    token = _get_tushare_token()
    if not token:
        return None
    try:
        import tushare as ts

        ts.set_token(token)
        return ts.pro_api()
    except Exception:
        return None


def _normalize_trade_date(s: Optional[str]) -> str:
    if not s:
        return ""
    s = str(s).strip().replace("-", "")
    if len(s) != 8 or not s.isdigit():
        raise ValueError("trade_date 格式应为 YYYYMMDD 或 YYYY-MM-DD")
    return s


def fetch_trade_cal_dates(pro, start_date: str, end_date: str) -> List[str]:
    try:
        cal = pro.trade_cal(exchange="SSE", start_date=start_date, end_date=end_date, is_open="1")
        if cal is None or cal.empty:
            return []
        dates = cal["cal_date"].astype(str).tolist()
        return sorted(d for d in dates if d.isdigit())
    except Exception:
        return []


def resolve_trade_date(pro, trade_date: Optional[str] = None) -> str:
    explicit = _normalize_trade_date(trade_date)
    if explicit:
        return explicit

    anchor = pd.Timestamp.today().normalize()
    start = (anchor - pd.Timedelta(days=45)).strftime("%Y%m%d")
    end = anchor.strftime("%Y%m%d")
    eligible: List[pd.Timestamp] = []
    try:
        cal = pro.trade_cal(exchange="SSE", start_date=start, end_date=end, is_open="1")
        if cal is not None and not cal.empty:
            dates = pd.to_datetime(cal["cal_date"].astype(str), format="%Y%m%d", errors="coerce")
            eligible = sorted(dates.dropna().dt.normalize().unique().tolist())
            eligible = [d for d in eligible if d <= anchor]
    except Exception:
        eligible = []

    if not eligible:
        return pd.bdate_range(end=anchor, periods=1)[0].strftime("%Y%m%d")

    for d in reversed(eligible):
        td = d.strftime("%Y%m%d")
        try:
            df = pro.daily(trade_date=td)
            if df is not None and not df.empty:
                return td
        except Exception:
            pass
        try:
            idx = pro.index_daily(ts_code=PRIMARY_INDEX, trade_date=td)
            if idx is not None and not idx.empty:
                return td
        except Exception:
            pass

    return eligible[-1].strftime("%Y%m%d")


def compute_score_at_date(
    trade_date: str,
    metrics_cache: pd.DataFrame,
    index_dfs: Dict[str, pd.DataFrame],
    pro=None,
    *,
    include_hot: bool = True,
    hot_neutral_score: float = 10.0,
) -> Dict[str, Any]:
    """
    单日评分（回测用）：复用已加载 cache / 指数，避免重复拉取日线。
    include_hot=False 时热点因子取中性分（默认 10/20）。
    """
    td = str(trade_date)
    sh_df = index_dfs.get(PRIMARY_INDEX, pd.DataFrame())

    factors: List[FactorScore] = [
        score_index_above_ma(index_dfs, 20, td),
        score_index_above_ma(index_dfs, 60, td),
        score_volume_factor_group(sh_df, metrics_cache, td),
        score_market_breadth(metrics_cache, td, pd.DataFrame()),
    ]
    if include_hot and pro is not None:
        factors.append(score_hot_sector_persistence(pro, td))
    else:
        factors.append(FactorScore(
            "热点持续性", hot_neutral_score, float(CORE_FACTOR_WEIGHT), False, "回测快速模式(中性分)"
        ))

    total = sum(f.score for f in factors)
    risk_signals, risk_plain = detect_risk_signals(pro, td, index_dfs, metrics_cache, pd.DataFrame())
    risk_penalty = 0.0
    if len(risk_signals) >= 2:
        risk_penalty = min(30.0, 10.0 * (len(risk_signals) - 1))
        total = max(0.0, total - risk_penalty)

    buckets = load_position_buckets()
    position_pct, position_label = _score_to_position(total, buckets=buckets)
    return {
        "trade_date": td,
        "total_score": round(total, 1),
        "position_pct": position_pct,
        "position_label": position_label,
        "risk_penalty": risk_penalty,
        "risk_signal_count": len(risk_signals),
        "factor_scores": {f.name: f.score for f in factors},
        "calibration_loaded": os.path.isfile(CALIBRATION_JSON_PATH),
    }


def fetch_index_daily_panel(pro, end_date: str, lookback_cal_days: int = 900) -> Dict[str, pd.DataFrame]:
    """批量拉取三指数日线面板（回测用，每指数 1 次 API）。"""
    start = (pd.Timestamp(end_date) - pd.Timedelta(days=lookback_cal_days)).strftime("%Y%m%d")
    out: Dict[str, pd.DataFrame] = {}
    for code in INDEX_CODES:
        try:
            df = pro.index_daily(ts_code=code, start_date=start, end_date=end_date)
        except Exception:
            df = pd.DataFrame()
        if df is None or df.empty:
            out[code] = pd.DataFrame()
            continue
        df = df.sort_values("trade_date").reset_index(drop=True)
        for col in ("close", "amount", "vol", "open", "high", "low", "pct_chg"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "pct_chg" not in df.columns and "close" in df.columns:
            df["pct_chg"] = df["close"].pct_change() * 100.0
        out[code] = df
    return out


def slice_index_dfs_as_of(panel: Dict[str, pd.DataFrame], trade_date: str) -> Dict[str, pd.DataFrame]:
    """截取截至 trade_date 的指数序列（模拟当日可见数据）。"""
    out: Dict[str, pd.DataFrame] = {}
    for code, df in panel.items():
        if df.empty:
            out[code] = df
            continue
        sub = df[df["trade_date"].astype(str) <= trade_date].copy()
        out[code] = sub.reset_index(drop=True)
    return out


def build_forward_returns(
    sh_df: pd.DataFrame,
    cal_dates: List[str],
    horizons: List[int],
) -> pd.DataFrame:
    """上证收盘价 -> 未来 N 个交易日收益率（%）。"""
    if sh_df.empty or "close" not in sh_df.columns:
        return pd.DataFrame(columns=["trade_date"] + [f"fwd_ret_{h}d" for h in horizons])
    px = sh_df[["trade_date", "close"]].copy()
    px["trade_date"] = px["trade_date"].astype(str)
    px["close"] = pd.to_numeric(px["close"], errors="coerce")
    date_to_close = dict(zip(px["trade_date"], px["close"]))
    rows: List[Dict[str, Any]] = []
    for i, d in enumerate(cal_dates):
        row: Dict[str, Any] = {"trade_date": d}
        c0 = date_to_close.get(d)
        if c0 is None or np.isnan(c0) or c0 <= 0:
            for h in horizons:
                row[f"fwd_ret_{h}d"] = float("nan")
            rows.append(row)
            continue
        for h in horizons:
            j = i + h
            if j < len(cal_dates):
                c1 = date_to_close.get(cal_dates[j])
                if c1 is not None and not np.isnan(c1) and c1 > 0:
                    row[f"fwd_ret_{h}d"] = (c1 / c0 - 1.0) * 100.0
                else:
                    row[f"fwd_ret_{h}d"] = float("nan")
            else:
                row[f"fwd_ret_{h}d"] = float("nan")
        rows.append(row)
    return pd.DataFrame(rows)


def load_position_buckets(path: Optional[str] = None) -> List[Dict[str, Any]]:
    """加载仓位映射；无校准文件时使用默认阶梯。"""
    p = path or CALIBRATION_JSON_PATH
    if not os.path.isfile(p):
        return list(DEFAULT_POSITION_BUCKETS)
    try:
        import json

        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        buckets = data.get("buckets") if isinstance(data, dict) else None
        if not isinstance(buckets, list) or not buckets:
            return list(DEFAULT_POSITION_BUCKETS)
        out: List[Dict[str, Any]] = []
        for b in buckets:
            if not isinstance(b, dict):
                continue
            out.append({
                "max_score": float(b.get("max_score", 101)),
                "position_pct": float(b.get("position_pct", 0)),
                "label": str(b.get("label", "")),
            })
        out.sort(key=lambda x: x["max_score"])
        return out if out else list(DEFAULT_POSITION_BUCKETS)
    except Exception:
        return list(DEFAULT_POSITION_BUCKETS)


def _score_to_position(
    score: float,
    buckets: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[float, str]:
    """得分 -> 建议仓位（支持回测校准映射）。"""
    bl = buckets if buckets is not None else load_position_buckets()
    s = max(0.0, min(100.0, float(score)))
    for b in bl:
        if s < float(b["max_score"]):
            label = str(b.get("label") or f"{b['position_pct']:.0f}%")
            return float(b["position_pct"]), label
    last = bl[-1]
    return float(last["position_pct"]), str(last.get("label") or "满仓 100%")


def _calc_ma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=window).mean()


def _percentile_rank(value: float, history: pd.Series) -> float:
    """返回 value 在 history 中的百分位 (0~100)。"""
    hist = pd.to_numeric(history, errors="coerce").dropna()
    if hist.empty or np.isnan(value):
        return float("nan")
    return float((hist <= value).sum() / len(hist) * 100.0)


def _metric_int(val: Any, default: int = 0) -> int:
    v = pd.to_numeric(val, errors="coerce")
    return default if pd.isna(v) else int(v)


def _score_from_inverse_percentile(
    pct: float, max_score: float, pass_pct: float = 45.0
) -> Tuple[float, bool]:
    """百分位越高越差（如跌停家数），得分按逆向映射。"""
    if np.isnan(pct):
        return 0.0, False
    return _score_from_percentile(100.0 - pct, max_score, pass_pct=pass_pct)


def _score_from_percentile(pct: float, max_score: float, pass_pct: float = 60.0) -> Tuple[float, bool]:
    if np.isnan(pct):
        return 0.0, False
    if pct >= 80:
        score = max_score
    elif pct >= pass_pct:
        score = max_score * (0.6 + 0.4 * (pct - pass_pct) / max(80 - pass_pct, 1))
    else:
        score = max_score * max(0.0, pct / pass_pct * 0.6)
    return round(score, 2), pct >= pass_pct


def fetch_index_daily(
    pro,
    ts_code: str,
    end_date: str,
    lookback_days: int = INDEX_LOOKBACK_CAL_DAYS,
) -> pd.DataFrame:
    start = (pd.Timestamp(end_date) - pd.Timedelta(days=lookback_days)).strftime("%Y%m%d")
    try:
        df = pro.index_daily(ts_code=ts_code, start_date=start, end_date=end_date)
    except Exception as e:
        print(f"index_daily 失败 [{ts_code}]: {e}", file=sys.stderr)
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.sort_values("trade_date").reset_index(drop=True)
    for col in ("close", "amount", "vol", "open", "high", "low", "pct_chg"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "pct_chg" not in df.columns and "close" in df.columns:
        df["pct_chg"] = df["close"].pct_change() * 100.0
    return df


def fetch_market_daily(pro, trade_date: str) -> pd.DataFrame:
    try:
        df = pro.daily(trade_date=trade_date)
    except Exception as e:
        print(f"daily 失败 [{trade_date}]: {e}", file=sys.stderr)
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    for col in ("pct_chg", "amount", "close"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _fetch_limit_counts(pro, trade_date: str) -> Tuple[int, int]:
    up_n, down_n = 0, 0
    for fn_name in ("limit_list_d", "limit_list"):
        try:
            fn = getattr(pro, fn_name, None)
            if fn is None:
                continue
            df_up = fn(trade_date=trade_date, limit_type="U")
            df_down = fn(trade_date=trade_date, limit_type="D")
            if df_up is not None and not df_up.empty:
                up_n = len(df_up)
            if df_down is not None and not df_down.empty:
                down_n = len(df_down)
            if up_n or down_n:
                return up_n, down_n
        except Exception:
            continue
    return up_n, down_n


def _fetch_day_metrics(pro, trade_date: str) -> Dict[str, Any]:
    daily_df = fetch_market_daily(pro, trade_date)
    up_n = down_n = total = 0
    amount_yi = float("nan")
    if not daily_df.empty and "pct_chg" in daily_df.columns:
        up_n = int((daily_df["pct_chg"] > 0).sum())
        down_n = int((daily_df["pct_chg"] < 0).sum())
        total = len(daily_df)
        if "amount" in daily_df.columns:
            amount_yi = float(daily_df["amount"].sum()) / 1e5
    limit_up, limit_down = _fetch_limit_counts(pro, trade_date)
    up_ratio = up_n / total if total else float("nan")
    spread = limit_up - limit_down
    adv_dec = up_n - down_n
    limit_ratio = limit_up / max(limit_down, 1)
    return {
        "trade_date": trade_date,
        "market_amount_yi": amount_yi,
        "up_count": up_n,
        "down_count": down_n,
        "total_count": total,
        "up_ratio": up_ratio,
        "advance_decline_spread": adv_dec,
        "limit_up": limit_up,
        "limit_down": limit_down,
        "limit_spread": spread,
        "limit_ratio": limit_ratio,
    }


def load_metrics_cache() -> pd.DataFrame:
    cols = [
        "trade_date", "market_amount_yi", "up_count", "down_count", "total_count",
        "up_ratio", "advance_decline_spread", "limit_up", "limit_down", "limit_spread",
        "limit_ratio",
    ]
    if not os.path.isfile(METRICS_CACHE_PATH):
        return pd.DataFrame(columns=cols)
    try:
        df = pd.read_csv(METRICS_CACHE_PATH, dtype={"trade_date": str})
        for c in cols:
            if c not in df.columns:
                df[c] = np.nan
        return _backfill_cache_derived(df.sort_values("trade_date").reset_index(drop=True))
    except Exception:
        return pd.DataFrame(columns=cols)


def _backfill_cache_derived(df: pd.DataFrame) -> pd.DataFrame:
    """为旧缓存补算 limit_ratio 等派生列。"""
    if df.empty:
        return df
    if "limit_ratio" not in df.columns:
        df["limit_ratio"] = np.nan
    mask = pd.to_numeric(df["limit_ratio"], errors="coerce").isna()
    if mask.any() and {"limit_up", "limit_down"}.issubset(df.columns):
        up = pd.to_numeric(df.loc[mask, "limit_up"], errors="coerce").fillna(0)
        down = pd.to_numeric(df.loc[mask, "limit_down"], errors="coerce").fillna(0)
        df.loc[mask, "limit_ratio"] = up / down.replace(0, 1).clip(lower=1)
    return df


def _upper_shadow_ratio(row: pd.Series) -> float:
    if not {"high", "low", "open", "close"}.issubset(row.index):
        return float("nan")
    body_top = max(float(row["open"]), float(row["close"]))
    upper_shadow = float(row["high"]) - body_top
    rng = float(row["high"]) - float(row["low"])
    return upper_shadow / rng if rng > 0 else float("nan")


def save_metrics_cache(df: pd.DataFrame) -> None:
    df.sort_values("trade_date").drop_duplicates("trade_date", keep="last").to_csv(
        METRICS_CACHE_PATH, index=False, encoding="utf-8-sig"
    )


def _batch_index_amount_yi(pro, start_date: str, end_date: str) -> pd.DataFrame:
    """批量拉取上证+深证 index_daily.amount，汇总为亿元（2 次 API）。"""
    totals: Dict[str, float] = {}
    for code in (PRIMARY_INDEX, "399001.SZ"):
        try:
            df = pro.index_daily(ts_code=code, start_date=start_date, end_date=end_date)
        except Exception:
            continue
        if df is None or df.empty or "amount" not in df.columns:
            continue
        for _, row in df.iterrows():
            td = str(row["trade_date"])
            amt = float(row["amount"]) if pd.notna(row["amount"]) else 0.0
            totals[td] = totals.get(td, 0.0) + amt
    if not totals:
        return pd.DataFrame(columns=["trade_date", "market_amount_yi"])
    return pd.DataFrame(
        [{"trade_date": td, "market_amount_yi": amt / 1e5} for td, amt in sorted(totals.items())]
    )


def ensure_metrics_cache(pro, end_date: str, *, warm: bool = False) -> pd.DataFrame:
    """增量补齐至 end_date；warm=True 时尽量补全 P250 窗口内全部广度数据。"""
    cache = load_metrics_cache()
    start = (pd.Timestamp(end_date) - pd.Timedelta(days=PERCENTILE_WINDOW_LONG * 2)).strftime("%Y%m%d")
    cal_dates = fetch_trade_cal_dates(pro, start, end_date)
    if not cal_dates:
        return cache

    end_idx = cal_dates.index(end_date) if end_date in cal_dates else len(cal_dates) - 1
    window_start_idx = max(0, end_idx - PERCENTILE_WINDOW_LONG + 1)
    needed_dates = cal_dates[window_start_idx : end_idx + 1]
    window_start = needed_dates[0]

    existing = set(cache["trade_date"].astype(str).tolist()) if not cache.empty else set()

    amt_df = _batch_index_amount_yi(pro, window_start, end_date)
    if not amt_df.empty:
        if cache.empty:
            cache = amt_df.copy()
            for col in (
                "up_count", "down_count", "total_count", "up_ratio", "advance_decline_spread",
                "limit_up", "limit_down", "limit_spread", "limit_ratio",
            ):
                cache[col] = np.nan
        else:
            cache = cache.drop(columns=["market_amount_yi"], errors="ignore").merge(
                amt_df, on="trade_date", how="outer"
            )
        existing = set(cache["trade_date"].astype(str).tolist())

    need_detail = [d for d in needed_dates if d not in existing or _row_needs_detail(cache, d)]
    if warm:
        need_detail = need_detail[:WARM_CACHE_MAX_FETCH]
        if need_detail:
            print(f"warm-cache: 补齐广度数据 {len(need_detail)} 个交易日...", file=sys.stderr)
    else:
        need_detail = need_detail[-MAX_MISSING_FETCH_PER_RUN:]

    rows: List[Dict[str, Any]] = []
    for i, td in enumerate(need_detail):
        rows.append(_fetch_day_metrics(pro, td))
        if warm and (i + 1) % 20 == 0:
            print(f"  已拉取 {i + 1}/{len(need_detail)} ...", file=sys.stderr)

    if rows:
        detail_df = pd.DataFrame(rows)
        if cache.empty:
            cache = detail_df
        else:
            cache = cache.merge(detail_df, on="trade_date", how="outer", suffixes=("", "_d"))
            for col in detail_df.columns:
                if col == "trade_date":
                    continue
                new_col = f"{col}_d"
                if new_col in cache.columns:
                    cache[col] = cache[new_col].combine_first(cache[col])
                    cache = cache.drop(columns=[new_col])
        cache = cache.sort_values("trade_date").drop_duplicates("trade_date", keep="last")
        save_metrics_cache(cache)
    elif not amt_df.empty:
        cache = cache.sort_values("trade_date").drop_duplicates("trade_date", keep="last")
        save_metrics_cache(cache)

    return _backfill_cache_derived(cache)


def breadth_history_stats(cache: pd.DataFrame, trade_date: str) -> Dict[str, int]:
    """P250 窗口内可用于广度百分位的历史天数。"""
    if cache.empty:
        return {"breadth_days_250": 0, "breadth_days_500": 0}
    sub250 = cache[
        (cache["trade_date"].astype(str) < trade_date)
        & pd.to_numeric(cache["up_ratio"], errors="coerce").notna()
    ].tail(PERCENTILE_WINDOW)
    sub500 = cache[
        (cache["trade_date"].astype(str) < trade_date)
        & pd.to_numeric(cache["up_ratio"], errors="coerce").notna()
    ].tail(PERCENTILE_WINDOW_LONG)
    return {"breadth_days_250": len(sub250), "breadth_days_500": len(sub500)}


def _row_needs_detail(cache: pd.DataFrame, trade_date: str) -> bool:
    row = cache[cache["trade_date"].astype(str) == trade_date]
    if row.empty:
        return True
    up_ratio = pd.to_numeric(row.iloc[0].get("up_ratio"), errors="coerce")
    return pd.isna(up_ratio)


def _history_before(cache: pd.DataFrame, trade_date: str, col: str, window: int) -> pd.Series:
    if cache.empty or col not in cache.columns:
        return pd.Series(dtype=float)
    sub = cache[cache["trade_date"].astype(str) < trade_date].tail(window)
    return pd.to_numeric(sub[col], errors="coerce").dropna()


def score_index_above_ma(
    index_dfs: Dict[str, pd.DataFrame],
    ma_window: int,
    trade_date: str,
) -> FactorScore:
    weighted_score = 0.0
    sh_passed = False
    details: List[str] = []
    for code in INDEX_CODES:
        weight = INDEX_WEIGHTS.get(code, 0.0)
        label = INDEX_LABELS.get(code, code)
        df = index_dfs.get(code, pd.DataFrame())
        if df.empty or "close" not in df.columns:
            details.append(f"{label}: 无数据")
            continue
        sub = df[df["trade_date"].astype(str) <= trade_date].copy()
        if sub.empty:
            details.append(f"{label}: 无当日数据")
            continue
        sub["ma"] = _calc_ma(sub["close"], ma_window)
        row = sub.iloc[-1]
        close_v = float(row["close"])
        ma_v = float(row["ma"]) if pd.notna(row["ma"]) else float("nan")
        ok = pd.notna(ma_v) and close_v >= ma_v
        if ok:
            weighted_score += CORE_FACTOR_WEIGHT * weight
        if code == PRIMARY_INDEX:
            sh_passed = ok
        details.append(
            f"{label}({weight:.0%}) close={close_v:.2f} ma{ma_window}={ma_v:.2f} {'Y' if ok else 'N'}"
        )

    return FactorScore(
        name=f"站上{ma_window}日线",
        score=round(weighted_score, 1),
        max_score=float(CORE_FACTOR_WEIGHT),
        passed=sh_passed and weighted_score >= CORE_FACTOR_WEIGHT - 0.1,
        detail="; ".join(details),
    )


def _subscore_vol_ratio(vol_ratio: float, max_pts: float) -> float:
    if np.isnan(vol_ratio) or vol_ratio <= 0:
        return 0.0
    if vol_ratio >= 1.35:
        return max_pts
    if vol_ratio >= 1.20:
        return max_pts * 0.85
    if vol_ratio >= 1.10:
        return max_pts * 0.65
    if vol_ratio >= 1.00:
        return max_pts * 0.45
    if vol_ratio >= 0.90:
        return max_pts * 0.25
    return max_pts * max(0.0, vol_ratio / 1.5)


def _subscore_consecutive_vol(sh_df: pd.DataFrame, trade_date: str, max_pts: float, window: int = 5) -> Tuple[float, int]:
    sub = sh_df[sh_df["trade_date"].astype(str) <= trade_date].copy()
    if sub.empty or "vol" not in sub.columns:
        return 0.0, 0
    sub["vol_ma5"] = _calc_ma(sub["vol"], 5)
    tail = sub.tail(window)
    hits = 0
    for _, row in tail.iterrows():
        v = float(row["vol"]) if pd.notna(row["vol"]) else float("nan")
        ma = float(row["vol_ma5"]) if pd.notna(row["vol_ma5"]) else float("nan")
        if pd.notna(v) and pd.notna(ma) and v >= ma:
            hits += 1
    return round(max_pts * hits / window, 2), hits


def _subscore_vol_price(sh_df: pd.DataFrame, trade_date: str, max_pts: float, window: int = 5) -> Tuple[float, int]:
    sub = sh_df[sh_df["trade_date"].astype(str) <= trade_date].copy()
    if len(sub) < 2 or "vol" not in sub.columns:
        return 0.0, 0
    if "pct_chg" not in sub.columns and "close" in sub.columns:
        sub["pct_chg"] = sub["close"].pct_change() * 100.0
    sub["vol_ma5"] = _calc_ma(sub["vol"], 5)
    tail = sub.tail(window).reset_index(drop=True)
    hits = 0
    for i in range(len(tail)):
        pct = float(tail.loc[i, "pct_chg"]) if pd.notna(tail.loc[i, "pct_chg"]) else 0.0
        vol = float(tail.loc[i, "vol"]) if pd.notna(tail.loc[i, "vol"]) else float("nan")
        if np.isnan(vol):
            continue
        if i > 0:
            prev_vol = float(tail.loc[i - 1, "vol"]) if pd.notna(tail.loc[i - 1, "vol"]) else vol
        else:
            prev_vol = float(tail.loc[i, "vol_ma5"]) if pd.notna(tail.loc[i, "vol_ma5"]) else vol
        if pct > 0 and vol >= prev_vol * 0.95:
            hits += 1
        elif pct <= 0 and vol <= prev_vol * 1.05:
            hits += 1
    return round(max_pts * hits / max(len(tail), 1), 2), hits


def score_volume_factor_group(
    sh_df: pd.DataFrame,
    metrics_cache: pd.DataFrame,
    trade_date: str,
) -> FactorScore:
    """
    资金活跃度因子组（20 分）：
    - 量比（上证 vol / MA5 vol）35%
    - 连续放量天数 25%
    - 量价配合 25%
    - 成交额 250 日百分位 15%（两市汇总，环境过滤）
    """
    max_score = float(CORE_FACTOR_WEIGHT)
    w = VOL_SUB_WEIGHTS
    pts = {k: max_score * v for k, v in w.items()}
    details: List[str] = []

    sub = sh_df[sh_df["trade_date"].astype(str) <= trade_date].copy()
    if sub.empty or "vol" not in sub.columns:
        return FactorScore("资金活跃度", 0.0, max_score, False, "无上证成交量数据")

    sub["vol_ma5"] = _calc_ma(sub["vol"], 5)
    row = sub.iloc[-1]
    vol_today = float(row["vol"]) if pd.notna(row["vol"]) else float("nan")
    vol_ma5 = float(row["vol_ma5"]) if pd.notna(row["vol_ma5"]) else float("nan")
    vol_ratio = vol_today / vol_ma5 if pd.notna(vol_ma5) and vol_ma5 > 0 else float("nan")
    s_ratio = _subscore_vol_ratio(vol_ratio, pts["vol_ratio"])
    details.append(f"量比(上证)={vol_ratio:.2f} -> {s_ratio:.1f}/{pts['vol_ratio']:.1f}")

    s_consec, consec_n = _subscore_consecutive_vol(sh_df, trade_date, pts["consecutive_vol"])
    details.append(f"近5日放量{consec_n}天 -> {s_consec:.1f}/{pts['consecutive_vol']:.1f}")

    s_vp, vp_n = _subscore_vol_price(sh_df, trade_date, pts["vol_price"])
    details.append(f"量价配合{vp_n}/5 -> {s_vp:.1f}/{pts['vol_price']:.1f}")

    amount_yi = float("nan")
    amount_pct_250 = float("nan")
    amount_pct_500 = float("nan")
    amount_dev20 = float("nan")
    if not metrics_cache.empty:
        today_row = metrics_cache[metrics_cache["trade_date"].astype(str) == trade_date]
        if not today_row.empty:
            amount_yi = float(pd.to_numeric(today_row.iloc[0]["market_amount_yi"], errors="coerce"))
        hist250 = _history_before(metrics_cache, trade_date, "market_amount_yi", PERCENTILE_WINDOW)
        hist500 = _history_before(metrics_cache, trade_date, "market_amount_yi", PERCENTILE_WINDOW_LONG)
        if not np.isnan(amount_yi):
            amount_pct_250 = _percentile_rank(amount_yi, hist250)
            amount_pct_500 = _percentile_rank(amount_yi, hist500)
        if not hist250.empty and len(hist250) >= 20:
            ma20_amt = float(hist250.tail(20).mean())
            if ma20_amt > 0 and not np.isnan(amount_yi):
                amount_dev20 = (amount_yi / ma20_amt - 1.0) * 100.0

    s_amt, _ = _score_from_percentile(amount_pct_250, pts["amount_pct"], pass_pct=50.0)
    amt_note = f"成交额{amount_yi:,.0f}亿" if not np.isnan(amount_yi) else "成交额N/A"
    pct_note = f"P250={amount_pct_250:.0f}" if not np.isnan(amount_pct_250) else "P250=N/A"
    pct500_note = f"P500={amount_pct_500:.0f}" if not np.isnan(amount_pct_500) else "P500=N/A"
    dev_note = f"偏离20均={amount_dev20:+.1f}%" if not np.isnan(amount_dev20) else ""
    details.append(f"{amt_note} {pct_note} {pct500_note} {dev_note} -> {s_amt:.1f}/{pts['amount_pct']:.1f}")

    total = s_ratio + s_consec + s_vp + s_amt
    passed = (not np.isnan(vol_ratio) and vol_ratio >= 1.1) or (
        not np.isnan(amount_pct_250) and amount_pct_250 >= 60
    )
    return FactorScore(
        name="资金活跃度",
        score=round(total, 1),
        max_score=max_score,
        passed=passed,
        detail=" | ".join(details),
    )


def _subscore_breadth_persistence(
    metrics_cache: pd.DataFrame,
    trade_date: str,
    max_pts: float,
    window: int = 5,
) -> Tuple[float, int]:
    """近 window 日上涨比例 >= 阈值 或高于 5 日均值的天数。"""
    if metrics_cache.empty:
        return 0.0, 0
    sub = metrics_cache[metrics_cache["trade_date"].astype(str) <= trade_date].copy()
    sub["up_ratio"] = pd.to_numeric(sub["up_ratio"], errors="coerce")
    sub = sub.dropna(subset=["up_ratio"]).tail(window)
    if sub.empty:
        return 0.0, 0
    ma5 = float(sub["up_ratio"].mean())
    hits = 0
    for _, row in sub.iterrows():
        r = float(row["up_ratio"])
        if r >= BREADTH_PERSISTENCE_MIN_RATIO or r >= ma5:
            hits += 1
    return round(max_pts * hits / len(sub), 2), hits


def score_market_breadth(
    metrics_cache: pd.DataFrame,
    trade_date: str,
    daily_df: pd.DataFrame,
) -> FactorScore:
    """
    V2.1 市场广度因子组（20 分）：
    - 上涨比例 P250 40%
    - 上涨家数 P250 25%
    - 涨跌扩散 P250 20%
    - 广度持续性 15%
    """
    max_score = float(CORE_FACTOR_WEIGHT)
    w = BREADTH_SUB_WEIGHTS
    pts = {k: max_score * v for k, v in w.items()}
    details: List[str] = []

    up_ratio = float("nan")
    up = down = flat = 0
    adv_spread = float("nan")
    if not metrics_cache.empty:
        row = metrics_cache[metrics_cache["trade_date"].astype(str) == trade_date]
        if not row.empty:
            up_ratio = float(pd.to_numeric(row.iloc[0]["up_ratio"], errors="coerce"))
            up = _metric_int(row.iloc[0].get("up_count"))
            down = _metric_int(row.iloc[0].get("down_count"))
            total = _metric_int(row.iloc[0].get("total_count"))
            flat = max(total - up - down, 0)
            adv_spread = float(pd.to_numeric(row.iloc[0].get("advance_decline_spread"), errors="coerce"))
            if np.isnan(adv_spread):
                adv_spread = float(up - down)

    if np.isnan(up_ratio) and not daily_df.empty and "pct_chg" in daily_df.columns:
        up = int((daily_df["pct_chg"] > 0).sum())
        down = int((daily_df["pct_chg"] < 0).sum())
        flat = len(daily_df) - up - down
        up_ratio = up / len(daily_df) if len(daily_df) else float("nan")
        adv_spread = float(up - down)

    if np.isnan(up_ratio):
        return FactorScore("市场广度", 0.0, max_score, False, "无上涨比例数据")

    hist_stats = breadth_history_stats(metrics_cache, trade_date)
    hist_n = hist_stats.get("breadth_days_250", 0)

    hist_ratio = _history_before(metrics_cache, trade_date, "up_ratio", PERCENTILE_WINDOW)
    hist_count = _history_before(metrics_cache, trade_date, "up_count", PERCENTILE_WINDOW)
    hist_spread = _history_before(metrics_cache, trade_date, "advance_decline_spread", PERCENTILE_WINDOW)
    hist500 = _history_before(metrics_cache, trade_date, "up_ratio", PERCENTILE_WINDOW_LONG)

    pct_ratio = _percentile_rank(up_ratio, hist_ratio)
    pct500 = _percentile_rank(up_ratio, hist500)
    pct_count = _percentile_rank(float(up), hist_count)
    pct_spread = _percentile_rank(adv_spread, hist_spread) if not np.isnan(adv_spread) else float("nan")

    s_ratio, _ = _score_from_percentile(pct_ratio, pts["up_ratio_pct"], pass_pct=55.0)
    s_count, _ = _score_from_percentile(pct_count, pts["up_count_pct"], pass_pct=55.0)
    s_spread, _ = _score_from_percentile(pct_spread, pts["spread_pct"], pass_pct=55.0)
    s_persist, persist_n = _subscore_breadth_persistence(metrics_cache, trade_date, pts["persistence"])

    details.append(
        f"上涨比例={up_ratio:.1%} P250={pct_ratio:.0f} P500={pct500:.0f} -> {s_ratio:.1f}/{pts['up_ratio_pct']:.1f}"
    )
    details.append(f"上涨家数={up} P250={pct_count:.0f} -> {s_count:.1f}/{pts['up_count_pct']:.1f}")
    spread_note = f"扩散={int(adv_spread):+d}" if not np.isnan(adv_spread) else "扩散=N/A"
    pct_spread_note = f"P250={pct_spread:.0f}" if not np.isnan(pct_spread) else "P250=N/A"
    details.append(f"{spread_note} {pct_spread_note} -> {s_spread:.1f}/{pts['spread_pct']:.1f}")
    details.append(f"近5日广度持续{persist_n}天 -> {s_persist:.1f}/{pts['persistence']:.1f}")

    total = s_ratio + s_count + s_spread + s_persist
    passed = (not np.isnan(pct_ratio) and pct_ratio >= 55) or (
        not np.isnan(pct_count) and pct_count >= 55
    )
    head = f"上涨{up} 下跌{down} 平盘{flat} | 历史样本{hist_n}日"
    return FactorScore(
        name="市场广度",
        score=round(total, 1),
        max_score=max_score,
        passed=passed,
        detail=f"{head} | " + " | ".join(details),
    )


def score_limit_sentiment(
    metrics_cache: pd.DataFrame,
    trade_date: str,
    pro=None,
) -> FactorScore:
    """
    V2.2 涨跌停情绪因子组（10 分）：
    - 涨停家数 P250 35%
    - 跌停家数 P250 逆向 25%
    - 涨跌停差 P250 25%
    - 涨跌停比 P250 15%
    """
    max_score = SENTIMENT_MAX_SCORE
    w = SENTIMENT_SUB_WEIGHTS
    pts = {k: max_score * v for k, v in w.items()}
    details: List[str] = []

    limit_up = limit_down = 0
    limit_spread = float("nan")
    limit_ratio = float("nan")
    if not metrics_cache.empty:
        row = metrics_cache[metrics_cache["trade_date"].astype(str) == trade_date]
        if not row.empty:
            limit_up = _metric_int(row.iloc[0].get("limit_up"))
            limit_down = _metric_int(row.iloc[0].get("limit_down"))
            limit_spread = float(pd.to_numeric(row.iloc[0].get("limit_spread"), errors="coerce"))
            limit_ratio = float(pd.to_numeric(row.iloc[0].get("limit_ratio"), errors="coerce"))
    if limit_up == 0 and limit_down == 0 and pro is not None:
        limit_up, limit_down = _fetch_limit_counts(pro, trade_date)
        limit_spread = float(limit_up - limit_down)
        limit_ratio = limit_up / max(limit_down, 1)

    if limit_up == 0 and limit_down == 0:
        return FactorScore("涨跌停情绪", 0.0, max_score, False, "无涨跌停明细")

    if np.isnan(limit_spread):
        limit_spread = float(limit_up - limit_down)
    if np.isnan(limit_ratio):
        limit_ratio = limit_up / max(limit_down, 1)

    pct_up = _percentile_rank(float(limit_up), _history_before(metrics_cache, trade_date, "limit_up", PERCENTILE_WINDOW))
    pct_down = _percentile_rank(float(limit_down), _history_before(metrics_cache, trade_date, "limit_down", PERCENTILE_WINDOW))
    pct_spread = _percentile_rank(limit_spread, _history_before(metrics_cache, trade_date, "limit_spread", PERCENTILE_WINDOW))
    pct_ratio = _percentile_rank(limit_ratio, _history_before(metrics_cache, trade_date, "limit_ratio", PERCENTILE_WINDOW))

    s_up, _ = _score_from_percentile(pct_up, pts["limit_up_pct"], pass_pct=55.0)
    s_down, _ = _score_from_inverse_percentile(pct_down, pts["limit_down_inv"], pass_pct=45.0)
    s_spread, _ = _score_from_percentile(pct_spread, pts["limit_spread_pct"], pass_pct=50.0)
    s_ratio, _ = _score_from_percentile(pct_ratio, pts["limit_ratio_pct"], pass_pct=50.0)

    details.append(f"涨停{limit_up} P250={pct_up:.0f} -> {s_up:.1f}/{pts['limit_up_pct']:.1f}")
    details.append(f"跌停{limit_down} P250={pct_down:.0f}(逆向) -> {s_down:.1f}/{pts['limit_down_inv']:.1f}")
    details.append(f"扩散{int(limit_spread):+d} P250={pct_spread:.0f} -> {s_spread:.1f}/{pts['limit_spread_pct']:.1f}")
    details.append(f"比值{limit_ratio:.1f} P250={pct_ratio:.0f} -> {s_ratio:.1f}/{pts['limit_ratio_pct']:.1f}")

    total = s_up + s_down + s_spread + s_ratio
    passed = (not np.isnan(pct_up) and pct_up >= 55) and (not np.isnan(pct_down) and pct_down <= 45)
    return FactorScore(
        name="涨跌停情绪",
        score=round(total, 1),
        max_score=max_score,
        passed=passed,
        detail=" | ".join(details),
    )


def _risk_plain_message(key: str, pct: float, raw_note: str) -> str:
    """风险信号白话说明。"""
    mapping = {
        "limit_down_high": f"跌停家数处于近一年高位（P250={pct:.0f}），短线恐慌升温",
        "limit_up_low": f"涨停家数处于近一年低位（P250={pct:.0f}），投机情绪低迷",
        "up_ratio_low": f"上涨股票占比处于近一年低位（P250={pct:.0f}），赚钱效应差",
        "limit_spread_low": f"涨跌停差处于近一年低位（P250={pct:.0f}），多头明显偏弱",
        "limit_ratio_low": f"涨跌停比处于近一年低位（P250={pct:.0f}），短线情绪偏弱",
        "market_amount_high": f"两市成交额处于近一年极高水平（P250={pct:.0f}），注意放量滞涨",
        "upper_shadow_high": f"上证上影线偏长（P250={pct:.0f}），上方抛压较重",
    }
    base = mapping.get(key, raw_note)
    return base


def detect_risk_signals(
    pro,
    trade_date: str,
    index_dfs: Dict[str, pd.DataFrame],
    metrics_cache: pd.DataFrame,
    daily_df: pd.DataFrame,
) -> Tuple[List[str], List[str]]:
    """
    V2.2 风险信号：全部基于 P250 百分位阈值，返回 (技术描述, 白话描述)。
    """
    tech: List[str] = []
    plain: List[str] = []
    th = RISK_PCT_THRESHOLDS

    row = metrics_cache[metrics_cache["trade_date"].astype(str) == trade_date] if not metrics_cache.empty else pd.DataFrame()
    limit_up = limit_down = 0
    up_ratio = limit_spread = limit_ratio = float("nan")
    amount_yi = float("nan")
    if not row.empty:
        limit_up = _metric_int(row.iloc[0].get("limit_up"))
        limit_down = _metric_int(row.iloc[0].get("limit_down"))
        up_ratio = float(pd.to_numeric(row.iloc[0].get("up_ratio"), errors="coerce"))
        limit_spread = float(pd.to_numeric(row.iloc[0].get("limit_spread"), errors="coerce"))
        limit_ratio = float(pd.to_numeric(row.iloc[0].get("limit_ratio"), errors="coerce"))
        amount_yi = float(pd.to_numeric(row.iloc[0].get("market_amount_yi"), errors="coerce"))
    else:
        limit_up, limit_down = _fetch_limit_counts(pro, trade_date)
        limit_spread = float(limit_up - limit_down)
        limit_ratio = limit_up / max(limit_down, 1)
        if not daily_df.empty and "pct_chg" in daily_df.columns:
            up = int((daily_df["pct_chg"] > 0).sum())
            up_ratio = up / len(daily_df) if len(daily_df) else float("nan")

    def _add(key: str, msg: str, pct: float) -> None:
        tech.append(msg)
        plain.append(_risk_plain_message(key, pct, msg))

    hist_down = _history_before(metrics_cache, trade_date, "limit_down", PERCENTILE_WINDOW)
    hist_up = _history_before(metrics_cache, trade_date, "limit_up", PERCENTILE_WINDOW)
    hist_ratio = _history_before(metrics_cache, trade_date, "up_ratio", PERCENTILE_WINDOW)
    hist_lspread = _history_before(metrics_cache, trade_date, "limit_spread", PERCENTILE_WINDOW)
    hist_lratio = _history_before(metrics_cache, trade_date, "limit_ratio", PERCENTILE_WINDOW)
    hist_amt = _history_before(metrics_cache, trade_date, "market_amount_yi", PERCENTILE_WINDOW)

    if limit_down > 0:
        pct = _percentile_rank(float(limit_down), hist_down)
        if not np.isnan(pct) and pct >= th["limit_down_high"]:
            _add("limit_down_high", f"跌停P250={pct:.0f}（{limit_down}家）", pct)
    if limit_up > 0:
        pct = _percentile_rank(float(limit_up), hist_up)
        if not np.isnan(pct) and pct <= th["limit_up_low"]:
            _add("limit_up_low", f"涨停P250={pct:.0f}（{limit_up}家）", pct)
    if not np.isnan(up_ratio):
        pct = _percentile_rank(up_ratio, hist_ratio)
        if not np.isnan(pct) and pct <= th["up_ratio_low"]:
            _add("up_ratio_low", f"上涨比例P250={pct:.0f}（{up_ratio:.1%}）", pct)
    if not np.isnan(limit_spread):
        pct = _percentile_rank(limit_spread, hist_lspread)
        if not np.isnan(pct) and pct <= th["limit_spread_low"]:
            _add("limit_spread_low", f"涨跌停差P250={pct:.0f}（{int(limit_spread):+d}）", pct)
    if not np.isnan(limit_ratio):
        pct = _percentile_rank(limit_ratio, hist_lratio)
        if not np.isnan(pct) and pct <= th["limit_ratio_low"]:
            _add("limit_ratio_low", f"涨跌停比P250={pct:.0f}（{limit_ratio:.1f}）", pct)
    if not np.isnan(amount_yi):
        pct = _percentile_rank(amount_yi, hist_amt)
        if not np.isnan(pct) and pct >= th["market_amount_high"]:
            _add("market_amount_high", f"成交额P250={pct:.0f}（{amount_yi:,.0f}亿）", pct)

    sh = index_dfs.get(PRIMARY_INDEX, pd.DataFrame())
    if not sh.empty and {"high", "low", "open", "close"}.issubset(sh.columns):
        sub = sh[sh["trade_date"].astype(str) <= trade_date].copy()
        sub["shadow_ratio"] = sub.apply(_upper_shadow_ratio, axis=1)
        shadow_hist = pd.to_numeric(sub["shadow_ratio"], errors="coerce").dropna()
        if len(shadow_hist) >= 2:
            today_shadow = float(shadow_hist.iloc[-1])
            hist_shadow = shadow_hist.iloc[:-1].tail(PERCENTILE_WINDOW)
            pct = _percentile_rank(today_shadow, hist_shadow)
            if not np.isnan(pct) and pct >= th["upper_shadow_high"]:
                _add("upper_shadow_high", f"上证上影比P250={pct:.0f}", pct)

    return tech, plain


def _fetch_sw_l1_meta(pro) -> Tuple[List[str], Dict[str, str]]:
    for src in ("SW2021", "SW2014"):
        try:
            df = pro.index_classify(level="L1", src=src)
            if df is not None and not df.empty and "index_code" in df.columns:
                codes = df["index_code"].astype(str).tolist()
                name_map = dict(zip(df["index_code"].astype(str), df["industry_name"].astype(str)))
                return codes, name_map
        except Exception:
            continue
    return [], {}


def _sector_streak_positive(df: pd.DataFrame, streak_days: int) -> bool:
    if df is None or df.empty or "pct_change" not in df.columns:
        return False
    tail = df.sort_values("trade_date").tail(streak_days)
    if len(tail) < streak_days:
        return False
    return bool((pd.to_numeric(tail["pct_change"], errors="coerce") > 0).all())


def score_hot_sector_persistence(
    pro,
    trade_date: str,
    top_n: int = HOT_SECTOR_TOP_N,
    streak_days: int = HOT_SECTOR_STREAK_DAYS,
) -> FactorScore:
    codes, name_map = _fetch_sw_l1_meta(pro)
    if not codes:
        return FactorScore("热点持续性", 0.0, float(CORE_FACTOR_WEIGHT), False, "无申万一级行业列表")

    end = pd.Timestamp(trade_date)
    start = (end - pd.Timedelta(days=streak_days * 4 + 30)).strftime("%Y%m%d")
    day_pct: List[Tuple[str, str, float]] = []
    series_cache: Dict[str, pd.DataFrame] = {}

    for code in codes:
        try:
            df = pro.sw_daily(ts_code=code, start_date=start, end_date=trade_date)
        except Exception:
            continue
        if df is None or df.empty or "pct_change" not in df.columns:
            continue
        df = df.sort_values("trade_date")
        series_cache[code] = df
        sub = df[df["trade_date"].astype(str) <= trade_date]
        if sub.empty:
            continue
        pct = float(pd.to_numeric(sub.iloc[-1]["pct_change"], errors="coerce"))
        if np.isnan(pct):
            continue
        day_pct.append((code, name_map.get(code, code), pct))

    if not day_pct:
        return FactorScore("热点持续性", 0.0, float(CORE_FACTOR_WEIGHT), False, "无行业涨跌幅数据")

    day_pct.sort(key=lambda x: x[2], reverse=True)
    top_sectors = day_pct[:top_n]
    strong: List[str] = []
    weak: List[str] = []
    for code, name, pct in top_sectors:
        ok = _sector_streak_positive(series_cache.get(code, pd.DataFrame()), streak_days)
        tag = f"{name}({pct:+.2f}%)"
        (strong if ok else weak).append(tag)

    n_ok = len(strong)
    score = CORE_FACTOR_WEIGHT * (n_ok / top_n)
    passed = n_ok == top_n
    rank_text = " > ".join(f"{n}({p:+.2f}%)" for _, n, p in top_sectors)
    detail = (
        f"涨幅前{top_n}: {rank_text}; 连续{streak_days}日强势 {n_ok}/{top_n} "
        f"[强势: {', '.join(strong) if strong else '无'}; 未满足: {', '.join(weak) if weak else '无'}]"
    )
    return FactorScore("热点持续性", round(score, 1), float(CORE_FACTOR_WEIGHT), passed, detail)


def compute_market_temperature(
    trade_date: Optional[str] = None,
    pro=None,
    *,
    warm_cache: bool = False,
) -> TemperatureResult:
    """
    V2.2 核心五因子（各 20 分）+ 涨跌停情绪（10 分辅助，P250 因子组）
    风险信号全部百分位化（无固定涨跌停家数门槛）
    """
    if pro is None:
        pro = _get_tushare_pro()
    if pro is None:
        raise RuntimeError("未配置 TuShare token")

    td = resolve_trade_date(pro, trade_date)
    metrics_cache = ensure_metrics_cache(pro, td, warm=warm_cache)
    breadth_stats = breadth_history_stats(metrics_cache, td)

    index_dfs = {code: fetch_index_daily(pro, code, td) for code in INDEX_CODES}
    sh_df = index_dfs.get(PRIMARY_INDEX, pd.DataFrame())
    daily_df = fetch_market_daily(pro, td)

    factors: List[FactorScore] = [
        score_index_above_ma(index_dfs, 20, td),
        score_index_above_ma(index_dfs, 60, td),
        score_volume_factor_group(sh_df, metrics_cache, td),
        score_market_breadth(metrics_cache, td, daily_df),
        score_hot_sector_persistence(pro, td),
    ]

    total = sum(f.score for f in factors)
    sentiment = score_limit_sentiment(metrics_cache, td, pro=pro)

    risk_signals, risk_plain = detect_risk_signals(pro, td, index_dfs, metrics_cache, daily_df)
    risk_penalty = 0.0
    if len(risk_signals) >= 2:
        risk_penalty = min(30.0, 10.0 * (len(risk_signals) - 1))
        total = max(0.0, total - risk_penalty)

    position_pct, position_label = _score_to_position(total)

    result = TemperatureResult(
        trade_date=td,
        total_score=round(total, 1),
        position_pct=position_pct,
        position_label=position_label,
        factors=factors,
        risk_signals=risk_signals,
        risk_penalty=risk_penalty,
        extra={
            "sentiment": sentiment,
            "model_version": "V2.3" if os.path.isfile(CALIBRATION_JSON_PATH) else "V2.2",
            "percentile_window": PERCENTILE_WINDOW,
            "percentile_window_long": PERCENTILE_WINDOW_LONG,
            "report_time": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
            "index_weights": INDEX_WEIGHTS,
            "metrics_cache_rows": len(metrics_cache),
            "breadth_days_250": breadth_stats.get("breadth_days_250", 0),
            "breadth_days_500": breadth_stats.get("breadth_days_500", 0),
            "risk_signals_plain": risk_plain,
            "calibration_loaded": os.path.isfile(CALIBRATION_JSON_PATH),
        },
    )
    plain = build_plain_diagnosis(result)
    result.extra["plain"] = plain
    return result


def result_to_dict(result: TemperatureResult) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "report_time": result.extra.get("report_time", ""),
        "model_version": result.extra.get("model_version", "V2.2"),
        "trade_date": result.trade_date,
        "total_score": result.total_score,
        "position_pct": result.position_pct,
        "position_label": result.position_label,
        "risk_penalty": result.risk_penalty,
        "risk_signal_count": len(result.risk_signals),
        "risk_signals": " | ".join(result.risk_signals),
        "risk_signals_plain": " | ".join(result.extra.get("risk_signals_plain") or []),
        "metrics_cache_rows": result.extra.get("metrics_cache_rows", 0),
        "breadth_days_250": result.extra.get("breadth_days_250", 0),
        "breadth_days_500": result.extra.get("breadth_days_500", 0),
    }
    for f in result.factors:
        key = f.name.replace(" ", "_")
        row[f"score_{key}"] = f.score
        row[f"pass_{key}"] = f.passed
        row[f"detail_{key}"] = f.detail
    sent = result.extra.get("sentiment")
    if isinstance(sent, FactorScore):
        row["score_涨跌停情绪"] = sent.score
        row["detail_涨跌停情绪"] = sent.detail
    plain = result.extra.get("plain")
    if isinstance(plain, PlainDiagnosis):
        row["诊断_一句话"] = plain.headline
        row["诊断_市场基调"] = plain.mood
        row["诊断_市场快照"] = " | ".join(s.strip() for s in plain.market_snapshot)
        row["诊断_操作建议"] = " | ".join(plain.action_hints)
    return row


def print_result(result: TemperatureResult) -> None:
    report_time = result.extra.get("report_time", "")
    version = result.extra.get("model_version", "V2.2")
    plain = result.extra.get("plain")
    if not isinstance(plain, PlainDiagnosis):
        plain = build_plain_diagnosis(result)

    print("=" * 60)
    print(f"市场温度计 - 每日仓位报告 ({version})")
    print("=" * 60)
    if report_time:
        print(f"报告时间: {report_time}")
    print(f"数据交易日: {result.trade_date}")
    print(f"综合得分: {result.total_score} / 100")
    print(f"建议仓位: {result.position_pct:.0f}% ({result.position_label})")
    print()
    print("【一句话结论】")
    print(f"  {plain.headline}")
    print()
    print("【市场快照】（不用看指标也能读懂）")
    for line in plain.market_snapshot:
        print(line)
    print()
    print("【操作建议】")
    for i, hint in enumerate(plain.action_hints, 1):
        print(f"  {i}. {hint}")
    print()
    print("-" * 60)
    print("以下为技术指标明细（供进阶参考）")
    print("仓位档位: 0-20空仓 | 20-40=20% | 40-60=40% | 60-80=70% | 80-100=100%")
    cache_rows = result.extra.get("metrics_cache_rows", 0)
    b250 = result.extra.get("breadth_days_250", 0)
    b500 = result.extra.get("breadth_days_500", 0)
    if cache_rows:
        print(f"历史缓存: {cache_rows} 个交易日 | 广度样本 P250={b250} P500={b500}")
        if result.extra.get("calibration_loaded"):
            print(f"仓位映射: 已加载回测校准 {CALIBRATION_JSON_PATH}")
        if b250 < PERCENTILE_WINDOW:
            print(f"提示: 广度 P250 样本不足 {PERCENTILE_WINDOW} 日，可运行 --warm-cache 补齐")
    if result.risk_signals:
        print(f"\n风险信号 ({len(result.risk_signals)} 项, 扣分 {result.risk_penalty}):")
        plain_risks = result.extra.get("risk_signals_plain") or []
        for i, s in enumerate(result.risk_signals):
            line = f"  - {s}"
            if i < len(plain_risks) and plain_risks[i]:
                line += f"\n    -> {plain_risks[i]}"
            print(line)
    print("\n因子明细:")
    for f in result.factors:
        mark = "Y" if f.passed else "N"
        print(f"  [{mark}] {f.name}: {f.score}/{f.max_score}")
        print(f"       {f.detail}")
    sent = result.extra.get("sentiment")
    if isinstance(sent, FactorScore):
        print(f"\n辅助情绪: {sent.score}/{sent.max_score} - {sent.detail}")


def main() -> None:
    parser = argparse.ArgumentParser(description="市场温度计 V2.3 - 每日 CLI 仓位报告")
    parser.add_argument("--trade-date", default=None, help="交易日 YYYYMMDD；默认取最近有数据的交易日")
    parser.add_argument(
        "--out-csv",
        default=DEFAULT_OUT_CSV,
        help=f"输出 CSV，默认 {DEFAULT_OUT_CSV}；传 none 跳过保存",
    )
    parser.add_argument("--no-csv", action="store_true", help="不写入 CSV（仅终端报告）")
    parser.add_argument(
        "--rebuild-cache",
        action="store_true",
        help="删除并重建 market_metrics_cache.csv",
    )
    parser.add_argument(
        "--warm-cache",
        action="store_true",
        help="补齐 P250 窗口内广度历史（首次建议与 --rebuild-cache 联用）",
    )
    args = parser.parse_args()

    if not _get_tushare_token():
        print("未配置 TuShare token。请设置 config.settings.DATA_CONFIG['tushare_token'] 或环境变量 TUSHARE_TOKEN")
        return

    if args.rebuild_cache and os.path.isfile(METRICS_CACHE_PATH):
        os.remove(METRICS_CACHE_PATH)
        print(f"已删除缓存: {METRICS_CACHE_PATH}")

    result = compute_market_temperature(
        trade_date=args.trade_date,
        warm_cache=args.warm_cache or args.rebuild_cache,
    )
    print_result(result)

    if not args.no_csv and str(args.out_csv).lower() != "none":
        out = os.path.abspath(args.out_csv)
        pd.DataFrame([result_to_dict(result)]).to_csv(out, index=False, encoding="utf-8-sig")
        print(f"\n报告已保存: {out}")


if __name__ == "__main__":
    main()

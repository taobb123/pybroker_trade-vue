# -*- coding: utf-8 -*-
"""用日线计算波动率、动能、流动性的原始描述变量。"""
from __future__ import annotations

import numpy as np
import pandas as pd


def price_raw_frame(
    panel: pd.DataFrame,
    *,
    industry_name: pd.Series | None = None,
    hs300_ret60: float | None = None,
    circ_mv: pd.Series | None = None,
) -> pd.DataFrame:
    """
    panel 列：symbol, date, close, ret, vol, amount。
    ret 为小数收益率。amount 为千元，circ_mv 为万元。
    截面取每只股票最后一个交易日。
    """
    if panel is None or panel.empty:
        return pd.DataFrame()
    work = panel.copy()
    work["symbol"] = work["symbol"].astype(str).str[-6:].str.zfill(6)
    work["date"] = pd.to_datetime(work["date"])
    work["close"] = pd.to_numeric(work["close"], errors="coerce")
    work["ret"] = pd.to_numeric(work["ret"], errors="coerce")
    work["vol"] = pd.to_numeric(work["vol"], errors="coerce")
    work["amount"] = pd.to_numeric(work["amount"], errors="coerce")
    work = work.dropna(subset=["symbol", "date", "close"])
    work = work.sort_values(["symbol", "date"])
    rows: list[dict] = []
    for symbol, group in work.groupby("symbol", sort=False):
        rows.append(_one_symbol(str(symbol), group))
    out = pd.DataFrame(rows).set_index("symbol")
    if out.empty:
        return out
    _add_relative(out, industry_name, hs300_ret60)
    _add_amount_to_float(out, circ_mv)
    return out


def _one_symbol(symbol: str, group: pd.DataFrame) -> dict:
    close = group["close"].to_numpy(dtype=float)
    ret = group["ret"].to_numpy(dtype=float)
    vol = group["vol"].to_numpy(dtype=float)
    amount = group["amount"].to_numpy(dtype=float)
    row = {"symbol": symbol, "date": group["date"].iloc[-1]}
    row["20日收益率标准差"] = _std(ret, 20)
    row["60日收益率标准差"] = _std(ret, 60)
    row["120日收益率标准差"] = _std(ret, 120)
    std60 = row["60日收益率标准差"]
    row["年化波动率"] = std60 * np.sqrt(252.0) if std60 == std60 else np.nan
    row["20日下行波动率"] = _downside(ret, 20)
    row["60日下行波动率"] = _downside(ret, 60)
    row["最大回撤"] = _max_drawdown(close, 250)
    var, cvar = _var_cvar(ret, 60)
    row["VaR"] = var
    row["CVaR"] = cvar
    row["20日收益率"] = _total_return(close, 20)
    row["60日收益率"] = _total_return(close, 60)
    row["120日收益率"] = _total_return(close, 120)
    row["250日收益率"] = _total_return(close, 250)
    row["股价/20日MA"] = _price_to_ma(close, 20)
    row["股价/60日MA"] = _price_to_ma(close, 60)
    row["股价/120日MA"] = _price_to_ma(close, 120)
    row["20日平均成交量"] = _mean(vol, 20)
    row["60日平均成交量"] = _mean(vol, 60)
    row["20日平均成交额"] = _mean(amount, 20)
    row["60日平均成交额"] = _mean(amount, 60)
    row["Amihud非流动性"] = _amihud(ret, amount, 20)
    return row


def _std(ret: np.ndarray, window: int) -> float:
    sample = ret[-window:]
    sample = sample[np.isfinite(sample)]
    if len(sample) < max(10, window // 2):
        return np.nan
    return float(np.std(sample, ddof=0))


def _downside(ret: np.ndarray, window: int) -> float:
    sample = ret[-window:]
    sample = sample[np.isfinite(sample)]
    if len(sample) < max(10, window // 2):
        return np.nan
    loss = np.minimum(sample, 0.0)
    return float(np.sqrt(np.mean(loss ** 2)))


def _max_drawdown(close: np.ndarray, window: int) -> float:
    sample = close[-window:]
    sample = sample[np.isfinite(sample) & (sample > 0)]
    if len(sample) < 60:
        return np.nan
    peak = np.maximum.accumulate(sample)
    drop = 1.0 - sample / peak
    return float(np.max(drop))


def _var_cvar(ret: np.ndarray, window: int) -> tuple[float, float]:
    sample = ret[-window:]
    sample = sample[np.isfinite(sample)]
    if len(sample) < max(20, window // 2):
        return np.nan, np.nan
    cutoff = float(np.quantile(sample, 0.05))
    tail = sample[sample <= cutoff]
    var = -cutoff
    cvar = -float(np.mean(tail)) if len(tail) else np.nan
    return var, cvar


def _total_return(close: np.ndarray, window: int) -> float:
    sample = close[np.isfinite(close) & (close > 0)]
    if len(sample) <= window:
        return np.nan
    start = float(sample[-1 - window])
    end = float(sample[-1])
    if start <= 0:
        return np.nan
    return end / start - 1.0


def _price_to_ma(close: np.ndarray, window: int) -> float:
    sample = close[-window:]
    sample = sample[np.isfinite(sample) & (sample > 0)]
    if len(sample) < max(10, window // 2):
        return np.nan
    mean = float(np.mean(sample))
    if mean <= 0:
        return np.nan
    return float(sample[-1] / mean)


def _mean(values: np.ndarray, window: int) -> float:
    sample = values[-window:]
    sample = sample[np.isfinite(sample)]
    if len(sample) < max(10, window // 2):
        return np.nan
    return float(np.mean(sample))


def _amihud(ret: np.ndarray, amount: np.ndarray, window: int) -> float:
    r = ret[-window:]
    a = amount[-window:]
    ok = np.isfinite(r) & np.isfinite(a) & (a > 0)
    if int(ok.sum()) < max(10, window // 2):
        return np.nan
    return float(np.mean(np.abs(r[ok]) / a[ok]))


def _add_relative(frame: pd.DataFrame, industry_name: pd.Series | None, hs300_ret60: float | None) -> None:
    ret60 = frame["60日收益率"]
    if industry_name is not None and not industry_name.empty:
        names = industry_name.copy()
        names.index = names.index.astype(str).str[-6:].str.zfill(6)
        joined = ret60.to_frame("ret").join(names.rename("industry"), how="left")
        industry_ret = joined.groupby("industry")["ret"].transform("mean")
        frame["股票收益率减行业收益率"] = ret60 - industry_ret
    else:
        frame["股票收益率减行业收益率"] = np.nan
    if hs300_ret60 is not None and hs300_ret60 == hs300_ret60:
        frame["股票收益率减沪深300收益率"] = ret60 - float(hs300_ret60)
    else:
        frame["股票收益率减沪深300收益率"] = np.nan


def _add_amount_to_float(frame: pd.DataFrame, circ_mv: pd.Series | None) -> None:
    if circ_mv is None or circ_mv.empty:
        frame["成交额比流通市值"] = np.nan
        return
    mv = pd.to_numeric(circ_mv, errors="coerce")
    mv.index = mv.index.astype(str).str[-6:].str.zfill(6)
    aligned = mv.reindex(frame.index)
    # 成交额千元，流通市值万元 = 10 千元
    frame["成交额比流通市值"] = frame["20日平均成交额"] / (aligned * 10.0)

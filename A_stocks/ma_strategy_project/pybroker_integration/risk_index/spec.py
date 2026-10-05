# -*- coding: utf-8 -*-
"""风险指数描述变量与方向。↑ 为 +1，↓ 为 -1，方向未定的不进指数。"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Descriptor:
    index: str
    index_label: str
    group: str
    name: str
    sign: int | None
    source: str


def _rows() -> list[Descriptor]:
    vol = "volatility", "波动率"
    mom = "momentum", "动能"
    liq = "liquidity", "流动性"
    gro = "growth", "成长性"
    val = "value", "价值"
    earn = "earnings_volatility", "盈利波动率"
    lev = "leverage", "财务杠杆"
    rows = [
        Descriptor(*vol, "历史价格波动", "20日收益率标准差", 1, "price"),
        Descriptor(*vol, "历史价格波动", "60日收益率标准差", 1, "price"),
        Descriptor(*vol, "历史价格波动", "120日收益率标准差", 1, "price"),
        Descriptor(*vol, "历史价格波动", "年化波动率", 1, "price"),
        Descriptor(*vol, "下行风险", "20日下行波动率", 1, "price"),
        Descriptor(*vol, "下行风险", "60日下行波动率", 1, "price"),
        Descriptor(*vol, "下行风险", "最大回撤", 1, "price"),
        Descriptor(*vol, "尾部风险", "VaR", 1, "price"),
        Descriptor(*vol, "尾部风险", "CVaR", 1, "price"),
        Descriptor(*mom, "价格动能", "20日收益率", 1, "price"),
        Descriptor(*mom, "价格动能", "60日收益率", 1, "price"),
        Descriptor(*mom, "价格动能", "120日收益率", 1, "price"),
        Descriptor(*mom, "价格动能", "250日收益率", 1, "price"),
        Descriptor(*mom, "趋势强度", "股价/20日MA", 1, "price"),
        Descriptor(*mom, "趋势强度", "股价/60日MA", 1, "price"),
        Descriptor(*mom, "趋势强度", "股价/120日MA", 1, "price"),
        Descriptor(*mom, "相对动能", "股票收益率减行业收益率", 1, "price"),
        Descriptor(*mom, "相对动能", "股票收益率减沪深300收益率", 1, "price"),
        Descriptor(*liq, "成交量", "20日平均成交量", -1, "price"),
        Descriptor(*liq, "成交量", "60日平均成交量", -1, "price"),
        Descriptor(*liq, "成交金额", "20日平均成交额", -1, "price"),
        Descriptor(*liq, "成交金额", "60日平均成交额", -1, "price"),
        Descriptor(*liq, "换手", "20日平均换手率", None, "price"),
        Descriptor(*liq, "冲击成本", "Amihud非流动性", 1, "price"),
        Descriptor(*liq, "冲击成本", "成交额比流通市值", -1, "price"),
        Descriptor(*liq, "市场深度", "买卖价差", 1, "unavailable"),
        Descriptor(*gro, "收入增长", "营业收入同比", 1, "fundamental"),
        Descriptor(*gro, "收入增长", "营业收入3年CAGR", 1, "fundamental"),
        Descriptor(*gro, "利润增长", "净利润同比", 1, "fundamental"),
        Descriptor(*gro, "利润增长", "扣非净利润同比", 1, "fundamental"),
        Descriptor(*gro, "利润增长", "净利润3年CAGR", 1, "fundamental"),
        Descriptor(*gro, "盈利增长质量", "EPS同比", 1, "fundamental"),
        Descriptor(*gro, "盈利增长质量", "ROE增长率", 1, "fundamental"),
        Descriptor(*gro, "盈利增长质量", "营业利润增长率", 1, "fundamental"),
        Descriptor(*gro, "预期增长", "未来EPS增长预期", 1, "unavailable"),
        Descriptor(*gro, "预期增长", "未来收入增长预期", 1, "unavailable"),
        Descriptor(*val, "估值", "PE_TTM", 1, "value"),
        Descriptor(*val, "估值", "PB", 1, "value"),
        Descriptor(*val, "估值", "PS_TTM", 1, "value"),
        Descriptor(*val, "估值", "PCF", 1, "fundamental"),
        Descriptor(*val, "股息", "股息率", -1, "value"),
        Descriptor(*val, "EV估值", "EV/EBITDA", 1, "fundamental"),
        Descriptor(*val, "EV估值", "EV/Sales", 1, "fundamental"),
        Descriptor(*val, "盈利收益", "E/P", -1, "value"),
        Descriptor(*earn, "利润波动", "5年净利润标准差", 1, "fundamental"),
        Descriptor(*earn, "利润波动", "3年净利润标准差", 1, "fundamental"),
        Descriptor(*earn, "盈利增长波动", "5年净利润增长率标准差", 1, "fundamental"),
        Descriptor(*earn, "盈利增长波动", "3年净利润增长率标准差", 1, "fundamental"),
        Descriptor(*earn, "收入波动", "5年收入增长率标准差", 1, "fundamental"),
        Descriptor(*earn, "EPS波动", "3年EPS增长率标准差", 1, "fundamental"),
        Descriptor(*earn, "EPS波动", "5年EPS增长率标准差", 1, "fundamental"),
        Descriptor(*earn, "盈利稳定性", "ROE标准差", 1, "fundamental"),
        Descriptor(*earn, "现金流稳定性", "CFO增长率标准差", 1, "fundamental"),
        Descriptor(*lev, "负债", "资产负债率", 1, "fundamental"),
        Descriptor(*lev, "负债", "有息负债率", 1, "fundamental"),
        Descriptor(*lev, "负债", "净负债/EBITDA", 1, "fundamental"),
        Descriptor(*lev, "权益杠杆", "Debt/Equity", 1, "fundamental"),
        Descriptor(*lev, "利息压力", "利息保障倍数", -1, "fundamental"),
        Descriptor(*lev, "利息压力", "EBITDA/利息支出", -1, "fundamental"),
        Descriptor(*lev, "短期偿债", "流动比率", -1, "fundamental"),
        Descriptor(*lev, "短期偿债", "速动比率", -1, "fundamental"),
        Descriptor(*lev, "利率风险", "浮动利率债务占比", 1, "unavailable"),
        Descriptor(*lev, "利率风险", "有息负债/总负债", 1, "fundamental"),
    ]
    return rows


DESCRIPTORS: tuple[Descriptor, ...] = tuple(_rows())
INDEX_LABELS = {
    "volatility": "波动率",
    "momentum": "动能",
    "liquidity": "流动性",
    "growth": "成长性",
    "value": "价值",
    "earnings_volatility": "盈利波动率",
    "leverage": "财务杠杆",
}


def descriptors_for(index: str, *, source: str | None = None) -> list[Descriptor]:
    out = [d for d in DESCRIPTORS if d.index == index and d.sign is not None]
    if source is not None:
        out = [d for d in out if d.source == source]
    return out

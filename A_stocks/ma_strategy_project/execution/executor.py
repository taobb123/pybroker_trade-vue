#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略执行器（基础版）
根据最新信号给出可执行的下单建议（方向+数量）。
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    from ..risk.manager import RiskManager
except Exception:  # pragma: no cover
    from risk.manager import RiskManager


@dataclass
class OrderSuggestion:
    action: str  # BUY/SELL/HOLD
    quantity: int
    price: float
    reason: str


class StrategyExecutor:
    def __init__(self, risk_manager: RiskManager):
        self.risk_manager = risk_manager

    def suggest(self, latest_signal: int, latest_price: float) -> OrderSuggestion:
        if latest_signal == 1:
            qty = self.risk_manager.calc_max_buy_amount(latest_price)
            return OrderSuggestion(action="BUY", quantity=qty, price=latest_price, reason="策略买入信号")
        if latest_signal == -1:
            # 简化：全量卖出由上层根据仓位管理，这里仅给动作
            return OrderSuggestion(action="SELL", quantity=0, price=latest_price, reason="策略卖出信号")
        return OrderSuggestion(action="HOLD", quantity=0, price=latest_price, reason="无新信号")



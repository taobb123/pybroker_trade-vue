#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
风险管理器
提供：
- 仓位控制（基于风险占比或固定资金）
- 止损检查（基于百分比）
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RiskParams:
    max_position_ratio: float = 0.2  # 单笔最大仓位占比（相对总资金）
    stop_loss_percent: float = 0.08  # 止损比例（8%）


class RiskManager:
    def __init__(self, total_capital: float, params: RiskParams | None = None):
        self.total_capital = float(total_capital)
        self.params = params or RiskParams()

    def calc_max_buy_amount(self, price: float) -> int:
        """计算在当前价格下的最大可买股数（不考虑手续费、最小交易单位等）"""
        budget = self.total_capital * self.params.max_position_ratio
        if price <= 0:
            return 0
        return int(budget // price)

    def hit_stop_loss(self, entry_price: float, current_price: float) -> bool:
        """是否触发止损"""
        if entry_price <= 0:
            return False
        drop_pct = (entry_price - current_price) / entry_price
        return drop_pct >= self.params.stop_loss_percent



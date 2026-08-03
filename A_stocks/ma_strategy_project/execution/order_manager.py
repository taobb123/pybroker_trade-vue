#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
订单管理（基础版）
记录本次会话中的下单建议与执行记录。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List
from datetime import datetime


@dataclass
class OrderRecord:
    time: str
    action: str
    symbol: str
    quantity: int
    price: float
    note: str = ""


class OrderManager:
    def __init__(self):
        self.orders: List[OrderRecord] = []

    def add_order(self, action: str, symbol: str, quantity: int, price: float, note: str = "") -> None:
        self.orders.append(OrderRecord(
            time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            action=action,
            symbol=symbol,
            quantity=quantity,
            price=price,
            note=note,
        ))

    def summary(self) -> str:
        if not self.orders:
            return "无订单记录"
        lines = ["本次回测建议订单："]
        for i, o in enumerate(self.orders, 1):
            lines.append(f"  {i}. {o.time} {o.action} {o.symbol} {o.quantity} @ {o.price:.2f} {o.note}")
        return "\n".join(lines)



#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
执行管理器（占位实现）
用于实时场景中根据最新信号给出执行建议。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExecutionAdvice:
    action: str
    reason: str


class ExecutionManager:
    def advise(self, latest_signal: int) -> ExecutionAdvice:
        if latest_signal == 1:
            return ExecutionAdvice(action="BUY", reason="短期均线下穿长期均线（反向策略信号）")
        if latest_signal == -1:
            return ExecutionAdvice(action="SELL", reason="短期均线上穿长期均线（反向策略信号）")
        return ExecutionAdvice(action="HOLD", reason="无新信号")



# -*- coding: utf-8 -*-
"""
因子轮动规格（方案默认）：

- 主 KPI：合成组合月胜率；Rank IC / ICIR 作门禁
- 输出：软权重合成五因子 + 市场温度阶梯仓位缩放总敞口
- MVP：温度分档 × 滚动 ICIR 规则；样本足够时可选轻量 GBM 增量
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Sequence, Tuple

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_INTEG = os.path.dirname(_PKG)

ROTATION_FACTORS: Tuple[str, ...] = ("A", "B", "Q", "M+", "M-")

# 滚动窗口（周）
LOOKBACK_WEEKS: Tuple[int, ...] = (4, 8, 12)
# 权重 EMA 平滑（越大越跟新信号）
WEIGHT_EMA_ALPHA: float = 0.35
# 单因子权重上限 / 下限（下限后仍归一化）
MAX_FACTOR_WEIGHT: float = 0.50
MIN_FACTOR_WEIGHT: float = 0.05
# 规则：ICIR 代理负值按 0 裁切后再加温度偏置
ICIR_FLOOR: float = 0.0
# 轻量 GBM：最少训练样本（周）
GBM_MIN_SAMPLES: int = 36
# GBM 相对规则的混合比例（0=纯规则）
GBM_BLEND: float = 0.35


@dataclass
class RotationSpec:
    factors: Tuple[str, ...] = ROTATION_FACTORS
    lookback_weeks: Tuple[int, ...] = LOOKBACK_WEEKS
    ema_alpha: float = WEIGHT_EMA_ALPHA
    max_weight: float = MAX_FACTOR_WEIGHT
    min_weight: float = MIN_FACTOR_WEIGHT
    icir_floor: float = ICIR_FLOOR
    gbm_min_samples: int = GBM_MIN_SAMPLES
    gbm_blend: float = GBM_BLEND
    use_gbm: bool = True
    # 温度序列：优先历史回测表，缺则用 latest 单点前向填充
    temp_history_csv: str = field(
        default_factory=lambda: os.path.join(_INTEG, "market_temperature_backtest.csv")
    )
    temp_latest_csv: str = field(
        default_factory=lambda: os.path.join(_INTEG, "market_temperature_latest.csv")
    )


def temp_bucket(position_pct: float) -> str:
    """温度仓位分档：low / mid / high。"""
    p = float(position_pct or 0.0)
    if p <= 25:
        return "low"
    if p >= 70:
        return "high"
    return "mid"


# 分档对因子的乘法偏置（再归一化）
TEMP_BIAS = {
    "high": {"A": 1.15, "B": 0.90, "Q": 0.85, "M+": 1.25, "M-": 0.75},
    "mid": {"A": 1.00, "B": 1.00, "Q": 1.00, "M+": 1.00, "M-": 1.00},
    "low": {"A": 0.85, "B": 1.15, "Q": 1.20, "M+": 0.70, "M-": 1.25},
}

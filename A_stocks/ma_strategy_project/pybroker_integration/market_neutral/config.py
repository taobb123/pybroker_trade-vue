# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Sequence, Tuple

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_PKG_DIR)  # pybroker_integration

# 形态门禁：可进多头候选的 state_code
PATTERN_LONG_STATES = frozenset({"entry", "confirming", "trial"})

HEDGE_INDEX = "000905.SH"  # 中证500（日历/兼容）
HEDGE_INDEX_NAME = "中证500"
BENCHMARK_INDEX = "000300.SH"  # 沪深300：净值曲线基准
BENCHMARK_INDEX_NAME = "沪深300"


@dataclass
class MNConfig:
    """MVP 运行配置。"""

    start_date: str = "2025-01-01"
    end_date: str = ""  # 空则用最近交易日
    rebalance: str = "weekly"  # weekly | monthly
    top_n: int = 10  # 兼容旧参数；个股多空以 quantile 为准
    quantile: float = 0.10  # 前/后分位（默认 10%）
    upside_min: float = 0.0  # 旧门禁参数，个股多空排序不再使用
    # 估值 upside 稳健化：截面分位截断 + 硬顶硬底
    upside_winsor_q_low: float = 0.05
    upside_winsor_q_high: float = 0.95
    upside_clip_low: float = -0.80
    upside_clip_high: float = 1.50
    variants: Tuple[str, ...] = ("A", "B", "Q", "M+", "M-")
    initial_cash: float = 1_000_000.0
    commission_rate: float = 0.0003
    # Q 单独调仓频率：monthly | quarterly
    q_rebalance: str = "monthly"
    # Rank IC 前瞻交易日：周频因子默认 5；Q 默认 20
    ic_forward_days: int = 5
    ic_forward_days_q: int = 20
    # 形态评估需要的历史日历天数（对齐 fetch_pattern_entry）
    history_calendar_days: int = 220
    # 观察池历史快照目录（由 fetch_vp_six_combo 写入）
    watch_archive_dir: str = field(
        default_factory=lambda: os.path.join(_PKG_DIR, "archive", "watch_pool")
    )
    use_watch_archive: bool = True  # 调仓日优先用 ≤当日 的归档池
    # 输出
    output_dir: str = field(
        default_factory=lambda: os.path.join(_PKG_DIR, "output")
    )
    latest_output_dir: str = field(
        default_factory=lambda: os.path.join(_PKG_DIR, "output", "latest")
    )
    # 上游路径
    integration_root: str = field(default_factory=lambda: _ROOT)
    pattern_scan_csv: str = field(
        default_factory=lambda: os.path.join(_ROOT, "pattern_entry_scan.csv")
    )
    combo_ids: Sequence[int] = field(default_factory=lambda: (4, 6))

    def resolve_end_date(self) -> str:
        if str(self.end_date or "").strip():
            return str(self.end_date)[:10]
        from datetime import datetime

        return datetime.now().strftime("%Y-%m-%d")


def ensure_sys_path() -> None:
    """保证可 import 同级脚本与 ma_strategy_project.config。"""
    import sys

    root = os.path.dirname(_ROOT)  # ma_strategy_project
    for p in (_ROOT, root):
        if p not in sys.path:
            sys.path.insert(0, p)

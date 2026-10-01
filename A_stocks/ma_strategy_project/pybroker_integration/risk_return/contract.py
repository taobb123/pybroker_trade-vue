# -*- coding: utf-8 -*-
"""M+ / T+3 研究产物的字段契约。改字段必须同时改前端和测试。"""
from __future__ import annotations

SCHEMA_VERSION = "mplus_t3_v1"
FACTOR = "M+"
FACTOR_FIELD = "mud_plus"
FACTOR_NOTE = "现有 mud_plus：0.7×(60日收益/20日波动)的截面分位 + 0.3×量比截面分位"
HOLD_TRADING_DAYS = 3
SAMPLE_STEP_TRADING_DAYS = 3
DEFAULT_N_PATHS = 10_000
DEFAULT_N_TRADES = 100
DEFAULT_SEED = 20261001
SEED_RULE = "base+decile"
PRIOR_ALPHA = 1.0
PRIOR_BETA = 1.0
SMALL_SAMPLE_N = 30
WEALTH_START = 1.0
KELLY_FRACTIONS = (
    (1.0, "100% Kelly"),
    (0.75, "75% Kelly"),
    (0.5, "50% Kelly"),
    (0.25, "25% Kelly"),
)
HISTOGRAM_BINS = 12

NOTES = (
    "条件因子仅为现有 M+（mud_plus）。",
    "持有期为信号日收盘到其后第 3 个交易日收盘。",
    "信号日与 mud_plus 来自市场中性截面 factor_snapshot，不另行重算 M+。",
    "胜率后验使用 Beta(1,1) 先验；收益大于 0 记为胜，其余记为负。",
    "盈亏比与 Kelly 使用后验胜率；蒙特卡洛从该分位历史 T+3 收益中有放回抽样。",
    "Kelly 四档只作研究对照，不写凯利仓位表。",
)

SNAPSHOT_RELATIVE = "market_neutral/output/latest/factor_snapshot.csv"

TOP_LEVEL_KEYS = (
    "schema_version",
    "factor",
    "factor_field",
    "factor_note",
    "hold_trading_days",
    "sample_step_trading_days",
    "sample_source",
    "sample_end",
    "n_rows",
    "n_signal_dates",
    "n_paths",
    "n_trades",
    "seed",
    "seed_rule",
    "prior_alpha",
    "prior_beta",
    "small_sample_n",
    "wealth_start",
    "deciles",
    "notes",
    "created_at",
)

DECILE_KEYS = (
    "decile",
    "label",
    "n",
    "small_sample",
    "mean",
    "median",
    "win_rate",
    "posterior_win_rate",
    "prob_win_rate_gt_half",
    "prob_loss",
    "std",
    "skew",
    "excess_kurtosis",
    "var_95",
    "cvar_95",
    "payoff_b",
    "kelly_raw",
    "kelly_full",
    "histogram",
    "scenarios",
    "note",
)

SCENARIO_KEYS = (
    "name",
    "fraction_of_kelly",
    "position",
    "median_terminal_wealth",
    "p05_terminal_wealth",
    "p25_terminal_wealth",
    "p75_terminal_wealth",
    "p95_terminal_wealth",
    "median_max_drawdown",
    "prob_dd_gt_20",
    "prob_dd_gt_30",
)

# 日常链产物文件名。研究模块即使路径里带 risk_return，也不许写成这些名字。
PROTECTED_OUTPUT_NAMES = frozenset(
    {
        "dc_concept_ma5_scan.csv",
        "dc_concept_ma5_members.csv",
        "vp_six_combo_scan.csv",
        "vp_combo_watch_2.csv",
        "vp_combo_watch_3.csv",
        "vp_combo_watch_4.csv",
        "vp_combo_watch_6.csv",
        "fetch_pattern_entry_symbols.txt",
        "fetch_pattern_entry_symbols_6.txt",
        "fetch_vp_six_combo_symbols.txt",
        "stocks_pool.txt",
        "pattern_entry_scan.csv",
        "pattern_entry_valuation_rank.csv",
        "pattern_entry_q_rank.csv",
        "pattern_entry_mplus_rank.csv",
        "pattern_entry_mplus_growth_rank.csv",
        "pattern_entry_g_rank.csv",
        "pattern_entry_g_growth_rank.csv",
        "pattern_entry_volume_growth_rank.csv",
        "pattern_entry_mminus_rank.csv",
        "pattern_entry_kelly_positions.csv",
        "vp_combo_23_vs_46_long_annual.md",
        "vp_combo_23_vs_46_long_annual.csv",
        "vp_combo_23_mminus_top.csv",
        "vp_combo_23_q_rank.csv",
        "vp_combo_23_q_growth_rank.csv",
        "vp_combo_23_g_rank.csv",
        "vp_combo_23_g_growth_rank.csv",
        "vp_combo_23_valuation_rank.csv",
        "vp_combo_23_kelly_positions.csv",
        "summary.md",
    }
)

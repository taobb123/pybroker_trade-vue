#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
均值回归策略（最小核心功能，单标）

思路：基于布林带/标准差通道的价格回归
- 计算 rolling mean 与 std
- Z 分数 z = (close - mean) / std
- 默认规则（与MA策略一致）：超跌买入，超涨卖出
  - 进场：z <= -entry_z 认为价格偏离过度（超跌），买入
  - 出场：z >= exit_z（默认 0）认为价格回归/超涨，卖出

仅实现多头回归（long-only），与现有 BacktestEngine 兼容。
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from .base import BaseStrategy
try:
    from ..utils.logger import logger  # type: ignore
except Exception:  # pragma: no cover
    from utils.logger import logger  # type: ignore


class MeanReversionStrategy(BaseStrategy):
    def __init__(self, window: int = 20, entry_z: float = 2.0, exit_z: float = 0.0,
                 early_entry_threshold: float = 0.3, enable_early_entry: bool = True,
                 momentum_confirmation: bool = False, reverse_signals: bool = False,
                 name: str = "MeanReversion"):
        """
        初始化均值回归策略
        
        Args:
            window: 滚动窗口大小（默认20）
            entry_z: 进场Z阈值（默认2.0），当Z<=-entry_z时买入
            exit_z: 出场Z阈值（默认0.0），当Z>=exit_z时卖出
            early_entry_threshold: 提前进场阈值（默认0.3），当Z接近-entry_z但未达到时提前买入
            enable_early_entry: 是否启用提前进场（默认True）
            momentum_confirmation: 是否使用动量确认（默认False）
            reverse_signals: 是否反转买卖信号（默认False），True时：Z<=-entry_z卖出，Z>=exit_z买入
            name: 策略名称
        """
        super().__init__(name=f"{name}_{window}_{entry_z}_{exit_z}")
        self.window = window
        self.entry_z = float(entry_z)
        self.exit_z = float(exit_z)
        self.early_entry_threshold = float(early_entry_threshold)
        self.enable_early_entry = enable_early_entry
        self.momentum_confirmation = momentum_confirmation
        self.reverse_signals = reverse_signals
        
        logger.info(f"初始化{self.name}策略: 窗口={window}, 进场Z={entry_z}, 出场Z={exit_z}, "
                   f"提前进场={'启用' if enable_early_entry else '禁用'}, 阈值={early_entry_threshold}, "
                   f"信号反转={'是' if reverse_signals else '否'}")

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:  # type: ignore[override]
        """
        生成交易信号
        
        策略逻辑（默认：超跌买入，超涨卖出，与MA策略一致）：
        - 计算均值和标准差，Z分数 = (价格 - 均值) / 标准差
        - Z <= -entry_z（超跌）→ 买入信号(1)
        - Z >= exit_z（回归/超涨）→ 卖出信号(-1)
        
        反转模式（reverse_signals=True）：
        - Z <= -entry_z（超跌）→ 卖出信号(-1)（反向策略）
        - Z >= exit_z（回归）→ 买入信号(1)（反向策略）
        """
        if not self.validate_data(data):
            raise ValueError("数据验证失败")

        df = data.copy().sort_values('date').reset_index(drop=True)

        # 计算均值、标准差、Z 分数
        df['mr_mean'] = df['close'].rolling(self.window, min_periods=1).mean()
        df['mr_std'] = df['close'].rolling(self.window, min_periods=1).std(ddof=0)
        # 修复pandas FutureWarning：使用赋值而不是inplace操作
        df['mr_std'] = df['mr_std'].replace(0, np.nan)
        df['z'] = (df['close'] - df['mr_mean']) / df['mr_std']
        df['z'] = df['z'].fillna(0)

        # 初始化信号列
        df['signal'] = 0
        df['early_signal'] = 0  # 提前信号标记

        # 计算价格变化率（用于动量确认）
        if self.momentum_confirmation:
            df['price_change'] = df['close'].pct_change()
            df['momentum'] = df['price_change'].rolling(window=3, min_periods=1).sum()
            df['momentum'] = df['momentum'].fillna(0)
            # 买入需要负动量（价格下跌），卖出需要正动量（价格上涨）
            momentum_confirm_buy = df['momentum'] < 0
            momentum_confirm_sell = df['momentum'] > 0
        else:
            momentum_confirm_buy = pd.Series([True] * len(df), index=df.index)
            momentum_confirm_sell = pd.Series([True] * len(df), index=df.index)

        # 标准进场条件：z <= -entry_z
        entry_idx = df['z'] <= -self.entry_z
        
        # 提前进场条件：Z接近-entry_z但未达到（提前0.3个Z分数）
        if self.enable_early_entry:
            early_entry_z = -self.entry_z + self.early_entry_threshold
            # 提前买入：Z在[early_entry_z, -entry_z]区间，且Z正在下降（价格继续下跌）
            z_change = df['z'].diff()
            early_entry_idx = (
                (df['z'] <= early_entry_z) & 
                (df['z'] > -self.entry_z) &
                (z_change < 0)  # Z正在下降，价格继续下跌
            )
            df.loc[early_entry_idx, 'early_signal'] = 1
        else:
            early_entry_idx = pd.Series([False] * len(df), index=df.index)
        
        # 出场条件：z >= exit_z（默认0）
        exit_idx = df['z'] >= self.exit_z
        
        # 提前出场条件：Z接近exit_z但未达到，且价格已回归
        if self.enable_early_entry:
            early_exit_z = self.exit_z - self.early_entry_threshold
            z_change = df['z'].diff()
            # 提前卖出：Z在[exit_z - threshold, exit_z]区间，且Z正在上升（价格继续上涨）
            early_exit_idx = (
                (df['z'] >= early_exit_z) & 
                (df['z'] < self.exit_z) &
                (z_change > 0)  # Z正在上升，价格继续上涨
            )
            df.loc[early_exit_idx, 'early_signal'] = -1
        else:
            early_exit_idx = pd.Series([False] * len(df), index=df.index)

        # 生成买卖信号（long-only）
        # 信号含义：1=买入，-1=卖出，0=无操作
        if self.reverse_signals:
            # 信号反转：entry（超跌）-> 卖出，exit（回归）-> 买入
            df.loc[entry_idx & momentum_confirm_buy, 'signal'] = -1  # entry（超跌）-> 卖出（反向）
            df.loc[exit_idx & momentum_confirm_sell, 'signal'] = 1   # exit（回归）-> 买入（反向）
        else:
            # 正向策略：entry（超跌）-> 买入，exit（回归）-> 卖出
            df.loc[entry_idx & momentum_confirm_buy, 'signal'] = 1  # entry（超跌）-> 买入
            df.loc[exit_idx & momentum_confirm_sell, 'signal'] = -1   # exit（回归）-> 卖出
        
        # 如果启用提前信号且没有标准信号，使用提前信号
        if self.enable_early_entry:
            early_buy_mask = (df['early_signal'] == 1) & (df['signal'] == 0)
            early_sell_mask = (df['early_signal'] == -1) & (df['signal'] == 0)
            
            if self.reverse_signals:
                # 信号反转：提前entry -> 实际卖出，提前exit -> 实际买入
                if self.momentum_confirmation:
                    df.loc[early_buy_mask & momentum_confirm_buy, 'signal'] = -1  # 提前entry -> 实际卖出
                    df.loc[early_sell_mask & momentum_confirm_sell, 'signal'] = 1  # 提前exit -> 实际买入
                else:
                    df.loc[early_buy_mask, 'signal'] = -1  # 提前entry -> 实际卖出
                    df.loc[early_sell_mask, 'signal'] = 1  # 提前exit -> 实际买入
            else:
                # 正向策略：提前entry -> 实际买入，提前exit -> 实际卖出
                if self.momentum_confirmation:
                    df.loc[early_buy_mask & momentum_confirm_buy, 'signal'] = 1  # 提前entry -> 实际买入
                    df.loc[early_sell_mask & momentum_confirm_sell, 'signal'] = -1  # 提前exit -> 实际卖出
                else:
                    df.loc[early_buy_mask, 'signal'] = 1  # 提前entry -> 实际买入
                    df.loc[early_sell_mask, 'signal'] = -1  # 提前exit -> 实际卖出

        # 计算 positions（仅在信号变化时产生交易）
        # 使用更精确的逻辑：只标记信号从0变为非0，或从非0变为0，或从1变为-1，或从-1变为1
        df['positions'] = 0
        prev_signal = df['signal'].shift(1).fillna(0)
        curr_signal = df['signal']
        
        # 买入：signal从0或-1变为1（开仓或重新开仓）
        buy_mask = ((prev_signal == 0) | (prev_signal == -1)) & (curr_signal == 1)
        df.loc[buy_mask, 'positions'] = 1
        
        # 卖出：signal从0或1变为-1（平仓或重新平仓）
        sell_mask = ((prev_signal == 0) | (prev_signal == 1)) & (curr_signal == -1)
        df.loc[sell_mask, 'positions'] = -1
        
        # 确保不会同时出现买入和卖出（清除冲突）
        # 如果同一天同时满足买入和卖出条件，优先卖出（平仓优先）
        conflict_mask = buy_mask & sell_mask
        if conflict_mask.any():
            logger.warning(f"发现 {conflict_mask.sum()} 个信号冲突点，优先处理为卖出")
            df.loc[conflict_mask, 'positions'] = -1  # 冲突时优先卖出

        early_count = sum(df['early_signal'] != 0)
        logger.info(
            f"均值回归信号生成完成: 窗口={self.window}, 进场Z={self.entry_z}, 出场Z={self.exit_z}; "
            f"买入信号={int((df['signal']==1).sum())}, 卖出信号={int((df['signal']==-1).sum())}, "
            f"提前信号={early_count}"
        )

        return df



#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双均线策略实现

默认规则（与MR策略一致）：超跌买入，超涨卖出
- 短期均线下穿长期均线：买入（超跌买入）
- 短期均线上穿长期均线：卖出（超涨卖出）

反转模式（reverse_signals=True）：
- 短期均线上穿长期均线：买入（反向策略）
- 短期均线下穿长期均线：卖出（反向策略）
"""

import pandas as pd  # type: ignore
import numpy as np  # type: ignore
from decimal import Decimal, ROUND_HALF_UP
from .base import BaseStrategy
try:
    from ..utils.logger import logger  # type: ignore
except Exception:  # pragma: no cover
    from utils.logger import logger  # type: ignore


class MovingAverageStrategy(BaseStrategy):
    """双均线策略"""
    
    def __init__(self, short_window: int = 5, long_window: int = 20, 
                 early_signal_threshold: float = 2.0, enable_early_signals: bool = True,
                 volume_confirmation: bool = False, reverse_signals: bool = False, 
                 name: str = "MovingAverage"):
        """
        初始化均线策略
        
        Args:
            short_window: 短期均线周期（默认5）
            long_window: 长期均线周期（默认20）
            early_signal_threshold: 提前信号阈值（默认2.0，即2%），当两条均线距离小于此百分比时提前发出信号
            enable_early_signals: 是否启用提前信号（默认True）
            volume_confirmation: 是否使用成交量确认（默认False）
            reverse_signals: 是否反转买卖信号（默认False），True时：上穿买入，下穿卖出（反向策略）
            name: 策略名称
        """
        super().__init__(name=f"{name}_{short_window}_{long_window}")
        self.short_window = short_window
        self.long_window = long_window
        self.early_signal_threshold = early_signal_threshold
        self.enable_early_signals = enable_early_signals
        self.volume_confirmation = volume_confirmation
        self.reverse_signals = reverse_signals
        
        if short_window >= long_window:
            raise ValueError(f"短期均线周期({short_window})必须小于长期均线周期({long_window})")
        
        logger.info(f"初始化{self.name}策略: 短期={short_window}天, 长期={long_window}天, "
                   f"提前信号={'启用' if enable_early_signals else '禁用'}, 阈值={early_signal_threshold}, "
                   f"信号反转={'是' if reverse_signals else '否'}")
    
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        生成交易信号
        
        策略逻辑（默认：超跌买入，超涨卖出，与MR策略一致）：
        - 计算短期和长期均线
        - 短期均线下穿长期均线 → 买入信号(1)（超跌买入）
        - 短期均线上穿长期均线 → 卖出信号(-1)（超涨卖出）
        - 其他情况 → 持有信号(0)
        
        反转模式（reverse_signals=True）：
        - 短期均线上穿长期均线 → 买入信号(1)（反向策略）
        - 短期均线下穿长期均线 → 卖出信号(-1)（反向策略）
        
        Args:
            data: 包含date, open, high, low, close, volume列的DataFrame
        
        Returns:
            DataFrame: 添加了ma_short, ma_long, signal, positions列
        """
        # 验证数据
        if not self.validate_data(data):
            raise ValueError("数据验证失败")
        
        # 复制数据，避免修改原始数据
        df = data.copy()
        
        # 确保日期排序
        df = df.sort_values('date').reset_index(drop=True)
        
        # 检查数据量是否足够
        if len(df) < self.long_window:
            logger.warning(f"数据量({len(df)})少于长期均线周期({self.long_window})，无法计算信号")
            df['ma_short'] = np.nan
            df['ma_long'] = np.nan
            df['signal'] = 0
            df['positions'] = 0
            return df
        
        # 计算短期和长期均线
        # 为了与行情软件口径更一致：
        # 1) 先按“商业四舍五入(ROUND_HALF_UP)”把每根收盘价保留到分
        # 2) 再做简单移动平均
        # 3) 最终结果也按“ROUND_HALF_UP”保留到分
        def round_half_up_2(x: float) -> float:
            return float(Decimal(str(x)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))

        close_half_up = df['close'].apply(round_half_up_2)
        ma_s = close_half_up.rolling(window=self.short_window, min_periods=1).mean()
        ma_l = close_half_up.rolling(window=self.long_window, min_periods=1).mean()
        df['ma_short'] = ma_s.apply(round_half_up_2)
        df['ma_long'] = ma_l.apply(round_half_up_2)
        
        # 初始化信号列
        df['signal'] = 0
        df['early_signal'] = 0  # 提前信号标记

        # 使用向量化方式判定交叉（提高性能与可读性）
        ma_s = df['ma_short']
        ma_l = df['ma_long']
        prev_ma_s = ma_s.shift(1)
        prev_ma_l = ma_l.shift(1)

        # 计算均线距离百分比（用于提前信号）
        # early_signal_threshold 是百分比值（如2.0表示2%）
        ma_distance_pct = abs(ma_s - ma_l) / ma_l * 100
        ma_distance_pct = ma_distance_pct.fillna(0)
        
        # 计算均线趋势（短期相对长期的变化率）
        ma_trend = (ma_s - ma_l) / ma_l * 100
        ma_trend = ma_trend.fillna(0)
        prev_ma_trend = ma_trend.shift(1).fillna(0)

        # 统一策略：下穿 → 买入(1)（超跌买入），上穿 → 卖出(-1)（超涨卖出）
        # 与MR策略保持一致：超跌买入，超涨卖出
        cross_up = (prev_ma_s <= prev_ma_l) & (ma_s > ma_l)  # 上穿：短期均线上穿长期均线
        cross_down = (prev_ma_s >= prev_ma_l) & (ma_s < ma_l)  # 下穿：短期均线下穿长期均线

        # 提前买入信号：均线接近但未交叉，且趋势向下（接近下穿）
        if self.enable_early_signals:
            # 提前买入：均线距离小于阈值，且短期均线正在接近长期均线下方（趋势向下，接近下穿）
            early_buy = (
                (ma_distance_pct <= self.early_signal_threshold) &  # 距离接近
                (ma_trend < prev_ma_trend) &  # 趋势向下（价格走弱）
                (ma_s < ma_l) &  # 尚未交叉（短期低于长期）
                (prev_ma_s < prev_ma_l)  # 之前也是短期低于长期
            )
            
            # 提前卖出：均线距离小于阈值，且短期均线正在接近长期均线上方（趋势向上，接近上穿）
            early_sell = (
                (ma_distance_pct <= self.early_signal_threshold) &  # 距离接近
                (ma_trend > prev_ma_trend) &  # 趋势向上（价格走强）
                (ma_s > ma_l) &  # 尚未交叉（短期高于长期）
                (prev_ma_s > prev_ma_l)  # 之前也是短期高于长期
            )
            
            df.loc[early_buy, 'early_signal'] = 1   # 提前买入预警（接近下穿，超跌）
            df.loc[early_sell, 'early_signal'] = -1  # 提前卖出预警（接近上穿，超涨）

        # 成交量确认（可选）
        if self.volume_confirmation and 'volume' in df.columns:
            # 计算成交量移动平均
            volume_ma = df['volume'].rolling(window=5, min_periods=1).mean()
            volume_ratio = df['volume'] / volume_ma
            volume_ratio = volume_ratio.fillna(1.0)
            
            # 买入信号需要成交量放大（ratio > 1.2）
            # 卖出信号也需要成交量放大（ratio > 1.2）
            volume_confirm_buy = volume_ratio > 1.2
            volume_confirm_sell = volume_ratio > 1.2
        else:
            volume_confirm_buy = pd.Series([True] * len(df), index=df.index)
            volume_confirm_sell = pd.Series([True] * len(df), index=df.index)

        # 标准交叉信号（优先于提前信号）
        # 默认规则：超跌买入，超涨卖出（与MR策略一致）
        # 注意：上穿和下穿是互斥的，不会同时发生
        if self.reverse_signals:
            # 信号反转：上穿 → 买入(1)，下穿 → 卖出(-1)（反向策略）
            # 上穿和下穿互斥，不会冲突
            df.loc[cross_up & volume_confirm_buy, 'signal'] = 1   # 上穿：买入（反向）
            df.loc[cross_down & volume_confirm_sell, 'signal'] = -1  # 下穿：卖出（反向）
        else:
            # 默认策略：下穿 → 买入(1)（超跌买入），上穿 → 卖出(-1)（超涨卖出）
            # 上穿和下穿互斥，不会冲突
            df.loc[cross_down & volume_confirm_buy, 'signal'] = 1   # 下穿：买入（超跌买入）
            df.loc[cross_up & volume_confirm_sell, 'signal'] = -1  # 上穿：卖出（超涨卖出）
        
        # 如果启用提前信号且没有标准信号，使用提前信号
        if self.enable_early_signals:
            # 在提前信号位置，如果没有标准信号，则使用提前信号
            early_buy_mask = (df['early_signal'] == 1) & (df['signal'] == 0)
            early_sell_mask = (df['early_signal'] == -1) & (df['signal'] == 0)
            
            if self.reverse_signals:
                # 信号反转：提前买入信号 -> 实际卖出，提前卖出信号 -> 实际买入
                if self.volume_confirmation and 'volume' in df.columns:
                    df.loc[early_buy_mask & volume_confirm_buy, 'signal'] = -1  # 提前买入信号 -> 实际卖出
                    df.loc[early_sell_mask & volume_confirm_sell, 'signal'] = 1  # 提前卖出信号 -> 实际买入
                else:
                    df.loc[early_buy_mask, 'signal'] = -1  # 提前买入信号 -> 实际卖出
                    df.loc[early_sell_mask, 'signal'] = 1  # 提前卖出信号 -> 实际买入
            else:
                # 默认策略：提前买入信号 -> 实际买入（接近下穿），提前卖出信号 -> 实际卖出（接近上穿）
                if self.volume_confirmation and 'volume' in df.columns:
                    df.loc[early_buy_mask & volume_confirm_buy, 'signal'] = 1  # 提前买入信号 -> 实际买入（超跌买入）
                    df.loc[early_sell_mask & volume_confirm_sell, 'signal'] = -1  # 提前卖出信号 -> 实际卖出（超涨卖出）
                else:
                    df.loc[early_buy_mask, 'signal'] = 1  # 提前买入信号 -> 实际买入（超跌买入）
                    df.loc[early_sell_mask, 'signal'] = -1  # 提前卖出信号 -> 实际卖出（超涨卖出）
        
        # 计算持仓变化（positions）
        # positions 表示何时开仓/平仓，只保留实际交易动作
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
        logger.info(f"信号生成完成(反向): 买入信号={sum(df['signal']==1)}, 卖出信号={sum(df['signal']==-1)}, "
                   f"提前信号={early_count}")
        
        return df
    
    def get_latest_signal(self, data: pd.DataFrame) -> dict:
        """
        获取最新交易信号
        
        Args:
            data: 包含signals的DataFrame（已调用generate_signals）
        
        Returns:
            dict: 包含信号信息的字典
        """
        if 'signal' not in data.columns:
            data = self.generate_signals(data)
        
        if data.empty:
            return {'signal': 0, 'message': '无数据'}
        
        latest = data.iloc[-1]
        signal_value = latest['signal']
        
        signal_map = {
            1: '买入',
            -1: '卖出',
            0: '持有'
        }
        
        return {
            'signal': int(signal_value),
            'action': signal_map.get(signal_value, '未知'),
            'date': latest['date'],
            'price': float(latest['close']),
            'ma_short': float(latest.get('ma_short', 0)),
            'ma_long': float(latest.get('ma_long', 0))
        }




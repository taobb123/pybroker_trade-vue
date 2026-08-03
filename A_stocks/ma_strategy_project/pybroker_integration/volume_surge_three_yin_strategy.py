"""
放量阳线（相对约半年均量）后连续三根逐级缩量阴线建仓；
持仓期间累计出现 2 根阳线（不要求连续）则清仓。

说明：
- 「半年」按约 126 个交易日均量作为基准（可调 HALF_YEAR_BARS）。
- 「明显放大」用当日成交量 > 半年均量 × SURGE_VOLUME_MULT（可调）。
- 形态在「当前已完成 bar」上判定：-4 为放量阳线，-3/-2/-1 为三根阴线；
  信号当根下单，实际成交时刻遵循 StrategyConfig 的 buy_delay / sell_delay。
"""

import os
import sys

import numpy as np
import pybroker
from pybroker import Strategy, StrategyConfig

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from pybroker_integration.custom_data_source import create_custom_data_source

pybroker.enable_data_source_cache("volume_surge_three_yin")

# 约半年交易日；放量基准为放量阳线「之前」这若干根 K 的成交量均值（不含放量当日）
HALF_YEAR_BARS = 126
# 相对半年均量认定为「明显放大」的倍数
SURGE_VOLUME_MULT = 1.5

# 至少需要：1 根放量阳 + 3 根阴 + 半年窗口（均量在 [-130:-4]）
MIN_BARS = 4 + HALF_YEAR_BARS


def volume_surge_three_yin_exec(ctx):
    """单标的执行：空仓找形态买入；持仓累计两根阳线卖出。"""
    session = ctx.session
    vol = ctx.volume
    close = ctx.close
    open_ = ctx.open

    if ctx.bars < MIN_BARS:
        return

    pos = ctx.long_pos()
    if pos is not None:
        if close[-1] > open_[-1]:
            session["yang_bars"] = session.get("yang_bars", 0) + 1
        if session.get("yang_bars", 0) >= 2:
            ctx.sell_all_shares()
            session["yang_bars"] = 0
        return

    # 空仓：避免仍有未成交买单时重复发信号
    if tuple(ctx.pending_orders()):
        return

    window = vol[-(HALF_YEAR_BARS + 4) : -4]
    if window.size != HALF_YEAR_BARS or not np.all(np.isfinite(window)):
        return
    mean_vol = float(np.mean(window))
    if mean_vol <= 0 or not np.isfinite(mean_vol):
        return

    # 放量阳线（bar -4）
    if not (close[-4] > open_[-4]):
        return
    if not (vol[-4] > SURGE_VOLUME_MULT * mean_vol):
        return
    if not np.isfinite(vol[-4]) or vol[-4] <= 0:
        return

    # 连续三根阴线（bar -3, -2, -1）
    for k in (-3, -2, -1):
        if not (close[k] < open_[k]):
            return

    # 逐级递减缩量：vol[-3] > vol[-2] > vol[-1]
    if not (vol[-3] > vol[-2] > vol[-1]):
        return
    # 三根阴线成交量均小于放量阳线当日量
    surge_v = vol[-4]
    if not (vol[-3] < surge_v and vol[-2] < surge_v and vol[-1] < surge_v):
        return

    session["yang_bars"] = 0
    ctx.buy_shares = ctx.calc_target_shares(1.0)


if __name__ == "__main__":
    config = StrategyConfig(initial_cash=500_000)
    data_source = create_custom_data_source()
    strategy = Strategy(data_source, "20230101", "20260430", config)
    strategy.add_execution(volume_surge_three_yin_exec, ["601636"])
    result = strategy.backtest(warmup=MIN_BARS, calc_bootstrap=True)
    print(result.metrics_df)

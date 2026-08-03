import os
import sys

import numpy as np
import pandas as pd
import pybroker
from numba import njit


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

pybroker.enable_caches('walkforward_strategy')

from pybroker_integration.indicators import cmma, cmma_20, buy_cmma_cross

# 构建一个模型，使用 20 天的 CMMA 预测第二天的回报

from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score


# 我们创建一个 train_slr 函数来训练 LinearRegression 模型
def train_slr(symbol, train_data, test_data):
    # Train
    # Previous day close prices.
    train_prev_close = train_data['close'].shift(1)
    # Calculate daily returns.
    train_daily_returns = (train_data['close'] - train_prev_close) / train_prev_close
    # Predict next day's return.
    train_data['pred'] = train_daily_returns.shift(-1)
    train_data = train_data.dropna()
    # Train the LinearRegession model to predict the next day's return
    # given the 20-day CMMA.
    X_train = train_data[['cmma_20']]
    y_train = train_data[['pred']]
    model = LinearRegression()
    model.fit(X_train, y_train)

    # Test
    test_prev_close = test_data['close'].shift(1)
    test_daily_returns = (test_data['close'] - test_prev_close) / test_prev_close
    test_data['pred'] = test_daily_returns.shift(-1)
    test_data = test_data.dropna()
    X_test = test_data[['cmma_20']]
    y_test = test_data[['pred']]
    # Make predictions from test data.
    y_pred = model.predict(X_test)
    # Print goodness of fit.
    r2 = r2_score(y_test, np.squeeze(y_pred))
    print(symbol, f'R^2={r2}')

    # Return the trained model and columns to use as input data.
    return model, ['cmma_20']


from pybroker import Strategy, StrategyConfig
from pybroker_integration.custom_data_source import create_custom_data_source
model_slr = pybroker.model('slr', train_slr, indicators=[cmma_20])
config = StrategyConfig(bootstrap_sample_size=100)
custom_data_source = create_custom_data_source()

# 使用自定义数据源，日期格式为 YYYYMMDD，股票代码使用 A 股代码
strategy = Strategy(custom_data_source, '20220101', '20250101', config)
strategy.add_execution(None, ['600570', '600690', '601939'], models=model_slr)
# print(strategy.backtest(train_size=0.5))



# 从我们之前训练的 LinearRegression 模型生成买卖信号的交易策略
def hold_long(ctx):
    if not ctx.long_pos():
        # Buy if the next bar is predicted to have a positive return:
        if ctx.preds('slr')[-1] > 0:
            ctx.buy_shares = 100
    else:
        # Sell if the next bar is predicted to have a negative return:
        if ctx.preds('slr')[-1] < 0:
            ctx.sell_shares = 100

strategy.clear_executions()
strategy.add_execution(hold_long, ['000408'], models=model_slr)

result = strategy.walkforward(
    warmup=20,
    windows=3,
    train_size=0.5,
    lookahead=1,
    calc_bootstrap=True
)



print(result.metrics_df)
# result.bootstrap.drawdown_conf






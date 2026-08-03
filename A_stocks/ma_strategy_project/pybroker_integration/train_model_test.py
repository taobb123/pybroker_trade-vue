import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score
from numba import njit

import os
import sys
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pybroker
from pybroker import ExecContext, Strategy, StrategyConfig, indicator, enable_caches
from pybroker_integration.custom_data_source import create_custom_data_source
# 1. 启用缓存以加快数据和模型的加载速度
enable_caches('walkforward_strategy')

# 2. 定义自定义指标 (例如: 收盘价减去移动平均线, CMMA)
def cmma(bar_data, lookback):
    """计算收盘价减去移动平均线 (CMMA)"""
    
    @njit  # 使用 Numba JIT 加速计算
    def vec_cmma(values, lookback):
        # 初始化结果数组
        n = len(values)
        out = np.array([np.nan for _ in range(n)])
        
        # 从 lookback 开始计算所有 bar
        for i in range(lookback, n):
            # 计算移动平均
            ma = 0
            for j in range(i - lookback, i):
                ma += values[j]
            ma /= lookback
            # 用当前值减去移动平均
            out[i] = values[i] - ma
        return out
    
    # 使用收盘价计算
    return vec_cmma(bar_data.close, lookback)

cmma_20 = indicator('cmma_20', cmma, lookback=20)

# 3. 定义模型训练函数
def train_slr(symbol, train_data, test_data):
    # 准备训练数据
    train_prev_close = train_data['close'].shift(1)
    train_daily_returns = (train_data['close'] - train_prev_close) / train_prev_close
    train_data['pred'] = train_daily_returns.shift(-1)
    train_data = train_data.dropna()

    X_train = train_data[['cmma_20']]
    y_train = train_data[['pred']]
    
    # 训练模型
    model = LinearRegression()
    model.fit(X_train, y_train)

    # 准备测试数据 (PyBroker 会在内部处理测试数据的准备，这里仅作示例展示逻辑)
    test_prev_close = test_data['close'].shift(1)
    test_daily_returns = (test_data['close'] - test_prev_close) / test_prev_close
    test_data['pred'] = test_daily_returns.shift(-1)
    test_data = test_data.dropna()
    X_test = test_data[['cmma_20']]
    y_test = test_data[['pred']]
    y_pred = model.predict(X_test)
    
    r2 = r2_score(y_test, np.squeeze(y_pred))
    print(symbol, f'R^2={r2}') # 打印 R^2 分数

    # 返回训练好的模型和所需的输入特征列名
    return model, ['cmma_20']

# 4. 定义交易执行函数 (基于模型预测信号)
def exec_fn(ctx: ExecContext):
    # 获取模型对下一个时间窗口的预测值
    prediction = ctx.preds('slr')[-1]
    
    # 根据预测值实施策略
    if not ctx.long_pos():
        # 如果没有持仓，预测上涨时买入
        if prediction > 0:
            ctx.buy_shares = ctx.calc_target_shares(1.0)  # 全仓买入
    else:
        # 如果已有持仓，预测下跌时卖出
        if prediction < 0:
            ctx.sell_all_shares()  # 清空持仓

# 5. 初始化 Strategy 对象并运行前向分析
if __name__ == '__main__':
    # 从自定义数据源获取数据
    custom_data_source = create_custom_data_source()
    
    # 注册模型：使用 pybroker.model() 注册训练函数
    model_slr = pybroker.model('slr', train_slr, indicators=[cmma_20])
    
    # 定义策略配置
    config = StrategyConfig(bootstrap_sample_size=100)
    
    # 定义策略 (使用自定义数据源)
    strategy = Strategy(custom_data_source, start_date='20220101', end_date='20251101', config=config)
    
    # 添加模型训练和交易执行
    # 传入注册后的模型对象
    strategy.add_execution(exec_fn, ['600690', '601939'], models=model_slr)
    
    # 运行前向分析
    # 使用 5 个时间窗口，每个窗口 50/50 的训练/测试数据分割，前瞻期为 1 bar
    result = strategy.walkforward(
        warmup=20, # 预热期，确保指标有足够数据
        windows=5, 
        train_size=0.5, 
        lookahead=1, # 预测未来 1 个 bar，防止数据泄露
        calc_bootstrap=True # 使用引导程序计算更可靠的指标
    )
    
    # 打印和分析结果
    print(result.metrics_df)
    print(result.bootstrap.conf_intervals) # 示例：打印夏普比率的置信区间

    # 保存交易信息到csv
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_filename = 'train_model_test.csv'
    csv_file = os.path.join(script_dir, base_filename)
    trades_df = result.trades
    trades_df.to_csv(csv_file, index=False, encoding='utf-8-sig')

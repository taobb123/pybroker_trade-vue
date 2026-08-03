import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score
from numba import njit
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

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
# 用于存储预测值和价格数据的全局变量
prediction_data = {}  # {symbol: {'dates': [], 'predictions': [], 'prices': []}}

def exec_fn(ctx: ExecContext):
    # 获取模型对下一个时间窗口的预测值
    preds = ctx.preds('slr')
    if isinstance(preds, (list, np.ndarray)) and len(preds) > 0:
        prediction = float(preds[-1])
    else:
        prediction = float(preds) if preds is not None else 0.0
    
    # 记录预测值和当前价格用于绘图
    symbol = ctx.symbol
    if symbol not in prediction_data:
        prediction_data[symbol] = {'dates': [], 'predictions': [], 'prices': []}
    
    # 记录日期、预测收益率和当前收盘价
    # 尝试获取当前日期
    try:
        # 优先使用 ctx.dt 获取当前日期
        if hasattr(ctx, 'dt') and ctx.dt is not None:
            current_date = ctx.dt
        # 其次尝试从 ctx.data 获取
        elif hasattr(ctx, 'data') and ctx.data is not None and len(ctx.data) > 0:
            current_date = ctx.data.index[-1] if hasattr(ctx.data.index, '__getitem__') else None
        else:
            current_date = None
        
        if current_date is not None:
            prediction_data[symbol]['dates'].append(current_date)
        else:
            prediction_data[symbol]['dates'].append(len(prediction_data[symbol]['dates']))
    except:
        # 如果获取日期失败，使用索引
        prediction_data[symbol]['dates'].append(len(prediction_data[symbol]['dates']))
    
    # 确保prediction是标量值
    prediction_data[symbol]['predictions'].append(prediction)
    
    # 确保获取单个价格值（ctx.close可能是数组）
    try:
        if isinstance(ctx.close, (list, np.ndarray)):
            current_price = float(ctx.close[-1]) if len(ctx.close) > 0 else 0.0
        else:
            current_price = float(ctx.close)
    except:
        # 如果ctx.close不可用，尝试从ctx.data获取
        try:
            if hasattr(ctx, 'data') and ctx.data is not None and len(ctx.data) > 0:
                current_price = float(ctx.data['close'].iloc[-1])
            else:
                current_price = 0.0
        except:
            current_price = 0.0
    
    prediction_data[symbol]['prices'].append(current_price)
    
    # 计算并打印模型预测的下一个交易日股价
    # 预测下一个交易日股价 = 当前价格 * (1 + 预测收益率)
    predicted_price = current_price * (1 + prediction) if current_price > 0 else 0.0
    
    # 获取当前日期用于打印
    try:
        # 优先使用 ctx.dt 获取当前日期
        if hasattr(ctx, 'dt') and ctx.dt is not None:
            current_date = ctx.dt
        # 其次尝试从 ctx.data 获取
        elif hasattr(ctx, 'data') and ctx.data is not None and len(ctx.data) > 0:
            current_date = ctx.data.index[-1] if hasattr(ctx.data.index, '__getitem__') else None
        else:
            current_date = None
        
        # 格式化日期
        if current_date is not None:
            if isinstance(current_date, (pd.Timestamp, datetime)):
                print_date = current_date.strftime('%Y-%m-%d')
            else:
                print_date = str(current_date)
        else:
            print_date = 'N/A'
    except Exception as e:
        print_date = 'N/A'
    
    # 打印预测的下一个交易日股价
    print(f"[{symbol}] 当前日期: {print_date}, 当前价格: {current_price:.2f}, 预测收益率: {prediction:.4f}, 预测下一个交易日股价: {predicted_price:.2f}")
    
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
    # ========== 配置参数 ==========
    # 日期配置
    start_date = '20220101'  # 开始日期（格式：YYYYMMDD）
    end_date = '20251205'    # 结束日期（格式：YYYYMMDD）
    
    # 股票列表配置
    symbols = ['000408']     # 要交易的股票代码列表
    
    # ========== 执行策略 ==========
    # 清空之前的预测数据
    prediction_data.clear()
    
    # 从自定义数据源获取数据
    custom_data_source = create_custom_data_source()
    
    # 注册模型：使用 pybroker.model() 注册训练函数
    model_slr = pybroker.model('slr', train_slr, indicators=[cmma_20])
    
    # 定义策略配置
    config = StrategyConfig(initial_cash=50000, bootstrap_sample_size=100)  # 初始资金10万元
    
    # 定义策略 (使用自定义数据源)
    strategy = Strategy(custom_data_source, start_date=start_date, end_date=end_date, config=config)
    
    # 添加模型训练和交易执行
    # 传入注册后的模型对象
    strategy.add_execution(exec_fn, symbols, models=model_slr)
    
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
    print(result.bootstrap.drawdown_conf)  #自助法检查策略的最大回撤

    # 保存交易信息到csv
    script_dir = os.path.dirname(os.path.abspath(__file__))
    base_filename = 'train_model_test.csv'
    csv_file = os.path.join(script_dir, base_filename)
    trades_df = result.trades
    trades_df.to_csv(csv_file, index=False, encoding='utf-8-sig')
    
    # 6. 绘制预测价格和实际价格对比图
    print("\n开始绘制预测价格和实际价格对比图...")
    
    # 获取实际价格数据（使用上面定义的 symbols 变量）
    for symbol in symbols:
        if symbol not in prediction_data or len(prediction_data[symbol]['dates']) == 0:
            print(f"警告: {symbol} 没有预测数据，跳过绘图")
            continue
        
        # 准备数据
        dates = prediction_data[symbol]['dates']
        
        # 确保转换为numpy数组时所有元素都是标量
        predictions_list = prediction_data[symbol]['predictions']
        prices_list = prediction_data[symbol]['prices']
        
        # 清理数据，确保所有元素都是标量
        predictions_clean = [float(p) if not isinstance(p, (list, np.ndarray)) else float(p[-1] if len(p) > 0 else 0.0) for p in predictions_list]
        prices_clean = [float(p) if not isinstance(p, (list, np.ndarray)) else float(p[-1] if len(p) > 0 else 0.0) for p in prices_list]
        
        predictions = np.array(predictions_clean, dtype=float)  # 预测的收益率
        actual_prices = np.array(prices_clean, dtype=float)  # 实际价格
        
        # 计算预测价格：基于前一日价格和预测收益率
        predicted_prices = np.zeros_like(actual_prices)
        predicted_prices[0] = actual_prices[0]  # 第一个价格使用实际价格
        
        for i in range(1, len(actual_prices)):
            # 预测价格 = 前一日实际价格 * (1 + 预测收益率)
            predicted_prices[i] = actual_prices[i-1] * (1 + predictions[i-1])
        
        # 处理日期格式
        try:
            if isinstance(dates[0], (int, float)) or not isinstance(dates[0], (pd.Timestamp, datetime)):
                # 如果dates是索引，尝试使用portfolio的日期
                try:
                    portfolio_dates = result.portfolio.index
                    if len(portfolio_dates) >= len(dates):
                        dates = portfolio_dates[:len(dates)]
                    else:
                        # 使用策略的开始日期
                        dates = pd.date_range(start='2022-01-01', periods=len(dates), freq='D')
                except:
                    # 使用策略的开始日期（从 start_date 转换格式）
                    start_date_str = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
                    dates = pd.date_range(start=start_date_str, periods=len(dates), freq='D')
            else:
                dates = pd.to_datetime(dates)
        except Exception as e:
            print(f"日期处理警告: {e}, 使用默认日期范围")
            # 使用策略的开始日期（从 start_date 转换格式）
            start_date_str = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
            dates = pd.date_range(start=start_date_str, periods=len(dates), freq='D')
        
        # 创建图表
        fig, ax = plt.subplots(figsize=(14, 8))
        
        # 绘制实际价格曲线
        ax.plot(dates, actual_prices, label='实际价格', linewidth=2, color='blue', alpha=0.7)
        
        # 绘制预测价格曲线
        ax.plot(dates, predicted_prices, label='预测价格', linewidth=2, color='red', alpha=0.7, linestyle='--')
        
        # 设置图表属性
        ax.set_title(f'{symbol} - 预测价格 vs 实际价格对比', fontsize=16, fontweight='bold', pad=20)
        ax.set_xlabel('日期', fontsize=12)
        ax.set_ylabel('价格 (元)', fontsize=12)
        ax.legend(loc='best', fontsize=11)
        ax.grid(True, alpha=0.3, linestyle='--')
        
        # 格式化日期显示
        if len(dates) > 0:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
            ax.xaxis.set_major_locator(mdates.AutoDateLocator())
            plt.xticks(rotation=45)
        
        plt.tight_layout()
        
    #     # 保存图表
    #     plot_filename = f'{symbol}_prediction_vs_actual.png'
    #     plot_path = os.path.join(script_dir, plot_filename)
    #     plt.savefig(plot_path, dpi=300, bbox_inches='tight')
    #     print(f"图表已保存: {plot_path}")
        
    #     # 显示图表（可选，如果是在交互式环境中）
    #     # plt.show()
    #     plt.close()
    
    # print("绘图完成！")

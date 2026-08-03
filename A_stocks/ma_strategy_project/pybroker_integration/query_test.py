# 导入所需的库和模块
import os
import sys
import pybroker as pb
from pybroker import Strategy, ExecContext
from pybroker.ext.data import AKShare

# ========== 代理配置 ==========
# 如果遇到代理连接错误，可以尝试以下方法：
# 方法1: 禁用代理（推荐，如果不需要代理）
os.environ.pop('HTTP_PROXY', None)
os.environ.pop('HTTPS_PROXY', None)
os.environ.pop('http_proxy', None)
os.environ.pop('https_proxy', None)

# 方法2: 如果需要使用代理，取消下面的注释并配置正确的代理地址
# os.environ['HTTP_PROXY'] = 'http://your-proxy:port'
# os.environ['HTTPS_PROXY'] = 'http://your-proxy:port'

# 方法3: 配置 requests 库不使用代理
try:
    import requests
    # 禁用 requests 的代理
    session = requests.Session()
    session.trust_env = False  # 不信任环境变量中的代理设置
except ImportError:
    pass

print("="*70)
print("PyBroker AKShare 数据源测试")
print("="*70)

# 定义全局参数 "stock_code"（股票代码）、"percent"（持仓百分比）和 "stop_profit_pct"（止盈百分比）
pb.param(name='stock_code', value='600000')
pb.param(name='percent', value=1)
pb.param(name='stop_loss_pct', value=10)
pb.param(name='stop_profit_pct', value=10)

# 初始化 AKShare 数据源
try:
    print("\n[1/4] 初始化 AKShare 数据源...")
    akshare = AKShare()
    print("✓ AKShare 初始化成功")
except Exception as e:
    print(f"✗ AKShare 初始化失败: {e}")
    sys.exit(1)

# 使用 AKShare 数据源查询特定股票（由 "stock_code" 参数指定）在指定日期范围内的数据
try:
    print(f"\n[2/4] 查询股票数据: {pb.param(name='stock_code')} (2020-01-31 至 2023-02-28)...")
    df = akshare.query(symbols=[pb.param(name='stock_code')], start_date='20200131', end_date='20230228')
    if df is not None and not df.empty:
        print(f"✓ 数据查询成功，共 {len(df)} 条记录")
    else:
        print("✗ 数据查询返回空结果")
        sys.exit(1)
except Exception as e:
    print(f"✗ 数据查询失败: {e}")
    print("\n可能的解决方案：")
    print("1. 检查网络连接")
    print("2. 如果使用代理，请检查代理配置是否正确")
    print("3. 尝试禁用代理（代码中已自动禁用）")
    print("4. 稍后重试（可能是临时网络问题）")
    print("5. 使用备用数据源（见下面的备用方案）")
    sys.exit(1)


# 定义交易策略：如果当前没有持有该股票，则买入股票，并设置止盈点位
def buy_with_stop_loss(ctx: ExecContext):
    pos = ctx.long_pos()
    if not pos:
        # 计算目标股票数量，根据 "percent" 参数确定应购买的股票数量
        ctx.buy_shares = ctx.calc_target_shares(pb.param(name='percent'))
        ctx.hold_bars = 100
    else:
        ctx.sell_shares = pos.shares
        # 设置止盈点位，根据 "stop_profit_pct" 参数确定止盈点位
        ctx.stop_profit_pct = pb.param(name='stop_profit_pct')


# 创建策略配置，初始资金为 500000
try:
    print(f"\n[3/4] 创建策略配置...")
    my_config = pb.StrategyConfig(initial_cash=500000)
    print("✓ 策略配置创建成功")
    
    # 使用配置、数据源、起始日期、结束日期，以及刚才定义的交易策略创建策略对象
    print(f"\n[4/4] 创建策略对象并执行回测...")
    strategy = Strategy(akshare, start_date='20200131', end_date='20230228', config=my_config)
    # 添加执行策略，设置股票代码和要执行的函数
    strategy.add_execution(fn=buy_with_stop_loss, symbols=[pb.param(name='stock_code')])
    
    # 执行回测，并打印出回测结果的度量值（四舍五入到小数点后四位）
    result = strategy.backtest()
    print("✓ 回测完成")
    print("\n" + "="*70)
    print("回测结果:")
    print("="*70)
    print(result.metrics_df.round(4))
    print("="*70)
    
except Exception as e:
    print(f"✗ 回测执行失败: {e}")
    import traceback
    print("\n详细错误信息:")
    traceback.print_exc()
    sys.exit(1)
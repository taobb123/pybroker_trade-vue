#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全局配置文件
"""

# 回测默认参数
BACKTEST_CONFIG = {
    'initial_capital': 100000,      # 初始资金（元）
    'commission': 0.001,            # 手续费率（0.1%）
    'slippage': 0.0,                # 滑点（Phase 2使用）
}

# 策略默认参数
STRATEGY_DEFAULT_PARAMS = {
    'moving_average': {
        'short_window': 5,          # 短期均线周期
        'long_window': 20,           # 长期均线周期
    }
}

# 数据配置
DATA_CONFIG = {
    'data_source_priority': ['database', 'api'],  # 数据源优先级：先数据库后API
    'min_data_points': 60,          # 最小数据点数（用于策略计算）
    'api_preference': 'tushare',    # API偏好：'akshare', 'tushare', 'baostock' 或 'yfinance'
    'tushare_token': 'e433bebb1abbbdb014cbdfd619dfce5f399eeb79442aba1184df6882',           # tushare token（如使用tushare需配置）
    # 可选：覆盖默认回退链（按顺序尝试）。示例：['yfinance','tushare','akshare','baostock']
    # 对ETF代码，'tushare' 会自动切换到 fund_daily。
    # 优先使用 tushare，如果失败则回退到 baostock、akshare、yfinance
    'provider_override': ['tushare', 'baostock', 'akshare', 'yfinance'],
    # 仅当自行调用 utils.tushare_rate_limit.resolve_tushare_rate_limit 时有效；主流程已不做客户端限流
    'tushare_max_requests_per_minute': None,
    'tushare_rate_window_seconds': 60,
}

# 日志配置
LOG_CONFIG = {
    'level': 'INFO',                 # 日志级别：DEBUG, INFO, WARNING, ERROR
    'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    'file_path': 'logs/strategy.log',  # 日志文件路径
}


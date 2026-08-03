#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
开发环境配置
"""

# 数据源配置
DATA_SOURCE = {
    'type': 'tushare',  # 可选: tushare, baostock, akshare
    'timeout': 30,
    'retry_times': 3,
}

# 回测配置
BACKTEST_CONFIG = {
    'initial_cash': 100000,
    'commission': 0.001,
    'slippage': 0.001,
}

# 日志配置
LOG_CONFIG = {
    'level': 'DEBUG',
    'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    'file': 'logs/dev.log',
}

# 缓存配置
CACHE_CONFIG = {
    'enabled': True,
    'cache_dir': 'cache/dev',
    'ttl': 3600,  # 秒
}


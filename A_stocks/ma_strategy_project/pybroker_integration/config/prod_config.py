#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生产环境配置
注意：敏感信息应使用环境变量
"""

import os

# 数据源配置
DATA_SOURCE = {
    'type': os.getenv('DATA_SOURCE_TYPE', 'tushare'),
    'api_key': os.getenv('TUSHARE_API_KEY', ''),
    'timeout': 60,
    'retry_times': 5,
}

# 回测配置
BACKTEST_CONFIG = {
    'initial_cash': 1000000,
    'commission': 0.001,
    'slippage': 0.001,
}

# 日志配置
LOG_CONFIG = {
    'level': 'INFO',
    'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    'file': 'logs/prod.log',
}

# 缓存配置
CACHE_CONFIG = {
    'enabled': True,
    'cache_dir': 'cache/prod',
    'ttl': 7200,  # 秒
}


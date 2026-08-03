#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库配置文件
引用父级db_config.py
"""

import sys
import os

# 添加父级目录到路径
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

try:
    from db_config import DB_CONFIG
    print(f"✓ 已加载数据库配置")
except ImportError:
    print("⚠ 警告：无法导入父级db_config.py，使用默认配置")
    # 备用配置
    DB_CONFIG = {
        'host': '127.0.0.1',
        'port': 3306,
        'user': 'root',
        'password': 'guox123123',
        'database': 'stocks',
        'charset': 'utf8mb4'
    }


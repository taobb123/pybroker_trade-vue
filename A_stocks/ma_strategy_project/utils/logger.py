#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日志工具模块
"""

import logging
import os
from datetime import datetime
try:  # 兼容包内/脚本两种运行方式
    from ..config.settings import LOG_CONFIG  # type: ignore
except Exception:  # pragma: no cover
    from config.settings import LOG_CONFIG  # type: ignore

def setup_logger(name='strategy', log_file=None, level=None):
    """
    设置日志记录器
    
    Args:
        name: 日志记录器名称
        log_file: 日志文件路径（可选）
        level: 日志级别（可选）
    
    Returns:
        logger: 配置好的日志记录器
    """
    logger = logging.getLogger(name)
    
    # 设置日志级别
    log_level = level or LOG_CONFIG.get('level', 'INFO')
    logger.setLevel(getattr(logging, log_level.upper()))
    
    # 避免重复添加处理器
    if logger.handlers:
        return logger
    
    # 创建格式器
    formatter = logging.Formatter(LOG_CONFIG.get('format', 
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    
    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 文件处理器（如果指定了日志文件）
    if log_file:
        # 确保日志目录存在
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
        
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger

# 创建默认日志记录器
logger = setup_logger()






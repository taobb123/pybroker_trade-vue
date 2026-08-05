#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据获取模块
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT in sys.path:
    sys.path.remove(_ROOT)
sys.path.insert(0, _ROOT)
try:
    from path_bootstrap import prefer_ma_strategy_project_root

    prefer_ma_strategy_project_root(__file__)
except Exception:
    pass

from .fetcher import DataFetcher
from .financial_fetcher import FinancialDataFetcher

__all__ = ['DataFetcher', 'FinancialDataFetcher']

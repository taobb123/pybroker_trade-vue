#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工作流入口：市场中性（形态/PE/Q/MUD 个股多空 + Rank IC）。"""
from __future__ import annotations

import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJ = os.path.dirname(_SCRIPT_DIR)
for p in (_SCRIPT_DIR, _PROJ):
    if p not in sys.path:
        sys.path.insert(0, p)

from market_neutral.run import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())

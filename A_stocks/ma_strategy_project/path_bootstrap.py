# -*- coding: utf-8 -*-
"""确保 ma_strategy_project 的 config/data/utils 优先于 pybroker_integration 同名包。"""

from __future__ import annotations

import os
import sys


def prefer_ma_strategy_project_root(file_in_package: str | None = None) -> str:
    """
    将 ma_strategy_project 插到 sys.path 最前，并卸掉错误加载的 config 包。

    file_in_package: 任意位于 ma_strategy_project 下的 __file__（如 data/fetcher.py）。
    """
    if file_in_package:
        root = os.path.dirname(os.path.dirname(os.path.abspath(file_in_package)))
    else:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    if root in sys.path:
        sys.path.remove(root)
    sys.path.insert(0, root)

    cfg = sys.modules.get("config")
    if cfg is not None:
        cfg_file = (getattr(cfg, "__file__", "") or "").replace("\\", "/")
        # 被 pybroker_integration/config 抢占时清掉，迫使重新从 ma_strategy_project 加载
        if "pybroker_integration/config" in cfg_file or cfg_file.endswith(
            "pybroker_integration/config/__init__.py"
        ):
            for key in list(sys.modules):
                if key == "config" or key.startswith("config."):
                    del sys.modules[key]
    return root

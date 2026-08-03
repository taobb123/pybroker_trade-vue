# -*- coding: utf-8 -*-
"""train_model_shift.py / train_model_shift-2.py 共用的股票列表加载。"""

import os
import re
from pathlib import Path


def normalize_a_share_symbol(symbol: str) -> str:
    """统一为 6 位 A 股代码字符串（去后缀、补零），便于 CSV 与配置列表对齐。"""
    raw = str(symbol or "").strip()
    if not raw:
        return raw
    if "." in raw:
        raw = raw.split(".", 1)[0].strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return raw
    if len(digits) >= 6:
        return digits[-6:]
    return digits.zfill(6)


def load_train_model_shift_symbols() -> list[str]:
    """
    默认读取本目录下 config/train_model_shift_symbols.txt（一行一只代码，# 后为注释）。
    可通过环境变量 TRAIN_MODEL_SHIFT_SYMBOLS_FILE 覆盖文件路径。
    """
    default = Path(__file__).resolve().parent / "config" / "train_model_shift_symbols.txt"
    path = Path(os.environ.get("TRAIN_MODEL_SHIFT_SYMBOLS_FILE", str(default)))
    if not path.is_file():
        raise FileNotFoundError(f"股票列表文件不存在: {path}")
    symbols: list[str] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        s = line.split("#", 1)[0].strip()
        if s:
            symbols.append(normalize_a_share_symbol(s))
    if not symbols:
        raise ValueError(f"股票列表为空: {path}")
    return symbols

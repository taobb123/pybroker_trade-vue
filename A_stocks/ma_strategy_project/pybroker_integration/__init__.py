#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PyBroker 集成模块

注意：不要在包导入时拉取 data_provider / DataFetcher。
否则 `from pybroker_integration.xxx` 会先执行本文件，在
`pybroker_integration/config` 抢占 `config` 包名时触发
`ModuleNotFoundError: config.db_config`。
"""

__all__ = [
    "PyBrokerAdapter",
    "convert_strategy_to_pybroker",
    "PyBrokerDataProvider",
]


def __getattr__(name: str):
    if name in ("PyBrokerAdapter", "convert_strategy_to_pybroker"):
        from .adapter import PyBrokerAdapter, convert_strategy_to_pybroker

        return {
            "PyBrokerAdapter": PyBrokerAdapter,
            "convert_strategy_to_pybroker": convert_strategy_to_pybroker,
        }[name]
    if name == "PyBrokerDataProvider":
        from .data_provider import PyBrokerDataProvider

        return PyBrokerDataProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

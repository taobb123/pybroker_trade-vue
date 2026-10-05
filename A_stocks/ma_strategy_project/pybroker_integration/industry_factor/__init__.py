# -*- coding: utf-8 -*-
"""申万一级行业因子。只建暴露并在 M+ 池上观察动量，不改观察池入池规则。"""

from industry_factor.build import (
    assign_unique_industry,
    industry_cap_weights,
    mplus_industry_behavior,
)

__all__ = [
    "assign_unique_industry",
    "industry_cap_weights",
    "mplus_industry_behavior",
]

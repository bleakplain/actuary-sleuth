#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
整改策略模块

提供违规整改策略的接口和实现

文件结构:
- strategy.py: RemediationStrategy接口
- registry.py: RemediationStrategies集合
- waiting_period.py: WaitingPeriodRemediation
- exemption_clause.py: ExemptionClauseRemediation
- insurance_amount.py: InsuranceAmountRemediation
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .strategy import RemediationStrategy

from .registry import RemediationStrategies
from .waiting_period import WaitingPeriodRemediation
from .exemption_clause import ExemptionClauseRemediation
from .insurance_amount import InsuranceAmountRemediation

__all__ = [
    # 策略集合
    'RemediationStrategies',
    # 具体策略
    'WaitingPeriodRemediation',
    'ExemptionClauseRemediation',
    'InsuranceAmountRemediation',
]

# 导出策略接口（仅用于类型检查）
if TYPE_CHECKING:
    __all__.append('RemediationStrategy')


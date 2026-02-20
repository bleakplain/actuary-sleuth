#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
整改策略注册表

管理所有整改策略，根据违规类型选择合适的策略
"""
from typing import Dict, Any, List, Optional

from .strategy import RemediationStrategy
from .waiting_period import WaitingPeriodRemediation
from .exemption_clause import ExemptionClauseRemediation
from .insurance_amount import InsuranceAmountRemediation


class RemediationStrategies:
    """
    整改策略集合

    管理所有整改策略，提供统一的访问接口

    职责：
    1. 管理所有可用的整改策略
    2. 根据违规类型查找合适的策略
    3. 返回具体的整改建议
    """

    def __init__(self):
        """
        初始化策略集合，注册所有可用的整改策略

        策略列表会按照注册顺序进行匹配，优先级高的策略放在前面
        """
        self._strategies: List[RemediationStrategy] = [
            WaitingPeriodRemediation(),
            ExemptionClauseRemediation(),
            InsuranceAmountRemediation(),
        ]

    def find_strategy(self, violation: Dict[str, Any]) -> Optional[RemediationStrategy]:
        """
        根据违规类型查找合适的策略

        Args:
            violation: 违规记录字典

        Returns:
            Optional[RemediationStrategy]: 匹配的策略，如果没有匹配则返回 None
        """
        for strategy in self._strategies:
            if strategy.can_handle(violation):
                return strategy
        return None

    def get_remediation(self, violation: Dict[str, Any]) -> str:
        """
        根据违规类型获取整改建议

        Args:
            violation: 违规记录，包含 description 和 remediation 字段

        Returns:
            str: 整改建议文本
        """
        # 优先使用违规记录中已有的整改建议
        if violation.get('remediation'):
            return violation['remediation']

        # 查找合适的策略并获取整改建议
        strategy = self.find_strategy(violation)
        if strategy:
            return strategy.get_remediation(violation)

        # 没有匹配的策略，返回默认建议
        return '请根据监管要求完善相关条款'

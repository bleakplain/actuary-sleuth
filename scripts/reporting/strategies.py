#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
违规处理策略模块

使用策略模式处理不同类型的违规
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List


class ViolationRemediationStrategy(ABC):
    """违规整改策略基类"""

    @abstractmethod
    def can_handle(self, violation: Dict[str, Any]) -> bool:
        """判断是否可以处理该违规"""
        pass

    @abstractmethod
    def get_remediation(self, violation: Dict[str, Any]) -> str:
        """获取整改建议"""
        pass


class WaitingPeriodStrategy(ViolationRemediationStrategy):
    """等待期违规策略"""

    def can_handle(self, violation: Dict[str, Any]) -> bool:
        description = violation.get('description', '')
        return '等待期' in description

    def get_remediation(self, violation: Dict[str, Any]) -> str:
        description = violation.get('description', '')

        if '过长' in description or '超过' in description:
            return '将等待期调整为90天以内'
        elif '症状' in description or '体征' in description:
            return '删除将等待期内症状或体征作为免责依据的表述'
        elif '突出' in description:
            return '在条款中以加粗或红色字体突出说明等待期'
        return '合理设置等待期长度，确保符合监管规定'


class ExemptionClauseStrategy(ViolationRemediationStrategy):
    """免责条款违规策略"""

    def can_handle(self, violation: Dict[str, Any]) -> bool:
        description = violation.get('description', '')
        return '免责条款' in description or '责任免除' in description

    def get_remediation(self, violation: Dict[str, Any]) -> str:
        description = violation.get('description', '')

        if '不集中' in description:
            return '将免责条款集中在合同显著位置'
        elif '不清晰' in description or '表述不清' in description:
            return '使用清晰明确的语言表述免责情形'
        elif '加粗' in description or '标红' in description or '突出' in description:
            return '使用加粗或红色字体突出显示免责条款'
        elif '免除' in description and '不合理' in description:
            return '删除不合理的免责条款，确保不违反保险法规定'
        return '完善免责条款的表述和展示方式'


class RemediationStrategyHandler:
    """整改策略处理器"""

    def __init__(self):
        self.strategies: List[ViolationRemediationStrategy] = [
            WaitingPeriodStrategy(),
            ExemptionClauseStrategy(),
            # 添加更多策略
        ]

    def get_remediation(self, violation: Dict[str, Any]) -> str:
        """
        获取违规的整改建议

        Args:
            violation: 违规记录

        Returns:
            整改建议
        """
        # 首先尝试使用策略
        for strategy in self.strategies:
            if strategy.can_handle(violation):
                return strategy.get_remediation(violation)

        # 回退到默认建议
        return violation.get('remediation', '请根据具体情况进行整改')

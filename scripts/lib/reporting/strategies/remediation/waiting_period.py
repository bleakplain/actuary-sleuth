#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
等待期违规整改策略

WaitingPeriodRemediation类：处理与等待期相关的违规问题

违规类型：
- 等待期过长
- 等待期内症状/体征免责
- 等待期条款不突出
"""
from typing import Dict, Any, Tuple, List
from .strategy import RemediationStrategy


class WaitingPeriodRemediation(RemediationStrategy):
    """
    等待期整改策略 (Concrete Strategy)

    处理等待期相关的违规问题
    """

    # 关键词到整改建议的映射（使用元组支持多个关键词映射到同一建议）
    REMEDIATION_MAP: List[Tuple[Tuple[str, ...], str]] = [
        (('过长', '超过'), '将等待期调整为90天以内'),
        (('症状', '体征'), '删除将等待期内症状或体征作为免责依据的表述'),
        (('突出',), '在条款中以加粗或红色字体突出说明等待期'),
    ]

    DEFAULT_REMEDIATION = '合理设置等待期长度，确保符合监管规定'

    def can_handle(self, violation: Dict[str, Any]) -> bool:
        """
        判断是否为等待期相关违规

        Args:
            violation: 违规记录字典

        Returns:
            bool: 如果违规描述包含'等待期'则返回 True
        """
        description = violation.get('description', '')
        return '等待期' in description

    def get_remediation(self, violation: Dict[str, Any]) -> str:
        """
        根据等待期违规的具体问题返回整改建议

        Args:
            violation: 违规记录字典

        Returns:
            str: 具体的整改建议
        """
        description = violation.get('description', '')

        # 遍历映射表，查找匹配的关键词
        for keywords, remediation in self.REMEDIATION_MAP:
            if any(kw in description for kw in keywords):
                return remediation

        # 默认建议
        return self.DEFAULT_REMEDIATION

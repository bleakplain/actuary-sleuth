#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
保险金额违规整改策略

InsuranceAmountRemediation类：处理与保险金额相关的违规问题
"""
from typing import Dict, Any, Tuple, List
from .strategy import RemediationStrategy


class InsuranceAmountRemediation(RemediationStrategy):
    """
    保险金额整改策略 (Concrete Strategy)

    处理保险金额相关的违规问题
    """

    # 关键词到整改建议的映射
    REMEDIATION_MAP: List[Tuple[Tuple[str, ...], str]] = [
        (('不规范', '不一致'), '使用规范的保险金额表述，确保与保险法一致'),
    ]

    DEFAULT_REMEDIATION = '明确保险金额的确定方式和计算标准'

    def can_handle(self, violation: Dict[str, Any]) -> bool:
        """
        判断是否为保险金额相关违规

        Args:
            violation: 违规记录字典

        Returns:
            bool: 如果违规描述包含'保险金额'则返回 True
        """
        description = violation.get('description', '')
        category = violation.get('category', '')
        return '保险金额' in description or '保险金额' in category

    def get_remediation(self, violation: Dict[str, Any]) -> str:
        """
        根据保险金额违规的具体问题返回整改建议

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

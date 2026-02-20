#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
免责条款违规整改策略

ExemptionClauseRemediation类：处理与免责条款相关的违规问题

违规类型：
- 免责条款不集中
- 免责条款表述不清晰
- 免责条款未突出显示
- 不合理的免责条款
"""
from typing import Dict, Any, Tuple, List
from .strategy import RemediationStrategy


class ExemptionClauseRemediation(RemediationStrategy):
    """
    免责条款整改策略 (Concrete Strategy)

    处理免责条款相关的违规问题
    """

    # 关键词到整改建议的映射
    REMEDIATION_MAP: List[Tuple[Tuple[str, ...], str]] = [
        (('不集中',), '将免责条款集中在合同显著位置'),
        (('不清晰', '表述不清'), '使用清晰明确的语言表述免责情形'),
        (('加粗', '标红', '突出'), '使用加粗或红色字体突出显示免责条款'),
    ]

    DEFAULT_REMEDIATION = '完善免责条款的表述和展示方式'

    def can_handle(self, violation: Dict[str, Any]) -> bool:
        """
        判断是否为免责条款相关违规

        Args:
            violation: 违规记录字典

        Returns:
            bool: 如果违规描述包含'免责条款'或'责任免除'则返回 True
        """
        description = violation.get('description', '')
        return '免责条款' in description or '责任免除' in description

    def get_remediation(self, violation: Dict[str, Any]) -> str:
        """
        根据免责条款违规的具体问题返回整改建议

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

        # 特殊处理：删除不合理免责条款
        if '免除' in description and '不合理' in description:
            return '删除不合理的免责条款，确保不违反保险法规定'

        # 默认建议
        return self.DEFAULT_REMEDIATION

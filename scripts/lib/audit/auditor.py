#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
合规审核器

负责根据监管规定审核保险产品条款。
"""

import json
import logging
import hashlib
from dataclasses import dataclass
from typing import List, Dict

from lib.common.models import RegulationRecord, RegulationStatus, ProcessingOutcome
from lib.llm_client import BaseLLMClient, LLMClientFactory

logger = logging.getLogger(__name__)


@dataclass
class AuditIssue:
    """单个审核问题"""
    clause: str
    severity: str  # high/medium/low
    regulation: str
    description: str
    suggestion: str


@dataclass
class AuditReport:
    """审核报告"""
    overall_assessment: str  # 通过/有条件通过/不通过
    issues: List[AuditIssue]
    score: int  # 0-100
    summary: str


class ComplianceAuditor:
    """合规审核器"""

    def __init__(self, llm_client: BaseLLMClient = None):
        """
        Args:
            llm_client: LLM 客户端，默认使用 Audit 模型（更高质量）
        """
        self.llm_client = llm_client or LLMClientFactory.get_audit_llm()

    def audit(
        self,
        product_clause: str,
        regulation_record: RegulationRecord,
        regulation_content: str
    ) -> ProcessingOutcome:
        """
        审核产品条款是否符合监管规定

        Args:
            product_clause: 产品条款内容
            regulation_record: 相关法规记录
            regulation_content: 法规内容

        Returns:
            ProcessingOutcome: 审核结果
        """
        try:
            # 使用 LLM 进行合规审核
            audit_result = self._llm_audit(product_clause, regulation_content)

            # 更新记录状态
            regulation_record.status = RegulationStatus.AUDITED

            return ProcessingOutcome(
                success=True,
                regulation_id=self._generate_regulation_id(regulation_record),
                record=regulation_record,
                errors=[],
                warnings=[],
                processor="audit.auditor"
            )

        except Exception as e:
            logger.error(f"合规审核失败: {e}")
            regulation_record.status = RegulationStatus.FAILED
            return ProcessingOutcome(
                success=False,
                regulation_id="",
                record=regulation_record,
                errors=[str(e)],
                warnings=[],
                processor="audit.auditor"
            )

    def _llm_audit(self, product_clause: str, regulation_content: str) -> AuditReport:
        """使用 LLM 进行合规审核"""
        from .prompts import AUDIT_SYSTEM_PROMPT

        prompt = f"""请审核以下产品条款：

【产品条款】
{product_clause}

【相关监管规定】
{regulation_content}
"""

        messages = [
            {'role': 'system', 'content': AUDIT_SYSTEM_PROMPT},
            {'role': 'user', 'content': prompt}
        ]

        try:
            response = self.llm_client.chat(messages)
            result = json.loads(response)

            issues = [
                AuditIssue(**issue) for issue in result.get('issues', [])
            ]

            return AuditReport(
                overall_assessment=result.get('overall_assessment', '不通过'),
                issues=issues,
                score=result.get('score', 0),
                summary=result.get('summary', '')
            )
        except Exception as e:
            logger.error(f"LLM 审核失败: {e}")
            return AuditReport(
                overall_assessment='不通过',
                issues=[],
                score=0,
                summary=f'审核失败: {str(e)}'
            )

    def compare_clauses(
        self,
        product_clause: str,
        regulation_content: str
    ) -> Dict:
        """对比产品条款与监管规定"""
        from .prompts import format_comparison_prompt

        prompt = format_comparison_prompt(product_clause, regulation_content)

        messages = [
            {'role': 'user', 'content': prompt}
        ]

        try:
            response = self.llm_client.chat(messages)
            return json.loads(response)
        except Exception as e:
            logger.error(f"条款对比失败: {e}")
            return {
                'is_compliant': False,
                'differences': [str(e)],
                'missing_points': [],
                'risk_level': 'high'
            }

    def _generate_regulation_id(self, record: RegulationRecord) -> str:
        """生成法规唯一标识"""
        key = f"{record.law_name}_{record.article_number}"
        return hashlib.md5(key.encode()).hexdigest()[:16]

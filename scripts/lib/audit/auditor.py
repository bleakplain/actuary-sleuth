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
from typing import List, Dict, Any, Optional

from lib.common.models import RegulationRecord, RegulationStatus
from lib.llm import BaseLLMClient, LLMClientFactory

logger = logging.getLogger(__name__)

DEFAULT_CATEGORY = "未分类"


@dataclass
class AuditIssue:
    """单个审核问题"""
    clause: str
    severity: str
    dimension: str  # 审核维度：合规性/信息披露/条款清晰度/费率合理性
    regulation: str
    description: str
    suggestion: str


@dataclass
class AuditResult:
    """审核结果"""
    overall_assessment: str
    assessment_reason: str  # 评定依据说明
    issues: List[AuditIssue]
    score: int
    summary: str
    regulations_used: List[str]  # 参与审核的法规列表


@dataclass
class AuditOutcome:
    """审核输出结果"""
    success: bool
    result: Optional[AuditResult]
    regulation_id: str
    record: RegulationRecord
    errors: List[str]
    warnings: List[str]
    processor: str = "audit.auditor"
    regulations_count: int = 0  # 检索到的法规数量


class ComplianceAuditor:
    """合规审核器"""

    def __init__(self, llm_client: BaseLLMClient = None, rag_engine: Any = None):
        self.llm_client = llm_client or LLMClientFactory.get_audit_llm()
        self.rag_engine = rag_engine

    def audit(
        self,
        product_clause: str,
        top_k: int = 3,
        filters: Dict[str, Any] = None
    ) -> AuditOutcome:
        if not self.rag_engine:
            return self._failed_outcome("RAG 引擎未配置")

        regulations = self._search_regulations(
            query_text=product_clause,
            top_k=top_k,
            filters=filters
        )

        if not regulations:
            return self._failed_outcome("未检索到相关法规")

        primary_regulation = regulations[0]
        metadata = primary_regulation.get('metadata', {})
        record = RegulationRecord(
            law_name=metadata.get('law_name', ''),
            article_number=metadata.get('article_number', ''),
            category=metadata.get('category', DEFAULT_CATEGORY),
            status=RegulationStatus.AUDITED
        )

        try:
            audit_result = self._llm_audit(product_clause, regulations)

            return AuditOutcome(
                success=True,
                result=audit_result,
                regulation_id=self._generate_regulation_id(record),
                record=record,
                errors=[],
                warnings=[],
                regulations_count=len(regulations)
            )

        except Exception as e:
            logger.error(f"审核失败: {e}")
            return self._failed_outcome(str(e), record)

    def _search_regulations(
        self,
        query_text: str,
        top_k: int = 3,
        filters: Dict[str, Any] = None
    ) -> List[Dict[str, Any]]:
        try:
            results = self.rag_engine.search(
                query_text=query_text,
                top_k=top_k,
                use_hybrid=True,
                filters=filters
            )
            logger.info(f"检索到 {len(results)} 条相关法规")
            return results
        except Exception as e:
            logger.error(f"法规检索失败: {e}")
            return []

    def _llm_audit(self, product_clause: str, regulations: List[Dict[str, Any]]) -> AuditResult:
        from .prompts import get_system_prompt, get_user_prompt

        messages = [
            {'role': 'system', 'content': get_system_prompt()},
            {'role': 'user', 'content': get_user_prompt(product_clause, regulations)}
        ]

        response = self.llm_client.chat(messages)
        result = json.loads(response)

        issues = [
            AuditIssue(**issue) for issue in result.get('issues', [])
        ]

        regulations_used = [
            f"{ref.get('metadata', {}).get('law_name', '')} {ref.get('metadata', {}).get('article_number', '')}"
            for ref in regulations
        ]

        return AuditResult(
            overall_assessment=result.get('overall_assessment', '不通过'),
            assessment_reason=result.get('assessment_reason', ''),
            issues=issues,
            score=result.get('score', 0),
            summary=result.get('summary', ''),
            regulations_used=regulations_used
        )

    def _failed_outcome(
        self,
        error_message: str,
        record: RegulationRecord = None
    ) -> AuditOutcome:
        if record is None:
            record = RegulationRecord(
                law_name="",
                article_number="",
                category=DEFAULT_CATEGORY,
                status=RegulationStatus.FAILED
            )
        return AuditOutcome(
            success=False,
            result=None,
            regulation_id="",
            record=record,
            errors=[error_message],
            warnings=[]
        )

    def _generate_regulation_id(self, record: RegulationRecord) -> str:
        key = f"{record.law_name}_{record.article_number}"
        return hashlib.md5(key.encode()).hexdigest()[:16]

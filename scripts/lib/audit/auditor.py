#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
合规审核器

负责根据监管规定审核保险产品条款。
"""

import json
import logging
import hashlib
import re
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

from lib.common.models import RegulationRecord, RegulationStatus, AuditRequest, Product, ProductCategory, Coverage, Premium
from lib.llm import BaseLLMClient, LLMClientFactory
from .prompts import ASSESSMENT_RESULTS, AUDIT_DIMENSIONS, SEVERITY_LEVELS
from .validator import AuditRequestValidator

logger = logging.getLogger(__name__)

DEFAULT_CATEGORY = "未分类"


def _parse_json_response(response: str, context: str = "") -> Dict[str, Any]:
    """安全解析 LLM JSON 响应（增强版）"""

    parsers = [
        lambda r: json.loads(r),
        lambda r: json.loads(re.search(r'```json\s*(.*?)\s*```', r, re.DOTALL).group(1)),
        lambda r: json.loads(re.search(r'```\s*(.*?)\s*```', r, re.DOTALL).group(1)),
        lambda r: json.loads(r[r.find('{'):r.rfind('}') + 1]),
        lambda r: json.loads(r[r.find('['):r.rfind(']') + 1]),
        lambda r: json.loads(_clean_llm_output(r)),
    ]

    errors = []

    for i, parser in enumerate(parsers, 1):
        try:
            result = parser(response)
            if not isinstance(result, dict):
                raise ValueError(f"解析结果不是字典: {type(result)}")
            if i > 1:
                logger.debug(f"使用策略 {i} 成功解析 LLM 响应")
            return result
        except Exception as e:
            errors.append(f"策略{i}: {type(e).__name__}: {str(e)[:100]}")
            continue

    logger.error(f"JSON 解析失败，尝试了 {len(errors)} 种策略: {errors}")
    raise ValueError(f"无法解析 LLM 响应为 JSON")


def _clean_llm_output(text: str) -> str:
    """清理 LLM 输出中的常见噪音"""
    text = re.sub(r'```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```', '', text)
    text = text.strip()
    return text


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

    def validate(self) -> List[str]:
        """验证审核结果的完整性"""
        errors = []

        if self.overall_assessment not in ASSESSMENT_RESULTS:
            errors.append(f"无效的评定结果: {self.overall_assessment}")

        if not 0 <= self.score <= 100:
            errors.append(f"分数超出范围: {self.score}")

        for i, issue in enumerate(self.issues):
            if issue.severity not in SEVERITY_LEVELS:
                errors.append(f"问题 {i}: 无效的严重程度: {issue.severity}")
            if issue.dimension not in AUDIT_DIMENSIONS:
                errors.append(f"问题 {i}: 无效的审核维度: {issue.dimension}")

        return errors


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

    def _build_regulations_reference(self, regulations: List[Dict[str, Any]]) -> List[str]:
        """构建法规引用列表"""
        return [
            f"{ref.get('metadata', {}).get('law_name', '')} {ref.get('metadata', {}).get('article_number', '')}"
            for ref in regulations
        ]

    def _parse_audit_response(self, response: str, clause_text: str) -> Dict[str, Any]:
        """解析 LLM 审核响应"""
        result = _parse_json_response(response, f"条款: {clause_text[:50]}...")

        # 验证必需字段
        if 'overall_assessment' not in result:
            raise ValueError("响应缺少 overall_assessment 字段")

        # 验证评定结果
        if result['overall_assessment'] not in ASSESSMENT_RESULTS:
            raise ValueError(f"无效的评定结果: {result['overall_assessment']}")

        return result

    def _create_audit_result(
        self,
        result: Dict[str, Any],
        regulations: List[Dict[str, Any]]
    ) -> AuditResult:
        """创建审核结果"""
        issues = []
        for issue_data in result.get('issues', []):
            # 验证并规范化问题数据
            severity = issue_data.get('severity', 'medium')
            if severity not in SEVERITY_LEVELS:
                logger.warning(f"无效的严重程度 '{severity}'，使用默认值 'medium'")
                severity = 'medium'

            dimension = issue_data.get('dimension', '合规性')
            if dimension not in AUDIT_DIMENSIONS:
                logger.warning(f"无效的审核维度 '{dimension}'，使用默认值 '合规性'")
                dimension = '合规性'

            issues.append(AuditIssue(
                clause=issue_data.get('clause', ''),
                severity=severity,
                dimension=dimension,
                regulation=issue_data.get('regulation', ''),
                description=issue_data.get('description', ''),
                suggestion=issue_data.get('suggestion', '')
            ))

        return AuditResult(
            overall_assessment=result.get('overall_assessment', '不通过'),
            assessment_reason=result.get('assessment_reason', ''),
            issues=issues,
            score=max(0, min(100, result.get('score', 0))),
            summary=result.get('summary', ''),
            regulations_used=self._build_regulations_reference(regulations)
        )

    def audit(
        self,
        request: AuditRequest,
        top_k: int = 3,
        filters: Dict[str, Any] = None
    ) -> List[AuditOutcome]:
        try:
            AuditRequestValidator.validate_request(request)
        except Exception as e:
            return [self._failed_outcome(f"请求验证失败: {e}")]

        if not request.clauses:
            return [self._failed_outcome("没有待审核的条款")]

        if not self.rag_engine:
            return [self._failed_outcome("RAG 引擎未配置")]

        outcomes = []
        for clause_item in request.clauses:
            clause_text = clause_item.get('text', '')
            if not clause_text:
                continue

            # 使用条款文本进行法规检索
            regulations = self._search_regulations(
                query_text=clause_text,
                top_k=top_k,
                filters=filters
            )

            if not regulations:
                outcomes.append(self._failed_outcome("未检索到相关法规"))
                continue

            primary_regulation = regulations[0]
            metadata = primary_regulation.get('metadata', {})
            record = RegulationRecord(
                law_name=metadata.get('law_name', ''),
                article_number=metadata.get('article_number', ''),
                category=metadata.get('category', DEFAULT_CATEGORY),
                status=RegulationStatus.AUDITED
            )

            try:
                audit_result = self._audit(
                    clause=clause_item,
                    regulations=regulations,
                    product=request.product,
                    coverage=request.coverage,
                    premium=request.premium
                )
                outcomes.append(AuditOutcome(
                    success=True,
                    result=audit_result,
                    regulation_id=self._generate_regulation_id(record),
                    record=record,
                    errors=[],
                    warnings=[],
                    regulations_count=len(regulations)
                ))
            except Exception as e:
                clause_id = f"{clause_item.get('number', '')} {clause_item.get('title', '')}".strip()
                logger.error(f"审核失败 [{clause_id}]: {e}")
                outcomes.append(self._failed_outcome(str(e), record))

        return outcomes

    def _audit(
        self,
        clause: Dict[str, str],
        regulations: List[Dict[str, Any]],
        product: Product = None,
        coverage: Optional[Coverage] = None,
        premium: Optional[Premium] = None
    ) -> AuditResult:
        """执行条款审核

        Args:
            clause: 条款对象，包含 text, number, title
            regulations: 相关法规列表
            product: 产品信息（可选）
            coverage: 保障信息（可选）
            premium: 费率信息（可选）
        """
        from .prompts import get_system_prompt, get_user_prompt

        # 构建产品上下文，如果没有提供则使用默认值
        if product is None:
            product = Product(
                name="",
                company="",
                category=ProductCategory.OTHER,
                period=""
            )

        product_context = self._build_product_context(product, coverage, premium)

        clause_text = clause.get('text', '')
        clause_for_log = f"{clause.get('number', '')} {clause.get('title', '')}"[:50]

        messages = [
            {'role': 'system', 'content': get_system_prompt()},
            {'role': 'user', 'content': get_user_prompt(product_context, clause, regulations)}
        ]

        logger.info(f"开始审核条款: {clause_for_log}")

        response = self.llm_client.chat(messages)
        result = self._parse_audit_response(response, clause_text)

        audit_result = self._create_audit_result(result, regulations)

        logger.info(f"条款审核完成: 评定={audit_result.overall_assessment}, 分数={audit_result.score}, 问题数={len(audit_result.issues)}")

        return audit_result

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

    def _build_product_context(
        self,
        product: Product,
        coverage: Optional[Coverage] = None,
        premium: Optional[Premium] = None
    ) -> Dict[str, Any]:
        """构建产品上下文"""
        product_context = {
            'product_name': product.name,
            'company': product.company,
            'category': product.category,
            'period': product.period,
            'waiting_period': product.waiting_period,
            'age_min': product.age_min,
            'age_max': product.age_max,
        }

        if coverage and any([coverage.scope, coverage.deductible,
                              coverage.payout_ratio, coverage.amount]):
            product_context['coverage'] = {
                'scope': coverage.scope,
                'deductible': coverage.deductible,
                'payout_ratio': coverage.payout_ratio,
                'amount': coverage.amount,
            }

        if premium and any([premium.payment_method, premium.payment_period]):
            product_context['premium'] = {
                'payment_method': premium.payment_method,
                'payment_period': premium.payment_period,
            }

        return product_context

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
        """生成法规唯一标识（使用 SHA256 防止碰撞）"""
        key = f"{record.law_name}_{record.article_number}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

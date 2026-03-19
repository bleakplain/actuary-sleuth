#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公共数据模型

预处理、审核、RAG 等模块共享的数据结构。
"""

import sys
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Any, Optional, Union, Tuple

# 添加 scripts 目录到路径以便导入
scripts_dir = Path(__file__).parent.parent.parent
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from lib.preprocessing.models import (
    RegulationStatus,
    RegulationLevel,
    RegulationRecord,
    RegulationProcessingOutcome,
    RegulationDocument,
)


# ==================== Preprocessing → Audit 接口模型 ====================

class ProductCategory(str, Enum):
    """产品类别"""
    CRITICAL_ILLNESS = "critical_illness"
    MEDICAL_INSURANCE = "medical_insurance"
    LIFE_INSURANCE = "life_insurance"
    PARTICIPATING_LIFE = "participating_life"
    UNIVERSAL_LIFE = "universal_life"
    ANNUITY = "annuity"
    ACCIDENT = "accident"
    HEALTH = "health"
    PENSION = "pension"
    OTHER = "other"


@dataclass
class Product:
    """产品信息"""
    name: str
    company: str
    category: ProductCategory
    period: str
    waiting_period: Optional[int] = None
    age_min: Optional[int] = None
    age_max: Optional[int] = None


@dataclass
class Coverage:
    """保障信息"""
    scope: Optional[str] = None
    deductible: Optional[str] = None
    payout_ratio: Optional[str] = None
    limits: Optional[str] = None
    amount: Optional[str] = None


@dataclass
class Premium:
    """费率信息"""
    payment_method: Optional[str] = None
    payment_period: Optional[str] = None
    table_data: Optional[Dict[str, Any]] = None


@dataclass
class AuditRequest:
    """审核请求：Preprocessing → Audit 接口契约"""
    clauses: List[Dict[str, str]]
    product: Product = None
    coverage: Optional[Coverage] = None
    premium: Optional[Premium] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    source: str = ""

    def __post_init__(self):
        if self.product is None:
            self.product = Product(
                name="",
                company="",
                category=ProductCategory.OTHER,
                period=""
            )

    @classmethod
    def from_extract_result(cls, extract_result: 'ExtractResult') -> 'AuditRequest':
        """
        从 ExtractResult 转换为 AuditRequest

        Args:
            extract_result: 提取结果

        Returns:
            AuditRequest: 审核请求

        Raises:
            ValueError: 当提取质量不满足要求或 clauses 为空时
        """
        import logging
        logger = logging.getLogger(__name__)

        data = extract_result.data

        # 质量门控: 检查验证分数
        validation_score = extract_result.metadata.get('validation_score', 0)

        if validation_score == 0:
            # 未验证的情况：记录警告，但允许继续
            logger.warning(
                f"未设置 validation_score（未验证提取质量），建议先验证。"
                f"product={data.get('product_name', 'Unknown')}"
            )
        elif validation_score < 60:
            # 低质量情况：阻止审核
            raise ValueError(
                f"提取质量过低 (score: {validation_score}/100)，"
                f"不满足审核要求（最低60分）。"
                f"错误={len(extract_result.metadata.get('validation_errors', []))}个, "
                f"警告={len(extract_result.metadata.get('validation_warnings', []))}个"
            )
        elif validation_score < 80:
            # 中等质量：记录信息
            logger.info(
                f"提取质量中等 (score: {validation_score}/100)，"
                f"建议审核时关注数据准确性"
            )

        category_map = {
            'critical_illness': ProductCategory.CRITICAL_ILLNESS,
            'medical_insurance': ProductCategory.MEDICAL_INSURANCE,
            'life_insurance': ProductCategory.LIFE_INSURANCE,
            'term_life': ProductCategory.LIFE_INSURANCE,
            'whole_life': ProductCategory.LIFE_INSURANCE,
            'participating_life': ProductCategory.PARTICIPATING_LIFE,
            'universal_life': ProductCategory.UNIVERSAL_LIFE,
            'annuity': ProductCategory.ANNUITY,
            'accident': ProductCategory.ACCIDENT,
            'accident_insurance': ProductCategory.ACCIDENT,
        }

        product_type = extract_result.metadata.get('product_type', 'other')
        category = category_map.get(product_type, ProductCategory.OTHER)

        product = Product(
            name=data.get('product_name', ''),
            company=data.get('insurance_company', ''),
            category=category,
            period=data.get('insurance_period', ''),
            waiting_period=_parse_days(data.get('waiting_period')),
            age_min=_parse_age_min(data.get('age_min')),
            age_max=_parse_age_max(data.get('age_max')),
        )

        coverage = None
        if any(f in data for f in ['coverage_scope', 'deductible', 'payout_ratio', 'limits']):
            coverage = Coverage(
                scope=_normalize_field(data.get('coverage_scope')),
                deductible=_normalize_field(data.get('deductible')),
                payout_ratio=_normalize_field(data.get('payout_ratio')),
                limits=_normalize_field(data.get('limits')),
                amount=_normalize_field(data.get('coverage_amount')),
            )

        premium = None
        if any(f in data for f in ['payment_method', 'payment_period']):
            premium = Premium(
                payment_method=data.get('payment_method'),
                payment_period=data.get('payment_period'),
            )

        # 获取并规范化 clauses
        clauses_data = _normalize_clauses(data.get('clauses', []))

        # 验证 clauses 不为空
        if not clauses_data:
            raise ValueError("没有可审核的条款：clauses 为空")

        return cls(
            clauses=clauses_data,
            product=product,
            coverage=coverage,
            premium=premium,
            extra={k: v for k, v in data.items() if k not in _used_fields()},
            source=extract_result.metadata.get('source_file', ''),
        )


def _parse_days(value: Any) -> Optional[int]:
    """
    解析天数（用于等待期等）

    Args:
        value: 输入值，如 "90天", "180天", 90

    Returns:
        天数或 None
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        import re
        match = re.search(r'\d+', value)
        return int(match.group()) if match else None
    return None


def _parse_age_min(value: Any) -> Optional[int]:
    """
    解析最低投保年龄

    对于范围值（如 "0-60岁"），返回下限。

    Args:
        value: 输入值，如 "0岁", "0-60岁", 0

    Returns:
        最低年龄或 None
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        import re
        # 尝试解析范围 "0-60岁"
        range_match = re.search(r'(\d+)\s*[-~到]\s*(\d+)', value)
        if range_match:
            return int(range_match.group(1))  # 下限
        # 单个值
        match = re.search(r'\d+', value)
        return int(match.group()) if match else None
    return None


def _parse_age_max(value: Any) -> Optional[int]:
    """
    解析最高投保年龄

    对于范围值（如 "0-60岁"），返回上限。

    Args:
        value: 输入值，如 "60岁", "0-60岁", 60

    Returns:
        最高年龄或 None
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        import re
        # 尝试解析范围 "0-60岁"
        range_match = re.search(r'(\d+)\s*[-~到]\s*(\d+)', value)
        if range_match:
            return int(range_match.group(2))  # 上限
        # 单个值
        match = re.search(r'\d+', value)
        return int(match.group()) if match else None
    return None


def _normalize_field(value: Any) -> Optional[str]:
    """规范化字段值为字符串"""
    if value is None:
        return None
    if isinstance(value, str):
        return value if value.strip() else None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        return str(value)
    return None


def _normalize_clauses(clauses: Any) -> List[Dict[str, Any]]:
    """规范化条款列表

    确保每个条款包含必需字段，同时保留原始数据。

    转换规则：
    - 如果 text 为空，尝试使用 title
    - 保留 number, title, content, reference 等字段
    - 保留原始数据以便后续使用
    """
    if not isinstance(clauses, list):
        return []

    normalized = []
    for clause in clauses:
        if not isinstance(clause, dict):
            continue

        # 提取 text 字段
        text = clause.get('text', '')
        if not text:
            # 如果 text 为空，尝试使用 title
            title = clause.get('title', '')
            text = title if title else ''

        if not text:
            continue

        # 构建规范化的条款，保留所有原始字段
        normalized_clause = {
            'text': text,
            'number': clause.get('number', ''),
            'title': clause.get('title', ''),  # 保留标题
            'content': clause.get('content', ''),  # 保留详细内容
            'reference': clause.get('reference', ''),  # 保留引用
            'original': clause,  # 保留完整的原始数据
        }

        normalized.append(normalized_clause)

    return normalized


def _used_fields() -> set:
    """返回已被使用的字段名"""
    return {
        'product_name', 'insurance_company', 'insurance_period',
        'waiting_period', 'age_min', 'age_max',
        'coverage_scope', 'deductible', 'payout_ratio', 'limits', 'coverage_amount',
        'payment_method', 'payment_period', 'clauses'
    }


__all__ = [
    # 法规文档模型
    'RegulationStatus',
    'RegulationLevel',
    'RegulationRecord',
    'RegulationProcessingOutcome',
    'RegulationDocument',
    # Preprocessing → Audit 接口模型
    'ProductCategory',
    'Product',
    'Coverage',
    'Premium',
    'AuditRequest',
]

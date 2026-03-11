#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
路由选择器

根据文档特征和分类结果选择最优的提取通道。
"""
import logging
from typing import List

from .models import NormalizedDocument, ExtractionRoute, FormatInfo
from .classifier import ProductTypeClassifier


logger = logging.getLogger(__name__)


class RouteSelector:
    """提取路由选择器"""

    # 必需字段（所有产品都需要）
    REQUIRED_FIELDS = {
        'product_name',
        'insurance_company',
        'insurance_period',
        'waiting_period'
    }

    def __init__(self):
        self.type_classifier = ProductTypeClassifier()

    def select_route(self, document: NormalizedDocument) -> ExtractionRoute:
        """
        选择提取路由

        Returns:
            ExtractionRoute: 提取路由决策
        """
        # 1. 产品类型识别
        type_code, confidence = self.type_classifier.get_primary_type(document.content)

        # 2. 判断是否走快速通道
        use_dynamic = self._use_dynamic(
            document.format_info, confidence, document
        )

        mode = 'dynamic' if use_dynamic else 'fast'

        return ExtractionRoute(
            mode=mode,
            product_type=type_code,
            confidence=confidence,
            is_hybrid=self.type_classifier.is_hybrid_product(document.content),
            reason=self._explain_decision(use_dynamic, document.format_info, confidence)
        )

    def _use_dynamic(self,
                   format_info: FormatInfo,
                   confidence: float,
                   document: NormalizedDocument) -> bool:
        """判断是否使用动态通道"""
        # 条件1: 格式非标准化 或 复杂结构
        is_complex = (
            not format_info.is_structured or
            not format_info.has_clause_numbers
        )

        # 条件2: 分类置信度低
        is_low_confidence = confidence < 0.7

        # 条件3: 关键信息不在文档前部
        has_key_info_back = not self._check_key_info_position(document)

        return is_complex or is_low_confidence or has_key_info_back

    def _check_key_info_position(self, document: NormalizedDocument) -> bool:
        """检查关键信息是否在文档前部（前2000字符）"""
        front = document.content[:2000]

        # 检查必需字段是否在前面
        required_found = sum(
            1 for field in self.REQUIRED_FIELDS
            if any(indicator in front for indicator in self._field_indicators(field))
        )

        return required_found >= len(self.REQUIRED_FIELDS) * 0.75

    def _field_indicators(self, field: str) -> List[str]:
        """字段指示词列表"""
        indicators = {
            'product_name': ['产品名称', '保险产品', '保险计划'],
            'insurance_company': ['保险公司', '承保机构', '公司名称'],
            'insurance_period': ['保险期间', '保障期限', '保险期限'],
            'waiting_period': ['等待期', '观察期']
        }
        return indicators.get(field, [field])

    def _explain_decision(self,
                        use_dynamic: bool,
                        format_info: FormatInfo,
                        confidence: float) -> str:
        """解释决策原因"""
        reasons = []

        if use_dynamic:
            if not format_info.is_structured:
                reasons.append("格式非标准化")
            if confidence < 0.7:
                reasons.append(f"分类置信度低({confidence:.2f})")
            if len(reasons) == 1:
                reasons.append("或关键信息不在前部")
        else:
            reasons.append("格式标准化")
            reasons.append(f"分类置信度高({confidence:.2f})")

        return "; ".join(reasons) if reasons else "默认路由"

    @classmethod
    def get_required_fields(cls) -> set:
        """获取必需字段集合"""
        return cls.REQUIRED_FIELDS.copy()

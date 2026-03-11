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
        can_use_fast_route = self._can_use_fast_route(
            document.format_info, confidence, document
        )

        mode = 'fast' if can_use_fast_route else 'structured'

        return ExtractionRoute(
            mode=mode,
            product_type=type_code,
            confidence=confidence,
            is_hybrid=self.type_classifier.is_hybrid_product(document.content),
            reason=self._explain_decision(can_use_fast_route, document.format_info, confidence)
        )

    def _can_use_fast_route(self,
                           format_info: FormatInfo,
                           confidence: float,
                           document: NormalizedDocument) -> bool:
        """判断是否可以使用快速通道"""
        # 条件1: 格式标准化
        is_standard = (
            format_info.is_structured and
            format_info.has_clause_numbers
        )

        # 条件2: 分类置信度高
        is_confident = confidence >= 0.7

        # 条件3: 关键信息在文档前部可提取
        has_key_info_front = self._check_key_info_position(document)

        return is_standard and is_confident and has_key_info_front

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
                        can_use_fast_route: bool,
                        format_info: FormatInfo,
                        confidence: float) -> str:
        """解释决策原因"""
        reasons = []

        if can_use_fast_route:
            reasons.append("格式标准化")
            reasons.append(f"分类置信度高({confidence:.2f})")
        else:
            if not format_info.is_structured:
                reasons.append("格式非标准化")
            if confidence < 0.7:
                reasons.append(f"分类置信度低({confidence:.2f})")

        return "; ".join(reasons) if reasons else "默认路由"

    @classmethod
    def get_required_fields(cls) -> set:
        """获取必需字段集合"""
        return cls.REQUIRED_FIELDS.copy()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
提取器选择器

根据文档特征和分类结果选择最优的提取通道。
"""
import logging
from typing import List, Tuple, Union

from .models import NormalizedDocument, DocumentProfile
from .classifier import ProductClassifier
from .fast_extractor import FastExtractor
from .dynamic_extractor import DynamicExtractor


logger = logging.getLogger(__name__)


class ExtractorSelector:
    """提取器选择器：根据文档特征选择合适的提取器"""

    # 必需字段（所有产品都需要）
    REQUIRED_FIELDS = {
        'product_name',
        'insurance_company',
        'insurance_period',
        'waiting_period'
    }

    def __init__(self, fast_extractor: FastExtractor, dynamic_extractor: DynamicExtractor, classifier: ProductClassifier = None):
        """
        初始化提取器选择器

        Args:
            fast_extractor: 快速提取器
            dynamic_extractor: 动态提取器
            classifier: 产品类型分类器（可选，默认创建新实例）
        """
        self.fast_extractor = fast_extractor
        self.dynamic_extractor = dynamic_extractor
        self.type_classifier = classifier or ProductClassifier()

    def select(self, document: NormalizedDocument) -> Union[FastExtractor, DynamicExtractor]:
        """
        选择提取器

        Returns:
            提取器实例
        """
        # 1. 产品类型识别
        type_code, confidence = self.type_classifier.get_primary_type(document.content)

        # 2. 判断是否走动态通道
        use_dynamic = self._use_dynamic(document.profile, confidence, document)

        # 3. 选择提取器
        extractor = self.dynamic_extractor if use_dynamic else self.fast_extractor

        # 4. 记录决策日志
        mode = 'dynamic' if use_dynamic else 'fast'
        rationale = self._explain_decision(use_dynamic, document.profile, confidence)
        logger.debug(f"提取器选择: {mode} | {rationale}")

        return extractor

    def _use_dynamic(self, profile: DocumentProfile, confidence: float, document: NormalizedDocument) -> bool:
        """判断是否使用动态通道"""
        # 条件1: 格式非标准化 或 复杂结构
        is_complex = (
            not profile.is_structured or
            not profile.has_clause_numbers
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

    def _explain_decision(self, use_dynamic: bool, profile: DocumentProfile, confidence: float) -> str:
        """解释决策原因"""
        reasons = []

        if use_dynamic:
            if not profile.is_structured:
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

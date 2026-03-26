#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
产品分类器

多标签产品类型分类，支持混合产品识别。
"""
import logging
from typing import List, Tuple, Optional, Dict

from .product_types import PRODUCT_TYPES
from .models import ProductType
from .utils.constants import config


logger = logging.getLogger(__name__)


class Classifier:
    """产品分类器 - 多标签支持"""

    def __init__(self, threshold: Optional[float] = None):
        self.threshold = threshold if threshold is not None else config.DEFAULT_CLASSIFICATION_THRESHOLD
        self.types = PRODUCT_TYPES
        # Build O(1) lookup dictionary
        self._type_by_code: Dict[str, ProductType] = {pt.code: pt for pt in PRODUCT_TYPES}

    def classify(self, document: str) -> List[Tuple[str, float]]:
        """
        分类产品类型（多标签）

        Returns:
            [(type_code, confidence), ...] 按置信度降序排序
        """
        scores = []

        for product_type in self.types:
            score = product_type.match_score(document)
            if score >= self.threshold:
                scores.append((product_type.code, score))

        # 按分数降序排序
        scores.sort(key=lambda x: x[1], reverse=True)

        return scores

    def get_primary_type(self, document: str) -> Tuple[str, float]:
        """获取主导类型"""
        classifications = self.classify(document)

        if not classifications:
            # 默认类型
            return ("life_insurance", 0.0)

        return classifications[0]

    def is_hybrid_product(self, document: str, classifications: Optional[List[Tuple[str, float]]] = None) -> bool:
        """
        判断是否为混合产品

        Args:
            document: 待分类文档
            classifications: 已分类的结果（可选，如果提供则跳过分类）

        Returns:
            是否为混合产品
        """
        if classifications is None:
            classifications = self.classify(document)

        return len(classifications) > 1 and classifications[1][1] > config.HYBRID_PRODUCT_THRESHOLD

    def get_required_fields(self, product_type: str) -> List[str]:
        """获取产品类型的必需字段 (O(1) lookup)"""
        pt = self._type_by_code.get(product_type)
        return pt.required_fields if pt else []

    def get_type_info(self, code: str) -> Optional[ProductType]:
        """获取产品类型信息 (O(1) lookup)"""
        return self._type_by_code.get(code)

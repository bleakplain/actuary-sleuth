#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
产品类型分类器

多标签产品类型分类，支持混合产品识别。
"""
import logging
from typing import List, Tuple, Optional

from .product_types import PRODUCT_TYPES
from .models import ProductType


logger = logging.getLogger(__name__)


class ProductTypeClassifier:
    """产品类型分类器 - 多标签支持"""

    def __init__(self, threshold: float = 0.3):
        self.types = PRODUCT_TYPES
        self.threshold = threshold

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

    def is_hybrid_product(self, document: str) -> bool:
        """判断是否为混合产品"""
        classifications = self.classify(document)
        return len(classifications) > 1 and classifications[1][1] > 0.5

    def get_required_fields(self, product_type: str) -> List[str]:
        """获取产品类型的必需字段"""
        for pt in self.types:
            if pt.code == product_type:
                return pt.required_fields
        return []

    def get_type_info(self, code: str) -> Optional[ProductType]:
        """获取产品类型信息"""
        for pt in self.types:
            if pt.code == code:
                return pt
        return None

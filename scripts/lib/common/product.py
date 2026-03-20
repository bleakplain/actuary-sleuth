#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
产品类型映射模块

建立集中的产品类型映射系统，将 ProductCategory 枚举映射到 scoring 模块的类型字符串。
"""
from typing import Dict

from lib.common.models import ProductCategory


class ScoringType:
    """Scoring 模块产品类型常量"""

    LIFE = 'life'
    HEALTH = 'health'
    ACCIDENT = 'accident'
    DEFAULT = 'default'


# 产品类别到评分类型的映射表
CATEGORY_TO_SCORING: Dict[ProductCategory, str] = {
    # 寿险类
    ProductCategory.LIFE_INSURANCE: ScoringType.LIFE,
    ProductCategory.PARTICIPATING_LIFE: ScoringType.LIFE,
    ProductCategory.UNIVERSAL_LIFE: ScoringType.LIFE,
    ProductCategory.ANNUITY: ScoringType.LIFE,
    ProductCategory.PENSION: ScoringType.LIFE,

    # 健康险类
    ProductCategory.CRITICAL_ILLNESS: ScoringType.HEALTH,
    ProductCategory.MEDICAL_INSURANCE: ScoringType.HEALTH,
    ProductCategory.HEALTH: ScoringType.HEALTH,

    # 意外险类
    ProductCategory.ACCIDENT: ScoringType.ACCIDENT,

    # 其他
    ProductCategory.OTHER: ScoringType.DEFAULT,
}


def map_to_scoring_type(category: ProductCategory) -> str:
    """
    将 ProductCategory 映射到 scoring 模块的类型

    Args:
        category: 产品类别枚举

    Returns:
        str: scoring 模块期望的类型字符串 ('life', 'health', 'accident', 'default')
    """
    return CATEGORY_TO_SCORING.get(category, ScoringType.DEFAULT)

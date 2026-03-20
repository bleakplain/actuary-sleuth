#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一的产品类型映射工具

提供产品类型字符串与 ProductCategory 枚举之间的双向映射。
整合来自 evaluation、reporting、common 等模块的映射逻辑。
"""
from typing import Dict, List
from lib.common.models import ProductCategory


# 模块级常量 - 避免每次函数调用时重建
_CHINESE_ALIASES: Dict[ProductCategory, List[str]] = {
    ProductCategory.CRITICAL_ILLNESS: [
        '重大疾病', '重疾', '重大疾病保险', '重疾险'
    ],
    ProductCategory.MEDICAL_INSURANCE: [
        '医疗', '医疗保险'
    ],
    ProductCategory.LIFE_INSURANCE: [
        '人寿', '寿险', '终身', '人寿保险', '终身寿险', '定期寿险'
    ],
    ProductCategory.PARTICIPATING_LIFE: [
        '分红', '分红型人寿保险'
    ],
    ProductCategory.UNIVERSAL_LIFE: [
        '万能', '万能险'
    ],
    ProductCategory.ANNUITY: [
        '年金', '年金保险', '养老金'
    ],
    ProductCategory.ACCIDENT: [
        '意外', '伤害', '意外险', '意外伤害保险'
    ],
    ProductCategory.HEALTH: [
        '健康', '健康保险'
    ],
    ProductCategory.PENSION: [
        '养老', '养老保险'
    ],
}

_CLASSIFIER_CODE_MAP: Dict[str, ProductCategory] = {
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

_DISPLAY_NAMES: Dict[ProductCategory, str] = {
    ProductCategory.CRITICAL_ILLNESS: '重大疾病保险',
    ProductCategory.MEDICAL_INSURANCE: '医疗保险',
    ProductCategory.LIFE_INSURANCE: '人寿保险',
    ProductCategory.PARTICIPATING_LIFE: '分红型人寿保险',
    ProductCategory.UNIVERSAL_LIFE: '万能险',
    ProductCategory.ANNUITY: '年金保险',
    ProductCategory.ACCIDENT: '意外伤害保险',
    ProductCategory.HEALTH: '健康保险',
    ProductCategory.PENSION: '养老保险',
    ProductCategory.OTHER: '其他保险',
}


def from_chinese_string(type_str: str) -> ProductCategory:
    """
    将中文产品类型字符串映射到 ProductCategory 枚举

    使用子字符串匹配，支持各种产品类型表述。

    Args:
        type_str: 产品类型字符串，如 "重大疾病保险", "医疗险", "终身寿险"

    Returns:
        ProductCategory: 产品类别枚举值

    Examples:
        >>> from_chinese_string("重大疾病保险")
        <ProductCategory.CRITICAL_ILLNESS>
        >>> from_chinese_string("医疗险")
        <ProductCategory.MEDICAL_INSURANCE>
        >>> from_chinese_string("未知产品")
        <ProductCategory.OTHER>
    """
    if not type_str:
        return ProductCategory.OTHER

    for category, aliases in _CHINESE_ALIASES.items():
        for alias in aliases:
            if alias in type_str:
                return category

    return ProductCategory.OTHER


def from_classifier_code(code: str) -> ProductCategory:
    """
    将分类器代码映射到 ProductCategory 枚举

    Args:
        code: 分类器代码，如 "critical_illness", "medical_insurance"

    Returns:
        ProductCategory: 产品类别枚举值
    """
    return _CLASSIFIER_CODE_MAP.get(code, ProductCategory.OTHER)


def to_display_name(category: ProductCategory) -> str:
    """
    获取 ProductCategory 的标准中文显示名称

    Args:
        category: 产品类别枚举值

    Returns:
        str: 标准中文显示名称
    """
    return _DISPLAY_NAMES.get(category, str(category))


# 便捷别名（用于简化现有代码迁移）
parse_product_type = from_chinese_string

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
产品类型识别工具

提供产品类型字符串与 ProductCategory 枚举之间的转换。
"""
from typing import Dict, List
from lib.common.models import ProductCategory


# 模块级常量
_KEYWORDS: Dict[ProductCategory, List[str]] = {
    ProductCategory.CRITICAL_ILLNESS: ['重大疾病', '重疾', '重大疾病保险', '重疾险'],
    ProductCategory.MEDICAL_INSURANCE: ['医疗', '医疗保险'],
    ProductCategory.LIFE_INSURANCE: ['人寿', '寿险', '终身', '人寿保险', '终身寿险', '定期寿险'],
    ProductCategory.PARTICIPATING_LIFE: ['分红', '分红型人寿保险'],
    ProductCategory.UNIVERSAL_LIFE: ['万能', '万能险'],
    ProductCategory.ANNUITY: ['年金', '年金保险', '养老金'],
    ProductCategory.ACCIDENT: ['意外', '伤害', '意外险', '意外伤害保险'],
    ProductCategory.HEALTH: ['健康', '健康保险'],
    ProductCategory.PENSION: ['养老', '养老保险'],
}

_CODE_MAP: Dict[str, ProductCategory] = {
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

_NAMES: Dict[ProductCategory, str] = {
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


def get_category(product_name: str) -> ProductCategory:
    """
    从产品名称获取类别

    Examples:
        >>> get_category("重大疾病保险")
        <ProductCategory.CRITICAL_ILLNESS>
        >>> get_category("百万医疗险")
        <ProductCategory.MEDICAL_INSURANCE>
    """
    if not product_name:
        return ProductCategory.OTHER

    for category, keywords in _KEYWORDS.items():
        for keyword in keywords:
            if keyword in product_name:
                return category
    return ProductCategory.OTHER


def get_name(category: ProductCategory) -> str:
    """
    获取类别显示名称

    Examples:
        >>> get_name(ProductCategory.CRITICAL_ILLNESS)
        '重大疾病保险'
        >>> get_name(ProductCategory.OTHER)
        '其他保险'
    """
    return _NAMES.get(category, str(category))


def from_code(code: str) -> ProductCategory:
    """
    从分类器代码获取类别

    Examples:
        >>> from_code("critical_illness")
        <ProductCategory.CRITICAL_ILLNESS>
        >>> from_code("unknown")
        <ProductCategory.OTHER>
    """
    return _CODE_MAP.get(code, ProductCategory.OTHER)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
产品类型识别和映射工具

提供产品类型与 ProductCategory 枚举之间的转换，以及评分类型映射。
"""
from typing import Dict, List
from lib.common.models import ProductCategory


# ========== 评分类型常量 ==========

class ScoringType:
    """Scoring 模块产品类型常量"""
    LIFE = 'life'
    HEALTH = 'health'
    ACCIDENT = 'accident'
    DEFAULT = 'default'


# ========== 产品类别关键词映射 ==========

# 产品类别 -> 关键词列表
# 用于从文本中识别产品类型
PRODUCT_CATEGORIES: Dict[ProductCategory, List[str]] = {
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


# ========== 公共函数 ==========

def get_category(product_name: str) -> ProductCategory:
    """从产品名称获取类别"""
    if not product_name:
        return ProductCategory.OTHER

    for category, keywords in PRODUCT_CATEGORIES.items():
        for keyword in keywords:
            if keyword in product_name:
                return category
    return ProductCategory.OTHER


def get_name(category: ProductCategory) -> str:
    """获取类别显示名称"""
    return _NAMES.get(category, str(category))


def from_code(code: str) -> ProductCategory:
    """从分类器代码获取类别"""
    return _CODE_MAP.get(code, ProductCategory.OTHER)


def map_to_scoring_type(category: ProductCategory) -> str:
    """将 ProductCategory 映射到 scoring 模块的类型"""
    return CATEGORY_TO_SCORING.get(category, ScoringType.DEFAULT)


def extract_product_type(text: str) -> str | None:
    """从文本中提取产品类型关键词。

    返回匹配到的第一个关键词（按 PRODUCT_CATEGORIES 顺序）。
    用于会话上下文的险种识别。

    Args:
        text: 待识别的文本（问题或回答）

    Returns:
        匹配的关键词，如 "重疾险"、"医疗"，或 None
    """
    for keywords in PRODUCT_CATEGORIES.values():
        for kw in keywords:
            if kw in text:
                return kw
    return None


def get_product_category_options() -> List[str]:
    """获取产品类型选项列表（用于澄清选项）。

    返回各 ProductCategory 的通俗名称，带"险"后缀更符合用户习惯。
    """
    return [
        "重疾险",
        "医疗险",
        "意外险",
        "人寿险",
    ]

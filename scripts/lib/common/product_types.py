#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
产品类型配置（集中管理）

提供产品类别枚举和集中配置，避免分散在多个文件中
"""
from enum import Enum
from typing import Dict, List, Optional


class ProductCategory(Enum):
    """产品类别枚举"""
    LIFE = "人寿保险"
    HEALTH = "健康保险"
    ACCIDENT = "意外保险"
    ANNUITY = "年金保险"
    MOTOR = "机动车保险"
    PROPERTY = "财产保险"
    PENSION = "养老保险"
    EDUCATION = "教育保险"
    TRAVEL = "旅游保险"
    OTHER = "其他"


PRODUCT_TYPE_CONFIGS: Dict[ProductCategory, Dict] = {
    ProductCategory.LIFE: {
        "keywords": ["人寿", "寿险", "终身", "定期寿险", "终身寿险", "定期寿"],
        "focus_fields": ["waiting_period", "age_min", "age_max", "coverage_period"],
        "scoring_weight": 1.0,
        "default_premium_range": (1000, 50000)
    },
    ProductCategory.HEALTH: {
        "keywords": ["健康", "医疗", "重疾", "百万医疗", "门诊", "住院", "医疗险"],
        "focus_fields": ["coverage", "deductible", "payout_ratio", "amount"],
        "scoring_weight": 1.2,
        "default_premium_range": (500, 20000)
    },
    ProductCategory.ACCIDENT: {
        "keywords": ["意外", "意外险", "意外伤害", "综合意外", "交通意外"],
        "focus_fields": ["coverage", "occupation", "age_max"],
        "scoring_weight": 0.8,
        "default_premium_range": (100, 1000)
    },
    ProductCategory.ANNUITY: {
        "keywords": ["年金", "理财", "返还", "分红", "万能"],
        "focus_fields": ["payment_period", "amount", "yield_rate"],
        "scoring_weight": 1.1,
        "default_premium_range": (5000, 100000)
    },
    ProductCategory.MOTOR: {
        "keywords": ["机动车", "车险", "交强险", "商业险", "车辆"],
        "focus_fields": ["vehicle_type", "seat_count", "usage"],
        "scoring_weight": 0.9,
        "default_premium_range": (1000, 10000)
    },
    ProductCategory.PROPERTY: {
        "keywords": ["财产", "家财", "企业财产", "火灾", "盗抢"],
        "focus_fields": ["property_type", "coverage", "amount"],
        "scoring_weight": 0.9,
        "default_premium_range": (100, 5000)
    },
    ProductCategory.PENSION: {
        "keywords": ["养老", "退休", "养老年金", "商业养老"],
        "focus_fields": ["payment_period", "amount", "start_age"],
        "scoring_weight": 1.1,
        "default_premium_range": (10000, 200000)
    },
    ProductCategory.EDUCATION: {
        "keywords": ["教育", "教育金", "少儿", "学费"],
        "focus_fields": ["age_min", "age_max", "payment_period"],
        "scoring_weight": 1.0,
        "default_premium_range": (1000, 50000)
    },
    ProductCategory.TRAVEL: {
        "keywords": ["旅游", "旅行", "境内旅游", "境外旅游", "观光"],
        "focus_fields": ["duration", "destination", "age_min", "age_max"],
        "scoring_weight": 0.7,
        "default_premium_range": (50, 500)
    },
    ProductCategory.OTHER: {
        "keywords": [],
        "focus_fields": ["coverage", "amount"],
        "scoring_weight": 1.0,
        "default_premium_range": (100, 10000)
    },
}


def get_product_config(category: ProductCategory) -> Dict:
    """
    获取产品配置

    Args:
        category: 产品类别

    Returns:
        dict: 产品配置字典
    """
    return PRODUCT_TYPE_CONFIGS.get(category, PRODUCT_TYPE_CONFIGS[ProductCategory.OTHER])


def classify_product(product_name: str, description: str = "") -> ProductCategory:
    """
    根据产品名称和描述分类产品

    Args:
        product_name: 产品名称
        description: 产品描述

    Returns:
        ProductCategory: 产品类别
    """
    text = f"{product_name} {description}".lower()

    best_match = ProductCategory.OTHER
    best_score = 0

    for category, config in PRODUCT_TYPE_CONFIGS.items():
        if category == ProductCategory.OTHER:
            continue

        score = 0
        for keyword in config["keywords"]:
            if keyword.lower() in text:
                score += 1

        if score > best_score:
            best_match = category
            best_score = score

    return best_match


def get_focus_fields(category: ProductCategory) -> List[str]:
    """
    获取产品类别关注的字段

    Args:
        category: 产品类别

    Returns:
        list: 字段名称列表
    """
    config = get_product_config(category)
    return config.get("focus_fields", [])


def get_scoring_weight(category: ProductCategory) -> float:
    """
    获取产品类别的评分权重

    Args:
        category: 产品类别

    Returns:
        float: 权重值
    """
    config = get_product_config(category)
    return config.get("scoring_weight", 1.0)


def get_premium_range(category: ProductCategory) -> tuple:
    """
    获取产品类别的保费范围

    Args:
        category: 产品类别

    Returns:
        tuple: (最小保费, 最大保费)
    """
    config = get_product_config(category)
    return config.get("default_premium_range", (100, 10000))

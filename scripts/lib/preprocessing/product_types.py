#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
产品类型定义

保险产品类型的完整定义，用于分类和动态 Prompt 生成。
"""
from typing import List, Dict
from .models import ProductType


# 产品类型定义
PRODUCT_TYPES = [
    # 健康险
    ProductType(
        code="critical_illness",
        name="重大疾病险",
        patterns=[r'重大疾病.*?保险', r'重疾险', r'重疾.*?保险'],
        features={'diseases_list': 0.3, 'grading': 0.2, 'waiting_period': 0.1},
        required_fields=['covered_diseases', 'waiting_period', 'payout_ratio']
    ),
    ProductType(
        code="medical_insurance",
        name="医疗保险",
        patterns=[r'医疗.*?保险', r'费用.*?报销', r'医疗保险'],
        features={'deductible': 0.3, 'payout_ratio': 0.3, 'hospital': 0.2},
        required_fields=['coverage', 'deductible', 'payout_ratio', 'limits']
    ),

    # 寿险
    ProductType(
        code="term_life",
        name="定期寿险",
        patterns=[r'定期.*?寿险', r'定期.*?保险'],
        features={'insurance_period': 0.3, 'death_benefit': 0.3},
        required_fields=['insurance_period', 'death_benefit', 'waiting_period']
    ),
    ProductType(
        code="whole_life",
        name="终身寿险",
        patterns=[r'终身.*?寿险', r'终身.*?保险'],
        features={'cash_value': 0.3, 'insurance_period': 0.3},
        required_fields=['insurance_period', 'cash_value', 'death_benefit']
    ),
    ProductType(
        code="universal_life",
        name="万能险",
        patterns=[r'万能.*?保险'],
        features={'account': 0.4, 'settlement_rate': 0.3, 'death_benefit': 0.2},
        required_fields=['account_management', 'settlement_rate', 'death_benefit']
    ),
    ProductType(
        code="annuity",
        name="年金保险",
        patterns=[r'年金.*?保险', r'养老金'],
        features={'annuity_period': 0.3, 'annuity_amount': 0.3},
        required_fields=['annuity_period', 'annuity_amount', 'insurance_period']
    ),

    # 意外险
    ProductType(
        code="accident_insurance",
        name="意外伤害保险",
        patterns=[r'意外.*?保险', r'意外险'],
        features={'accident_scope': 0.3, 'payout_ratio': 0.3},
        required_fields=['accident_scope', 'payout_ratio', 'waiting_period']
    ),

    # 默认
    ProductType(
        code="life_insurance",
        name="人身保险",
        patterns=[r'保险', r'条款'],
        features={'insurance_period': 0.2, 'waiting_period': 0.2},
        required_fields=['product_name', 'insurance_company', 'insurance_period', 'waiting_period']
    ),
]


# 提取重点映射
EXTRACTION_FOCUS_MAP = {
    'critical_illness': ['病种清单', '等待期', '赔付分级', '赔付比例'],
    'medical_insurance': ['保障范围', '免赔额', '赔付比例', '医院分级', '限额'],
    'universal_life': ['保单账户', '结算利率', '保额调整', '部分领取', '追加保费'],
    'term_life': ['保险期间', '身故保险金', '等待期', '缴费方式'],
    'whole_life': ['保险期间', '现金价值', '身故保险金', '缴费方式'],
    'annuity': ['年金领取方式', '年金领取金额', '保险期间', '保证期间'],
    'accident_insurance': ['意外伤害范围', '赔付比例', '等待期', '责任免除'],
    'life_insurance': ['产品基本信息', '保险责任', '责任免除', '等待期'],
}


# 输出 Schema 模板
OUTPUT_SCHEMA_TEMPLATES = {
    'critical_illness': {
        "product_info": {
            "product_name": "产品名称",
            "insurance_company": "保险公司",
            "waiting_period": "等待期天数"
        },
        "covered_diseases": [
            {
                "disease_name": "疾病名称",
                "disease_grade": "轻症/中症/重症",
                "payout_ratio": 0.5,
                "waiting_period": 90
            }
        ]
    },
    'medical_insurance': {
        "product_info": {
            "product_name": "产品名称",
            "insurance_company": "保险公司"
        },
        "coverage": {
            "inpatient": "住院保障说明",
            "outpatient": "门诊保障说明",
            "emergency": "急诊保障说明"
        },
        "deductible": {
            "general": "一般免赔额",
            "by_hospital_grade": {
                "grade_a": "三级医院免赔额",
                "grade_b": "二级医院免赔额"
            }
        },
        "payout_ratio": {
            "by_hospital_grade": {
                "grade_a": 0.9,
                "grade_b": 0.8
            }
        },
        "limits": {
            "annual_limit": "年度总限额",
            "per_claim_limit": "单次限额"
        }
    },
    'universal_life': {
        "product_info": {
            "product_name": "产品名称",
            "insurance_company": "保险公司",
            "guaranteed_interest_rate": "保证利率",
            "current_interest_rate": "当前利率"
        },
        "account_management": {
            "initial_premium": "初始保费",
            "minimum_premium": "最低保费",
            "add_premium_rules": "追加保费规则",
            "partial_withdrawal_rules": "部分领取规则"
        },
        "death_benefit": {
            "option_a": "选项A说明",
            "option_b": "选项B说明"
        }
    },
    'life_insurance': {
        "product_info": {
            "product_name": "产品名称",
            "insurance_company": "保险公司",
            "product_type": "产品类型",
            "insurance_period": "保险期间",
            "payment_method": "缴费方式",
            "waiting_period": "等待期天数"
        },
        "clauses": [
            {
                "number": "条款编号",
                "title": "条款标题",
                "text": "条款内容"
            }
        ],
        "pricing_params": {
            "premium_rate": "保费",
            "interest_rate": "预定利率",
            "expense_rate": "费用率"
        }
    },
}


def get_extraction_focus(product_type: str) -> List[str]:
    """获取提取重点"""
    return EXTRACTION_FOCUS_MAP.get(product_type, ['产品基本信息', '保险责任'])


def get_output_schema(product_type: str) -> Dict:
    """获取输出 Schema"""
    return OUTPUT_SCHEMA_TEMPLATES.get(product_type, OUTPUT_SCHEMA_TEMPLATES['life_insurance'])

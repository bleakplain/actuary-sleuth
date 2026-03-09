#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
规则提取器模块

使用预定义的正则表达式模式快速提取保险产品文档信息。
"""
import re
import logging
from typing import Dict, Any


logger = logging.getLogger(__name__)


class RuleExtractor:
    """规则提取器"""

    # 正则表达式模式
    PATTERNS = {
        # 产品信息
        'product_name': [
            r'^#\s*(.+?)(?:\s|条款|保险|产品|\n)',
            r'产品名称[：:]\s*([^\n]+)',
            r'保险产品名称[：:]\s*([^\n]+)',
            r'^(.+?)保险条款'
        ],
        'product_type': [
            r'产品类型[：:]\s*([^\n]+)',
            r'###\s*##\s*(.+?)险',
            r'险种[：:]\s*([^\n]+)'
        ],
        'insurance_company': [
            r'(.+?)人寿保险股份有限公司',
            r'(.+?)保险有限公司',
            r'保险公司[：:]\s*([^\n]+)',
            r'承保公司[：:]\s*([^\n]+)'
        ],

        # 投保信息
        'age_min': [
            r'(\d+)周?岁',
            r'出生满\s*(\d+)\s*日',
            r'投保年龄.*?(\d+)\s*周?岁'
        ],
        'age_max': [
            r'至\s*(\d+)\s*周岁',
            r'(\d+)周岁以下'
        ],
        'occupation': [
            r'职业类别[：:]\s*([^\n]+)',
            r'职业等级[：:]\s*([^\n]+)'
        ],

        # 保险期间
        'insurance_period': [
            r'保险期间[：:]\s*([^\n]+)',
            r'保障期限[：:]\s*([^\n]+)',
            r'保险期限[：:]\s*([^\n]+)'
        ],

        # 缴费方式
        'payment_method': [
            r'缴费方式[：:]\s*([^\n]+)',
            r'交费方式[：:]\s*([^\n]+)'
        ],
        'payment_period': [
            r'缴费期间[：:]\s*([^\n]+)',
            r'交费期间[：:]\s*([^\n]+)'
        ],

        # 等待期
        'waiting_period': [
            r'等待期[：:]\s*(\d+)[日天年]',
            r'观察期[：:]\s*(\d+)[日天年]',
            r'等待期.*?(\d+)[日天]'
        ],

        # 费率信息
        'premium_rate': [
            r'年交\s*([0-9.]+)\s*元',
            r'保费[：:]\s*([0-9.]+)'
        ],
        'expense_rate': [
            r'费用率[：:]\s*([0-9.]+)%',
            r'附加费用率[：:]\s*([0-9.]+)%'
        ],
        'interest_rate': [
            r'预定利率[：:]\s*([0-9.]+)%',
            r'定价利率[：:]\s*([0-9.]+)%',
            r'年利率[：:]\s*([0-9.]+)%'
        ],

        # 犹豫期
        'cooling_period': [
            r'犹豫期[：:]\s*(\d+)[日天]'
        ],

        # 现金价值
        'cash_value': [
            r'现金价值[：:]\s*([^\n]+)',
            r'退保金[：:]\s*([^\n]+)'
        ]
    }

    def extract(self, document: str) -> Dict[str, Any]:
        """
        执行规则提取

        Args:
            document: 文档内容

        Returns:
            提取结果字典
        """
        result = {}
        confidence = {}

        for field, patterns in self.PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, document, re.MULTILINE | re.IGNORECASE)
                if match:
                    result[field] = match.group(1).strip()
                    confidence[field] = self._calculate_confidence(pattern, match)
                    break

        return result

    def _calculate_confidence(self, pattern: str, match) -> float:
        """计算置信度"""
        base = 0.85

        if match.group(1).strip():
            base += 0.10

        if '产品名称' in pattern or '保险公司' in pattern:
            base += 0.05

        return min(base, 1.0)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
规则提取器模块

使用预定义的正则表达式模式快速提取保险产品文档信息。
"""
import json
import logging
import re
from pathlib import Path
from typing import Dict, Any, Optional


logger = logging.getLogger(__name__)


# 默认正则表达式模式
DEFAULT_PATTERNS = {
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


class RuleExtractor:
    """规则提取器"""

    def __init__(self, patterns: Optional[Dict[str, list]] = None, config_path: Optional[Path] = None):
        """
        初始化规则提取器

        Args:
            patterns: 正则模式字典，默认使用 DEFAULT_PATTERNS
            config_path: 从 JSON 文件加载模式
        """
        if config_path:
            self.patterns = self._load_patterns_from_file(config_path)
        elif patterns:
            self.patterns = patterns
        else:
            self.patterns = DEFAULT_PATTERNS

    def _load_patterns_from_file(self, config_path: Path) -> Dict[str, list]:
        """从 JSON 文件加载正则模式"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"加载规则配置失败 {config_path}: {e}，使用默认模式")
            return DEFAULT_PATTERNS

    def extract(self, document: str) -> Dict[str, Any]:
        """
        执行规则提取

        Args:
            document: 文档内容

        Returns:
            提取结果字典
        """
        result = {}

        for field, patterns in self.patterns.items():
            for pattern in patterns:
                match = re.search(pattern, document, re.MULTILINE | re.IGNORECASE)
                if match:
                    result[field] = match.group(1).strip()
                    break

        return result

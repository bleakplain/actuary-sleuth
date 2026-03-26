#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
正则提取器

使用正则表达式和模式匹配快速提取常见字段。
成本最低，速度最快，适合标准化格式的文档。
"""
import re
import logging
import time
from typing import Dict, Any, Set

from .base import Extractor, ExtractionResult
from ..utils.constants import config


logger = logging.getLogger(__name__)


class RegexExtractor(Extractor):
    """正则提取器 - 最低成本，最快速度"""

    name = "regex"
    description = "使用正则表达式提取标准化字段"

    # 产品名称模式
    PRODUCT_NAME_PATTERNS = [
        r'产品名称[：:]\s*([^\n]{2,30})',
        r'产品为[：:]\s*([^\n]{2,30})',
        r'^([^\n]{2,20}?保险)\s',
    ]

    # 保险公司模式
    COMPANY_PATTERNS = [
        r'([^\n]{2,15}?保险公司)',
        r'承保公司[：:]\s*([^\n]{2,30})',
        r'保险公司[：:]\s*([^\n]{2,30})',
    ]

    # 保险期间模式
    PERIOD_PATTERNS = [
        r'保险期间[：:]\s*([^\n]{2,50})',
        r'保障期限[：:]\s*([^\n]{2,50})',
        r'至(\d{2,4}岁)',
        r'(\d+)年',
    ]

    # 等待期模式
    WAITING_PERIOD_PATTERNS = [
        r'等待期[：:]\s*([^\n]{2,30})',
        r'观察期[：:]\s*([^\n]{2,30})',
        r'(\d+)\s*天',
    ]

    def can_handle(self, document: str, structure: Dict[str, Any]) -> bool:
        """始终可以尝试规则提取"""
        return True

    def extract(self, document: str, structure: Dict[str, Any],
                required_fields: Set) -> ExtractionResult:
        """执行规则提取"""
        start_time = time.time()
        result = {}

        # 只提取前 3000 字符（通常关键信息在前部）
        sample = document[:3000]

        # 提取各字段
        if 'product_name' in required_fields:
            result['product_name'] = self._extract_product_name(sample)

        if 'insurance_company' in required_fields:
            result['insurance_company'] = self._extract_company(sample)

        if 'insurance_period' in required_fields:
            result['insurance_period'] = self._extract_period(sample)

        if 'waiting_period' in required_fields:
            result['waiting_period'] = self._extract_waiting_period(sample)

        duration = time.time() - start_time
        confidence = self.get_confidence(result, required_fields)

        logger.info(f"规则提取完成: 耗时 {duration:.3f}s, "
                   f"提取字段 {len(result)}/{len(required_fields)}, "
                   f"置信度 {confidence:.2f}")

        return ExtractionResult(
            data=result,
            confidence=confidence,
            extractor=self.name,
            duration=duration,
            metadata={'fields_extracted': list(result.keys())}
        )

    def _extract_product_name(self, text: str) -> str:
        """提取产品名称"""
        for pattern in self.PRODUCT_NAME_PATTERNS:
            match = re.search(pattern, text, re.MULTILINE)
            if match:
                return match.group(1).strip()
        return ""

    def _extract_company(self, text: str) -> str:
        """提取保险公司"""
        for pattern in self.COMPANY_PATTERNS:
            match = re.search(pattern, text, re.MULTILINE)
            if match:
                return match.group(1).strip()
        return ""

    def _extract_period(self, text: str) -> str:
        """提取保险期间"""
        for pattern in self.PERIOD_PATTERNS:
            match = re.search(pattern, text, re.MULTILINE)
            if match:
                return match.group(1).strip()
        return ""

    def _extract_waiting_period(self, text: str) -> str:
        """提取等待期"""
        for pattern in self.WAITING_PERIOD_PATTERNS:
            match = re.search(pattern, text, re.MULTILINE)
            if match:
                return match.group(1).strip()
        return ""

    def estimate_cost(self, document: str) -> float:
        """规则提取成本极低"""
        return 0.01

    def estimate_duration(self, document: str) -> float:
        """规则提取速度极快"""
        return 0.1

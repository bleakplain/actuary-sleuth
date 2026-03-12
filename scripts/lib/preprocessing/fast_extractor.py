#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快速提取器

用于快速通道的低成本提取，使用 Few-shot Prompt。
"""
import logging
import re
from typing import Dict, List, Any, Optional

from .models import NormalizedDocument, ExtractResult
from .utils.json_parser import parse_llm_json_response
from .utils.constants import config


logger = logging.getLogger(__name__)


class FastExtractionFailed(Exception):
    """快速通道提取失败"""
    pass


class FastExtractor:
    """快速提取器 - 用于快速通道"""

    # Few-shot 提取模板
    FEW_SHOT_EXTRACT = """你是保险产品信息提取专家。

**任务**: 从以下文档片段中提取核心信息

**示例 1**:
输入: "# 平安福终身寿险\n平安人寿保险股份有限公司\n保险期间：终身\n等待期：90天"
输出: {{"product_name": "平安福终身寿险", "insurance_company": "平安人寿保险股份有限公司", "insurance_period": "终身", "waiting_period": 90}}

**示例 2**:
输入: "产品名称：国寿鑫享鸿福年金保险\n中国人寿保险股份有限公司\n保险期间：20年\n缴费方式：年交"
输出: {{"product_name": "国寿鑫享鸿福年金保险", "insurance_company": "中国人寿保险股份有限公司", "insurance_period": "20年", "payment_method": "年交"}}

**现在请提取**:
输入: {document}

**输出要求**:
- 只返回 JSON，不要其他内容
- 如果字段不存在，使用 null
- 日期格式统一为数字（如：90 表示 90 天）

**输出**: """

    def __init__(self, llm_client):
        self.llm_client = llm_client

    def extract(self,
                document: NormalizedDocument,
                required_fields: List[str]) -> ExtractResult:
        """
        快速提取

        Args:
            document: 规范化文档
            required_fields: 需要提取的字段

        Returns:
            ExtractResult

        Raises:
            FastExtractionFailed: 提取失败时
        """
        # 1. 使用 Few-shot Prompt 提取
        prompt = self.FEW_SHOT_EXTRACT.format(
            document=document.content[:config.FAST_CONTENT_MAX_CHARS]
        )

        try:
            response = self.llm_client.generate(
                prompt,
                max_tokens=config.FAST_EXTRACTION_MAX_TOKENS,
                temperature=0.1
            )

            result = parse_llm_json_response(response, strict=True)

            # 2. 补充提取（如果有缺失的必需字段）
            missing = [f for f in required_fields if f not in result]
            if missing:
                result = self._supplement_extract(document, missing, result)

            return ExtractResult(
                data=result,
                confidence={k: config.DEFAULT_FAST_CONFIDENCE for k in result},
                provenance={k: config.PROVENANCE_FAST_LLM for k in result},
                metadata={config.EXTRACTION_MODE: 'fast'}
            )

        except Exception as e:
            logger.warning(f"快速提取失败: {e}")
            raise FastExtractionFailed(f"快速通道提取失败: {e}")

    def _supplement_extract(self,
                           document: NormalizedDocument,
                           missing_fields: List[str],
                           current_result: Dict) -> Dict:
        """补充提取缺失字段"""
        for field in missing_fields:
            value = self._extract_by_regex(document.content, field)
            if value:
                current_result[field] = value

        return current_result

    def _extract_by_regex(self, document: str, field: str) -> Optional[str]:
        """使用正则表达式提取字段"""
        patterns = {
            'product_name': [
                r'产品名称[：:：]\s*([^\n]+)',
                r'^#+\s*([^\n]+?)(?:\s|条款|保险|产品)',
            ],
            'insurance_company': [
                r'([^。\n]{5,30})(?:人寿|财产|健康|养老)\s*保险',
                r'(?:保险公司|承保机构)[：:：]\s*([^。\n]{5,50})',
            ],
            'insurance_period': [
                r'保险期间[：:：]\s*([^\n]+)',
                r'保障期限[：:：]\s*([^\n]+)',
            ],
            'waiting_period': [
                r'等待期[：:：]\s*(\d+)[日天年]',
                r'观察期[：:：]\s*(\d+)[日天年]',
            ],
            'payment_method': [
                r'缴费方式[：:：]\s*([^\n]+)',
                r'交费方式[：:：]\s*([^\n]+)',
            ],
        }

        field_patterns = patterns.get(field, [])
        for pattern in field_patterns:
            match = re.search(pattern, document, re.MULTILINE | re.IGNORECASE)
            if match:
                return match.group(1).strip()

        return None

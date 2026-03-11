#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM 提取器

使用大语言模型从保险文档中提取结构化信息。
"""
import json
import logging
import re
from typing import Dict, Any

from lib.llm_client import BaseLLMClient
from lib.constants import MAX_DOCUMENT_LENGTH, LLM_MAX_TOKENS, LLM_DEFAULT_CONFIDENCE
from lib.exceptions import LLMParseException
from lib.prompts import format_extract_document_prompt, format_extract_chunk_prompt
from .models import ExtractResult


logger = logging.getLogger(__name__)


class LLMExtractor:
    """LLM提取器"""

    def __init__(self, client: BaseLLMClient, max_tokens: int = LLM_MAX_TOKENS):
        self.client = client
        self.max_tokens = max_tokens

    def extract(self, document: str) -> ExtractResult:
        """
        提取文档信息

        Args:
            document: 文档内容

        Returns:
            ExtractResult
        """
        document_to_process = self._truncate_document(document)
        prompt = format_extract_document_prompt(document_to_process)

        try:
            response = self._call_llm(prompt)
            llm_data = self._parse_response(response)
        except LLMParseException as e:
            logger.warning(f"LLM提取失败，返回空结果: {e.message}")
            llm_data = {}

        return ExtractResult(
            data=llm_data,
            confidence={k: LLM_DEFAULT_CONFIDENCE for k in llm_data},
            provenance={k: 'llm' for k in llm_data}
        )

    def extract_chunk(self, chunk: str, index: int, total: int) -> Dict[str, Any]:
        """
        提取单个文档块的信息

        Args:
            chunk: 文档块内容
            index: 当前块索引 (0-based)
            total: 总块数

        Returns:
            提取的数据字典，失败时返回空字典
        """
        prompt = format_extract_chunk_prompt(chunk, index, total)

        try:
            response = self._call_llm(prompt)
            return self._parse_response(response)
        except LLMParseException as e:
            logger.warning(f"Chunk {index+1}/{total} LLM提取失败: {e.message}")
            return {}

    def _truncate_document(self, document: str) -> str:
        """截断文档到合理长度"""
        if len(document) <= MAX_DOCUMENT_LENGTH:
            return document

        # 查找条款开始位置
        patterns = [
            r'第[一二三四五六七八九十]条',
            r'#+\s*[\u4e00-\u9fa5]+保险条款',
            r'1\.[1-9]',
        ]

        for pattern in patterns:
            match = re.search(pattern, document)
            if match:
                start = max(0, match.start() - 100)
                return document[start:start + MAX_DOCUMENT_LENGTH]

        # 未找到，直接截断
        return document[:MAX_DOCUMENT_LENGTH]

    def _call_llm(self, prompt: str) -> str:
        """调用LLM（由外部控制重试）"""
        try:
            response = self.client.generate(
                prompt,
                max_tokens=self.max_tokens,
                temperature=0
            )
            return response
        except Exception as e:
            logger.error(f"LLM调用失败: {e}")
            raise

    def _parse_response(self, response: str) -> Dict[str, Any]:
        """解析LLM响应"""
        try:
            # 尝试提取JSON
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(1))

            cleaned = response.strip()
            if cleaned.startswith('{') and cleaned.endswith('}'):
                return json.loads(cleaned)

            # 查找完整JSON对象
            first_brace = cleaned.find('{')
            last_brace = cleaned.rfind('}')
            if first_brace != -1 and last_brace != -1:
                return json.loads(cleaned[first_brace:last_brace + 1])

            # 无法解析，抛出异常
            logger.debug(f"LLM响应解析失败: {response[:200]}")
            raise LLMParseException(f"无法从LLM响应中提取JSON: {response[:100]}")

        except json.JSONDecodeError as e:
            logger.debug(f"LLM响应JSON解析失败: {e}")
            raise LLMParseException(f"JSON解析失败: {str(e)}")

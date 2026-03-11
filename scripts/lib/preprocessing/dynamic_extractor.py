#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动态提取器

用于动态通道的完整提取，使用动态 Prompt 和专用提取器。
"""
import json
import logging
import re
from typing import Dict, List, Any, Optional

from .models import NormalizedDocument, ExtractResult
from .prompt_builder import PromptBuilder
from .product_types import get_extraction_focus, get_output_schema


logger = logging.getLogger(__name__)


class PremiumTableExtractor:
    """费率表专用提取器"""

    TABLE_PROMPT = """你是保险费率表提取专家。

**任务**: 从以下表格内容中提取结构化数据。

**要求**:
1. 识别表格的列名和单位
2. 提取所有数据行
3. 识别费率的计算方式

**输出格式** (JSON):
{{
    "headers": ["年龄", "性别", "费率"],
    "units": {{"age": "岁", "rate": "元/份"}},
    "data": [
        {{"age": "0", "gender": "男", "rate": 1200}},
        {{"age": "0", "gender": "女", "rate": 1100}}
    ]
}}

表格内容:
{table_content}
"""

    def __init__(self, llm_client):
        self.llm_client = llm_client

    def extract(self, content: str) -> Dict[str, Any]:
        """提取费率表"""
        prompt = self.TABLE_PROMPT.format(table_content=content[:3000])

        try:
            response = self.llm_client.generate(
                prompt,
                max_tokens=2000,
                temperature=0.1
            )
            return self._parse_response(response)
        except Exception as e:
            logger.warning(f"费率表提取失败: {e}")
            return {}

    def _parse_response(self, response: str) -> Dict[str, Any]:
        """解析响应"""
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(1))

        cleaned = response.strip()
        if cleaned.startswith('{') and cleaned.endswith('}'):
            return json.loads(cleaned)

        return {}


class ClauseExtractor:
    """条款专用提取器"""

    CLAUSE_PROMPT = """你是保险条款提取专家。

**任务**: 从以下内容中提取所有条款。

**要求**:
1. 提取每个条款的完整文本
2. 识别条款编号或标题
3. 过滤非条款内容（如"阅读指引"、"投保须知"）

**输出格式** (JSON):
{{
    "clauses": [
        {{
            "number": "第一条",
            "title": "保险责任",
            "text": "本合同承担的保险责任为..."
        }}
    ]
}}

条款内容:
{clause_content}
"""

    def __init__(self, llm_client):
        self.llm_client = llm_client

    def extract(self, content: str) -> List[Dict[str, Any]]:
        """提取条款"""
        prompt = self.CLAUSE_PROMPT.format(clause_content=content[:8000])

        try:
            response = self.llm_client.generate(
                prompt,
                max_tokens=4000,
                temperature=0.1
            )
            result = self._parse_response(response)
            return result.get('clauses', [])
        except Exception as e:
            logger.warning(f"条款提取失败: {e}")
            return []

    def _parse_response(self, response: str) -> Dict[str, Any]:
        """解析响应"""
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(1))

        cleaned = response.strip()
        if cleaned.startswith('{') and cleaned.endswith('}'):
            return json.loads(cleaned)

        return {}


class DynamicExtractor:
    """动态提取器"""

    def __init__(self, llm_client):
        self.llm_client = llm_client
        self.prompt_builder = PromptBuilder()
        self.specialized_extractors = {
            'premium_table': PremiumTableExtractor(llm_client),
            'clauses': ClauseExtractor(llm_client),
        }

    def extract(self,
                document: NormalizedDocument,
                product_type: str,
                is_hybrid: bool,
                required_fields: List[str]) -> ExtractResult:
        """结构化提取"""

        # 1. 构建 Prompt
        prompt = self.prompt_builder.build(
            product_type=product_type,
            required_fields=required_fields,
            extraction_focus=get_extraction_focus(product_type),
            output_schema=get_output_schema(product_type),
            is_hybrid=is_hybrid
        )

        # 2. 添加文档内容 (增加到15000字符)
        full_prompt = f"{prompt}\n\n文档内容:\n{document.content[:15000]}"

        # 3. 调用 LLM (增加到6000 tokens)
        try:
            response = self.llm_client.generate(
                full_prompt,
                max_tokens=6000,
                temperature=0.1
            )

            result = self._parse_response(response)

        except Exception as e:
            logger.error(f"动态提取失败: {e}")
            result = {}

        # 4. 专用提取器（按需）
        if 'premium_table' in required_fields or 'pricing_params' in required_fields:
            if document.profile.has_premium_table:
                premium_result = self.specialized_extractors['premium_table'].extract(
                    document.content
                )
                if premium_result:
                    result['premium_table'] = premium_result

        if 'clauses' in required_fields:
            clause_result = self.specialized_extractors['clauses'].extract(
                document.content
            )
            if clause_result:
                result['clauses'] = clause_result

        return ExtractResult(
            data=result,
            confidence={k: 0.75 for k in result},
            provenance={k: 'dynamic_llm' for k in result},
            metadata={
                'extraction_mode': 'dynamic',
                'product_type': product_type,
                'is_hybrid': is_hybrid
            }
        )

    def _parse_response(self, response: str) -> Dict[str, Any]:
        """解析 LLM 响应"""
        # 尝试提取 JSON
        json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
        if json_match:
            return json.loads(json_match.group(1))

        cleaned = response.strip()
        if cleaned.startswith('{') and cleaned.endswith('}'):
            return json.loads(cleaned)

        # 查找完整 JSON 对象
        first_brace = cleaned.find('{')
        last_brace = cleaned.rfind('}')
        if first_brace != -1 and last_brace != -1:
            return json.loads(cleaned[first_brace:last_brace + 1])

        logger.warning(f"无法解析 LLM 响应: {response[:200]}")
        return {}

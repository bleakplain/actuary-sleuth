#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
动态提取器

用于动态通道的完整提取，使用动态 Prompt 和专用提取器。
支持大文件分块处理。
"""
import json
import logging
from typing import Dict, List, Any, Optional

from .models import NormalizedDocument, ExtractResult
from .classifier import ProductClassifier
from .prompt_builder import PromptBuilder
from .product_types import get_extraction_focus, get_output_schema
from .utils.json_parser import parse_llm_json_response
from .utils.constants import config


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
        prompt = self.TABLE_PROMPT.format(
            table_content=content[:config.TABLE_CONTENT_MAX_CHARS]
        )

        try:
            response = self.llm_client.generate(
                prompt,
                max_tokens=config.TABLE_EXTRACTION_MAX_TOKENS,
                temperature=0.1
            )
            return parse_llm_json_response(response)
        except Exception as e:
            logger.warning(f"费率表提取失败: {e}")
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
        prompt = self.CLAUSE_PROMPT.format(
            clause_content=content[:config.CLAUSE_CONTENT_MAX_CHARS]
        )

        try:
            response = self.llm_client.generate(
                prompt,
                max_tokens=config.CLAUSE_EXTRACTION_MAX_TOKENS,
                temperature=0.1
            )
            result = parse_llm_json_response(response)
            return result.get('clauses', [])
        except Exception as e:
            logger.warning(f"条款提取失败: {e}")
            return []


class DynamicExtractor:
    """动态提取器 - 支持大文件自动分块处理"""

    def __init__(self, llm_client, classifier: ProductClassifier):
        self.llm_client = llm_client
        self.classifier = classifier
        self.prompt_builder = PromptBuilder()
        self.specialized_extractors = {
            config.EXTRACTOR_PREMIUM_TABLE: PremiumTableExtractor(llm_client),
            config.EXTRACTOR_CLAUSES: ClauseExtractor(llm_client),
        }

    def extract(self,
                document: NormalizedDocument,
                required_fields: List[str]) -> ExtractResult:
        """结构化提取"""

        # 1. 获取产品类型信息（一次性分类，避免重复）
        classifications = self.classifier.classify(document.content)
        product_type = classifications[0][0] if classifications else 'life_insurance'
        is_hybrid = len(classifications) > 1 and classifications[1][1] > config.HYBRID_PRODUCT_THRESHOLD

        # 2. 构建 Prompt
        prompt = self.prompt_builder.build(
            product_type=product_type,
            required_fields=required_fields,
            extraction_focus=get_extraction_focus(product_type),
            output_schema=get_output_schema(product_type),
            is_hybrid=is_hybrid
        )

        # 3. 执行提取（自动判断是否分块）
        content_length = len(document.content)
        if content_length > config.DYNAMIC_CONTENT_MAX_CHARS:
            logger.info(f"文档较大 ({content_length} 字符)，使用分块提取")
            result = self._extract_chunked(document, prompt)
        else:
            result = self._extract_single(document, prompt)

        # 4. 专用提取器（按需）
        if config.EXTRACTOR_PREMIUM_TABLE in required_fields or 'pricing_params' in required_fields:
            if document.profile.has_premium_table:
                premium_result = self.specialized_extractors[config.EXTRACTOR_PREMIUM_TABLE].extract(
                    document.content
                )
                if premium_result:
                    result[config.EXTRACTOR_PREMIUM_TABLE] = premium_result

        if config.EXTRACTOR_CLAUSES in required_fields:
            clause_result = self.specialized_extractors[config.EXTRACTOR_CLAUSES].extract(
                document.content
            )
            if clause_result:
                result[config.EXTRACTOR_CLAUSES] = clause_result

        return ExtractResult(
            data=result,
            confidence={k: config.DEFAULT_DYNAMIC_CONFIDENCE for k in result},
            provenance={k: config.PROVENANCE_DYNAMIC_LLM for k in result},
            metadata={
                config.EXTRACTION_MODE: 'dynamic',
                config.PRODUCT_TYPE: product_type,
                config.IS_HYBRID: is_hybrid,
                'content_length': content_length
            }
        )

    def _extract_single(self, document: NormalizedDocument, prompt: str) -> Dict[str, Any]:
        """单次提取（标准文档）"""
        full_prompt = f"{prompt}\n\n文档内容:\n{document.content}"

        try:
            response = self.llm_client.generate(
                full_prompt,
                max_tokens=config.DYNAMIC_EXTRACTION_MAX_TOKENS,
                temperature=0.1
            )
            return parse_llm_json_response(response)

        except Exception as e:
            logger.error(f"动态提取失败: {e}")
            return {}

    def _extract_chunked(self, document: NormalizedDocument, base_prompt: str) -> Dict[str, Any]:
        """分块提取（大文档）"""
        content = document.content
        chunk_size = config.DYNAMIC_CONTENT_MAX_CHARS
        overlap = 1000  # 块之间重叠 1000 字符以保持上下文

        # 分块
        chunks = []
        start = 0
        while start < len(content):
            end = start + chunk_size
            chunks.append(content[start:end])
            start = end - overlap if end < len(content) else end

        logger.info(f"文档分为 {len(chunks)} 块进行处理")

        # 第一块：完整提取
        first_prompt = f"{base_prompt}\n\n文档内容:\n{chunks[0]}"
        try:
            response = self.llm_client.generate(
                first_prompt,
                max_tokens=config.DYNAMIC_EXTRACTION_MAX_TOKENS,
                temperature=0.1
            )
            result = parse_llm_json_response(response)
            logger.info(f"第 1/{len(chunks)} 块提取完成")
        except Exception as e:
            logger.error(f"第 1 块提取失败: {e}")
            result = {}

        # 后续块：补充提取
        for i, chunk in enumerate(chunks[1:], 1):
            supplement_prompt = f"""你是保险产品信息提取专家。

**任务**: 从以下文档片段中补充提取信息。

**已有提取结果**:
```json
{json.dumps(result, ensure_ascii=False, indent=2)}
```

**新文档片段**:
{chunk}

**要求**:
1. 只提取已有结果中缺失的字段
2. 如果已有字段的值不完整，用新信息补充
3. 输出格式为 JSON，只包含新增或更新的字段

**输出格式** (JSON):
{{}}
"""

            try:
                response = self.llm_client.generate(
                    supplement_prompt,
                    max_tokens=config.DYNAMIC_EXTRACTION_MAX_TOKENS,
                    temperature=0.1
                )
                chunk_result = parse_llm_json_response(response)

                # 合并结果
                for key, value in chunk_result.items():
                    if key not in result:
                        result[key] = value
                    elif isinstance(value, dict) and isinstance(result.get(key), dict):
                        result[key].update(value)
                    elif isinstance(value, list) and isinstance(result.get(key), list):
                        # 去重合并列表
                        existing = {json.dumps(item, ensure_ascii=False) for item in result[key]}
                        for item in value:
                            item_str = json.dumps(item, ensure_ascii=False)
                            if item_str not in existing:
                                result[key].append(item)

                logger.info(f"第 {i+1}/{len(chunks)} 块提取完成")

            except Exception as e:
                logger.warning(f"第 {i+1} 块提取失败: {e}")
                continue

        logger.info(f"分块提取完成，共 {len(chunks)} 块，得到 {len(result)} 个字段")
        return result

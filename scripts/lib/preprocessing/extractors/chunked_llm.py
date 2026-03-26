#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分块 LLM 提取器

使用语义分块和详细 Prompt 进行深度提取。
适合复杂、大文档、非标准化格式。
"""
import json
import logging
import re
import time
from typing import Dict, Any, Set, List

from .base import Extractor, ExtractionResult
from ..utils.json_parser import parse_llm_json_response
from ..utils.constants import config


logger = logging.getLogger(__name__)


class ChunkedLLMExtractor(Extractor):
    """分块 LLM 提取器 - 支持大文档分块"""

    name = "chunked_llm"
    description = "使用语义分块和详细 Prompt 深度提取"

    # 语义分块边界模式
    CHUNK_BOUNDARY_PATTERNS = [
        r'\n第[一二三四五六七八九十百千]+\s*[章节条款][^\n]*\n',
        r'\n#{1,2}\s+[^\n]+\n',
        r'\n\*\*(\d+\.\d+)\*\*\s',
        r'\n第[一二三四五六七八九十]+\s*条[^\n]*\n',
        r'\n\n+',
    ]

    def __init__(self, llm_client, prompt: str = ""):
        super().__init__(llm_client)
        self.prompt = prompt

    def can_handle(self, document: str, structure: Dict[str, Any]) -> bool:
        """始终可以尝试深度 LLM 提取"""
        return True

    def extract(self, document: str, structure: Dict[str, Any],
                required_fields: Set) -> ExtractionResult:
        """执行深度 LLM 提取"""
        start_time = time.time()

        # 使用 structure 中的 base_prompt，如果没有则使用初始化时的 prompt
        base_prompt = structure.get('base_prompt', self.prompt)

        # 判断是否需要分块
        content_length = len(document)
        if content_length > config.DYNAMIC_CONTENT_MAX_CHARS:
            result = self._extract_chunked(document, base_prompt, structure)
        else:
            result = self._extract_single(document, base_prompt)

        duration = time.time() - start_time
        confidence = self.get_confidence(result, required_fields)

        logger.info(f"深度 LLM 提取完成: 耗时 {duration:.3f}s, "
                   f"提取字段 {len(result)}/{len(required_fields)}, "
                   f"置信度 {confidence:.2f}")

        return ExtractionResult(
            data=result,
            confidence=confidence,
            extractor=self.name,
            duration=duration,
            metadata={
                'content_length': content_length,
                'was_chunked': content_length > config.DYNAMIC_CONTENT_MAX_CHARS,
                'fields_extracted': list(result.keys())
            }
        )

    def _extract_single(self, document: str, base_prompt: str) -> Dict[str, Any]:
        """单次提取（标准文档）"""
        full_prompt = f"{base_prompt}\n\n文档内容:\n{document}"

        try:
            response = self.llm_client.generate(
                full_prompt,
                max_tokens=config.DYNAMIC_EXTRACTION_MAX_TOKENS,
                temperature=0.1
            )
            return parse_llm_json_response(response)

        except (ValueError, KeyError, json.JSONDecodeError) as e:
            logger.error(f"深度 LLM 单次提取失败: {e}")
            return {}

    def _extract_chunked(self, document: str, base_prompt: str,
                         structure: Dict[str, Any]) -> Dict[str, Any]:
        """分块提取（大文档）"""
        chunk_size = config.DYNAMIC_CONTENT_MAX_CHARS
        overlap = config.DYNAMIC_CHUNK_OVERLAP

        # 使用语义结构分析器建议的分块，或回退到语义分块
        suggested_chunks = structure.get('suggested_chunks', [])
        if suggested_chunks and len(suggested_chunks) > 1:
            chunks = [document[start:end] for start, end in
                     [(c['start'], c['end']) for c in suggested_chunks]]
            logger.info(f"使用语义结构分析建议的分块，共 {len(chunks)} 块")
        else:
            chunks = self._semantic_chunking(document, chunk_size, overlap)
            logger.info(f"使用语义分块，共 {len(chunks)} 块")

        # 估算条款数量以调整 token 限制
        estimated_clauses = len(structure.get('clauses', []))
        max_tokens = (getattr(config, 'DYNAMIC_EXTRACTION_MAX_TOKENS_LARGE', 16000)
                     if estimated_clauses > 50 else config.DYNAMIC_EXTRACTION_MAX_TOKENS)

        # 第一块：完整提取
        first_prompt = f"{base_prompt}\n\n文档内容:\n{chunks[0]}"
        try:
            response = self.llm_client.generate(first_prompt, max_tokens=max_tokens, temperature=0.1)
            result = parse_llm_json_response(response)
            logger.info(f"第 1/{len(chunks)} 块提取完成，得到 {len(result)} 个字段")
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            logger.error(f"第 1 块提取失败: {e}")
            result = {}

        # 后续块：增量提取
        for i, chunk in enumerate(chunks[1:], 1):
            chunk_prompt = self._build_chunk_prompt(chunk, i + 1, len(chunks), base_prompt)

            try:
                response = self.llm_client.generate(
                    chunk_prompt,
                    max_tokens=max_tokens,
                    temperature=0.1
                )
                chunk_result = parse_llm_json_response(response)
                result = self._merge_chunk_result(result, chunk_result)
                logger.info(f"第 {i+1}/{len(chunks)} 块提取完成")
            except (ValueError, KeyError, json.JSONDecodeError) as e:
                logger.warning(f"第 {i+1} 块提取失败: {e}")
                continue

        return result

    def _semantic_chunking(self, content: str, chunk_size: int, overlap: int) -> List[str]:
        """语义分块：优先在章节/条款边界切分"""
        return list(self._semantic_chunking_generator(content, chunk_size, overlap))

    def _semantic_chunking_generator(self, content: str, chunk_size: int, overlap: int):
        """语义分块生成器：按需生成块，减少内存占用"""
        start = 0
        content_len = len(content)

        while start < content_len:
            end = min(start + chunk_size, content_len)

            if end < content_len:
                boundary = self._find_semantic_boundary(content, end, min(end + 1000, content_len))
                end = min(boundary, content_len)

            yield content[start:end]

            start = end - overlap if end < content_len else content_len

    def _find_semantic_boundary(self, content: str, start: int, end: int) -> int:
        """在指定范围内寻找最佳分块边界"""
        for pattern in self.CHUNK_BOUNDARY_PATTERNS:
            matches = list(re.finditer(pattern, content[start:end], re.MULTILINE))
            if matches:
                return start + matches[-1].end()
        return start

    def _build_chunk_prompt(self, chunk: str, chunk_index: int,
                            total_chunks: int, base_prompt: str) -> str:
        """构建分块提取 Prompt

        分块策略：
        - 第1块：提取核心信息（产品名称、公司、保险期间、等待期等）
        - 后续块：增量提取（条款、费率表等），只提取该块可见的内容
        """
        if chunk_index == 1:
            # 第一块：完整提取核心信息
            return f"""你是保险产品信息提取专家。

**任务**: 从以下文档片段中提取产品核心信息。

**文档信息**:
- 文档块 {chunk_index}/{total_chunks}
- 当前片段长度: {len(chunk)} 字符

**文档片段**:
{chunk}

{base_prompt}

**重要说明**:
- 专注提取产品基本信息：产品名称、保险公司、保险期间、等待期、投保年龄
- 如果有条款，请提取前5条重要条款
- 输出JSON格式，只输出JSON内容，不要其他解释

**输出格式** (JSON):
{self._get_output_schema()}
"""
        else:
            # 后续块：增量提取
            return f"""你是保险产品信息提取专家。

**任务**: 从以下文档片段中增量提取信息。

**文档信息**:
- 文档块 {chunk_index}/{total_chunks} (增量提取)
- 当前片段长度: {len(chunk)} 字符

**文档片段**:
{chunk}

{base_prompt}

**重要说明**:
- 这是增量提取，只提取当前片段中的新内容
- 重点提取：条款（编号+标题+内容）、费率表、病种列表
- 如果片段中没有新信息，返回空JSON对象 {{}}
- 输出JSON格式，只输出JSON内容，不要其他解释

**输出格式** (JSON):
{self._get_output_schema()}
"""

    def _get_output_schema(self) -> str:
        """获取输出 schema 说明"""
        return """{
  "product_info": {
    "product_name": "产品名称",
    "insurance_company": "保险公司",
    "product_type": "产品类型",
    "insurance_period": "保险期间",
    "waiting_period": "等待期",
    "coverage_scope": "保障范围"
  },
  "clauses": [
    {
      "number": "条款编号",
      "title": "条款标题",
      "text": "条款内容"
    }
  ],
  "pricing_params": {
    "premium_rate": "费率",
    "expense_rate": "费用率",
    "age_min": "最低年龄",
    "age_max": "最高年龄"
  }
}"""

    def _merge_chunk_result(self, base_result: Dict, chunk_result: Dict) -> Dict:
        """合并分块结果"""
        if not chunk_result:
            return base_result

        merged = base_result.copy()

        for key, value in chunk_result.items():
            if key not in merged:
                merged[key] = value
            elif isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key].update(value)
            elif key == 'clauses' and isinstance(value, list) and isinstance(merged.get(key), list):
                # 条款列表：简单合并（去重在后续阶段处理）
                merged[key].extend(value)

        return merged

    def estimate_cost(self, document: str) -> float:
        """深度 LLM 成本最高"""
        # 可能分块，每个块都要调用 LLM
        estimated_chunks = max(1, len(document) // config.DYNAMIC_CONTENT_MAX_CHARS)
        return estimated_chunks * (len(document) / 2000)

    def estimate_duration(self, document: str) -> float:
        """深度 LLM 耗时最长"""
        return self.estimate_cost(document) * 1.0

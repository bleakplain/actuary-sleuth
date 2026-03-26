#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Few-shot 提取器

使用 Few-shot Prompt 进行快速 LLM 提取。
适合标准化格式、内容较短的文档。
"""
import json
import logging
import time
from typing import Dict, Any, Set

from .base import Extractor, ExtractionResult
from ..classifier import Classifier
from ..prompt_builder import PromptBuilder
from ..product_types import get_few_shot_examples, get_extraction_focus, get_output_schema
from ..utils.json_parser import parse_llm_json_response
from ..utils.constants import config


logger = logging.getLogger(__name__)


class FewShotExtractor(Extractor):
    """Few-shot 提取器 - 使用 Few-shot Prompt"""

    name = "fewshot"
    description = "使用 Few-shot Prompt 快速提取"

    def __init__(self, llm_client, prompt: str = ""):
        super().__init__(llm_client)
        self.prompt = prompt

    def can_handle(self, document: str, structure: Dict[str, Any]) -> bool:
        """
        判断是否可以使用快速 LLM

        适用条件:
        1. 文档长度适中（< 15000 字符）
        2. 结构较为标准化
        """
        if len(document) > config.FAST_CONTENT_MAX_CHARS:
            return False

        is_structured = (
            structure.get('is_structured', False) or
            structure.get('has_headings', False) or
            len(structure.get('sections', [])) > 0
        )

        return is_structured

    def extract(self, document: str, structure: Dict[str, Any],
                required_fields: Set) -> ExtractionResult:
        start_time = time.time()

        prompt = self.prompt
        content = document[:config.FAST_CONTENT_MAX_CHARS]
        full_prompt = f"{prompt}\n\n文档内容:\n{content}"

        try:
            response = self.llm_client.generate(
                full_prompt,
                max_tokens=config.FAST_EXTRACTION_MAX_TOKENS,
                temperature=0.1
            )
            result = parse_llm_json_response(response)

            duration = time.time() - start_time
            confidence = self.get_confidence(result, required_fields)

            logger.info(f"快速 LLM 提取完成: 耗时 {duration:.3f}s, "
                       f"提取字段 {len(result)}/{len(required_fields)}, "
                       f"置信度 {confidence:.2f}")

            return ExtractionResult(
                data=result,
                confidence=confidence,
                extractor=self.name,
                duration=duration,
                metadata={'fields_extracted': list(result.keys())}
            )

        except (ValueError, KeyError, json.JSONDecodeError) as e:
            logger.warning(f"快速 LLM 提取失败: {e}")
            return ExtractionResult(
                data={},
                confidence=0.0,
                extractor=self.name,
                duration=time.time() - start_time,
                metadata={'error': str(e)}
            )

    def estimate_cost(self, document: str) -> float:
        return len(document) / 2000

    def estimate_duration(self, document: str) -> float:
        return self.estimate_cost(document) * 0.5

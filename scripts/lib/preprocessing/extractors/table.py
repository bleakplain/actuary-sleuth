#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
表格提取器

使用代码解析器提取结构化内容（费率表、病种列表等）。
准确率最高，成本极低，适合高度结构化的内容。
"""
import logging
import time
from typing import Dict, Any, Set

from .base import Extractor, ExtractionResult
from ..parser_engine import ParserEngine
from ..utils.constants import config


logger = logging.getLogger(__name__)


class TableExtractor(Extractor):
    """表格提取器 - 用于结构化内容"""

    name = "table"
    description = "使用专用解析器提取结构化内容"

    def __init__(self):
        super().__init__(llm_client=None)
        self.parser_engine = ParserEngine()

    def can_handle(self, document: str, structure: Dict[str, Any]) -> bool:
        """
        判断是否可以使用专用解析器

        适用条件:
        1. 检测到表格结构
        2. 检测到列表结构
        """
        # 检查是否有表格
        has_table = (
            structure.get('has_table', False) or
            '<table>' in document or
            '| ' in document  # Markdown 表格
        )

        # 检查是否有列表
        has_list = (
            '病种' in document or
            '重大疾病' in document or
            any(f'{i}.' in document or f'{i}、' in document for i in range(1, 100))
        )

        return has_table or has_list

    def extract(self, document: str, structure: Dict[str, Any],
                required_fields: Set) -> ExtractionResult:
        """执行专用解析器提取"""
        start_time = time.time()
        result = {}

        # 1. 解析费率表
        if config.EXTRACTOR_PREMIUM_TABLE in required_fields or 'pricing_params' in required_fields:
            if structure.get('has_table', False) or '<table>' in document:
                premium_result = self.parser_engine.parse_premium_table(document)
                if premium_result:
                    result[config.EXTRACTOR_PREMIUM_TABLE] = premium_result
                    logger.info(f"费率表解析成功: {len(premium_result.get('data', []))} 行数据")

        # 2. 解析病种列表
        if 'disease_list' in required_fields or 'clauses' in required_fields:
            if '病种' in document or '重大疾病' in document:
                disease_result = self.parser_engine.parse_disease_list(document)
                if disease_result:
                    result['disease_list'] = disease_result
                    logger.info(f"病种列表解析成功: {len(disease_result)} 个病种")

        # 3. 尝试解析其他结构化内容
        # 如果有表格但没有成功解析，记录日志
        if not result and (structure.get('has_table', False) or '<table>' in document):
            logger.debug("检测到表格但专用解析器未提取到数据")

        duration = time.time() - start_time

        # 计算置信度（专用解析器准确率很高）
        confidence = 0.95 if result else 0.0

        logger.info(f"专用解析器提取完成: 耗时 {duration:.3f}s, "
                   f"提取字段 {len(result)}/{len(required_fields)}, "
                   f"置信度 {confidence:.2f}")

        return ExtractionResult(
            data=result,
            confidence=confidence,
            extractor=self.name,
            duration=duration,
            metadata={'fields_extracted': list(result.keys())}
        )

    def estimate_cost(self, document: str) -> float:
        """专用解析器成本极低"""
        return 0.001

    def estimate_duration(self, document: str) -> float:
        """专用解析器速度极快"""
        return 0.05

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
法规结构化信息提取器

负责从法规文档中提取结构化元数据信息。
"""

import json
import logging
import hashlib
from typing import Dict, Optional

from lib.common.models import RegulationRecord, RegulationLevel, RegulationStatus, ProcessingOutcome
from lib.llm_client import BaseLLMClient, LLMClientFactory

logger = logging.getLogger(__name__)


class InformationExtractor:
    """结构化信息提取器"""

    def __init__(self, llm_client: BaseLLMClient = None):
        """
        Args:
            llm_client: LLM 客户端，默认使用 QA 模型
        """
        self.llm_client = llm_client or LLMClientFactory.get_qa_llm()

    def extract(
        self,
        content: str,
        record: RegulationRecord
    ) -> ProcessingOutcome:
        """
        从文档内容提取结构化信息

        Args:
            content: 清洗后的文档内容
            record: 法规记录（会更新提取到的信息）

        Returns:
            ProcessingOutcome: 提取结果
        """
        try:
            extracted_info = self._extract_with_llm(content)

            # 更新记录
            if extracted_info.get('law_name'):
                record.law_name = extracted_info['law_name']
            if extracted_info.get('effective_date'):
                record.effective_date = extracted_info['effective_date']
            if extracted_info.get('hierarchy_level'):
                record.hierarchy_level = RegulationLevel(extracted_info['hierarchy_level'])
            if extracted_info.get('issuing_authority'):
                record.issuing_authority = extracted_info['issuing_authority']
            if extracted_info.get('category'):
                record.category = extracted_info['category']

            # 质量检查（Phase 1 使用默认值）
            quality_result = self._check_completeness(content, record)
            record.quality_score = quality_result.get('quality_score', 0.5)
            record.status = RegulationStatus.EXTRACTED

            return ProcessingOutcome(
                success=True,
                regulation_id=self._generate_regulation_id(record),
                record=record,
                errors=[],
                warnings=quality_result.get('issues', []),
                processor="preprocessing.extractor"
            )

        except Exception as e:
            logger.error(f"信息提取失败: {e}")
            record.status = RegulationStatus.FAILED
            return ProcessingOutcome(
                success=False,
                regulation_id="",
                record=record,
                errors=[str(e)],
                warnings=[],
                processor="preprocessing.extractor"
            )

    def _extract_with_llm(self, content: str) -> Dict[str, Optional[str]]:
        """使用 LLM 提取结构化信息"""
        from .regulation_prompts import EXTRACTION_SYSTEM_PROMPT

        messages = [
            {'role': 'system', 'content': EXTRACTION_SYSTEM_PROMPT},
            {'role': 'user', 'content': content[:5000]}  # 限制长度
        ]

        try:
            response = self.llm_client.chat(messages)
            # 解析 JSON
            return json.loads(response)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON 解析失败: {e}")
            return {}
        except Exception as e:
            logger.error(f"LLM 提取失败: {e}")
            return {}

    def _check_completeness(self, content: str, record: RegulationRecord) -> Dict:
        """检查文档完整性"""
        from .regulation_prompts import format_completeness_check_prompt

        prompt = format_completeness_check_prompt(content[:3000])

        messages = [
            {'role': 'user', 'content': prompt}
        ]

        try:
            response = self.llm_client.chat(messages)
            return json.loads(response)
        except Exception as e:
            logger.warning(f"完整性检查失败: {e}")
            return {'is_complete': True, 'issues': [], 'quality_score': 0.5}

    def _generate_regulation_id(self, record: RegulationRecord) -> str:
        """生成法规唯一标识"""
        key = f"{record.law_name}_{record.article_number}"
        return hashlib.md5(key.encode()).hexdigest()[:16]

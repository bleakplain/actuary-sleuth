#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
法规文档清洗器

负责清洗和规范化法规文档内容。
"""

import re
import logging
import hashlib
from typing import Dict

from lib.common.models import RegulationRecord, RegulationStatus, ProcessingOutcome
from lib.llm_client import BaseLLMClient, LLMClientFactory

logger = logging.getLogger(__name__)


class DocumentCleaner:
    """文档清洗器 - 负责清洗和规范化法规文档"""

    def __init__(self, llm_client: BaseLLMClient = None):
        """
        Args:
            llm_client: LLM 客户端，默认使用 QA 模型
        """
        self.llm_client = llm_client or LLMClientFactory.get_qa_llm()

    def clean(
        self,
        content: str,
        source_file: str,
        record: RegulationRecord
    ) -> ProcessingOutcome:
        """
        清洗文档内容

        Args:
            content: 原始文档内容
            source_file: 来源文件路径
            record: 法规记录

        Returns:
            ProcessingOutcome: 清洗结果，包含清洗后的内容
        """
        try:
            # 规则清洗（快速）
            rule_cleaned = self._rule_based_clean(content)

            # 更新记录状态
            record.status = RegulationStatus.CLEANED

            return ProcessingOutcome(
                success=True,
                regulation_id=self._generate_regulation_id(record),
                record=record,
                errors=[],
                warnings=[],
                processor="preprocessing.cleaner"
            )

        except Exception as e:
            logger.error(f"文档清洗失败: {e}")
            record.status = RegulationStatus.FAILED
            return ProcessingOutcome(
                success=False,
                regulation_id="",
                record=record,
                errors=[str(e)],
                warnings=[],
                processor="preprocessing.cleaner"
            )

    def _rule_based_clean(self, content: str) -> str:
        """基于规则的快速清洗"""
        # 去除图片链接
        content = re.sub(r'!\[.*?\]\(.*?\)', '', content)
        content = re.sub(r'<img[^>]*>', '', content)

        # 去除 HTML 标签
        content = re.sub(r'<[^>]+>', '', content)

        # 统一换行符
        content = re.sub(r'\r\n', '\n', content)

        # 去除多余空行（3个或更多连续换行变成2个）
        content = re.sub(r'\n{3,}', '\n\n', content)

        return content.strip()

    def _llm_assisted_clean(self, content: str) -> str:
        """使用 LLM 辅助清洗（Phase 1 不启用）"""
        from .regulation_prompts import CLEANING_SYSTEM_PROMPT

        messages = [
            {'role': 'system', 'content': CLEANING_SYSTEM_PROMPT},
            {'role': 'user', 'content': content}
        ]

        try:
            cleaned = self.llm_client.chat(messages)
            return cleaned.strip()
        except Exception as e:
            logger.warning(f"LLM 清洗失败，使用规则清洗结果: {e}")
            return content

    def _generate_regulation_id(self, record: RegulationRecord) -> str:
        """生成法规唯一标识"""
        key = f"{record.law_name}_{record.article_number}"
        return hashlib.md5(key.encode()).hexdigest()[:16]

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LanceDB 元数据增强模块

负责从法规文档提取增强元数据，用于改进 RAG 检索质量。
"""

import logging
from pathlib import Path

from lib.preprocessing.models import RegulationStatus

logger = logging.getLogger(__name__)


def enhance_metadata_from_file(file_path: str, extractor=None) -> dict:
    """
    从文件提取增强元数据

    Args:
        file_path: 法规文档文件路径
        extractor: DocumentExtractor 实例（可选）

    Returns:
        dict: 增强元数据字典
    """
    if extractor is None:
        # 延迟导入避免循环依赖
        from lib.llm_client import LLMClientFactory
        from lib.preprocessing import DocumentExtractor

        llm_client = LLMClientFactory.get_qa_llm()
        extractor = DocumentExtractor(llm_client)

    try:
        # 读取原始内容
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 使用 DocumentExtractor 提取法规元数据
        result = extractor.extract_regulation_metadata(content, file_path)

        if not result.success:
            logger.warning(f"法规元数据提取失败: {result.errors}")
            return {
                'law_name': '',
                'article_number': '',
                'category': '未分类',
                'effective_date': None,
                'hierarchy_level': None,
                'issuing_authority': None,
                'status': RegulationStatus.FAILED.value,
                'quality_score': None
            }

        # 构建增强元数据
        return {
            'law_name': result.record.law_name,
            'article_number': result.record.article_number,
            'category': result.record.category,
            'effective_date': result.record.effective_date,
            'hierarchy_level': result.record.hierarchy_level.value if result.record.hierarchy_level else None,
            'issuing_authority': result.record.issuing_authority,
            'status': result.record.status.value,
            'quality_score': result.record.quality_score
        }

    except Exception as e:
        logger.error(f"元数据增强失败: {e}")
        return {
            'law_name': '',
            'article_number': '',
            'category': '未分类',
            'effective_date': None,
            'hierarchy_level': None,
            'issuing_authority': None,
            'status': RegulationStatus.FAILED.value,
            'quality_score': None
        }

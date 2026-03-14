#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LanceDB 元数据增强模块

负责从法规文档提取增强元数据，用于改进 RAG 检索质量。
"""

import logging
from pathlib import Path

from lib.preprocessing.regulation_cleaner import DocumentCleaner
from lib.preprocessing.regulation_extractor import InformationExtractor
from lib.common.models import RegulationRecord, RegulationStatus

logger = logging.getLogger(__name__)


def enhance_metadata_from_file(file_path: str) -> dict:
    """
    从文件提取增强元数据

    Args:
        file_path: 法规文档文件路径

    Returns:
        dict: 增强元数据字典
    """
    try:
        # 读取原始内容
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 创建初始记录
        record = RegulationRecord(
            law_name="",
            article_number="",
            category="未分类",
            status=RegulationStatus.RAW
        )

        # 清洗文档
        cleaner = DocumentCleaner()
        clean_result = cleaner.clean(content, file_path, record)

        if not clean_result.success:
            logger.warning(f"文档清洗失败: {clean_result.errors}")
            # 返回基础元数据
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

        # 提取结构化信息
        extractor = InformationExtractor()
        extract_result = extractor.extract(content, record)

        if not extract_result.success:
            logger.warning(f"信息提取失败: {extract_result.errors}")

        # 构建增强元数据
        return {
            'law_name': record.law_name,
            'article_number': record.article_number,
            'category': record.category,
            'effective_date': record.effective_date,
            'hierarchy_level': record.hierarchy_level.value if record.hierarchy_level else None,
            'issuing_authority': record.issuing_authority,
            'status': record.status.value,
            'quality_score': record.quality_score
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

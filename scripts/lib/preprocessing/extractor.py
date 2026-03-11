#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一文档提取器

主入口，整合所有组件，提供统一的提取接口。
"""
import logging
from typing import Dict, List, Any, Optional

from .models import NormalizedDocument, ExtractionPath, ExtractResult, ValidationResult
from .document_normalizer import DocumentNormalizer
from .path_selector import ExtractionPathSelector
from .lightweight_extractor import LightweightExtractor, FastPathExtractionFailed
from .structured_extractor import StructuredExtractor
from .validator import ExtractResultValidator


logger = logging.getLogger(__name__)


class UnifiedDocumentExtractor:
    """统一文档提取器 - 主入口"""

    def __init__(self, llm_client, config: Dict = None):
        """
        初始化提取器

        Args:
            llm_client: LLM 客户端
            config: 配置字典
        """
        self.config = config or {}

        # 初始化组件
        self.normalizer = DocumentNormalizer()
        self.path_selector = ExtractionPathSelector()
        self.lightweight_extractor = LightweightExtractor(llm_client)
        self.structured_extractor = StructuredExtractor(llm_client)
        self.validator = ExtractResultValidator()

    def extract(self,
                document: str,
                source_type: str = 'text',
                required_fields: Optional[List[str]] = None) -> ExtractResult:
        """
        统一提取接口

        Args:
            document: 原始文档
            source_type: 来源类型 (pdf/html/text/scan)
            required_fields: 需要提取的字段（默认使用必需字段）

        Returns:
            ExtractResult
        """
        # 使用默认必需字段
        if required_fields is None:
            required_fields = list(ExtractionPathSelector.get_required_fields())

        logger.info(f"开始文档提取，文档长度: {len(document)} 字符，来源类型: {source_type}")

        # 1. 文档规范化
        normalized = self.normalizer.normalize(document, source_type)
        logger.info(f"文档规范化完成: {normalized.metadata}")

        # 2. 路径选择
        path = self.path_selector.select_path(normalized)
        logger.info(f"选择路径: {path.path_type}, 产品类型: {path.product_type}, 置信度: {path.confidence:.2f}")

        # 3. 执行提取
        try:
            if path.path_type == 'fast':
                result = self.lightweight_extractor.extract(normalized, required_fields)
                logger.info("快速路径提取成功")
            else:
                result = self.structured_extractor.extract(normalized, path, required_fields)
                logger.info("结构化路径提取成功")
        except FastPathExtractionFailed:
            # 快速路径失败，回退到结构化路径
            logger.warning("快速路径失败，回退到结构化路径")
            result = self.structured_extractor.extract(normalized, path, required_fields)

        # 4. 验证
        validation = self.validator.validate(result)
        logger.info(f"验证结果: {validation.score}/100, 错误: {len(validation.errors)}, 警告: {len(validation.warnings)}")

        # 5. 添加元数据
        result.metadata.update({
            'extraction_path': path.path_type,
            'product_type': path.product_type,
            'confidence': path.confidence,
            'is_hybrid': path.is_hybrid,
            'validation_score': validation.score,
            'validation_errors': validation.errors,
            'validation_warnings': validation.warnings
        })

        logger.info(f"文档提取完成，提取字段数: {len(result.data)}")

        return result


def create_extractor(llm_client, config: Dict = None) -> UnifiedDocumentExtractor:
    """创建提取器的便捷函数"""
    return UnifiedDocumentExtractor(llm_client, config)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档提取器

主入口，整合所有组件，提供统一的提取接口。
"""
import logging
from typing import Dict, List, Any, Optional

from .models import NormalizedDocument, ExtractResult, ValidationResult
from .normalizer import Normalizer
from .route_selector import RouteSelector
from .fast_extractor import FastExtractor, FastExtractionFailed
from .dynamic_extractor import DynamicExtractor
from .validator import ResultValidator


logger = logging.getLogger(__name__)


class DocumentExtractor:
    """文档提取器 - 主入口"""

    def __init__(self, llm_client, config: Dict = None):
        """
        初始化提取器

        Args:
            llm_client: LLM 客户端
            config: 配置字典
        """
        self.config = config or {}

        # 初始化组件（注意顺序：RouteSelector 依赖提取器）
        self.normalizer = Normalizer()
        self.fast_extractor = FastExtractor(llm_client)
        self.dynamic_extractor = DynamicExtractor(llm_client)
        self.route_selector = RouteSelector(self.fast_extractor, self.dynamic_extractor)
        self.validator = ResultValidator()

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
            required_fields = list(RouteSelector.get_required_fields())

        logger.info(f"开始文档提取，文档长度: {len(document)} 字符，来源类型: {source_type}")

        # 1. 文档规范化
        normalized = self.normalizer.normalize(document, source_type)
        logger.info(f"文档规范化完成: {normalized.metadata}")

        # 2. 选择提取器
        extractor, product_type, confidence, is_hybrid = self.route_selector.select_extractor(normalized)
        extractor_name = extractor.__class__.__name__
        logger.info(f"选择提取器: {extractor_name}, 产品类型: {product_type}, 置信度: {confidence:.2f}")

        # 3. 执行提取
        try:
            if isinstance(extractor, FastExtractor):
                result = extractor.extract(normalized, required_fields)
                logger.info("快速通道提取成功")
            else:
                result = extractor.extract(normalized, product_type, is_hybrid, required_fields)
                logger.info("动态通道提取成功")
        except FastExtractionFailed:
            # 快速通道失败，回退到动态通道
            logger.warning("快速通道失败，回退到动态通道")
            result = self.dynamic_extractor.extract(normalized, product_type, is_hybrid, required_fields)

        # 4. 验证
        validation = self.validator.validate(result)
        logger.info(f"验证结果: {validation.score}/100, 错误: {len(validation.errors)}, 警告: {len(validation.warnings)}")

        # 5. 添加元数据
        result.metadata.update({
            'extraction_mode': 'fast' if isinstance(extractor, FastExtractor) else 'dynamic',
            'product_type': product_type,
            'confidence': confidence,
            'is_hybrid': is_hybrid,
            'validation_score': validation.score,
            'validation_errors': validation.errors,
            'validation_warnings': validation.warnings
        })

        logger.info(f"文档提取完成，提取字段数: {len(result.data)}")

        return result


def create_extractor(llm_client, config: Dict = None) -> DocumentExtractor:
    """创建提取器的便捷函数"""
    return DocumentExtractor(llm_client, config)

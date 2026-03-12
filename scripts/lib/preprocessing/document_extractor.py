#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档提取器

主入口，整合所有组件，提供统一的提取接口。

环境变量:
    DEBUG: 设置为 true/1 时，将提取结果输出到 /tmp 目录
"""
import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Any, Optional

from .models import NormalizedDocument, ExtractResult, ValidationResult
from .normalizer import Normalizer
from .classifier import ProductClassifier
from .extractor_selector import ExtractorSelector
from .fast_extractor import FastExtractor, FastExtractionFailed
from .dynamic_extractor import DynamicExtractor
from .validator import ResultValidator


logger = logging.getLogger(__name__)

# Debug 模式：通过环境变量 DEBUG 控制
DEBUG_MODE = os.getenv('DEBUG', '').lower() in ('true', '1', 'yes')


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

        # 初始化组件（注意顺序：DynamicExtractor 依赖 classifier）
        self.normalizer = Normalizer()
        self.classifier = ProductClassifier()
        self.fast_extractor = FastExtractor(llm_client)
        self.dynamic_extractor = DynamicExtractor(llm_client, self.classifier)
        self.extractor_selector = ExtractorSelector(
            self.fast_extractor,
            self.dynamic_extractor,
            self.classifier
        )
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
            required_fields = list(ExtractorSelector.get_required_fields())

        logger.info(f"开始文档提取，文档长度: {len(document)} 字符，来源类型: {source_type}")

        # 1. 文档规范化
        normalized = self.normalizer.normalize(document, source_type)
        logger.info(f"文档规范化完成: {normalized.metadata}")

        # 2. 选择提取器
        extractor = self.extractor_selector.select(normalized)
        logger.info(f"选择提取器: {extractor.__class__.__name__}")

        # 3. 执行提取
        try:
            result = extractor.extract(normalized, required_fields)
            logger.info(f"{extractor.__class__.__name__} 提取成功")
        except FastExtractionFailed:
            # 快速通道失败，回退到动态通道
            logger.warning("快速通道失败，回退到动态通道")
            result = self.dynamic_extractor.extract(normalized, required_fields)

        # 4. 验证
        validation = self.validator.validate(result)
        logger.info(f"验证结果: {validation.score}/100, 错误: {len(validation.errors)}, 警告: {len(validation.warnings)}")

        # 5. 添加元数据
        result.metadata.update({
            'extraction_mode': 'fast' if isinstance(extractor, FastExtractor) else 'dynamic',
            'validation_score': validation.score,
            'validation_errors': validation.errors,
            'validation_warnings': validation.warnings
        })

        logger.info(f"文档提取完成，提取字段数: {len(result.data)}")

        # Debug 模式：输出结构化结果
        if DEBUG_MODE:
            self._dump_debug_result(result)

        return result

    def _dump_debug_result(self, result: ExtractResult):
        """输出提取结果到 /tmp 目录"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_dir = "/tmp"
        os.makedirs(output_dir, exist_ok=True)

        # 输出 JSON 格式的提取结果
        debug_file = os.path.join(output_dir, f"extraction_result_{timestamp}.json")
        with open(debug_file, 'w', encoding='utf-8') as f:
            json.dump({
                'data': result.data,
                'confidence': result.confidence,
                'provenance': result.provenance,
                'metadata': result.metadata,
            }, f, ensure_ascii=False, indent=2)
        logger.info(f"提取结果已输出: {debug_file}")


def create_extractor(llm_client, config: Dict = None) -> DocumentExtractor:
    """创建提取器的便捷函数"""
    return DocumentExtractor(llm_client, config)

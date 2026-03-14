#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档提取器

主入口，整合所有组件，提供统一的提取接口。

支持两类文档:
1. 保险产品文档: 提取产品信息用于精算审核
2. 法规文档: 提取元数据用于 RAG 检索

环境变量:
    DEBUG: 设置为 true/1 时，将提取结果输出到 /tmp 目录
"""
import json
import logging
import os
import re
import hashlib
from datetime import datetime
from typing import Dict, List, Any, Optional

from .models import (
    NormalizedDocument, ExtractResult, ValidationResult,
    # 法规文档模型
    RegulationStatus, RegulationLevel, RegulationRecord,
    RegulationProcessingOutcome,
)
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
        self.llm_client = llm_client

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

    def extract_regulation_metadata(
        self,
        content: str,
        source_file: str = ""
    ) -> RegulationProcessingOutcome:
        """
        提取法规文档元数据（用于 RAG 检索增强）

        Args:
            content: 法规文档内容
            source_file: 来源文件路径

        Returns:
            RegulationProcessingOutcome: 处理结果，包含提取的元数据
        """
        # 创建初始记录
        record = RegulationRecord(
            law_name="",
            article_number="",
            category="未分类",
            status=RegulationStatus.RAW
        )

        try:
            # 1. 清洗文档
            cleaned_content = self._clean_regulation(content)

            # 2. 提取元数据
            extracted_info = self._extract_regulation_metadata(cleaned_content)

            # 3. 更新记录
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

            record.status = RegulationStatus.EXTRACTED
            record.quality_score = extracted_info.get('quality_score', 0.5)

            return RegulationProcessingOutcome(
                success=True,
                regulation_id=self._generate_regulation_id(record),
                record=record,
                errors=[],
                warnings=[],
                processor="document_extractor"
            )

        except Exception as e:
            logger.error(f"法规元数据提取失败: {e}")
            record.status = RegulationStatus.FAILED
            return RegulationProcessingOutcome(
                success=False,
                regulation_id="",
                record=record,
                errors=[str(e)],
                warnings=[],
                processor="document_extractor"
            )

    def _clean_regulation(self, content: str) -> str:
        """清洗法规文档"""
        # 去除图片链接
        content = re.sub(r'!\[.*?\]\(.*?\)', '', content)
        content = re.sub(r'<img[^>]*>', '', content)

        # 去除 HTML 标签
        content = re.sub(r'<[^>]+>', '', content)

        # 统一换行符
        content = re.sub(r'\r\n', '\n', content)

        # 去除多余空行
        content = re.sub(r'\n{3,}', '\n\n', content)

        return content.strip()

    def _extract_regulation_metadata(self, content: str) -> Dict[str, Any]:
        """使用 LLM 提取法规元数据"""
        prompt = f"""请从以下法规文档中提取元数据，输出 JSON 格式：

【文档内容】
{content[:5000]}

【提取字段】
- law_name: 法规/文件全称
- effective_date: 生效日期（YYYY-MM-DD 格式，无法确定返回 null）
- hierarchy_level: 法规层级（law/department_rule/normative/other）
- issuing_authority: 发布机关
- category: 法规分类（如"健康保险"、"产品管理"等）

【层级判断】
- law: 包含"法"字的法律
- department_rule: 部门规章（办法、规定、细则）
- normative: 规范性文件（通知、指引、意见）
- other: 其他

严格按照 JSON 格式输出，无其他内容：
```json
{{"law_name": "...", "effective_date": "...", "hierarchy_level": "...", "issuing_authority": "...", "category": "..."}}
```
"""

        try:
            response = self.llm_client.chat([
                {'role': 'user', 'content': prompt}
            ])

            # 解析 JSON
            import json
            return json.loads(response)
        except Exception as e:
            logger.warning(f"法规元数据提取失败: {e}")
            return {}

    def _generate_regulation_id(self, record: RegulationRecord) -> str:
        """生成法规唯一标识"""
        key = f"{record.law_name}_{record.article_number}"
        return hashlib.md5(key.encode()).hexdigest()[:16]

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

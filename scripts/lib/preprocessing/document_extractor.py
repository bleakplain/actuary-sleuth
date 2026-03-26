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
from typing import Dict, List, Any, Optional, Set

from .models import (
    NormalizedDocument, ExtractResult, ValidationResult,
    # 法规文档模型
    RegulationStatus, RegulationLevel, RegulationRecord,
    RegulationProcessingOutcome,
)
from .normalizer import Normalizer
from .classifier import Classifier
from .hybrid_extractor import HybridExtractor
from .validator import Validator
from .utils.constants import config


logger = logging.getLogger(__name__)

# Debug 模式：通过环境变量 DEBUG 控制
DEBUG_MODE = os.getenv('DEBUG', '').lower() in ('true', '1', 'yes')


class DocumentExtractor:
    """文档提取器 - 主入口（使用多策略并行提取架构）"""

    # 默认必需字段
    DEFAULT_REQUIRED_FIELDS = {
        'product_name',
        'insurance_company',
    }

    def __init__(self, llm_client, config: Optional[Dict[str, Any]] = None):
        """
        初始化提取器

        Args:
            llm_client: LLM 客户端
            config: 配置字典
        """
        self.config = config or {}
        self.llm_client = llm_client

        # 初始化组件
        self.normalizer = Normalizer()
        self.classifier = Classifier()
        self.hybrid_extractor = HybridExtractor.create_default(llm_client)
        self.validator = Validator()

        # 确保 LLM 客户端使用正确的超时设置
        from lib.config import get_config
        app_config = get_config()
        if hasattr(llm_client, 'timeout'):
            current_timeout = llm_client.timeout
            config_timeout = app_config.llm.timeout
            if current_timeout < config_timeout:
                logger.warning(f"LLM 客户端超时 ({current_timeout}s) 小于配置值 ({config_timeout}s)，"
                               f"大文档处理可能会超时")

    def extract(self,
                document: str,
                source_type: str = 'text',
                required_fields: Optional[List[str]] = None) -> ExtractResult:
        """
        统一提取接口（使用多策略并行提取）

        Args:
            document: 原始文档
            source_type: 来源类型 (pdf/html/text/scan)
            required_fields: 需要提取的字段（默认使用必需字段）

        Returns:
            ExtractResult
        """
        # 使用默认必需字段
        if required_fields is None:
            required_fields = list(self.DEFAULT_REQUIRED_FIELDS)
            # 根据产品类型添加其他必需字段
            required_fields.extend(['insurance_period', 'waiting_period'])

        required_fields_set = set(required_fields)

        # 边界情况：文档长度验证
        doc_length = len(document)
        if doc_length < 100:
            from .exceptions import DocumentValidationError
            raise DocumentValidationError(f"文档过短 ({doc_length} 字符)，无法有效提取")
        if doc_length > 500000:
            logger.warning(f"文档过长 ({doc_length} 字符)，可能需要较长处理时间")

        logger.info(f"开始文档提取，文档长度: {doc_length} 字符，来源类型: {source_type}")

        # 1. 文档规范化
        normalized = self.normalizer.normalize(document, source_type)
        logger.info(f"文档规范化完成: 原始长度={normalized.metadata.get('original_length')}, "
                   f"规范化长度={normalized.metadata.get('normalized_length')}, "
                   f"结构化={normalized.profile.is_structured}, "
                   f"有条款编号={normalized.profile.has_clause_numbers}")

        # 2. 多策略并行提取
        strategy_result = self.hybrid_extractor.extract(
            normalized.content,
            required_fields_set
        )

        # 3. 转换为 ExtractResult 格式
        result = ExtractResult(
            data=strategy_result.data,
            confidence={k: strategy_result.confidence for k in strategy_result.data},
            provenance={k: strategy_result.extractor for k in strategy_result.data},
            metadata={
                **strategy_result.metadata,
                'source_type': source_type,
                'original_length': doc_length,
                'normalized_length': len(normalized.content),
            }
        )

        # 4. 验证
        validation = self.validator.validate(result)
        logger.info(f"验证结果: {validation.score}/100, 错误: {len(validation.errors)}, 警告: {len(validation.warnings)}")

        # 5. 添加验证元数据
        result.metadata.update({
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

            # 3. 更新记录（使用 replace 不可变更新）
            from dataclasses import replace
            update_fields = {}
            if extracted_info.get('law_name'):
                update_fields['law_name'] = extracted_info['law_name']
            if extracted_info.get('effective_date'):
                update_fields['effective_date'] = extracted_info['effective_date']
            if extracted_info.get('hierarchy_level'):
                update_fields['hierarchy_level'] = RegulationLevel(extracted_info['hierarchy_level'])
            if extracted_info.get('issuing_authority'):
                update_fields['issuing_authority'] = extracted_info['issuing_authority']
            if extracted_info.get('category'):
                update_fields['category'] = extracted_info['category']

            update_fields['status'] = RegulationStatus.EXTRACTED
            update_fields['quality_score'] = extracted_info.get('quality_score', 0.5)

            record = replace(record, **update_fields)

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
            from dataclasses import replace
            record = replace(record, status=RegulationStatus.FAILED)
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
            return json.loads(response)
        except Exception as e:
            logger.warning(f"法规元数据提取失败: {e}")
            return {}

    def _generate_regulation_id(self, record: RegulationRecord) -> str:
        """生成法规唯一标识（使用 SHA256 防止碰撞）"""
        key = f"{record.law_name}_{record.article_number}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

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


def create_extractor(llm_client, config: Optional[Dict[str, Any]] = None) -> DocumentExtractor:
    """创建提取器的便捷函数"""
    return DocumentExtractor(llm_client, config)

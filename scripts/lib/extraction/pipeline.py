#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
提取流程管道

统一的文档提取流程，格式无关，自动适配不同文档类型。
"""
import logging
from typing import Dict, Any, Optional

from .detector import DocumentFormatDetector, FormatProfile
from .adapters import get_adapter, BaseFormatAdapter
from .chunkers import BaseChunker, TableSplitter, SectionSplitter, SemanticSplitter
from .deduplicator import BaseDeduplicator, HashDeduplicator
from lib.hybrid_extractor import (
    LLMExtractor, RuleExtractor, ResultFusion,
    ExtractResult, QualityAssessor
)
from lib.llm_client import LLMClientFactory


logger = logging.getLogger(__name__)


class ExtractionPipeline:
    """
    统一提取流程

    格式无关的文档提取框架，自动检测文档格式并选择适配策略。
    """

    # 默认配置
    DEFAULT_CHUNK_SIZE = 6000
    DEFAULT_OVERLAP = 1500
    DEFAULT_CHUNK_THRESHOLD = 10000

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化提取流程

        Args:
            config: 配置字典，包含以下可选项：
                - chunk_size: 分块大小
                - overlap: 重叠大小
                - chunk_threshold: 分块阈值
                - llm_config: LLM 配置
                - deduplicator: 去重器实例
        """
        self.config = config or {}

        # 从配置中获取参数，使用默认值
        self.chunk_size = self.config.get('chunk_size', self.DEFAULT_CHUNK_SIZE)
        self.overlap = self.config.get('overlap', self.DEFAULT_OVERLAP)
        self.chunk_threshold = self.config.get('chunk_threshold', self.DEFAULT_CHUNK_THRESHOLD)

        # 初始化组件
        self.detector = DocumentFormatDetector()
        self.rule_extractor = RuleExtractor()
        self.deduplicator = self.config.get('deduplicator', HashDeduplicator())

        # 初始化 LLM 客户端和提取器
        llm_config = self.config.get('llm_config')
        if llm_config is None:
            from lib.config import get_config
            app_config = get_config()
            llm_config = app_config.llm.to_client_config()

        self.llm_client = LLMClientFactory.create_client(llm_config)
        self.max_tokens = llm_config.get('max_tokens', 16384)
        self.llm_extractor = LLMExtractor(self.llm_client, max_tokens=self.max_tokens)
        self.fusion = ResultFusion()
        self.quality_assessor = QualityAssessor()

    def extract(self, document: str) -> ExtractResult:
        """
        主提取流程

        Args:
            document: 文档内容

        Returns:
            ExtractResult: 提取结果
        """
        logger.info(f"开始文档提取，文档长度: {len(document)} 字符")

        # 1. 检测文档格式
        profile = self.detector.analyze(document)
        logger.info(f"检测到格式: {profile.primary_type} (置信度: {profile.confidence:.2f})")
        if profile.features:
            logger.debug(f"格式特征: {profile.features}")

        # 2. 选择适配器
        adapter = get_adapter(profile)

        # 3. 选择分块策略
        chunker = self._create_chunker(adapter)

        # 4. 根据文档长度选择提取路径
        doc_len = len(document)
        if doc_len > self.chunk_threshold:
            llm_result = self._extract_long(document, chunker)
        else:
            llm_result = self._extract_short(document)

        # 5. 规则提取（用于验证和补充）
        rule_result = self.rule_extractor.extract(document)
        logger.info(f"规则提取完成: {len(rule_result.data)} 个字段")

        # 6. 结果融合
        final_result = self.fusion.fuse(llm_result, rule_result)

        # 7. 条款去重
        if 'clauses' in final_result.data:
            original_count = len(final_result.data.get('clauses', []))
            final_result.data['clauses'] = self.deduplicator.deduplicate(
                final_result.data['clauses']
            )
            if original_count != len(final_result.data['clauses']):
                logger.info(f"条款去重: {original_count} -> {len(final_result.data['clauses'])}")

        # 8. 质量评估
        quality = self.quality_assessor.assess(final_result)
        score = quality.overall_score()
        logger.info(f"提取质量评分: {score}/100")
        logger.info(f"  完整性: {quality.completeness:.2f}")
        logger.info(f"  准确性: {quality.accuracy:.2f}")
        logger.info(f"  一致性: {quality.consistency:.2f}")
        logger.info(f"  合理性: {quality.reasonableness:.2f}")

        return final_result

    def _create_chunker(self, adapter: BaseFormatAdapter) -> BaseChunker:
        """
        根据适配器建议创建分块器

        Args:
            adapter: 格式适配器

        Returns:
            分块器实例
        """
        chunker_name = adapter.get_suggested_chunker()

        chunker_map = {
            'table_splitter': TableSplitter,
            'section_splitter': SectionSplitter,
            'semantic_splitter': SemanticSplitter,
        }

        chunker_class = chunker_map.get(chunker_name, SectionSplitter)
        return chunker_class(self.chunk_size, self.overlap)

    def _extract_short(self, document: str) -> ExtractResult:
        """
        短文档提取

        Args:
            document: 文档内容

        Returns:
            ExtractResult
        """
        logger.info("使用短文档直接提取模式")
        return self.llm_extractor.extract(document)

    def _extract_long(self, document: str, chunker: BaseChunker) -> ExtractResult:
        """
        长文档分块提取

        Args:
            document: 文档内容
            chunker: 分块器

        Returns:
            ExtractResult
        """
        logger.info("使用长文档分块提取模式")

        # 分块
        chunks = chunker.split(document)
        logger.info(f"文档已分割为 {len(chunks)} 个块")

        # 逐块提取
        all_product_info = {}
        all_clauses = []
        all_pricing_params = {}

        for i, chunk in enumerate(chunks):
            logger.info(f"处理第 {i+1}/{len(chunks)} 个块 ({len(chunk)} 字符)")
            chunk_result = self._extract_from_chunk(chunk, i, len(chunks))

            # 合并 product_info
            if 'product_info' in chunk_result:
                for key, value in chunk_result['product_info'].items():
                    if value and (key not in all_product_info or not all_product_info[key]):
                        all_product_info[key] = value

            # 合并 clauses
            if 'clauses' in chunk_result and isinstance(chunk_result['clauses'], list):
                for clause in chunk_result['clauses']:
                    if clause and isinstance(clause, dict) and 'text' in clause:
                        all_clauses.append(clause)

            # 合并 pricing_params
            if 'pricing_params' in chunk_result:
                for key, value in chunk_result['pricing_params'].items():
                    if value and (key not in all_pricing_params or not all_pricing_params[key]):
                        all_pricing_params[key] = value

        # 构建最终结果
        final_data = {}
        if all_product_info:
            final_data['product_info'] = all_product_info
        if all_clauses:
            final_data['clauses'] = all_clauses
        if all_pricing_params:
            final_data['pricing_params'] = all_pricing_params

        # 规则提取补充
        rule_result = self.rule_extractor.extract(document)
        for key, value in rule_result.data.items():
            # 补充 product_info
            if key not in all_product_info or not all_product_info.get(key):
                if 'product_info' not in final_data:
                    final_data['product_info'] = {}
                final_data['product_info'][key] = value

        logger.info(f"分块提取完成: 产品信息 {len(all_product_info)} 字段, 条款 {len(all_clauses)} 条")

        return ExtractResult(
            data=final_data,
            confidence={k: 0.75 for k in final_data},
            provenance={k: 'llm_chunked' for k in final_data}
        )

    def _extract_from_chunk(self, chunk: str, index: int, total: int) -> Dict[str, Any]:
        """
        从单个块提取信息

        Args:
            chunk: 文档块
            index: 块索引
            total: 总块数

        Returns:
            提取结果字典
        """
        prompt = f"""你是保险产品文档解析专家。请分析以下保险产品文档片段（第{index + 1}/{total}块），提取结构化信息。

**重要要求**:
1. 只提取"条款正文"中的真正条款
2. 过滤HTML标签、格式化字符
3. 提取所有可见的条款内容
4. 如果产品信息在前面的块中已经提取过，可以忽略或补充
5. 提取定价相关参数（利率、费用率等）

文档片段:
```
{chunk}
```

**输出要求**:
- 必须且只能返回JSON格式
- 不要包含任何解释、分析或说明文字
- 直接返回JSON，不要使用markdown代码块

返回JSON:
{{
    "product_info": {{
        "product_name": "产品名称（如果在当前块中）",
        "insurance_company": "保险公司（如果在当前块中）",
        "product_type": "产品类型（如果在当前块中）",
        "insurance_period": "保险期间（如果在当前块中）",
        "payment_method": "缴费方式（如果在当前块中）",
        "age_min": "最低投保年龄（如果在当前块中）",
        "age_max": "最高投保年龄（如果在当前块中）",
        "waiting_period": "等待期天数（如果在当前块中）"
    }},
    "clauses": [
        {{"text": "条款内容", "reference": "条款编号/标题"}}
    ],
    "pricing_params": {{
        "interest_rate": "预定利率（如果在当前块中）",
        "expense_rate": "费用率（如果在当前块中）",
        "premium_rate": "保费（如果在当前块中）"
    }}
}}"""

        response = self.llm_extractor._call_llm(prompt)
        return self.llm_extractor._parse_llm_response(response)

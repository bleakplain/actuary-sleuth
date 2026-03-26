#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
混合提取器

使用多种提取器并行处理文档，通过投票融合获得最佳结果。
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Any, Set, Optional

from .extractors.base import Extractor, ExtractionResult
from .semantic_analyzer import SemanticAnalyzer
from .deduplicator import Deduplicator
from .fuser import Fuser
from .classifier import Classifier
from .prompt_builder import PromptBuilder
from .product_types import get_extraction_focus, get_output_schema, get_few_shot_examples
from .utils.constants import config


logger = logging.getLogger(__name__)


class HybridExtractor:
    """混合提取器 - 协调多种提取策略"""

    def __init__(self, extractors: Optional[Dict[str, Extractor]] = None,
                 llm_client=None,
                 fuser: Optional[Fuser] = None,
                 deduplicator: Optional[Deduplicator] = None,
                 enable_parallel: bool = True,
                 max_workers: int = 4):
        """初始化混合提取器

        Args:
            extractors: 提取器字典 {name: Extractor}
            llm_client: LLM 客户端
            fuser: 结果融合器（可选）
            deduplicator: 去重器（可选）
            enable_parallel: 是否启用并行执行
            max_workers: 最大并行工作线程数
        """
        self._extractors = extractors or {}
        self.llm_client = llm_client
        self.enable_parallel = enable_parallel
        self.max_workers = max_workers

        self._fuser = fuser or Fuser(min_agreement=config.MIN_VOTE_AGREEMENT)
        self._deduplicator = deduplicator or Deduplicator()

        if llm_client:
            self.classifier = Classifier()
            self.prompt_builder = PromptBuilder()
            self.semantic_analyzer = SemanticAnalyzer(llm_client)

    @classmethod
    def create_default(cls, llm_client, prompt_builder=None) -> 'HybridExtractor':
        """工厂方法：创建默认配置的混合提取器

        Args:
            llm_client: LLM 客户端
            prompt_builder: Prompt 构建器（可选）

        Returns:
            配置好的 HybridExtractor 实例
        """
        from .extractors.chunked_llm import ChunkedLLMExtractor

        base_prompt = prompt_builder or ""
        extractors: Dict[str, Extractor] = {
            'chunked_llm': ChunkedLLMExtractor(llm_client, base_prompt),
        }

        deduplicator = Deduplicator()

        return cls(extractors, llm_client, deduplicator=deduplicator)

    def extract(self, document: str, required_fields: Set) -> ExtractionResult:
        """
        执行多提取器提取

        Args:
            document: 文档内容
            required_fields: 必需字段集合

        Returns:
            提取结果
        """
        start_time = time.time()
        logger.info(f"开始多提取器提取: 文档长度 {len(document)}, "
                   f"必需字段 {len(required_fields)}, "
                   f"提取器数量 {len(self._extractors)}")

        # 1. 产品分类（一次性）
        classifications = self.classifier.classify(document)
        product_type = classifications[0][0] if classifications else 'life_insurance'
        is_hybrid = len(classifications) > 1 and classifications[1][1] > 0.5
        logger.info(f"产品分类: {product_type}, 置信度: {classifications[0][1] if classifications else 0:.2f}, "
                   f"混合产品: {is_hybrid}")

        # 2. 构建产品类型特定的 base_prompt（所有 LLM Extractor 共享）
        base_prompt = self.prompt_builder.build(
            product_type=product_type,
            required_fields=list(required_fields),
            extraction_focus=get_extraction_focus(product_type),
            output_schema=get_output_schema(product_type),
            is_hybrid=is_hybrid,
            include_few_shot=True,
            few_shot_content=get_few_shot_examples(product_type)
        )

        # 3. 语义结构分析
        structure = self.semantic_analyzer.analyze(document)
        logger.info(f"语义结构分析完成: 类型={structure.get('structure_type', 'unknown')}, "
                   f"章节={len(structure.get('sections', []))}, "
                   f"条款={len(structure.get('clauses', []))}, "
                   f"表格={len(structure.get('tables', []))}")

        # 4. 将 base_prompt 添加到 structure 中，供提取器使用
        structure['base_prompt'] = base_prompt

        # 5. 选择可用的提取器
        available_extractors = [
            s for s in self._extractors.values()
            if s.can_handle(document, structure)
        ]
        logger.info(f"可用提取器: {[s.name for s in available_extractors]}")

        # 6. 并行/串行执行提取器
        if self.enable_parallel and len(available_extractors) > 1:
            results = self._extract_parallel(available_extractors, document, structure, required_fields)
        else:
            results = self._extract_sequential(available_extractors, document, structure, required_fields)

        # 6. 投票融合
        fused_result = self._fuser.fuse(results, required_fields)

        # 7. 语义去重（针对条款）
        if 'clauses' in fused_result.data and fused_result.data['clauses']:
            original_count = len(fused_result.data['clauses'])
            fused_result.data['clauses'] = self._deduplicator.deduplicate_clauses(
                fused_result.data['clauses']
            )
            logger.info(f"条款去重: {original_count} → {len(fused_result.data['clauses'])}")

        # 9. 更新元数据
        total_duration = time.time() - start_time
        fused_result.metadata['total_duration'] = total_duration
        fused_result.metadata['structure_analysis'] = structure.get('structure_type', 'unknown')
        fused_result.metadata['product_type'] = product_type
        fused_result.metadata['is_hybrid'] = is_hybrid

        logger.info(f"多提取器提取完成: 总耗时 {total_duration:.3f}s, "
                   f"最终字段 {len(fused_result.data)}/{len(required_fields)}, "
                   f"置信度 {fused_result.confidence:.2f}")

        return fused_result

    def _extract_parallel(self, extractors: List[Extractor], document: str,
                          structure: Dict, required_fields: Set) -> List[ExtractionResult]:
        """并行执行多个提取器"""
        results = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_extractor = {
                executor.submit(s.extract, document, structure, required_fields): s
                for s in extractors
            }

            for future in as_completed(future_to_extractor):
                extractor = future_to_extractor[future]
                try:
                    result = future.result(timeout=getattr(config, 'STRATEGY_TIMEOUT', 30))
                    results.append(result)
                    logger.info(f"提取器 {extractor.name} 完成: "
                               f"字段 {len(result.data)}, "
                               f"置信度 {result.confidence:.2f}, "
                               f"耗时 {result.duration:.3f}s")
                except Exception as e:
                    logger.warning(f"提取器 {extractor.name} 执行失败: {e}")
                    results.append(ExtractionResult(
                        data={},
                        confidence=0.0,
                        extractor=extractor.name,
                        duration=0.0,
                        metadata={'error': str(e)}
                    ))

        return results

    def _extract_sequential(self, extractors: List[Extractor], document: str,
                            structure: Dict, required_fields: Set) -> List[ExtractionResult]:
        """串行执行多个提取器"""
        results = []

        for extractor in extractors:
            try:
                result = extractor.extract(document, structure, required_fields)
                results.append(result)
                logger.info(f"提取器 {extractor.name} 完成: "
                           f"字段 {len(result.data)}, "
                           f"置信度 {result.confidence:.2f}, "
                           f"耗时 {result.duration:.3f}s")
            except Exception as e:
                logger.warning(f"提取器 {extractor.name} 执行失败: {e}")
                results.append(ExtractionResult(
                    data={},
                    confidence=0.0,
                    extractor=extractor.name,
                    duration=0.0,
                    metadata={'error': str(e)}
                ))

        return results

    def add_extractor(self, name: str, extractor: Extractor):
        """添加提取器

        Args:
            name: 提取器名称
            extractor: 提取器实例
        """
        self._extractors[name] = extractor
        logger.info(f"添加提取器: {name}")

    def remove_extractor(self, extractor_name: str) -> bool:
        """移除提取器

        Args:
            extractor_name: 提取器名称

        Returns:
            是否成功移除
        """
        if extractor_name in self._extractors:
            del self._extractors[extractor_name]
            logger.info(f"移除提取器: {extractor_name}")
            return True
        return False

    def get_extractors(self) -> List[str]:
        """获取当前提取器名称列表"""
        return list(self._extractors.keys())

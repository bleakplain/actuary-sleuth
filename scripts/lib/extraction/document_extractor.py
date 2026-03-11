#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档提取器

统一的文档提取流程，格式无关，自动适配不同文档类型。
支持并发LLM调用以提升长文档处理速度。
"""
import asyncio
import logging
import os
import time
from typing import Dict, Any, Optional, List

from .chunkers import BaseChunker, HybridChunker
from .deduplicator import BaseDeduplicator, HashDeduplicator
from .llm_extractor import LLMExtractor
from .result_merger import LLMRuleMerger, ExtractQualityAssessor
from .models import ExtractResult
from .rule_extractor import RuleExtractor
from lib.llm_client import LLMClientFactory
from lib.constants import (
    DEFAULT_CHUNK_SIZE, DEFAULT_OVERLAP, DEFAULT_CHUNK_THRESHOLD,
    DEFAULT_MAX_CONCURRENT, MODEL_CONCURRENT_MAP,
    LLM_TARGET_QPS, LLM_MAX_RETRIES, LLM_RETRY_BASE_DELAY,
    LLM_RETRY_MAX_DELAY, LLM_MAX_TOKENS, LLM_DEFAULT_CONFIDENCE
)


logger = logging.getLogger(__name__)


class DocumentExtractor:
    """文档提取器（LLM + 规则混合提取）"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化提取流程

        Args:
            config: 配置字典
                - chunk_size: 分块大小
                - overlap: 重叠大小
                - chunk_threshold: 分块阈值
                - max_concurrent: 最大并发数 (默认1=串行)
        """
        self.config = config or {}

        self.chunk_size = self.config.get('chunk_size', DEFAULT_CHUNK_SIZE)
        self.overlap = self.config.get('overlap', DEFAULT_OVERLAP)
        self.chunk_threshold = self.config.get('chunk_threshold', DEFAULT_CHUNK_THRESHOLD)
        self.max_concurrent = self._resolve_max_concurrent()
        self.request_delay = 1.0 / LLM_TARGET_QPS  # 每个请求间的延迟（秒）

        # 初始化组件
        self.rule_extractor = RuleExtractor()
        self.deduplicator = self.config.get('deduplicator', HashDeduplicator())

        # 初始化 LLM
        llm_config = self.config.get('llm_config')
        if llm_config is None:
            from lib.config import get_config
            app_config = get_config()
            llm_config = app_config.llm.to_client_config()

        self.llm_client = LLMClientFactory.create_client(llm_config)
        self.max_tokens = llm_config.get('max_tokens', LLM_MAX_TOKENS)
        self.llm_extractor = LLMExtractor(self.llm_client, max_tokens=self.max_tokens)
        self.merger = LLMRuleMerger()
        self.quality_assessor = ExtractQualityAssessor()

        logger.info(
            f"DocumentExtractor 初始化: max_concurrent={self.max_concurrent}, "
            f"request_delay={self.request_delay:.2f}s"
        )

    def _resolve_max_concurrent(self) -> int:
        """解析最大并发数"""
        # 1. 配置字典
        if 'max_concurrent' in self.config:
            return self.config['max_concurrent']
        concurrent_config = self.config.get('concurrent', {})
        if isinstance(concurrent_config, dict):
            max_c = concurrent_config.get('max_concurrent')
            if max_c is not None:
                return max_c
        elif isinstance(concurrent_config, int):
            return concurrent_config

        # 2. 环境变量
        env_max = os.getenv('ACTUARY_MAX_CONCURRENT')
        if env_max:
            try:
                return int(env_max)
            except ValueError:
                pass

        # 3. 根据模型推断
        llm_config = self.config.get('llm_config')
        if llm_config and 'model' in llm_config:
            model = llm_config['model']
        else:
            try:
                from lib.config import get_config
                model = get_config().llm.model
            except Exception as e:
                logger.debug(f"获取模型配置失败，使用默认值: {e}")
                model = 'glm-4-flash'
        return MODEL_CONCURRENT_MAP.get(model, DEFAULT_MAX_CONCURRENT)

    def extract(self, document: str) -> ExtractResult:
        """主提取流程"""
        logger.info(f"开始文档提取，文档长度: {len(document)} 字符")

        # 1. 创建分块器（自动适配文档类型）
        chunker = HybridChunker(self.chunk_size, self.overlap)

        # 2. 根据文档长度选择提取路径
        doc_len = len(document)
        if doc_len > self.chunk_threshold:
            llm_result = self._extract_chunks(document, chunker)
        else:
            llm_result = self._extract_direct(document)

        # 3. 规则提取和融合
        rule_result = self.rule_extractor.extract(document)
        final_result = self.merger.merge(llm_result, rule_result)

        # 4. 去重和质量评估
        if 'clauses' in final_result.data:
            original_count = len(final_result.data.get('clauses', []))
            final_result.data['clauses'] = self.deduplicator.deduplicate(
                final_result.data['clauses']
            )
            if original_count != len(final_result.data['clauses']):
                logger.info(f"条款去重: {original_count} -> {len(final_result.data['clauses'])}")

        quality = self.quality_assessor.assess(final_result)
        logger.info(f"提取质量评分: {quality.overall_score()}/100")

        return final_result

    def _extract_direct(self, document: str) -> ExtractResult:
        """直接提取（无需分块）"""
        logger.info("使用直接提取模式")
        return self.llm_extractor.extract(document)

    def _extract_chunks(self, document: str, chunker: BaseChunker) -> ExtractResult:
        """分块提取（使用固定延迟并发）"""
        chunks = chunker.split(document)
        total = len(chunks)

        logger.info(
            f"文档分割为 {total} 个块, 并发数={self.max_concurrent}, "
            f"请求延迟={self.request_delay:.2f}s"
        )

        # 并发=1 时使用串行模式（避免 asyncio 开销）
        if self.max_concurrent == 1:
            return self._serial_extract_chunks(chunks)

        # 并发模式
        return asyncio.run(self._concurrent_extract_chunks(chunks))

    def _serial_extract_chunks(self, chunks: List[str]) -> ExtractResult:
        """串行提取（用于 max_concurrent=1）"""
        results = []
        total = len(chunks)
        start_time = time.time()

        for i, chunk in enumerate(chunks):
            try:
                result = self._extract_chunk(chunk, i, total)
                results.append(result)
                logger.info(
                    f"✓ Chunk {i+1}/{total} 完成 ({self._get_result_summary(result)})"
                )
            except Exception as e:
                logger.error(f"✗ Chunk {i+1}/{total} 失败: {e}")
                results.append({})

            # 请求间延迟
            if i < total - 1:
                time.sleep(self.request_delay)

        elapsed = time.time() - start_time
        logger.info(
            f"串行处理完成: {sum(1 for r in results if r)}/{total} 成功, "
            f"耗时 {elapsed:.1f}秒 (平均 {elapsed/total:.2f}s/chunk)"
        )

        return self._merge_chunk_results(results)

    async def _concurrent_extract_chunks(self, chunks: List[str]) -> ExtractResult:
        """并发提取（使用信号量+固定延迟）"""
        total = len(chunks)
        results = [None] * total
        semaphore = asyncio.Semaphore(self.max_concurrent)
        start_time = time.time()

        async def process_one(index: int, chunk: str):
            """处理单个块（带重试）"""
            async with semaphore:
                # 请求间延迟（在信号量内执行）
                if index > 0:
                    await asyncio.sleep(self.request_delay)

                # 指数退避重试
                for attempt in range(LLM_MAX_RETRIES):
                    try:
                        # 在线程池中执行同步函数
                        loop = asyncio.get_event_loop()
                        result = await loop.run_in_executor(
                            None,
                            self._extract_chunk,
                            chunk, index, total
                        )

                        logger.info(
                            f"✓ Chunk {index+1}/{total} 完成 "
                            f"({self._get_result_summary(result)})"
                        )
                        return index, result

                    except Exception as e:
                        error_msg = str(e)
                        is_429 = '429' in error_msg or 'rate limit' in error_msg.lower()

                        # 最后一次尝试或不可重试的错误
                        if attempt == LLM_MAX_RETRIES - 1 or not is_429:
                            logger.error(
                                f"✗ Chunk {index+1}/{total} 失败: {error_msg[:100]}"
                            )
                            return index, {}

                        # 指数退避
                        wait_time = min(
                            LLM_RETRY_BASE_DELAY * (2 ** attempt),
                            LLM_RETRY_MAX_DELAY
                        )
                        logger.warning(
                            f"⚠ Chunk {index+1}/{total} 遇到429限流，"
                            f"{wait_time:.1f}秒后重试 "
                            f"(尝试 {attempt+1}/{LLM_MAX_RETRIES})"
                        )
                        await asyncio.sleep(wait_time)

        # 启动所有任务
        tasks = [process_one(i, chunk) for i, chunk in enumerate(chunks)]
        completed = await asyncio.gather(*tasks)

        # 按原始顺序组装结果
        for index, result in completed:
            results[index] = result

        elapsed = time.time() - start_time
        success_count = sum(1 for r in results if r)
        logger.info(
            f"并发处理完成: {success_count}/{total} 成功, "
            f"耗时 {elapsed:.1f}秒 "
            f"(平均 {elapsed/total:.2f}s/chunk, 加速比 {total/elapsed:.1f}x)"
        )

        return self._merge_chunk_results(results)

    def _extract_chunk(self, chunk: str, index: int, total: int) -> Dict[str, Any]:
        """从单个块提取信息"""
        return self.llm_extractor.extract_chunk(chunk, index, total)

    def _merge_chunk_results(self, results: List[Dict]) -> ExtractResult:
        """合并所有chunk的结果（动态处理所有字段）"""
        # 分类收集器
        dict_collectors = {}  # 存储字典类型的字段
        list_collectors = {}  # 存储列表类型的字段
        scalar_collectors = {}  # 存储标量类型的字段

        for result in results:
            if not result:
                continue

            for key, value in result.items():
                if value is None:
                    continue

                if isinstance(value, dict):
                    if key not in dict_collectors:
                        dict_collectors[key] = {}
                    for k, v in value.items():
                        if v and (k not in dict_collectors[key] or not dict_collectors[key][k]):
                            dict_collectors[key][k] = v

                elif isinstance(value, list):
                    if key not in list_collectors:
                        list_collectors[key] = []
                    for item in value:
                        if item and isinstance(item, dict):
                            list_collectors[key].append(item)
                        elif isinstance(item, (str, int, float, bool)):
                            # 标量列表去重
                            if item not in list_collectors[key]:
                                list_collectors[key].append(item)

                else:
                    # 标量值：优先使用非空值
                    if key not in scalar_collectors or not scalar_collectors[key]:
                        scalar_collectors[key] = value

        # 组装最终数据
        final_data = {}
        final_data.update(dict_collectors)
        final_data.update(list_collectors)
        final_data.update(scalar_collectors)

        logger.info(
            f"分块提取完成: 字典字段 {len(dict_collectors)}, "
            f"列表字段 {len(list_collectors)}, "
            f"标量字段 {len(scalar_collectors)}"
        )

        return ExtractResult(
            data=final_data,
            confidence={k: LLM_DEFAULT_CONFIDENCE for k in final_data},
            provenance={k: 'llm_chunked' for k in final_data}
        )

    def _get_result_summary(self, result: Dict) -> str:
        """获取结果摘要（用于日志）"""
        if not result:
            return "空"
        clauses_count = len(result.get('clauses', []))
        fields_count = len(result.get('product_info', {}))
        return f"{fields_count}字段, {clauses_count}条款"

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
语义分析器

使用 LLM 分析文档结构，识别语义单元边界，指导后续提取策略。
"""
import json
import logging
from typing import Dict, List, Any, Optional

from .utils.json_parser import parse_llm_json_response
from .utils.constants import config


logger = logging.getLogger(__name__)


class SemanticAnalyzer:
    """语义分析器 - LLM 驱动的文档结构分析"""

    STRUCTURE_ANALYSIS_PROMPT = """你是保险文档结构分析专家。

**任务**: 分析文档结构，识别语义单元边界

**要求**:
1. 识别章节边界 (章、节、条款)
2. 识别表格类型 (费率表、病种表、现金价值表、其他)
3. 建议合理的分块位置（在语义边界处，确保内容完整）
4. 识别内容类型，指导提取策略

**输出格式** (JSON):
{{
  "structure_type": "structured|semi_structured|unstructured",
  "sections": [
    {{"start": 0, "end": 1500, "title": "第一章 总则", "type": "chapter"}}
  ],
  "clauses": [
    {{"start": 1500, "end": 2500, "number": "2.1", "title": "保险责任", "number_type": "decimal"}}
  ],
  "tables": [
    {{"start": 5000, "end": 8000, "type": "premium_table", "parser_type": "html", "confidence": 0.95}}
  ],
  "suggested_chunks": [
    {{"start": 0, "end": 12000, "rationale": "包含第一章到第三章，内容完整"}}
  ],
  "content_types": ["product_info", "clauses", "premium_table"],
  "extraction_strategy": "specialized_parsers|llm_primary|hybrid",
  "estimated_complexity": "low|medium|high"
}}

**文档内容** (前 5000 字符):
{document_sample}
"""

    def __init__(self, llm_client):
        """
        初始化语义分析器

        Args:
            llm_client: LLM 客户端
        """
        self.llm_client = llm_client

    def analyze(self, document: str) -> Dict[str, Any]:
        """
        分析文档结构

        Args:
            document: 完整文档内容

        Returns:
            结构分析结果，包含章节、条款、表格位置和分块建议
        """
        from .utils.constants import config

        doc_length = len(document)

        # 大文档 (>20000 字符) 使用规则分块，避免 LLM 建议不准确
        if doc_length > 20000:
            logger.info(f"大文档 ({doc_length} 字符)，使用规则分块策略")
            structure = self._analyze_with_rules(document)
            structure['_metadata'] = {
                'analyzer': 'SemanticAnalyzer (rule-based)',
                'document_length': doc_length,
                'reason': 'large_document'
            }
            return structure

        # 小文档使用 LLM 分析
        sample = self._get_rep_sample(document, max_chars=5000)

        try:
            prompt = self.STRUCTURE_ANALYSIS_PROMPT.format(document_sample=sample)
            response = self.llm_client.generate(
                prompt,
                max_tokens=2000,
                temperature=0.1
            )

            structure = parse_llm_json_response(response)
            structure['_metadata'] = {
                'analyzer': 'SemanticAnalyzer (LLM-based)',
                'document_length': doc_length,
                'sample_length': len(sample)
            }

        except Exception as e:
            logger.warning(f"LLM 结构分析失败: {e}，使用规则回退")
            structure = self._analyze_with_rules(document)

        # 验证和调整
        structure = self._validate_and_adjust(document, structure)

        logger.info(f"结构分析完成: 类型={structure.get('structure_type')}, "
                   f"策略={structure.get('extraction_strategy')}, "
                   f"复杂度={structure.get('estimated_complexity')}")

        return structure

    def _get_rep_sample(self, document: str, max_chars: int) -> str:
        """
        获取代表性样本

        Args:
            document: 完整文档
            max_chars: 最大字符数

        Returns:
            代表性样本（前部为主）
        """
        if len(document) <= max_chars:
            return document

        # 前 70% + 随机采样（简化版：只取前部）
        return document[:max_chars]

    def _validate_and_adjust(self, document: str, structure: Dict) -> Dict:
        """
        验证并调整结构分析结果

        Args:
            document: 完整文档
            structure: 结构分析结果

        Returns:
            验证并调整后的结构
        """
        doc_length = len(document)

        # 1. 验证边界不超出文档长度
        for section in structure.get('sections', []):
            section['end'] = min(section.get('end', doc_length), doc_length)

        for clause in structure.get('clauses', []):
            clause['end'] = min(clause.get('end', doc_length), doc_length)

        for table in structure.get('tables', []):
            table['end'] = min(table.get('end', doc_length), doc_length)

        for chunk in structure.get('suggested_chunks', []):
            chunk['end'] = min(chunk.get('end', doc_length), doc_length)

        # 2. 确保 suggested_chunks 覆盖整个文档
        chunks = structure.get('suggested_chunks', [])
        if chunks:
            # 检查是否覆盖到文档末尾
            last_end = chunks[-1].get('end', 0)
            if last_end < doc_length:
                # 将剩余内容均匀分块，避免单个大块
                remaining = doc_length - last_end
                from .utils.constants import config
                max_chunk_size = config.DYNAMIC_CONTENT_MAX_CHARS

                if remaining <= max_chunk_size:
                    # 剩余内容不大，直接添加一块
                    chunks.append({
                        'start': last_end,
                        'end': doc_length,
                        'rationale': '文档末尾补充'
                    })
                else:
                    # 剩余内容较大，均匀分块
                    num_additional_chunks = (remaining // max_chunk_size) + 1
                    chunk_size = remaining // num_additional_chunks

                    for i in range(num_additional_chunks):
                        start = last_end + i * chunk_size
                        end = min(start + chunk_size, doc_length) if i < num_additional_chunks - 1 else doc_length
                        chunks.append({
                            'start': start,
                            'end': end,
                            'rationale': f'文档末尾分块 {i+1}/{num_additional_chunks}'
                        })

        return structure

    def _analyze_with_rules(self, document: str) -> Dict[str, Any]:
        """
        使用规则进行结构分析（LLM 失败时的回退方案）

        Args:
            document: 文档内容

        Returns:
            基于规则的结构分析结果
        """
        import re

        # 1. 检测结构化程度
        section_patterns = [
            r'第[一二三四五六七八九十百千]+\s*[章节条款]',
            r'#{1,2}\s+',
            r'\d+\.[1-9]',
        ]
        section_count = sum(
            len(re.findall(p, document, re.MULTILINE))
            for p in section_patterns
        )

        is_structured = section_count >= 5
        structure_type = 'structured' if is_structured else 'semi_structured'

        # 2. 检测表格类型
        has_html_table = '<table>' in document or '<tr>' in document
        has_markdown_table = '|' in document and re.search(r'^\|.*\|', document, re.MULTILINE)
        has_premium_keywords = bool(re.search(r'(年龄|岁).*?(保费|费率|元)', document))

        tables = []
        if has_html_table:
            tables.append({
                'type': 'premium_table' if has_premium_keywords else 'generic_table',
                'parser_type': 'html',
                'confidence': 0.8
            })
        elif has_markdown_table:
            tables.append({
                'type': 'premium_table' if has_premium_keywords else 'generic_table',
                'parser_type': 'markdown',
                'confidence': 0.7
            })

        # 3. 建议分块策略 - 使用语义边界分块
        doc_length = len(document)
        if doc_length <= config.DYNAMIC_CONTENT_MAX_CHARS:
            chunks = [{'start': 0, 'end': doc_length, 'rationale': '小文档无需分块'}]
        else:
            # 使用语义边界分块
            chunks = self._semantic_chunking_by_rules(document, config.DYNAMIC_CONTENT_MAX_CHARS)

        # 4. 确定提取策略
        if tables and has_html_table:
            extraction_strategy = 'specialized_parsers'
        elif is_structured:
            extraction_strategy = 'hybrid'
        else:
            extraction_strategy = 'llm_primary'

        return {
            'structure_type': structure_type,
            'sections': [],
            'clauses': [],
            'tables': tables,
            'suggested_chunks': chunks,
            'content_types': ['product_info'],
            'extraction_strategy': extraction_strategy,
            'estimated_complexity': 'low' if doc_length < 10000 else 'medium',
            '_fallback': True
        }

    def _semantic_chunking_by_rules(self, document: str, max_chunk_size: int) -> List[Dict[str, Any]]:
        """
        基于规则的语义边界分块

        Args:
            document: 文档内容
            max_chunk_size: 最大块大小

        Returns:
            分块列表
        """
        import re

        # 语义边界模式（优先级从高到低）
        boundary_patterns = [
            r'\n第[一二三四五六七八九十百千]+\s*章[^\\n]*\n',  # 第X章
            r'\n#{1,2}\s+[^\\n]+\n',                         # Markdown 标题
            r'\n\d+\.\d+\s+',                                # 数字编号 (如 2.1)
            r'\n\n+',                                       # 空行
        ]

        chunks = []
        start = 0
        doc_length = len(document)
        chunk_num = 0

        while start < doc_length:
            # 计算理想的结束位置
            ideal_end = min(start + max_chunk_size, doc_length)

            # 如果是最后一块
            if ideal_end >= doc_length:
                chunks.append({
                    'start': start,
                    'end': doc_length,
                    'rationale': f'规则分块第 {chunk_num + 1} 部分（末尾）'
                })
                break

            # 在 ideal_end 附近寻找最佳语义边界
            search_start = max(start, ideal_end - 1000)
            search_end = min(ideal_end + 1000, doc_length)
            search_range = document[search_start:search_end]

            best_boundary = ideal_end
            for pattern in boundary_patterns:
                matches = list(re.finditer(pattern, search_range, re.MULTILINE))
                if matches:
                    # 找到最接近 ideal_end 的边界
                    for match in reversed(matches):
                        boundary_pos = search_start + match.end()
                        if start < boundary_pos <= ideal_end + 500:
                            best_boundary = boundary_pos
                            break
                    if best_boundary != ideal_end:
                        break

            # 确保块不会太小
            if best_boundary - start < max_chunk_size * 0.3:
                best_boundary = ideal_end

            chunks.append({
                'start': start,
                'end': int(best_boundary),
                'rationale': f'规则分块第 {chunk_num + 1} 部分（语义边界）'
            })

            start = int(best_boundary)
            chunk_num += 1

        logger.info(f"规则分块完成: {len(chunks)} 块，每块约 {max_chunk_size} 字符")
        return chunks

    def get_extraction_strategy(self, document: str) -> str:
        """
        快速获取推荐的提取策略

        Args:
            document: 文档内容

        Returns:
            提取策略: specialized_parsers|llm_primary|hybrid
        """
        structure = self.analyze(document)
        return structure.get('extraction_strategy', 'llm_primary')

    def should_use_chunking(self, document: str) -> bool:
        """
        判断是否需要分块处理

        Args:
            document: 文档内容

        Returns:
            是否需要分块
        """
        structure = self.analyze(document)
        chunks = structure.get('suggested_chunks', [])
        return len(chunks) > 1

    def get_suggested_chunks(self, document: str) -> List[Dict[str, Any]]:
        """
        获取建议的分块位置

        Args:
            document: 文档内容

        Returns:
            分块建议列表
        """
        structure = self.analyze(document)
        return structure.get('suggested_chunks', [{'start': 0, 'end': len(document)}])

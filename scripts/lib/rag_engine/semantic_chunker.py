#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""语义感知分块器

两阶段策略：
1. 结构分块：按 Markdown 标题层级和条款标记分割
2. 语义精调：使用 LlamaIndex SemanticSplitterNodeParser 在结构块内按语义边界分割
"""
import re
import logging
from typing import List

from llama_index.core import Document
from llama_index.core.schema import TextNode

from .config import ChunkingConfig
from .doc_parser import _extract_product_category, extract_law_name

logger = logging.getLogger(__name__)

_ARTICLE_PATTERN = re.compile(
    r'^#{1,3}\s*第([一二三四五六七八九十百千\d]+)条\s*(.*?)$'
)
_HEADING_PATTERN = re.compile(r'^(#{1,3})\s+(.+)$')
_SENTENCE_PATTERN = re.compile(r'(?<=[。；！？\n])\s*')


class SemanticChunker:
    """语义感知分块器

    两阶段分块策略：
    1. 按标题层级和条款标记进行结构分割
    2. 对每个结构块内部使用 SemanticSplitterNodeParser 做语义精调
    3. 对过短/过长 chunk 做合并/拆分处理
    4. 保留 overlap 重叠窗口
    5. 附加 hierarchy_path 层级元数据
    """

    def __init__(self, config: ChunkingConfig = None):
        self.config = config or ChunkingConfig()
        self._min_size = self.config.min_chunk_size
        self._max_size = self.config.max_chunk_size
        self._overlap_sentences = self.config.overlap_sentences
        self._use_semantic_split = self._check_semantic_split()

    def chunk(self, documents: List[Document]) -> List[TextNode]:
        all_nodes: List[TextNode] = []
        for doc in documents:
            nodes = self._chunk_single_document(doc)
            all_nodes.extend(nodes)
        return all_nodes

    def _chunk_single_document(self, doc: Document) -> List[TextNode]:
        law_name = extract_law_name(doc.text, doc.metadata)
        source_file = doc.metadata.get('file_name', '')
        lines = doc.text.split('\n')

        segments = self._split_by_structure(lines, law_name, source_file)
        segments = self._merge_short_segments(segments)
        segments = self._split_long_segments(segments)

        nodes = self._build_nodes_with_overlap(segments, law_name, source_file)

        if self._use_semantic_split:
            nodes = self._semantic_refine(nodes)

        return nodes

    @staticmethod
    def _check_semantic_split() -> bool:
        try:
            from llama_index.core.node_parser import SemanticSplitterNodeParser
            return True
        except ImportError:
            return False

    def _semantic_refine(self, nodes: List[TextNode]) -> List[TextNode]:
        from llama_index.core.node_parser import SemanticSplitterNodeParser

        embed_model = self._get_embed_model()
        if not embed_model:
            return nodes

        splitter = SemanticSplitterNodeParser(
            buffer_size=1,
            breakpoint_percentile_threshold=95,
            embed_model=embed_model,
        )

        refined: List[TextNode] = []
        for node in nodes:
            if len(node.text) <= self._max_size:
                refined.append(node)
                continue

            wrapper = Document(text=node.text, metadata=node.metadata)
            try:
                sub_nodes = splitter.get_nodes_from_documents([wrapper])
                for sub in sub_nodes:
                    sub.metadata.update(node.metadata)
                refined.extend(sub_nodes)
            except Exception as e:
                logger.warning(f"语义精调失败，保留原始节点: {e}")
                refined.append(node)

        return refined

    def _get_embed_model(self):
        try:
            from .llamaindex_adapter import get_embedding_model
            return get_embedding_model()
        except Exception:
            return None

    @staticmethod
    def _flush_lines(
        current_lines: List[str], current_heading: str, current_article: str, heading_level: int
    ) -> List[dict]:
        """将当前缓冲行刷新为 segment"""
        segments = []
        text = '\n'.join(current_lines).strip()
        if text:
            segments.append({
                'text': text,
                'heading': current_heading,
                'article': current_article,
                'heading_level': heading_level,
            })
        return segments

    def _split_by_structure(
        self,
        lines: List[str],
        law_name: str,
        source_file: str
    ) -> List[dict]:
        segments: List[dict] = []
        current_lines: List[str] = []
        current_heading = ''
        current_article = ''
        heading_level = 0

        for line in lines:
            stripped = line.strip()

            heading_match = _HEADING_PATTERN.match(stripped)
            if heading_match:
                segments.extend(self._flush_lines(current_lines, current_heading, current_article, heading_level))
                current_lines = []

                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()

                if level == 1 and not current_heading:
                    current_heading = title
                    heading_level = level
                    continue

                current_heading = title
                heading_level = level
                continue

            article_match = _ARTICLE_PATTERN.match(stripped)
            if article_match:
                segments.extend(self._flush_lines(current_lines, current_heading, current_article, heading_level))
                current_lines = []

                article_num = article_match.group(1)
                article_desc = article_match.group(2).strip()
                current_article = f"第{article_num}条"
                if article_desc:
                    current_article += f" {article_desc}"

            current_lines.append(line)

        segments.extend(self._flush_lines(current_lines, current_heading, current_article, heading_level))
        return segments

    def _merge_short_segments(self, segments: List[dict]) -> List[dict]:
        if not self.config.enable_semantic_merge:
            return segments

        merged: List[dict] = []
        buffer_segments: List[dict] = []
        buffer_text = ''

        for seg in segments:
            buffer_segments.append(seg)
            buffer_text += ('\n\n' if buffer_text else '') + seg['text']

            if len(buffer_text) >= self.config.merge_short_threshold:
                merged.append(self._combine_segments(buffer_segments, buffer_text))
                buffer_segments = []
                buffer_text = ''

        if buffer_segments:
            merged.append(self._combine_segments(buffer_segments, buffer_text))

        return merged

    def _combine_segments(self, segments: List[dict], combined_text: str) -> dict:
        first = segments[0]
        last = segments[-1]
        return {
            'text': combined_text.strip(),
            'heading': first['heading'] or last['heading'],
            'article': first['article'] or last['article'],
            'heading_level': first['heading_level'],
        }

    def _split_long_segments(self, segments: List[dict]) -> List[dict]:
        if not self.config.split_long_chunks:
            return segments

        result: List[dict] = []
        for seg in segments:
            if len(seg['text']) <= self._max_size:
                result.append(seg)
            else:
                result.extend(self._split_by_sentences(seg))
        return result

    def _split_by_sentences(self, seg: dict) -> List[dict]:
        text = seg['text']
        sentences = _SENTENCE_PATTERN.split(text)
        sentences = [s.strip() for s in sentences if s.strip()]

        if not sentences:
            return [seg]

        chunks: List[dict] = []
        current = ''
        for sentence in sentences:
            if current and len(current) + len(sentence) > self._max_size:
                chunks.append({
                    'text': current.strip(),
                    'heading': seg['heading'],
                    'article': seg['article'],
                    'heading_level': seg['heading_level'],
                })
                current = sentence
            else:
                current += sentence

        if current.strip():
            chunks.append({
                'text': current.strip(),
                'heading': seg['heading'],
                'article': seg['article'],
                'heading_level': seg['heading_level'],
            })

        return chunks

    def _build_nodes_with_overlap(
        self, segments: List[dict], law_name: str, source_file: str
    ) -> List[TextNode]:
        nodes: List[TextNode] = []
        category = _extract_product_category(source_file)

        for i, seg in enumerate(segments):
            overlap_text = ''
            if self._overlap_sentences > 0 and i > 0:
                prev_text = segments[i - 1]['text']
                prev_sentences = _SENTENCE_PATTERN.split(prev_text)
                prev_sentences = [s.strip() for s in prev_sentences if s.strip()]
                overlap_sentences = prev_sentences[-self._overlap_sentences:]
                overlap_text = ''.join(overlap_sentences)

            hierarchy_parts: List[str] = []
            if seg['heading']:
                hierarchy_parts.append(seg['heading'])
            if seg['article']:
                hierarchy_parts.append(seg['article'])
            hierarchy_path = ' > '.join(hierarchy_parts) if hierarchy_parts else ''

            full_text = seg['text']
            if overlap_text:
                full_text = overlap_text + full_text

            node = TextNode(
                text=full_text,
                metadata={
                    'law_name': law_name,
                    'article_number': seg['article'] or '未知',
                    'category': category,
                    'hierarchy_path': hierarchy_path,
                    'source_file': source_file,
                }
            )
            nodes.append(node)

        return nodes

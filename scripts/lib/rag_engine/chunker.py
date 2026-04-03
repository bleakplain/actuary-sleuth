#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""KB 检查清单分块器

解析 preprocessor.py 生成的结构化 Markdown 文件：
- YAML frontmatter → 文件级元数据
- ## 第N项 → 分块边界
- > **元数据** blockquote → 条款级元数据

产出的 TextNode 兼容现有检索管线（fusion.py、rag_engine.py、reranker.py）。
"""
import re
import logging
from pathlib import Path
from typing import List, Dict, Optional, Any

import yaml  # type: ignore[import-untyped]

from llama_index.core import Document
from llama_index.core.schema import TextNode

logger = logging.getLogger(__name__)

_ITEM_HEADING = re.compile(r'^##\s*第(\d+)项\s*$', re.MULTILINE)
_BLOCKQUOTE_META = re.compile(r'^>\s*\*\*元数据\*\*\s*:\s*(.+)$', re.MULTILINE)
_KV_PAIR = re.compile(r'(\S+?)=([^|]+)')
_MAX_CHUNK_CHARS = 3000
_SENTENCE_SPLIT = re.compile(r'(?<=[。；！？\n])\s*')


class ChecklistChunker:
    """KB 检查清单分块器。

    将预处理好的 Markdown 文件按 ## 第N项 拆分为独立 chunk，
    从 frontmatter 和 blockquote 中提取完整元数据。
    """

    def __init__(self):
        pass

    def chunk(self, documents: List[Document]) -> List[TextNode]:
        """分块入口，兼容 regulation 分块器接口。"""
        all_nodes: List[TextNode] = []
        for doc in documents:
            all_nodes.extend(self._chunk_single(doc))
        return all_nodes

    def _chunk_single(self, doc: Document) -> List[TextNode]:
        source_file = doc.metadata.get('file_name', '')
        text = doc.text

        frontmatter, body = self._extract_frontmatter(text)
        law_name = self._extract_law_name(frontmatter, body)
        items = self._split_by_items(body)

        return self._build_nodes(items, law_name, source_file, frontmatter)

    @staticmethod
    def _extract_frontmatter(text: str) -> tuple:
        """提取 YAML frontmatter，返回 (dict, body_text)。"""
        if not text.startswith('---'):
            return {}, text

        parts = text.split('---', 2)
        if len(parts) < 3:
            return {}, text

        yaml_str = parts[1].strip()
        body = parts[2].strip()

        try:
            data = yaml.safe_load(yaml_str)
            return data if isinstance(data, dict) else {}, body
        except yaml.YAMLError:
            logger.warning("YAML frontmatter 解析失败")
            return {}, body

    @staticmethod
    def _extract_law_name(frontmatter: dict, body: str) -> str:
        """从 frontmatter 或 body 标题提取法规名称。"""
        name = frontmatter.get('regulation', '')
        if name:
            return str(name)

        for line in body.split('\n'):
            m = re.match(r'^#\s+(.+)$', line.strip())
            if m:
                return m.group(1).strip()

        return frontmatter.get('collection', '未知')

    @staticmethod
    def _split_by_items(body: str) -> List[dict]:
        """按 ## 第N项 切分，提取 blockquote 元数据。"""
        matches = list(_ITEM_HEADING.finditer(body))
        if not matches:
            return []

        items = []
        for i, match in enumerate(matches):
            item_num = match.group(1)
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
            section = body[start:end].strip()

            chunk_meta: Dict[str, str] = {}
            meta_match = _BLOCKQUOTE_META.search(section)
            if meta_match:
                meta_str = meta_match.group(1)
                for kv in _KV_PAIR.finditer(meta_str):
                    chunk_meta[kv.group(1).strip()] = kv.group(2).strip()
                section = _BLOCKQUOTE_META.sub('', section).strip()

            section = re.sub(r'^\s+', '', section, count=1) if section else section

            items.append({
                'item_number': item_num,
                'content': section,
                'chunk_meta': chunk_meta,
            })

        return items

    def _build_nodes(
        self,
        items: List[dict],
        law_name: str,
        source_file: str,
        frontmatter: dict,
    ) -> List[TextNode]:
        """构建 TextNode 列表。"""
        collection = str(frontmatter.get('collection', ''))
        category = collection.split('_', 1)[1] if '_' in collection else collection

        agencies = frontmatter.get('发文机关', [])
        doc_numbers = frontmatter.get('文号', [])
        remarks = frontmatter.get('备注', [])

        issuing_authority = self._first_non_empty(agencies)
        doc_number = self._first_non_empty(doc_numbers)
        remark = self._first_non_empty(remarks)
        insurance_type = frontmatter.get('险种类型', '')

        nodes: List[TextNode] = []
        for item in items:
            content = item['content']
            if len(content) < 20:
                continue

            article_number = f"第{item['item_number']}项"
            hierarchy_path = f"{category} > {law_name} > {article_number}"

            metadata: Dict[str, Any] = {
                'law_name': law_name,
                'article_number': article_number,
                'category': category,
                'source_file': source_file,
                'hierarchy_path': hierarchy_path,
            }

            if doc_number:
                metadata['doc_number'] = doc_number
            if issuing_authority:
                metadata['issuing_authority'] = issuing_authority

            if insurance_type:
                metadata['险种类型'] = insurance_type
            if remark:
                metadata['备注'] = remark

            for key, value in item['chunk_meta'].items():
                metadata[key] = value

            if len(content) > _MAX_CHUNK_CHARS:
                sub_nodes = self._split_long_chunk(content, metadata)
                nodes.extend(sub_nodes)
            else:
                nodes.append(TextNode(text=content, metadata=metadata))

        return nodes

    @staticmethod
    def _split_long_chunk(
        text: str, metadata: Dict[str, Any]
    ) -> List[TextNode]:
        """按句子边界拆分超长 chunk。"""
        sentences = _SENTENCE_SPLIT.split(text)
        current = ''
        nodes: List[TextNode] = []

        for sent in sentences:
            if len(current) + len(sent) > _MAX_CHUNK_CHARS and current:
                nodes.append(TextNode(text=current.strip(), metadata=metadata))
                current = sent
            else:
                current += sent

        if current.strip():
            nodes.append(TextNode(text=current.strip(), metadata=metadata))

        return nodes

    @staticmethod
    def _first_non_empty(values: list) -> str:
        """取列表中第一个非空字符串。"""
        for v in values:
            if v and str(v).strip():
                return str(v).strip()
        return ''

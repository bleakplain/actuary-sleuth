#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Markdown 文档解析器

V3 分块策略:
1. 层级识别: 多策略融合识别章节标题
2. 递归切分: 章节→子标题→段落→句子
3. 语义完整性: should_merge() 检测错误断开
4. 智能Overlap: 基于句子边界
"""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple

import yaml
from llama_index.core import Document
from llama_index.core.schema import TextNode
from dataclasses import replace

from ..models import DocumentMeta

logger = logging.getLogger(__name__)

# 内存安全常量
MAX_DOCUMENT_CHARS = 10_000_000
MAX_CHUNKS = 10_000
FORCE_SPLIT_THRESHOLD = 10_000

# 句子边界
SENTENCE_ENDS = '。；！？.!?'

# 层级标题正则模式 (多策略融合)
HEADING_PATTERNS = {
    # Markdown 标题: # 一级, ## 二级, ### 三级
    'markdown': re.compile(r'^(#{1,6})\s+(.+?)\s*$', re.MULTILINE),
    # 中文条款: 第一条, 第二条, 第一百条
    'cn_clause': re.compile(r'^第([一二三四五六七八九十百零]+)条[：:\s]', re.MULTILINE),
    # 数字层级: 1., 1.1, 1.1.1
    'num_hierarchy': re.compile(r'^(\d+(?:\.\d+)*)[\.、\s]', re.MULTILINE),
    # 括号编号: （一）, (一), （1）, (1)
    'bracket': re.compile(r'^[（\(]([一二三四五六七八九十\d]+)[）\)]', re.MULTILINE),
    # 中文数字: 一、二、三、
    'cn_num': re.compile(r'^([一二三四五六七八九十]+)[、\.]', re.MULTILINE),
}

# 元数据提取
_BLOCKQUOTE_META = re.compile(r'^>\s*\*\*元数据\*\*\s*:\s*(.+)$', re.MULTILINE)
_KV_PAIR = re.compile(r'(\S+?)=([^|]+)')


@dataclass
class Heading:
    """标题节点"""
    level: int
    text: str
    start: int
    end: int
    heading_type: str

    @property
    def section_path(self) -> str:
        return self.text.strip()


@dataclass
class Chunk:
    """分块结果"""
    content: str
    section_path: str
    metadata: Dict[str, Any]
    chunk_id: int = 0
    prev_chunk_id: Optional[int] = None
    next_chunk_id: Optional[int] = None


class MdParser:
    """Markdown 解析器

    V3 分块策略:
    - 识别文档层级结构（多策略融合）
    - 按语义单元递归切分
    - 语义完整性检查
    - 智能句子边界 overlap
    """

    def __init__(
        self,
        max_chunk_chars: int = 3000,
        chunk_overlap_chars: int = 150,
        min_chunk_chars: int = 20,
        chunk_config: Optional[Any] = None,
    ):
        if chunk_config is not None:
            self.max_chunk_chars = chunk_config.max_chunk_chars
            self.chunk_overlap_chars = chunk_config.chunk_overlap_chars
            self.min_chunk_chars = chunk_config.min_chunk_chars
        else:
            self.max_chunk_chars = max_chunk_chars
            self.chunk_overlap_chars = chunk_overlap_chars
            self.min_chunk_chars = min_chunk_chars

    @staticmethod
    def supported_extensions() -> List[str]:
        return ['.md', '.markdown']

    def parse_document(self, doc: Document) -> List[TextNode]:
        """解析 Document 对象，返回分块后的 TextNode 列表。"""
        source_file = doc.metadata.get('file_name', '')
        text = doc.text

        # 内存安全检查
        if len(text) > MAX_DOCUMENT_CHARS:
            logger.warning(
                f"文档过大 ({len(text)} chars)，截断至 {MAX_DOCUMENT_CHARS} chars: {source_file}"
            )
            text = text[:MAX_DOCUMENT_CHARS]

        frontmatter, body = self._extract_frontmatter(text)
        doc_meta = DocumentMeta.from_frontmatter(frontmatter)

        if not doc_meta.law_name:
            law_name = self._extract_law_name(body)
            if law_name:
                doc_meta = replace(doc_meta, law_name=law_name)

        # V3: 识别层级结构
        headings = self._identify_headings(body)

        # V3: 递归切分
        chunks = self._recursive_chunk(body, headings, doc_meta, source_file)

        # 限制最大chunk数
        if len(chunks) > MAX_CHUNKS:
            logger.warning(
                f"分块数过多 ({len(chunks)})，仅保留前 {MAX_CHUNKS} 个: {source_file}"
            )
            chunks = chunks[:MAX_CHUNKS]

        # 设置chunk链
        self._link_chunks(chunks)

        return self._chunks_to_nodes(chunks)

    def _identify_headings(self, body: str) -> List[Heading]:
        """识别文档层级结构（多策略融合）

        支持的格式:
        - Markdown: # 一级标题, ## 二级标题
        - 中文条款: 第一条, 第二条
        - 数字层级: 1., 1.1, 1.1.1
        - 括号编号: （一）, (1)
        - 中文数字: 一、二、
        """
        all_headings: List[Heading] = []

        # Markdown 标题 (最高优先级)
        for m in HEADING_PATTERNS['markdown'].finditer(body):
            level = len(m.group(1))
            text = m.group(2).strip()
            all_headings.append(Heading(
                level=level,
                text=text,
                start=m.start(),
                end=m.end(),
                heading_type='markdown',
            ))

        # 如果已有Markdown标题，跳过其他模式
        if all_headings:
            all_headings.sort(key=lambda h: h.start)
            return all_headings

        # 中文条款
        for m in HEADING_PATTERNS['cn_clause'].finditer(body):
            text = m.group(0).strip()
            all_headings.append(Heading(
                level=1,
                text=text,
                start=m.start(),
                end=m.end(),
                heading_type='cn_clause',
            ))

        # 数字层级
        for m in HEADING_PATTERNS['num_hierarchy'].finditer(body):
            num = m.group(1)
            level = num.count('.') + 1
            text = m.group(0).strip()
            all_headings.append(Heading(
                level=level,
                text=text,
                start=m.start(),
                end=m.end(),
                heading_type='num_hierarchy',
            ))

        # 括号编号
        for m in HEADING_PATTERNS['bracket'].finditer(body):
            text = m.group(0).strip()
            all_headings.append(Heading(
                level=2,
                text=text,
                start=m.start(),
                end=m.end(),
                heading_type='bracket',
            ))

        # 中文数字
        for m in HEADING_PATTERNS['cn_num'].finditer(body):
            text = m.group(0).strip()
            all_headings.append(Heading(
                level=2,
                text=text,
                start=m.start(),
                end=m.end(),
                heading_type='cn_num',
            ))

        # 按位置排序
        all_headings.sort(key=lambda h: h.start)
        return all_headings

    def _recursive_chunk(
        self,
        body: str,
        headings: List[Heading],
        doc_meta: DocumentMeta,
        source_file: str,
    ) -> List[Chunk]:
        """递归切分文档

        策略:
        1. 如果章节 ≤ max_chunk_chars，整体作为一个chunk
        2. 如果超过，检查是否有子标题，递归处理
        3. 如果没有子标题，按段落累积
        4. 如果单段落超长，按句子边界切分
        """
        chunks: List[Chunk] = []

        if not headings:
            # 无标题结构，按段落切分
            return self._chunk_by_paragraph(body, doc_meta, source_file, "")

        # 按顶级标题切分
        for i, heading in enumerate(headings):
            start = heading.end
            end = headings[i + 1].start if i + 1 < len(headings) else len(body)
            section_text = body[start:end].strip()

            if not section_text:
                continue

            section_path = heading.section_path

            # 提取 blockquote 元数据
            chunk_meta: Dict[str, str] = {}
            meta_match = _BLOCKQUOTE_META.search(section_text)
            if meta_match:
                meta_str = meta_match.group(1)
                for kv in _KV_PAIR.finditer(meta_str):
                    chunk_meta[kv.group(1).strip()] = kv.group(2).strip()
                section_text = _BLOCKQUOTE_META.sub('', section_text).strip()

            if len(section_text) <= self.max_chunk_chars:
                # 整个章节作为一个chunk
                chunk = Chunk(
                    content=section_text,
                    section_path=section_path,
                    metadata=self._build_metadata(doc_meta, source_file, section_path),
                )
                # 合并 blockquote 元数据
                chunk.metadata.update(chunk_meta)
                chunks.append(chunk)
            else:
                # 检查子标题
                sub_headings = [
                    h for h in headings
                    if h.start > heading.start and h.end <= end and h.level > heading.level
                ]

                if sub_headings:
                    # 递归处理子章节
                    sub_chunks = self._recursive_chunk(
                        body[start:end], sub_headings, doc_meta, source_file
                    )
                    chunks.extend(sub_chunks)
                else:
                    # 按段落切分
                    para_chunks = self._chunk_by_paragraph(
                        section_text, doc_meta, source_file, section_path
                    )
                    # 合并 blockquote 元数据到所有子chunk
                    for c in para_chunks:
                        c.metadata.update(chunk_meta)
                    chunks.extend(para_chunks)

        return chunks

    def _chunk_by_paragraph(
        self,
        text: str,
        doc_meta: DocumentMeta,
        source_file: str,
        section_path: str,
    ) -> List[Chunk]:
        """按段落累积切分

        段落逐个加入，直到接近 max_chunk_chars 就封一个chunk。
        """
        paragraphs = re.split(r'\n{2,}', text)
        chunks: List[Chunk] = []
        current = ''

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(current) + len(para) + 1 <= self.max_chunk_chars:
                current = current + '\n\n' + para if current else para
            else:
                if current:
                    chunks.append(Chunk(
                        content=current,
                        section_path=section_path,
                        metadata=self._build_metadata(doc_meta, source_file, section_path),
                    ))

                if len(para) > self.max_chunk_chars:
                    # 单段落超长，按句子切分
                    sent_chunks = self._chunk_by_sentence(para, doc_meta, source_file, section_path)
                    chunks.extend(sent_chunks)
                    current = ''
                else:
                    current = para

        if current:
            chunks.append(Chunk(
                content=current,
                section_path=section_path,
                metadata=self._build_metadata(doc_meta, source_file, section_path),
            ))

        # 语义完整性检查与合并
        chunks = self._check_and_merge(chunks)

        return chunks

    def _chunk_by_sentence(
        self,
        text: str,
        doc_meta: DocumentMeta,
        source_file: str,
        section_path: str,
    ) -> List[Chunk]:
        """按句子边界切分（支持智能overlap）"""
        # 超长文本强制分割
        if len(text) > FORCE_SPLIT_THRESHOLD:
            return self._force_split(text, doc_meta, source_file, section_path)

        sentences = self._split_sentences(text)
        chunks: List[Chunk] = []
        current = ''

        for sent in sentences:
            if len(current) + len(sent) <= self.max_chunk_chars:
                current += sent
            else:
                if current:
                    chunks.append(Chunk(
                        content=current.strip(),
                        section_path=section_path,
                        metadata=self._build_metadata(doc_meta, source_file, section_path),
                    ))
                current = sent

        if current.strip():
            chunks.append(Chunk(
                content=current.strip(),
                section_path=section_path,
                metadata=self._build_metadata(doc_meta, source_file, section_path),
            ))

        return chunks

    def _split_sentences(self, text: str) -> List[str]:
        """按句子边界分割"""
        result = []
        start = 0
        for i, char in enumerate(text):
            if char in SENTENCE_ENDS:
                result.append(text[start:i + 1])
                start = i + 1
        if start < len(text):
            result.append(text[start:])
        return result

    def _force_split(
        self,
        text: str,
        doc_meta: DocumentMeta,
        source_file: str,
        section_path: str,
    ) -> List[Chunk]:
        """强制分割超长文本"""
        chunks: List[Chunk] = []
        step = self.max_chunk_chars - self.chunk_overlap_chars
        for i in range(0, len(text), step):
            chunk_text = text[i:i + self.max_chunk_chars]
            if len(chunk_text) >= self.min_chunk_chars:
                chunks.append(Chunk(
                    content=chunk_text,
                    section_path=section_path,
                    metadata=self._build_metadata(doc_meta, source_file, section_path),
                ))
        return chunks

    def _check_and_merge(self, chunks: List[Chunk]) -> List[Chunk]:
        """语义完整性检查：检测错误断开并合并

        检测场景:
        1. chunk以冒号结尾 → 后面大概率是列表
        2. 下一个chunk以列表项编号开头
        3. 下一个chunk以转折词开头
        """
        if len(chunks) <= 1:
            return chunks

        merged: List[Chunk] = []
        i = 0

        while i < len(chunks):
            current = chunks[i]

            while i + 1 < len(chunks):
                next_chunk = chunks[i + 1]

                if self._should_merge(current.content, next_chunk.content):
                    # 合并
                    combined = current.content + '\n\n' + next_chunk.content
                    if len(combined) <= self.max_chunk_chars * 1.5:  # 允许适度超长
                        current = Chunk(
                            content=combined,
                            section_path=current.section_path,
                            metadata=current.metadata,
                        )
                        i += 1
                    else:
                        break
                else:
                    break

            merged.append(current)
            i += 1

        return merged

    def _should_merge(self, chunk1: str, chunk2: str) -> bool:
        """检测两个chunk是否应该合并

        场景:
        1. chunk1 以冒号/分号结尾 → 后面是列表
        2. chunk2 是列表项编号开头
        3. chunk2 以转折词开头
        """
        text1 = chunk1.strip()
        text2 = chunk2.strip()

        # 场景1: 冒号结尾
        if text1.endswith((':', '：', ';', '；')):
            return True

        # 场景2: 列表项编号开头
        if re.match(r'^[（(]\d+[）)]|^[①②③④⑤]|^[a-zA-Z]\.', text2):
            return True

        # 场景3: 转折词开头
        if text2.startswith(('但', '然而', '除外', '不包括', '另有规定', '但是')):
            return True

        return False

    def _build_metadata(
        self,
        doc_meta: DocumentMeta,
        source_file: str,
        section_path: str,
    ) -> Dict[str, Any]:
        """构建chunk元数据"""
        metadata = doc_meta.to_chunk_metadata(section_path, source_file)
        metadata['section_path'] = section_path
        metadata['content_type'] = 'text'
        metadata['article_number'] = section_path
        return metadata

    def _link_chunks(self, chunks: List[Chunk]) -> None:
        """设置chunk链（prev/next）"""
        for i, chunk in enumerate(chunks):
            chunk.chunk_id = i
            chunk.prev_chunk_id = i - 1 if i > 0 else None
            chunk.next_chunk_id = i + 1 if i + 1 < len(chunks) else None

    def _chunks_to_nodes(self, chunks: List[Chunk]) -> List[TextNode]:
        """转换为TextNode，添加智能overlap"""
        nodes: List[TextNode] = []

        for i, chunk in enumerate(chunks):
            content = chunk.content

            # 添加智能overlap（从上一个chunk末尾）
            if i > 0 and self.chunk_overlap_chars > 0:
                overlap = self._get_smart_overlap(chunks[i - 1].content)
                if overlap and len(content) + len(overlap) <= self.max_chunk_chars:
                    content = overlap + content

            metadata = chunk.metadata.copy()
            metadata['chunk_id'] = chunk.chunk_id
            metadata['prev_chunk_id'] = chunk.prev_chunk_id
            metadata['next_chunk_id'] = chunk.next_chunk_id

            nodes.append(TextNode(text=content.strip(), metadata=metadata))

        return nodes

    def _get_smart_overlap(self, prev_content: str) -> str:
        """基于句子边界的智能overlap

        找到前一个chunk末尾最近的句号位置，从那之后开始overlap。
        确保overlap部分是完整的句子。
        """
        if len(prev_content) <= self.chunk_overlap_chars:
            return prev_content

        # 取末尾overlap范围
        overlap_raw = prev_content[-self.chunk_overlap_chars:]

        # 找最近的句子边界
        last_sentence_end = -1
        for end_char in SENTENCE_ENDS:
            pos = overlap_raw.find(end_char)
            if pos > last_sentence_end:
                last_sentence_end = pos

        if last_sentence_end >= 0:
            return overlap_raw[last_sentence_end + 1:]

        return overlap_raw

    @staticmethod
    def _extract_frontmatter(text: str) -> tuple:
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
    def _extract_law_name(body: str) -> str:
        """从 body 标题提取法规名称"""
        for line in body.split('\n'):
            m = re.match(r'^#\s+(.+)$', line.strip())
            if m:
                return m.group(1).strip()
        return ''

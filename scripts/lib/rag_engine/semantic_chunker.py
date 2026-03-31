#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""法规条款分块器

按条款逐条分割法规文档，保留层级元数据：
1. 结构识别：Markdown 标题、章节标题（第X章）、条款标记（第X条）
2. 元数据提取：法规名称、发文号
3. 层级路径：法规名 > 章节名
"""
import re
import logging
from typing import List

from llama_index.core import Document
from llama_index.core.schema import TextNode

from .config import ChunkingConfig
from .doc_parser import _extract_product_category, _HEADING_PATTERN

logger = logging.getLogger(__name__)

_ARTICLE_PATTERN = re.compile(
    r'^#{1,3}\s*第([一二三四五六七八九十百千\d]+)条\s*(.*?)$'
)
_PLAIN_ARTICLE_PATTERN = re.compile(
    r'^第([一二三四五六七八九十百千\d]+)条\s*(.*?)$'
)
_CHAPTER_PATTERN = re.compile(
    r'^(第[一二三四五六七八九十百千\d]+[章节部分篇])\s*(.*?)$'
)
_DOC_NUMBER_PATTERN = re.compile(
    r'^(\d{4})\s*年[第]\s*(\d+)\s*号$'
)
_MAX_CHUNK_CHARS = 3000
_SENTENCE_SPLIT = re.compile(r'(?<=[。；！？\n])\s*')


class SemanticChunker:
    """法规条款分块器 — 按条款逐条分割"""

    def __init__(self, config: ChunkingConfig = None):
        self.config = config or ChunkingConfig()

    def chunk(self, documents: List[Document]) -> List[TextNode]:
        all_nodes: List[TextNode] = []
        for doc in documents:
            nodes = self._chunk_single_document(doc)
            all_nodes.extend(nodes)
        return all_nodes

    def _chunk_single_document(self, doc: Document) -> List[TextNode]:
        source_file = doc.metadata.get('file_name', '')
        lines = doc.text.split('\n')

        doc_meta = self._extract_doc_meta(lines)
        law_name = doc_meta.get('law_name', '')
        segments = self._split_by_structure(lines)

        return self._build_nodes(segments, law_name, source_file, doc_meta)

    @staticmethod
    def _extract_doc_meta(lines: List[str]) -> dict:
        """从文档前置内容中提取元数据：发文机关、法规名称、发文号、生效日期等"""
        meta = {}
        preamble_text = []

        for line in lines:
            stripped = line.strip()
            # 遇到第一条或章节标题时停止
            if _PLAIN_ARTICLE_PATTERN.match(stripped) or _CHAPTER_PATTERN.match(stripped):
                break
            preamble_text.append(stripped)

        full_preamble = '\n'.join(preamble_text)

        # 发文号模式
        # 1. "2019 年第 3 号" (独占一行)
        m = re.search(r'(\d{4})\s*年\s*第\s*(\d+)\s*号', full_preamble)
        if m:
            meta['doc_number'] = f"{m.group(1)}年第{m.group(2)}号"
        # 2. "保监发〔2015〕93 号" 或 "银保监办发〔2019〕228 号"
        m = re.search(r'([\u4e00-\u9fff]+发\s*〔\s*(\d{4})\s*〕\s*(\d+)\s*号)', full_preamble)
        if m and 'doc_number' not in meta:
            meta['doc_number'] = m.group(1).replace(' ', '')

        # 生效日期 "自 XXXX 年 X 月 X 日起施行"
        m = re.search(r'自\s*(\d{4}\s*年\s*\d+\s*月\s*\d+\s*日)\s*起施行', full_preamble)
        if m:
            meta['effective_date'] = m.group(1).replace(' ', '')

        # 发文机关
        _AUTHORITY_NAMES = [
            '国家金融监督管理总局', '中国银行保险监督管理委员会',
            '中国保险监督管理委员会', '中国银保监会', '中国保监会', '银保监会',
        ]
        for auth in _AUTHORITY_NAMES:
            if auth in full_preamble:
                meta['issuing_authority'] = auth
                break

        # 法规名称
        # 优先从 ## 标题提取（如 "## 人身保险产品信息披露管理办法"）
        m = re.search(r'##\s*([^\n（(]+?(?:办法|规定|条例|细则|通知|意见))', full_preamble)
        if m:
            name = m.group(1).strip()
            if 4 < len(name) < 40:
                meta['law_name'] = name
        # 最后从纯文本行提取（如 "健康保险管理办法" 独占一行）
        if 'law_name' not in meta:
            for line in preamble_text:
                line = line.strip()
                if line.startswith('#'):
                    continue
                if re.match(r'^[\d（(]', line):
                    continue
                if re.match(r'^主席\s', line):
                    continue
                if any(kw in line for kw in ['法', '办法', '规定', '条例', '细则', '通知', '意见']):
                    name = re.split(r'[（(]', line)[0].strip()
                    if 4 < len(name) < 40 and '保监会' not in name and '委员会' not in name:
                        meta['law_name'] = name
                        break

        return meta

    @staticmethod
    def _split_by_structure(lines: List[str]) -> List[dict]:
        """按章节和条款分割文档，每个条款为一个 segment"""
        segments: List[dict] = []
        current_lines: List[str] = []
        current_article = ''
        chapter = ''
        md_law_name = ''
        seen_first_article = False

        for line in lines:
            stripped = line.strip()

            # Markdown 标题
            heading_match = _HEADING_PATTERN.match(stripped)
            if heading_match:
                if current_article and current_lines:
                    text = '\n'.join(current_lines).strip()
                    if text:
                        segments.append({
                            'text': text,
                            'article': current_article,
                            'chapter': chapter,
                        })
                    current_lines = []
                    current_article = ''

                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()

                if level == 1 and re.match(r'^第[一二三四五六七八九十百千\d]+部分', title):
                    continue
                if level == 2 and not md_law_name:
                    if any(kw in title for kw in ['法', '办法', '规定', '条例', '细则']):
                        md_law_name = title
                    continue
                if level == 3:
                    continue
                continue

            # 章节标题
            chapter_match = _CHAPTER_PATTERN.match(stripped)
            if chapter_match:
                if current_article and current_lines:
                    text = '\n'.join(current_lines).strip()
                    if text:
                        segments.append({
                            'text': text,
                            'article': current_article,
                            'chapter': chapter,
                        })
                    current_lines = []
                    current_article = ''
                chapter = stripped
                continue

            # 条款标记
            article_match = _ARTICLE_PATTERN.match(stripped)
            if not article_match:
                article_match = _PLAIN_ARTICLE_PATTERN.match(stripped)

            if article_match:
                # 遇到第一条时，丢弃之前积累的前置内容（发文号、颁布信息等）
                if not seen_first_article:
                    current_lines = []
                    seen_first_article = True
                else:
                    # 刷新前一条款
                    if current_article and current_lines:
                        text = '\n'.join(current_lines).strip()
                        if text:
                            segments.append({
                                'text': text,
                                'article': current_article,
                                'chapter': chapter,
                            })
                    current_lines = []

                article_num = article_match.group(1)
                article_desc = article_match.group(2).strip()
                current_article = f"第{article_num}条"
                if article_desc:
                    current_article += f" {article_desc}"

            # 只有遇到第一条之后才开始收集内容
            if seen_first_article:
                current_lines.append(line)

        # 刷新最后一条
        if current_article and current_lines:
            text = '\n'.join(current_lines).strip()
            if text:
                segments.append({
                    'text': text,
                    'article': current_article,
                    'chapter': chapter,
                })

        return segments

    @staticmethod
    def _build_nodes(
        segments: List[dict], law_name: str, source_file: str, doc_meta: dict = None
    ) -> List[TextNode]:
        """构建 TextNode，只保留有条款号的 segment，过长条款按句子拆分"""
        nodes: List[TextNode] = []
        category = _extract_product_category(source_file)
        doc_meta = doc_meta or {}

        for seg in segments:
            if not seg['article']:
                continue

            hierarchy_parts = []
            if law_name:
                hierarchy_parts.append(law_name)
            if seg['chapter']:
                hierarchy_parts.append(seg['chapter'])
            hierarchy_path = ' > '.join(hierarchy_parts)

            article_brief = re.match(r'^(第[一二三四五六七八九十百千\d]+条)', seg['article'])
            article_number = article_brief.group(1) if article_brief else seg['article']

            meta = {
                'law_name': law_name,
                'article_number': article_number,
                'category': category,
                'hierarchy_path': hierarchy_path,
                'source_file': source_file,
            }
            # 附加前置元数据
            for key in ('doc_number', 'issuing_authority', 'effective_date'):
                if doc_meta.get(key):
                    meta[key] = doc_meta[key]

            text = seg['text']
            if len(text) <= _MAX_CHUNK_CHARS:
                nodes.append(TextNode(text=text, metadata=meta))
            else:
                sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]
                chunk_text = ''
                for sentence in sentences:
                    if chunk_text and len(chunk_text) + len(sentence) > _MAX_CHUNK_CHARS:
                        nodes.append(TextNode(text=chunk_text.strip(), metadata=meta))
                        chunk_text = sentence
                    else:
                        chunk_text += sentence
                if chunk_text.strip():
                    nodes.append(TextNode(text=chunk_text.strip(), metadata=meta))

        return nodes

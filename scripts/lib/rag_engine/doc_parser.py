#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
法规文档解析模块

支持两种分块策略:
1. semantic: 语义感知分块（推荐，保留文档结构和语义完整性）
2. fixed: 固定长度分块（简单但会破坏语义）
"""
import re
import logging
from pathlib import Path
from typing import List

from llama_index.core import Document
from llama_index.core.node_parser import NodeParser
from llama_index.core.readers import SimpleDirectoryReader
from llama_index.core.schema import TextNode

from .config import RAGConfig, ChunkingConfig

logger = logging.getLogger(__name__)

_CATEGORY_PATTERN = re.compile(
    r'^\d+_(.+?)(?:产品开发|管理办法|规定|规则|相关)?$'
)

_TOC_PATTERN = re.compile(
    r'^#{1,4}\s*(目录|目\s*录|TABLE\s+OF\s+CONTENTS)',
    re.IGNORECASE,
)
_EMPTY_OR_SEPARATOR = re.compile(r'^[\s\-=_*]{3,}$')
_HEADING_PATTERN = re.compile(r'^(#{1,3})\s+(.+)$')


def _clean_documents(documents: List[Document]) -> List[Document]:
    return [
        Document(text=_clean_content(doc.text), metadata=doc.metadata)
        for doc in documents
    ]


def _nodes_to_documents(text_nodes) -> List[Document]:
    return [Document(text=node.text, metadata=node.metadata) for node in text_nodes]


def _clean_content(text: str) -> str:
    """清洗文档内容：去除目录、空行、分隔符等噪音"""
    lines = text.split('\n')
    cleaned: List[str] = []
    in_toc = False

    for line in lines:
        stripped = line.strip()

        if _TOC_PATTERN.match(stripped):
            in_toc = True
            continue

        if in_toc:
            if _HEADING_PATTERN.match(stripped):
                in_toc = False
            else:
                continue

        if _EMPTY_OR_SEPARATOR.match(stripped):
            continue

        if not stripped:
            if cleaned and cleaned[-1] != '':
                cleaned.append('')
            continue

        cleaned.append(line)

    while cleaned and not cleaned[0].strip():
        cleaned.pop(0)
    while cleaned and not cleaned[-1].strip():
        cleaned.pop()

    return '\n'.join(cleaned)


def _extract_product_category(file_name: str) -> str:
    if not file_name:
        return '未分类'

    name = file_name.replace('.md', '').strip()
    match = _CATEGORY_PATTERN.match(name)
    if match:
        return match.group(1).strip()

    return '未分类'


def extract_law_name(text: str, metadata: dict) -> str:
    """从文档文本和元数据中提取法规名称

    优先使用 metadata 中的 law_name，其次从 Markdown 标题中提取，
    最后回退到文件名。
    """
    if 'law_name' in metadata:
        return metadata['law_name']

    for line in text.split('\n'):
        match = re.match(r'^#\s+(.+)$', line.strip())
        if match:
            title = match.group(1).strip()
            if re.match(r'^第[一二三四五六七八九十百千\d]+部分', title):
                continue
            if re.match(r'^[一二三四五六七八九十]+、', title):
                continue
            title = re.split(r'\d{4}年', title)[0].strip()
            for sep in ['(', '（']:
                if sep in title:
                    title = title.split(sep)[0].strip()
            if len(title) > 5:
                return title

    file_name = metadata.get('file_name', '未知法规')
    if file_name.endswith('.md'):
        name = file_name[:-3]
        if name and name[0].isdigit():
            name = '_'.join(name.split('_')[1:])
            return name
    return file_name


class RegulationNodeParser(NodeParser):
    """法规条款节点解析器

    将完整的法规文档按条款分割成独立的节点
    """

    def __init__(self, include_extra_info: bool = True):
        super().__init__(include_extra_info=include_extra_info)

    def _parse_nodes(
        self,
        nodes: List,
        show_progress: bool = False,
        **kwargs
    ) -> List:
        """解析节点，将文件级 Document 转换为条款级 TextNode"""

        result_nodes = []

        for node in nodes:
            # 只处理 Document 类型的节点
            from llama_index.core.schema import Document
            if not isinstance(node, Document):
                result_nodes.append(node)
                continue

            # 解析条款
            law_name = self._extract_law_name(node.text, node.metadata)
            article_nodes = self._parse_article_nodes(
                node.text,
                law_name,
                node.metadata
            )
            result_nodes.extend(article_nodes)

        return result_nodes

    def _extract_law_name(self, content: str, metadata: dict) -> str:
        return extract_law_name(content, metadata)

    def _parse_article_nodes(
        self,
        content: str,
        law_name: str,
        metadata: dict
    ) -> List:
        """解析单个文档中的所有条款"""

        nodes = []
        lines = content.split('\n')
        current_article = None
        current_content = []

        # 条款标题模式
        article_patterns = [
            r'###\s*第([一二三四五六七八九十百千\d]+)条\s*(.+?)(?:\s|$)',
            r'##\s*第([一二三四五六七八九十百千\d]+)条\s*(.+?)(?:\s|$)',
            r'^第([一二三四五六七八九十百千\d]+)条\s*(.+?)(?:\s|$)',
        ]

        for line in lines:
            stripped = line.strip()

            # 检测是否为条款标题
            is_article = False
            article_title = None

            for pattern in article_patterns:
                match = re.match(pattern, stripped)
                if match:
                    is_article = True
                    article_num = match.group(1)
                    article_desc = match.group(2).strip() if len(match.groups()) > 1 else ""
                    article_title = f"第{article_num}条"
                    if article_desc:
                        article_title += f" {article_desc}"
                    break

            if is_article:
                # 保存前一条款
                if current_article and current_content:
                    node = self._create_node(
                        current_article,
                        current_content,
                        law_name,
                        metadata
                    )
                    if node:
                        nodes.append(node)

                # 开始新条款
                current_article = article_title
                current_content = [line]
            elif current_article:
                current_content.append(line)

        # 保存最后一条款
        if current_article and current_content:
            node = self._create_node(
                current_article,
                current_content,
                law_name,
                metadata
            )
            if node:
                nodes.append(node)

        return nodes

    def _create_node(
        self,
        article_title: str,
        content_lines: List[str],
        law_name: str,
        source_metadata: dict
    ):
        full_content = '\n'.join(content_lines).strip()
        full_content = re.sub(r'^#{1,3}\s*', '', full_content, flags=re.MULTILINE)
        full_content = full_content.strip()

        if len(full_content) <= 20:
            return None

        source_file = source_metadata.get('file_name', '')
        category = _extract_product_category(source_file)

        return TextNode(
            text=full_content,
            metadata={
                'law_name': law_name,
                'article_number': article_title,
                'category': category,
                'hierarchy_path': f"{law_name} > {article_title}",
                'source_file': source_file,
            }
        )


class RegulationDocParser:
    """保险法规文档解析器

    支持多种分块策略:
    - semantic: 语义感知分块（推荐）
    - fixed: 固定长度分块
    """

    def __init__(
        self,
        regulations_dir: str = "./references",
        config: RAGConfig = None
    ):
        self.regulations_dir = Path(regulations_dir)
        self.config = config or RAGConfig()

        # 根据配置选择分块策略
        self.chunking_strategy = self.config.chunking_strategy
        self.chunking_config = self.config.chunking_config

        if self.chunking_strategy == "semantic":
            logger.info("使用语义分块策略")
            from .semantic_chunker import SemanticChunker
            self.chunker = SemanticChunker(self.chunking_config)
        else:
            logger.info("使用传统条款分块策略")
            self.node_parser = RegulationNodeParser()

    def parse_all(self, file_pattern: str = "*.md") -> List[Document]:
        """解析目录下所有法规文档"""
        from llama_index.core.readers import SimpleDirectoryReader

        if not self.regulations_dir.exists():
            logger.error(f"法规目录不存在: {self.regulations_dir}")
            return []

        # 获取文件列表
        md_files = sorted(self.regulations_dir.glob(file_pattern))
        if not md_files:
            logger.error(f"未找到匹配 {file_pattern} 的文件")
            return []

        # 使用 SimpleDirectoryReader 读取文件 (标准方式)
        # 需要将路径转换为字符串
        file_paths = [str(f) for f in md_files]
        reader = SimpleDirectoryReader(input_files=file_paths)
        documents = reader.load_data()

        documents = _clean_documents(documents)

        # 根据策略选择解析方式
        if self.chunking_strategy == "semantic":
            # 语义分块：直接对文档进行语义分块
            from .semantic_chunker import SemanticChunker
            if not hasattr(self, 'chunker'):
                self.chunker = SemanticChunker(self.chunking_config)

            text_nodes = self.chunker.chunk(documents)

            result_documents = _nodes_to_documents(text_nodes)
        else:
            # 传统分块：先按条款分割
            if not hasattr(self, 'node_parser'):
                self.node_parser = RegulationNodeParser()

            text_nodes = self.node_parser._parse_nodes(documents)

            result_documents = _nodes_to_documents(text_nodes)

        logger.info(f"在 {self.regulations_dir} 中找到 {len(md_files)} 个 markdown 文件")
        logger.info(f"总共解析了 {len(result_documents)} 个文档块")
        return result_documents

    def parse_single_file(self, file_name: str) -> List[Document]:
        """解析单个法规文件"""
        file_path = self.regulations_dir / file_name
        if not file_path.exists():
            logger.warning(f"文件不存在: {file_path}")
            return []

        from llama_index.core.readers import SimpleDirectoryReader

        reader = SimpleDirectoryReader(input_files=[str(file_path)])
        docs = reader.load_data()

        if not docs:
            logger.warning(f"未找到文件: {file_name}")
            return []

        docs = _clean_documents(docs)

        # 根据策略选择解析方式
        if self.chunking_strategy == "semantic":
            if not hasattr(self, 'chunker'):
                from .semantic_chunker import SemanticChunker
                self.chunker = SemanticChunker(self.chunking_config)

            text_nodes = self.chunker.chunk(docs)
        else:
            if not hasattr(self, 'node_parser'):
                self.node_parser = RegulationNodeParser()

            text_nodes = self.node_parser._parse_nodes(docs)

        return _nodes_to_documents(text_nodes)


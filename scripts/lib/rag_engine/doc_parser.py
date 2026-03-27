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
        if 'law_name' in metadata:
            return metadata['law_name']

        matches = re.findall(r'^#\s+(.+)$', content, re.MULTILINE)
        if matches:
            for match in matches:
                title = match.strip()
                if not re.match(r'^第[一二三四五六七八九十百千\d]+部分', title):
                    if not re.match(r'^[一二三四五六七八九十]+、', title):
                        title = re.split(r'\d{4}年', title)[0].strip()
                        if '(' in title:
                            title = re.split(r'\(', title)[0].strip()
                        elif '（' in title:
                            title = re.split(r'（', title)[0].strip()

                        if title and len(title) > 5:
                            return title

        file_name = metadata.get('file_name', '未知法规')
        if file_name.endswith('.md'):
            name = file_name[:-3]
            if name[0].isdigit():
                name = '_'.join(name.split('_')[1:])
            return name
        return file_name

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
            r'###\s*第([一二三四五六七八九十百千\d]+)[条条]\s*(.+?)(?:\s|$)',
            r'##\s*第([一二三四五六七八九十百千\d]+)[条条]\s*(.+?)(?:\s|$)',
            r'^第([一二三四五六七八九十百千\d]+)[条条]\s*(.+?)(?:\s|$)',
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
        """创建条款节点"""

        # 清理内容
        full_content = '\n'.join(content_lines).strip()
        full_content = re.sub(r'^#{1,3}\s*', '', full_content, flags=re.MULTILINE)
        full_content = full_content.strip()

        if len(full_content) <= 20:
            return None

        # 提取条款编号
        article_num = article_title.split()[0] if article_title else article_title

        from llama_index.core.schema import TextNode
        return TextNode(
            text=full_content,
            metadata={
                'law_name': law_name,
                'article_number': article_title,
                'article_num_only': article_num,
                'category': '未分类',
                'source_file': source_metadata.get('file_name', ''),
                **source_metadata  # 保留原始元数据
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

        # 根据策略选择解析方式
        if self.chunking_strategy == "semantic":
            # 语义分块：直接对文档进行语义分块
            from .semantic_chunker import SemanticChunker
            if not hasattr(self, 'chunker'):
                self.chunker = SemanticChunker(self.chunking_config)

            text_nodes = self.chunker.chunk(documents)

            # 将 TextNode 转换为 Document
            result_documents = []
            for node in text_nodes:
                result_documents.append(
                    Document(text=node.text, metadata=node.metadata)
                )
        else:
            # 传统分块：先按条款分割
            if not hasattr(self, 'node_parser'):
                self.node_parser = RegulationNodeParser()

            text_nodes = self.node_parser._parse_nodes(documents)

            # 将 TextNode 转换为 Document
            result_documents = []
            for node in text_nodes:
                result_documents.append(
                    Document(text=node.text, metadata=node.metadata)
                )

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

        return [
            Document(text=node.text, metadata=node.metadata)
            for node in text_nodes
        ]


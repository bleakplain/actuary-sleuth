#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
法规文档解析模块
负责从 markdown 文件解析保险法规，提取结构化的条款信息
"""
import re
from pathlib import Path
from typing import List, Dict, Any

from llama_index.core import Document


class RegulationDocumentParser:
    """保险法规文档解析器"""

    def __init__(self, regulations_dir: str = "./references"):
        """
        初始化解析器

        Args:
            regulations_dir: 法规文档目录路径
        """
        self.regulations_dir = Path(regulations_dir)

    def parse_file(self, file_path: Path) -> List[Document]:
        """
        解析单个法规 markdown 文件

        Args:
            file_path: 法规文件路径

        Returns:
            List[Document]: 法规条款文档列表
        """
        regulations = []
        current_law = None
        current_category = None

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 提取法律/法规名称
            law_name_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
            if law_name_match:
                current_law = law_name_match.group(1).strip()
            else:
                current_law = file_path.stem

            # 按行解析条款
            lines = content.split('\n')
            current_article = None
            current_content = []

            for line in lines:
                stripped = line.strip()

                # 检测条款标题（支持多种格式）
                article_patterns = [
                    r'###\s*第([一二三四五六七八九十百千\d]+)[条条]\s*(.+?)(?:\s|$)',
                    r'##\s*第([一二三四五六七八九十百千\d]+)[条条]\s*(.+?)(?:\s|$)',
                    r'^第([一二三四五六七八九十百千\d]+)[条条]\s*(.+?)(?:\s|$)',
                ]

                is_article = False

                for pattern in article_patterns:
                    match = re.match(pattern, stripped)
                    if match:
                        is_article = True
                        article_num = match.group(1)
                        article_desc = match.group(2).strip() if len(match.groups()) > 1 else ""
                        current_article = f"第{article_num}条"
                        if article_desc:
                            current_article += f" {article_desc}"
                        break

                if is_article:
                    # 保存前一条款
                    if current_article and current_content:
                        full_content = '\n'.join(current_content).strip()
                        if len(full_content) > 20:
                            # 清理 markdown 标记
                            full_content = re.sub(r'^#{1,3}\s*', '', full_content, flags=re.MULTILINE)
                            full_content = full_content.strip()

                            # 创建 LlamaIndex Document
                            doc = Document(
                                text=full_content,
                                metadata={
                                    'law_name': current_law,
                                    'article_number': current_article,
                                    'category': current_category or '未分类',
                                    'source_file': file_path.name
                                }
                            )
                            regulations.append(doc)

                    current_content = [line]
                elif current_article:
                    current_content.append(line)

            # 保存最后一条款
            if current_article and current_content:
                full_content = '\n'.join(current_content).strip()
                full_content = re.sub(r'^#{1,3}\s*', '', full_content, flags=re.MULTILINE)
                full_content = full_content.strip()
                if len(full_content) > 20:
                    doc = Document(
                        text=full_content,
                        metadata={
                            'law_name': current_law,
                            'article_number': current_article,
                            'category': current_category or '未分类',
                            'source_file': file_path.name
                        }
                    )
                    regulations.append(doc)

            print(f"从 {file_path.name} 解析了 {len(regulations)} 条法规")
            return regulations

        except Exception as e:
            print(f"解析文件 {file_path} 时出错: {e}")
            import traceback
            traceback.print_exc()
            return []

    def parse_all(self, file_pattern: str = "*.md") -> List[Document]:
        """
        解析目录下所有法规文档

        Args:
            file_pattern: 文件匹配模式

        Returns:
            List[Document]: 所有法规条款文档列表
        """
        all_documents = []

        if not self.regulations_dir.exists():
            print(f"法规目录不存在: {self.regulations_dir}")
            return []

        # 查找所有 markdown 文件
        md_files = sorted(self.regulations_dir.glob(file_pattern))

        print(f"在 {self.regulations_dir} 中找到 {len(md_files)} 个 markdown 文件")

        for md_file in md_files:
            # 跳过 README 文件
            if md_file.name.upper() == 'README.MD':
                continue

            documents = self.parse_file(md_file)
            all_documents.extend(documents)

        print(f"总共解析了 {len(all_documents)} 条法规条款")
        return all_documents

    def parse_single_file(self, file_name: str) -> List[Document]:
        """
        解析单个法规文件

        Args:
            file_name: 文件名

        Returns:
            List[Document]: 法规条款文档列表
        """
        file_path = self.regulations_dir / file_name
        if not file_path.exists():
            print(f"文件不存在: {file_path}")
            return []

        return self.parse_file(file_path)

    def documents_to_sqlite_format(self, documents: List[Document]) -> List[Dict[str, Any]]:
        """
        将 LlamaIndex Document 转换为 SQLite 格式

        Args:
            documents: LlamaIndex Document 列表

        Returns:
            List[Dict]: SQLite 格式的法规列表
        """
        sqlite_records = []

        for idx, doc in enumerate(documents):
            record = {
                'id': f"REG_{idx:06d}",
                'law_name': doc.metadata.get('law_name', ''),
                'article_number': doc.metadata.get('article_number', ''),
                'content': doc.text,
                'category': doc.metadata.get('category', ''),
                'tags': '',
                'effective_date': ''
            }
            sqlite_records.append(record)

        return sqlite_records

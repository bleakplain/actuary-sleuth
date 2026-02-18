#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导入法规数据到数据库
从 markdown 文件解析法规条款并导入到 SQLite 和 LanceDB
"""
import sqlite3
import re
import json
from pathlib import Path
import sys

from infrastructure.database import get_connection, add_regulation


class RegulationImporter:
    """法规导入器"""

    def __init__(self, refs_dir: Path, use_vectors: bool = False):
        """
        初始化导入器

        Args:
            refs_dir: 法规文档目录
            use_vectors: 是否使用向量嵌入（需要 Ollama）
        """
        self.refs_dir = Path(refs_dir)
        self.use_vectors = use_vectors
        self.client = None

        if self.use_vectors:
            try:
                from infrastructure.ollama import get_client
                self.client = get_client()
                if not self.client.health_check():
                    print("Warning: Ollama service not available, disabling vector imports")
                    self.use_vectors = False
            except Exception as e:
                print(f"Warning: Could not initialize Ollama client: {e}")
                self.use_vectors = False

    def parse_markdown_file(self, file_path: Path) -> list:
        """
        解析 markdown 法规文件

        Args:
            file_path: markdown 文件路径

        Returns:
            list: 法规条款列表
        """
        regulations = []
        current_law = None
        current_category = None

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 提取法律名称（从文件名或标题）
            law_name_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
            if law_name_match:
                current_law = law_name_match.group(1).strip()
            else:
                current_law = file_path.stem

            # 使用更灵活的解析方式：按标题分割
            lines = content.split('\n')
            current_article = None
            current_content = []

            for i, line in enumerate(lines):
                stripped = line.strip()

                # 检测条款标题（多种格式）
                # 格式1: ### 第十六条
                # 格式2: ## 第十六条
                # 格式3: 第十六条 （行首）
                article_patterns = [
                    r'###\s*第([一二三四五六七八九十百千\d]+)[条条]\s*(.+?)(?:\s|$)',
                    r'##\s*第([一二三四五六七八九十百千\d]+)[条条]\s*(.+?)(?:\s|$)',
                    r'^第([一二三四五六七八九十百千\d]+)[条条]\s*(.+?)(?:\s|$)',
                ]

                is_article = False
                article_title = None

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
                            # 清理标题标记
                            full_content = re.sub(r'^#{1,3}\s*', '', full_content, flags=re.MULTILINE)
                            full_content = full_content.strip()
                            regulations.append({
                                'law_name': current_law,
                                'article_number': current_article,
                                'content': full_content,
                                'category': current_category or '未分类'
                            })

                    current_content = [line]
                elif current_article:
                    current_content.append(line)

            # 保存最后一条款
            if current_article and current_content:
                full_content = '\n'.join(current_content).strip()
                full_content = re.sub(r'^#{1,3}\s*', '', full_content, flags=re.MULTILINE)
                full_content = full_content.strip()
                if len(full_content) > 20:
                    regulations.append({
                        'law_name': current_law,
                        'article_number': current_article,
                        'content': full_content,
                        'category': current_category or '未分类'
                    })

            print(f"Parsed {len(regulations)} regulations from {file_path.name}")
            return regulations

        except Exception as e:
            print(f"Error parsing file {file_path}: {e}")
            import traceback
            traceback.print_exc()
            return []

    def import_to_sqlite(self, regulations: list) -> int:
        """
        导入法规到 SQLite

        Args:
            regulations: 法规列表

        Returns:
            int: 成功导入的数量
        """
        imported = 0
        try:
            with get_connection() as conn:
                for idx, reg in enumerate(regulations):
                    reg_id = f"REG_{idx:06d}"

                    data = {
                        'id': reg_id,
                        'law_name': reg['law_name'],
                        'article_number': reg['article_number'],
                        'content': reg['content'],
                        'category': reg['category'],
                        'tags': '',
                        'effective_date': ''
                    }

                    if add_regulation(data):
                        imported += 1
                    else:
                        print(f"Failed to import regulation {reg_id}")

            print(f"Imported {imported} regulations to SQLite")
            return imported

        except Exception as e:
            print(f"Error importing to SQLite: {e}")
            return imported

    def import_to_lancedb(self, regulations: list) -> int:
        """
        导入法规到 LanceDB（如果启用）

        Args:
            regulations: 法规列表

        Returns:
            int: 成功导入的文本块数量
        """
        if not self.use_vectors:
            print("Vector import disabled (Ollama not available)")
            return 0

        try:
            from vector_store import VectorDB

            all_chunks = []
            chunk_size = 500
            chunk_overlap = 50

            for idx, reg in enumerate(regulations):
                reg_id = f"REG_{idx:06d}"

                # 分割文本
                start = 0
                chunk_idx = 0
                text = reg['content']

                while start < len(text):
                    end = start + chunk_size
                    chunk_text = text[start:end]

                    all_chunks.append({
                        'id': f"{reg_id}_chunk_{chunk_idx}",
                        'regulation_id': reg_id,
                        'chunk_text': chunk_text,
                        'vector': [],  # 将由 generate_embeddings 填充
                        'metadata': {
                            'law_name': reg['law_name'],
                            'article_number': reg['article_number'],
                            'category': reg['category'],
                            'start_pos': start,
                            'end_pos': end,
                            'chunk_index': chunk_idx
                        }
                    })

                    start = end - chunk_overlap
                    chunk_idx += 1

            print(f"Generated {len(all_chunks)} chunks, generating embeddings...")

            # 生成向量
            for chunk in all_chunks:
                embedding = self.client.embed(chunk['chunk_text'])
                if embedding:
                    chunk['vector'] = embedding
                else:
                    chunk['vector'] = []

            valid_chunks = [c for c in all_chunks if c.get('vector')]
            print(f"Generated embeddings for {len(valid_chunks)}/{len(all_chunks)} chunks")

            if VectorDB.add_vectors(valid_chunks):
                print(f"Imported {len(valid_chunks)} chunks to LanceDB")

            return len(valid_chunks)

        except Exception as e:
            print(f"Error importing to LanceDB: {e}")
            return 0

    def import_file(self, file_path: Path) -> dict:
        """
        导入单个文件

        Args:
            file_path: 文件路径

        Returns:
            dict: 导入结果统计
        """
        print(f"\n{'='*60}")
        print(f"Importing: {file_path.name}")
        print(f"{'='*60}")

        # 解析文件
        regulations = self.parse_markdown_file(file_path)
        if not regulations:
            return {'sqlite': 0, 'lancedb': 0}

        # 导入到 SQLite
        sqlite_count = self.import_to_sqlite(regulations)

        # 导入到 LanceDB
        lancedb_count = self.import_to_lancedb(regulations)

        return {
            'sqlite': sqlite_count,
            'lancedb': lancedb_count
        }

    def import_all(self) -> dict:
        """
        导入所有 markdown 文件

        Returns:
            dict: 总体导入结果统计
        """
        if not self.refs_dir.exists():
            print(f"Error: References directory not found: {self.refs_dir}")
            return {'total_files': 0, 'total_sqlite': 0, 'total_lancedb': 0}

        # 查找所有 markdown 文件
        md_files = list(self.refs_dir.glob('*.md'))
        md_files.sort()

        print(f"Found {len(md_files)} markdown files in {self.refs_dir}")

        total_stats = {
            'total_files': len(md_files),
            'total_sqlite': 0,
            'total_lancedb': 0
        }

        for md_file in md_files:
            if md_file.name == 'README.md':
                continue

            stats = self.import_file(md_file)
            total_stats['total_sqlite'] += stats['sqlite']
            total_stats['total_lancedb'] += stats['lancedb']

        print(f"\n{'='*60}")
        print("Import Summary")
        print(f"{'='*60}")
        print(f"Total files processed: {total_stats['total_files']}")
        print(f"Total regulations imported to SQLite: {total_stats['total_sqlite']}")
        print(f"Total chunks imported to LanceDB: {total_stats['total_lancedb']}")
        print(f"{'='*60}\n")

        return total_stats


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='导入法规数据到数据库')
    parser.add_argument(
        '--refs-dir',
        type=str,
        default='./references',
        help='法规文档目录路径'
    )
    parser.add_argument(
        '--file',
        type=str,
        help='导入单个文件（指定文件名）'
    )
    parser.add_argument(
        '--no-vectors',
        action='store_true',
        help='禁用向量导入（不需要 Ollama）'
    )

    args = parser.parse_args()

    # 创建导入器
    refs_dir = Path(args.refs_dir)
    importer = RegulationImporter(refs_dir, use_vectors=not args.no_vectors)

    # 导入数据
    if args.file:
        file_path = refs_dir / args.file
        if not file_path.exists():
            print(f"Error: File not found: {file_path}")
            return

        stats = importer.import_file(file_path)
        print(f"\nImport complete: SQLite={stats['sqlite']}, LanceDB={stats['lancedb']}")
    else:
        importer.import_all()


if __name__ == '__main__':
    main()

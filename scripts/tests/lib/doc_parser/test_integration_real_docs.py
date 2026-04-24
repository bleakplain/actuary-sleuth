#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实文档集成测试

使用 /Users/plain/work/actuary-assets/products/ 目录下的真实保险产品文档进行验证。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from lib.doc_parser import parse_product_document

PRODUCTS_DIR = Path("/Users/plain/work/actuary-assets/products/")


@pytest.fixture
def real_pdf_files():
    """真实 PDF 文件列表"""
    if not PRODUCTS_DIR.exists():
        pytest.skip(f"产品目录不存在: {PRODUCTS_DIR}")
    return list(PRODUCTS_DIR.glob("*.pdf"))


@pytest.fixture
def real_docx_files():
    """真实 DOCX 文件列表"""
    if not PRODUCTS_DIR.exists():
        pytest.skip(f"产品目录不存在: {PRODUCTS_DIR}")
    return list(PRODUCTS_DIR.glob("*.docx"))


class TestRealDocuments:
    """真实文档集成测试"""

    def test_parse_real_pdfs(self, real_pdf_files):
        """测试解析真实 PDF 文件"""
        if not real_pdf_files:
            pytest.skip("无 PDF 文件")

        for pdf_path in real_pdf_files:
            doc = parse_product_document(str(pdf_path))
            assert doc.file_type == '.pdf'
            assert doc.file_name == pdf_path.name

            total_content = (
                len(doc.clauses) +
                len(doc.premium_tables) +
                len(doc.notices) +
                len(doc.exclusions)
            )
            assert total_content > 0, f"{pdf_path.name} 未提取到任何内容"

            print(f"\n{pdf_path.name}:")
            print(f"  条款: {len(doc.clauses)}")
            print(f"  费率表: {len(doc.premium_tables)}")
            print(f"  告知事项: {len(doc.notices)}")
            print(f"  责任免除: {len(doc.exclusions)}")
            print(f"  Warnings: {len(doc.warnings)}")

    def test_parse_real_docx_files(self, real_docx_files):
        """测试解析真实 DOCX 文件"""
        if not real_docx_files:
            pytest.skip("无 DOCX 文件")

        for docx_path in real_docx_files:
            doc = parse_product_document(str(docx_path))
            assert doc.file_type == '.docx'
            assert doc.file_name == docx_path.name

            total_content = len(doc.clauses) + len(doc.premium_tables)
            assert total_content > 0, f"{docx_path.name} 未提取到任何内容"

    def test_premium_table_markdown(self, real_pdf_files):
        """测试费率表 Markdown 输出"""
        if not real_pdf_files:
            pytest.skip("无 PDF 文件")

        for pdf_path in real_pdf_files:
            doc = parse_product_document(str(pdf_path))
            for table in doc.premium_tables:
                md = table.to_markdown()
                if md:
                    assert md.startswith("|"), "Markdown 表格应以 | 开头"
                    assert "---" in md, "Markdown 表格应包含分隔行"

    def test_no_header_footer_in_content(self, real_pdf_files):
        """验证页眉页脚被过滤"""
        if not real_pdf_files:
            pytest.skip("无 PDF 文件")

        header_patterns = ["内部资料", "严禁外传"]

        for pdf_path in real_pdf_files:
            doc = parse_product_document(str(pdf_path))
            all_text = "\n".join(c.text for c in doc.clauses)

            for pattern in header_patterns:
                count = all_text.count(pattern)
                if count > 3:
                    doc.warnings.append(f"可能的页眉残留: '{pattern}' 出现 {count} 次")

            matches = re.findall(r'第\s*\d+\s*页', all_text)
            if len(matches) > 3:
                doc.warnings.append(f"可能的页脚残留: '第 X 页' 出现 {len(matches)} 次")

    def test_chunk_metadata(self, real_pdf_files):
        """测试 Chunk 元数据生成"""
        if not real_pdf_files:
            pytest.skip("无 PDF 文件")

        for pdf_path in real_pdf_files[:1]:
            doc = parse_product_document(str(pdf_path))

            if doc.clauses:
                metadata = doc.get_chunk_metadata(
                    section_path="条款",
                    chunk_index=0,
                    is_key_clause=True,
                )
                assert metadata.doc_id == pdf_path.name.replace('.', '_')
                assert metadata.doc_name == pdf_path.name
                assert metadata.doc_type == "insurance_contract"
                assert metadata.section_path == "条款"
                assert metadata.is_key_clause is True

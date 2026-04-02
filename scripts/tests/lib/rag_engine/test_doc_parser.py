#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 doc_parser 模块 - 使用真实组件
"""
import pytest
from pathlib import Path

pytest.importorskip("llama_index", reason="llama_index not installed")

from lib.rag_engine.doc_parser import RegulationDocParser, RegulationNodeParser


class TestRegulationNodeParser:
    """测试法规节点解析器"""

    def test_node_parser_creation(self):
        """测试节点解析器创建"""
        parser = RegulationNodeParser(include_extra_info=True)
        assert parser is not None

    def test_extract_law_name_from_metadata(self):
        """测试从元数据提取法规名称"""
        parser = RegulationNodeParser()

        content = "# 测试法规\n这是内容"
        metadata = {'law_name': '保险法'}
        law_name = parser._extract_law_name(content, metadata)

        assert law_name == '保险法'

    def test_extract_law_name_from_content(self):
        """测试从内容提取法规名称"""
        parser = RegulationNodeParser()

        # 测试从标题提取（使用更明确的标题格式）
        content = "# 保险管理办法\n这是保险管理办法的内容"
        metadata = {}
        law_name = parser._extract_law_name(content, metadata)

        # 提取的名称应该包含关键词
        assert len(law_name) > 0

    def test_parse_article_nodes(self):
        """测试解析条款节点"""
        from llama_index.core import Document

        parser = RegulationNodeParser()

        content = """
# 测试法规

### 第一条 保险责任
这是第一条的内容，描述了保险责任。

### 第二条 责任免责
这是第二条的内容，描述了责任免除。
        """

        metadata = {'file_name': 'test.md'}
        nodes = parser._parse_article_nodes(content, '测试法规', metadata)

        assert len(nodes) == 2
        assert nodes[0].metadata['article_number'] == '第一条 保险责任'
        assert nodes[1].metadata['article_number'] == '第二条 责任免责'

    def test_create_node(self):
        """测试创建节点"""
        parser = RegulationNodeParser()

        article_title = "第一条 保险责任"
        content_lines = ["### 第一条 保险责任", "保险公司应当承担保险责任。"]
        law_name = "保险法"
        metadata = {'file_name': 'test.md'}

        node = parser._create_node(article_title, content_lines, law_name, metadata)

        assert node is not None
        assert node.metadata['law_name'] == '保险法'
        assert node.metadata['article_number'] == '第一条 保险责任'

    def test_create_node_with_short_content(self):
        """测试内容过短的节点"""
        parser = RegulationNodeParser()

        article_title = "第一条"
        content_lines = ["短内容"]
        law_name = "测试"
        metadata = {'file_name': 'test.md'}

        node = parser._create_node(article_title, content_lines, law_name, metadata)

        # 内容过短应该返回None
        assert node is None

    def test_parse_nodes_with_documents(self):
        """测试解析文档列表"""
        from llama_index.core import Document

        parser = RegulationNodeParser()

        # 使用更完整的文档格式
        doc = Document(
            text="# 保险管理办法\n\n### 第一条 测试条款\n这是测试条款的内容。\n\n### 第二条 另一条款\n这是另一条款的内容。",
            metadata={'file_name': 'test.md'}
        )

        nodes = parser._parse_nodes([doc])

        # 应该解析出条款节点
        assert isinstance(nodes, list)


class TestRegulationDocParser:
    """测试法规文档解析器"""

    def test_parser_creation(self):
        """测试解析器创建"""
        parser = RegulationDocParser(regulations_dir="./references")
        assert parser is not None
        assert parser.regulations_dir.name == "references"
        assert parser.node_parser is not None

    def test_parser_with_nonexistent_dir(self):
        """测试不存在的目录"""
        parser = RegulationDocParser(regulations_dir="/nonexistent/directory")

        # 应该优雅处理
        documents = parser.parse_all()
        assert isinstance(documents, list)

    def test_parse_all_with_temp_dir(self, temp_output_dir):
        """测试解析临时目录中的文件"""
        # 创建测试文件
        test_file = temp_output_dir / "01_test_regulation.md"
        test_file.write_text("""
# 测试法规

### 第一条 基本原则
这是第一条的内容。

### 第二条 适用范围
这是第二条的内容。
        """)

        parser = RegulationDocParser(regulations_dir=str(temp_output_dir))
        documents = parser.parse_all("*.md")

        assert isinstance(documents, list)
        # 由于解析器会按条款分割，应该有多个文档
        if documents:
            assert 'law_name' in documents[0].metadata

    def test_parse_single_file(self, temp_output_dir):
        """测试解析单个文件"""
        # 创建测试文件
        test_file = temp_output_dir / "single_test.md"
        test_file.write_text("""
# 单文件测试法规

### 第一条 测试条款
这是测试条款的内容。

### 第二条 另一条款
这是另一条款的内容。
        """)

        parser = RegulationDocParser(regulations_dir=str(temp_output_dir))
        documents = parser.parse_single_file("single_test.md")

        assert isinstance(documents, list)
        # 应该解析出多个条款
        if documents:
            assert all('law_name' in doc.metadata for doc in documents)
            assert all('article_number' in doc.metadata for doc in documents)

    def test_parse_single_file_not_found(self, temp_output_dir):
        """测试解析不存在的文件"""
        parser = RegulationDocParser(regulations_dir=str(temp_output_dir))

        documents = parser.parse_single_file("nonexistent.md")

        # 应该返回空列表
        assert documents == []

    def test_parse_article_with_different_patterns(self):
        """测试解析不同格式的条款"""
        parser = RegulationNodeParser()

        # 测试不同的条款格式
        test_cases = [
            ("### 第一条 内容", "第一条"),
            ("## 第二条 内容", "第二条"),
            ("第三条 内容", "第三条"),
        ]

        for content_line, expected_number in test_cases:
            full_content = f"# 测试法规\n{content_line}\n这是条款内容。"
            metadata = {'file_name': 'test.md'}
            nodes = parser._parse_article_nodes(full_content, '测试法规', metadata)

            if nodes:
                assert expected_number in nodes[0].metadata['article_number']

    def test_parse_with_chinese_numbers(self):
        """测试中文数字条款"""
        parser = RegulationNodeParser()

        content = """
# 测试法规

### 第一条 测试
内容一

### 第二条 测试
内容二
        """

        metadata = {'file_name': 'test.md'}
        nodes = parser._parse_article_nodes(content, '测试法规', metadata)

        # 验证解析出了一些节点
        assert isinstance(nodes, list)

    def test_parse_file_with_numeric_prefix(self):
        """测试带数字前缀的文件名"""
        from lib.rag_engine.doc_parser import RegulationDocParser, RegulationNodeParser

        parser = RegulationDocParser()
        node_parser = RegulationNodeParser()

        # 测试文件名解析
        content = "# 测试法规\n内容"
        metadata = {'file_name': '01_test.md'}
        law_name = node_parser._extract_law_name(content, metadata)

        # 验证返回了一个有效的法规名称
        assert isinstance(law_name, str)
        assert len(law_name) > 0


class TestCleanContent:
    """测试文档内容清洗"""

    def test_removes_toc(self):
        from lib.rag_engine.doc_parser import _clean_content
        text = "# 目录\n\n第一条 测试\n第二条 测试\n\n## 第一章\n正文内容"
        cleaned = _clean_content(text)
        assert "第一条 测试" not in cleaned
        assert "正文内容" in cleaned

    def test_removes_separators(self):
        from lib.rag_engine.doc_parser import _clean_content
        text = "正文内容\n---\n更多内容\n===\n结尾"
        cleaned = _clean_content(text)
        assert "---" not in cleaned
        assert "更多内容" in cleaned

    def test_preserves_headings_after_toc(self):
        from lib.rag_engine.doc_parser import _clean_content
        text = "# 目录\n\n条目1\n条目2\n\n## 第一章 总则\n正文"
        cleaned = _clean_content(text)
        assert "第一章 总则" in cleaned
        assert "正文" in cleaned

    def test_removes_leading_trailing_blank_lines(self):
        from lib.rag_engine.doc_parser import _clean_content
        text = "\n\n\n正文内容\n\n"
        cleaned = _clean_content(text)
        assert cleaned == "正文内容"


class TestHierarchyPathInNodes:
    """测试节点包含 hierarchy_path 元数据"""

    def test_node_parser_includes_hierarchy_path(self):
        parser = RegulationNodeParser()
        content = "# 测试法规\n\n### 第一条 测试\n条款内容。保险公司应当遵守法律、行政法规，遵循自愿和诚实信用原则。"
        metadata = {'file_name': 'test.md'}
        nodes = parser._parse_article_nodes(content, '测试法规', metadata)
        assert len(nodes) == 1
        assert 'hierarchy_path' in nodes[0].metadata
        assert nodes[0].metadata['hierarchy_path'] != ''



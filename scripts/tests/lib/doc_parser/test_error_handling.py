#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""错误处理测试"""
import pytest
from lib.doc_parser import parse_knowledge_base, DocumentParseError


class TestErrorHandling:

    def test_file_not_found(self):
        with pytest.raises(DocumentParseError) as exc:
            parse_knowledge_base("/nonexistent/path/file.md")
        assert "文件不存在" in str(exc.value)

    def test_unsupported_format(self, tmp_path):
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("content")

        with pytest.raises(DocumentParseError) as exc:
            parse_knowledge_base(str(txt_file))
        assert "不支持" in str(exc.value)

    def test_doc_format_error(self, tmp_path):
        """测试 .doc 格式不支持"""
        pytest.importorskip("docx")
        from lib.doc_parser import parse_product_document

        doc_file = tmp_path / "test.doc"
        doc_file.write_bytes(b"fake doc content")

        with pytest.raises(DocumentParseError) as exc:
            parse_product_document(str(doc_file))
        assert "不支持" in str(exc.value)

    def test_corrupted_docx(self, tmp_path):
        """测试损坏的 docx 文件"""
        pytest.importorskip("docx")
        from lib.doc_parser import parse_product_document

        docx_file = tmp_path / "corrupt.docx"
        docx_file.write_bytes(b"not a valid docx")

        with pytest.raises(DocumentParseError) as exc:
            parse_product_document(str(docx_file))
        assert "解析失败" in str(exc.value)

    def test_empty_file(self, tmp_path):
        md_file = tmp_path / "empty.md"
        md_file.write_text("")

        nodes = parse_knowledge_base(str(md_file))
        assert nodes == []

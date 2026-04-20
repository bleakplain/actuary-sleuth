#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Word 解析器测试"""
import pytest

pytest.importorskip("docx")

from lib.doc_parser import parse_product_document
from lib.doc_parser.pd.docx_parser import DocxParser


class TestDocxParser:

    def test_supported_extensions(self):
        assert '.docx' in DocxParser.supported_extensions()

    def test_extract_clauses(self, tmp_path, sample_docx_with_clauses):
        docx_file = tmp_path / "test.docx"
        sample_docx_with_clauses(docx_file, [
            ("1", "保险责任", "我们承担以下保险责任..."),
            ("2", "责任免除", "因下列情形导致..."),
        ])

        doc = parse_product_document(str(docx_file))
        assert len(doc.clauses) == 2
        assert doc.clauses[0].number == "1"
        assert doc.clauses[0].title == "保险责任"

    def test_extract_premium_tables(self, tmp_path, sample_docx_with_premium):
        docx_file = tmp_path / "test.docx"
        sample_docx_with_premium(docx_file)

        doc = parse_product_document(str(docx_file))
        assert len(doc.premium_tables) >= 1

    def test_non_clause_table_filtered(self, tmp_path, sample_docx_with_company_info):
        docx_file = tmp_path / "test.docx"
        sample_docx_with_company_info(docx_file)

        doc = parse_product_document(str(docx_file))
        assert all(c.number not in ['', '公司'] for c in doc.clauses)

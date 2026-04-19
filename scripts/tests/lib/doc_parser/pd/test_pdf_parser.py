#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 解析器测试"""
import pytest
from lib.doc_parser import parse_product_document
from lib.doc_parser.pd.pdf_parser import PdfParser


class TestPdfParser:

    def test_supported_extensions(self):
        assert '.pdf' in PdfParser.supported_extensions()

    def test_extract_clauses_from_pdf(self, tmp_path, sample_pdf_with_clauses):
        pdf_file = tmp_path / "test.pdf"
        sample_pdf_with_clauses(pdf_file)

        doc = parse_product_document(str(pdf_file))
        assert len(doc.clauses) >= 1

    def test_pdf_output_matches_docx(self, tmp_path, sample_docx_with_clauses, sample_pdf_with_clauses):
        docx_file = tmp_path / "test.docx"
        pdf_file = tmp_path / "test.pdf"

        sample_docx_with_clauses(docx_file, [("1", "保险责任", "内容...")])
        sample_pdf_with_clauses(pdf_file)

        docx_result = parse_product_document(str(docx_file))
        pdf_result = parse_product_document(str(pdf_file))

        assert len(docx_result.clauses) == len(pdf_result.clauses)

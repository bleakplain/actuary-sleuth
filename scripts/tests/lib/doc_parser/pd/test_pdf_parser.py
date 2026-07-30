#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 解析器测试"""
import pytest

pytest.importorskip("pdfplumber")

from lib.doc_parser import parse_product_document
from lib.doc_parser.models import DataTable, TableType
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
        pytest.importorskip("docx")

        docx_file = tmp_path / "test.docx"
        pdf_file = tmp_path / "test.pdf"

        sample_docx_with_clauses(docx_file, [("1", "保险责任", "内容...")])
        sample_pdf_with_clauses(pdf_file)

        docx_result = parse_product_document(str(docx_file))
        pdf_result = parse_product_document(str(pdf_file))

        assert len(docx_result.clauses) == len(pdf_result.clauses)

    def test_continuation_table_inherits_missing_header_without_losing_rows(self):
        inherited = PdfParser._inherit_continuation_header(
            ["药品名称", "适应症"],
            [["药品乙", "疾病乙"], ["药品丙", "疾病丙"]],
        )

        assert inherited == [
            ["药品名称", "适应症"],
            ["药品乙", "疾病乙"],
            ["药品丙", "疾病丙"],
        ]

    def test_second_page_table_recognizes_first_page_as_previous_page(self):
        previous = DataTable(
            data=[["药品名称", "适应症"], ["药品甲", "疾病甲"]],
            table_type=TableType.DRUG_LIST,
            page_number=1,
        )

        assert PdfParser._is_continuation_table(
            previous,
            current_page_index=1,
            table_top=20,
            page_height=1000,
            column_count=2,
        )
        assert not PdfParser._is_continuation_table(
            previous,
            current_page_index=2,
            table_top=20,
            page_height=1000,
            column_count=2,
        )

    def test_continuation_table_does_not_duplicate_repeated_header(self):
        inherited = PdfParser._inherit_continuation_header(
            ["药品名称", "适应症"],
            [["药品名称", "适应症"], ["药品乙", "疾病乙"]],
        )

        assert inherited == [
            ["药品名称", "适应症"],
            ["药品乙", "疾病乙"],
        ]

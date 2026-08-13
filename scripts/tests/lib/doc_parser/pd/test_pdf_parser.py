#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 解析器测试"""
import pytest

pytest.importorskip("pdfplumber")
Image = pytest.importorskip("PIL.Image")
ImageDraw = pytest.importorskip("PIL.ImageDraw")

from lib.doc_parser import parse_product_document
from lib.doc_parser.models import DataTable, TableType
from lib.doc_parser.pd import pdf_parser as pdf_parser_module
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

    def test_continuation_table_does_not_prepend_different_width_header(self):
        inherited = PdfParser._inherit_continuation_header(
            ["药品名称", "适应症"],
            [["药品名称"], ["药品乙"]],
        )

        assert inherited == [["药品名称"], ["药品乙"]]

    def test_image_only_pdf_page_disables_full_document_attestation(
        self,
        tmp_path,
        monkeypatch,
    ):
        class FakePage:
            def __init__(self, lines, images):
                self.lines = lines
                self.images = images
                self.objects = {"image": images}
                self.height = 1000
                self.width = 800

            def extract_text(self):
                return "\n".join(text for _, text in self.lines)

            def find_tables(self):
                return []

        class FakePdf:
            def __init__(self, pages):
                self.pages = pages

            def close(self):
                return None

        pages = [
            FakePage(
                [(100, "测试医疗保险"), (150, "1 保险责任"), (180, "提供保障。")],
                [],
            ),
            FakePage([], [{"name": "scanned-page"}]),
        ]
        parser = PdfParser()
        monkeypatch.setattr(
            parser.toc_detector,
            "detect",
            lambda page, page_index: (False, ""),
        )
        monkeypatch.setattr(
            parser.header_footer_filter,
            "_build_lines_from_chars",
            lambda page: page.lines,
        )
        monkeypatch.setattr(
            pdf_parser_module.pdfplumber,
            "open",
            lambda file_path: FakePdf(pages),
        )
        source = tmp_path / "image-page.pdf"
        source.write_bytes(b"fixture")

        document = parser.parse(str(source))

        assert not document.coverage_attested
        assert document.coverage_attestation.unreadable_pages == (2,)
        assert document.coverage_attestation.unparsed_image_count == 1
        assert document.coverage_attestation.coverage_attested_facts == ()
        assert any("正文图像" in warning for warning in document.warnings)

    def test_any_unverified_image_with_some_text_disables_coverage_attestation(
        self,
        tmp_path,
        monkeypatch,
    ):
        class FakePage:
            lines = [(80, "测试医疗保险"), (120, "1 正文见扫描图像")]
            images = [{"x0": 0, "x1": 800, "top": 40, "bottom": 980}]
            objects = {"image": images}
            height = 1000
            width = 800

            def extract_text(self):
                return "\n".join(text for _, text in self.lines)

            def find_tables(self):
                return []

        class FakePdf:
            pages = [FakePage()]

            def close(self):
                return None

        parser = PdfParser()
        monkeypatch.setattr(
            parser.toc_detector,
            "detect",
            lambda page, page_index: (False, ""),
        )
        monkeypatch.setattr(
            parser.header_footer_filter,
            "_build_lines_from_chars",
            lambda page: page.lines,
        )
        monkeypatch.setattr(
            pdf_parser_module.pdfplumber,
            "open",
            lambda file_path: FakePdf(),
        )
        source = tmp_path / "mixed-scan-page.pdf"
        source.write_bytes(b"fixture")

        document = parser.parse(str(source))

        assert not document.coverage_attested
        assert document.coverage_attestation.unreadable_pages == (1,)
        assert document.coverage_attestation.unparsed_image_count == 1
        assert any("正文图像" in warning for warning in document.warnings)

    def test_top_right_qr_image_is_ignored_and_counted(
        self,
        tmp_path,
        monkeypatch,
    ):
        qr_image = self._build_qr_finder_image()

        class FakePage:
            lines = [
                (100, "测试医疗保险"),
                (150, "1 保险责任"),
                (180, "提供保障。"),
            ]
            images = [{
                "x0": 710,
                "x1": 786,
                "top": 20,
                "bottom": 96,
                "srcsize": (76, 76),
            }]
            objects = {"image": images}
            chars = []
            height = 1000
            width = 800

            def extract_text(self):
                return "\n".join(text for _, text in self.lines)

            def find_tables(self):
                return []

            def crop(self, bbox):
                return TestPdfParser._fake_rendered_crop(qr_image)

        document = self._parse_fake_pdf(
            tmp_path,
            monkeypatch,
            [FakePage()],
            "qr.pdf",
        )

        assert document.coverage_attested
        assert document.coverage_attestation.unreadable_pages == ()
        assert document.coverage_attestation.unparsed_image_count == 0
        assert document.coverage_attestation.ignored_qr_image_count == 1
        assert document.coverage_attestation.coverage_attested_facts

    def test_top_right_square_without_qr_finders_remains_unresolved(
        self,
        tmp_path,
        monkeypatch,
    ):
        ordinary_image = Image.new("L", (84, 84), 128)

        class FakePage:
            lines = [
                (100, "测试医疗保险"),
                (150, "1 保险责任"),
                (180, "提供保障。"),
            ]
            images = [{
                "x0": 710,
                "x1": 786,
                "top": 20,
                "bottom": 96,
                "srcsize": (76, 76),
            }]
            objects = {"image": images}
            chars = []
            height = 1000
            width = 800

            def extract_text(self):
                return "\n".join(text for _, text in self.lines)

            def find_tables(self):
                return []

            def crop(self, bbox):
                return TestPdfParser._fake_rendered_crop(ordinary_image)

        document = self._parse_fake_pdf(
            tmp_path,
            monkeypatch,
            [FakePage()],
            "ordinary-square.pdf",
        )

        assert not document.coverage_attested
        assert document.coverage_attestation.unparsed_image_count == 1
        assert document.coverage_attestation.ignored_qr_image_count == 0

    def test_tiny_layout_image_does_not_disable_coverage(
        self,
        tmp_path,
        monkeypatch,
    ):
        class FakePage:
            lines = [
                (100, "测试医疗保险"),
                (150, "1 保险责任"),
                (180, "提供保障。"),
            ]
            images = [{
                "x0": 300,
                "x1": 306,
                "top": 300,
                "bottom": 307,
                "imagemask": True,
            }]
            objects = {"image": images}
            chars = []
            height = 1000
            width = 800

            def extract_text(self):
                return "\n".join(text for _, text in self.lines)

            def find_tables(self):
                return []

        document = self._parse_fake_pdf(
            tmp_path,
            monkeypatch,
            [FakePage()],
            "layout-image.pdf",
        )

        assert document.coverage_attested
        assert document.coverage_attestation.unparsed_image_count == 0

    def test_header_image_does_not_disable_coverage(
        self,
        tmp_path,
        monkeypatch,
    ):
        class FakePage:
            lines = [
                (100, "测试医疗保险"),
                (150, "1 保险责任"),
                (180, "提供保障。"),
            ]
            images = [{
                "x0": 100,
                "x1": 500,
                "top": 10,
                "bottom": 60,
            }]
            objects = {"image": images}
            chars = []
            height = 1000
            width = 800

            def extract_text(self):
                return "\n".join(text for _, text in self.lines)

            def find_tables(self):
                return []

        document = self._parse_fake_pdf(
            tmp_path,
            monkeypatch,
            [FakePage()],
            "header-image.pdf",
        )

        assert document.coverage_attested
        assert document.coverage_attestation.unparsed_image_count == 0

    def test_large_background_with_substantial_native_text_is_ignored(
        self,
        tmp_path,
        monkeypatch,
    ):
        chars = []
        for row in range(12):
            for column in range(12):
                left = 85 + column * 50
                top = 105 + row * 52
                chars.append({
                    "x0": left,
                    "x1": left + 10,
                    "top": top,
                    "bottom": top + 12,
                    "text": "条",
                })

        class FakePage:
            lines = [
                (100, "测试医疗保险"),
                (150, "1 保险责任"),
                (180, "提供保障。"),
            ]
            images = [{
                "x0": 80,
                "x1": 650,
                "top": 100,
                "bottom": 700,
                "stream": TestPdfParser._sparse_masked_stream(),
            }]
            objects = {"image": images}
            height = 1000
            width = 800

            def __init__(self):
                self.chars = chars

            def extract_text(self):
                return "\n".join(text for _, text in self.lines)

            def find_tables(self):
                return []

        document = self._parse_fake_pdf(
            tmp_path,
            monkeypatch,
            [FakePage()],
            "background-image.pdf",
        )

        assert document.coverage_attested
        assert document.coverage_attestation.unparsed_image_count == 0

    def test_sparse_large_image_with_only_partial_text_stays_unresolved(
        self,
        tmp_path,
        monkeypatch,
    ):
        chars = []
        for row in range(6):
            for column in range(20):
                left = 85 + column * 28
                top = 110 + row * 35
                chars.append({
                    "x0": left,
                    "x1": left + 10,
                    "top": top,
                    "bottom": top + 12,
                    "text": "条",
                })

        class FakePage:
            lines = [
                (100, "测试医疗保险"),
                (150, "1 保险责任"),
                (180, "提供保障。"),
            ]
            images = [{
                "x0": 80,
                "x1": 650,
                "top": 100,
                "bottom": 700,
                "stream": TestPdfParser._sparse_masked_stream(),
            }]
            objects = {"image": images}
            height = 1000
            width = 800

            def __init__(self):
                self.chars = chars

            def extract_text(self):
                return "\n".join(text for _, text in self.lines)

            def find_tables(self):
                return []

        document = self._parse_fake_pdf(
            tmp_path,
            monkeypatch,
            [FakePage()],
            "partial-overlay.pdf",
        )

        assert not document.coverage_attested
        assert document.coverage_attestation.unparsed_image_count == 1

    @staticmethod
    def _build_qr_finder_image():
        image = Image.new("L", (84, 84), 255)
        draw = ImageDraw.Draw(image)
        for left, top in ((6, 6), (57, 6), (6, 57)):
            draw.rectangle((left, top, left + 20, top + 20), fill=0)
            draw.rectangle(
                (left + 3, top + 3, left + 17, top + 17),
                fill=255,
            )
            draw.rectangle(
                (left + 6, top + 6, left + 14, top + 14),
                fill=0,
            )
        return image

    @staticmethod
    def _fake_rendered_crop(image):
        class FakePageImage:
            def __init__(self, rendered_image):
                self.original = rendered_image

        class FakeCrop:
            def to_image(self, **kwargs):
                return FakePageImage(image)

        return FakeCrop()

    @staticmethod
    def _sparse_masked_stream():
        class FakeStream:
            attrs = {"Mask": object()}

            def get_data(self):
                return b"\x00" * 10000 + b"\x01" * 20

        return FakeStream()

    @staticmethod
    def _parse_fake_pdf(
        tmp_path,
        monkeypatch,
        pages,
        file_name,
    ):
        class FakePdf:
            def __init__(self, pdf_pages):
                self.pages = pdf_pages

            def close(self):
                return None

        parser = PdfParser()
        monkeypatch.setattr(
            parser.toc_detector,
            "detect",
            lambda page, page_index: (False, ""),
        )
        monkeypatch.setattr(
            parser.header_footer_filter,
            "_build_lines_from_chars",
            lambda page: page.lines,
        )
        monkeypatch.setattr(
            pdf_parser_module.pdfplumber,
            "open",
            lambda file_path: FakePdf(pages),
        )
        source = tmp_path / file_name
        source.write_bytes(b"fixture")
        return parser.parse(str(source))

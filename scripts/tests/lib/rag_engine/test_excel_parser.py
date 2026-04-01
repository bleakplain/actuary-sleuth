#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Excel sheet structure parser tests."""
import pytest
from pathlib import Path

EXCEL_PATH = Path(__file__).parent.parent.parent.parent.parent / "references" / "1.产品开发检查清单2025年.xlsx"


class TestSheetStructureParser:
    """Tests for parsing sheet structure from Excel."""

    def test_list_content_sheets(self):
        """Should return only content sheets (skip '分工' and '相关法规')."""
        pytest.importorskip("openpyxl")
        from lib.rag_engine.excel_to_kb import list_content_sheets

        sheets = list_content_sheets(str(EXCEL_PATH))
        names = [s["name"] for s in sheets]
        assert "分工" not in names
        assert "相关法规" not in names
        assert len(sheets) == 11
        assert any("00" in n for n in names)

    def test_detect_regulation_boundaries_standard(self):
        """Standard sheets (00, 02-05) have title in row 1, headers in row 2, regulation in row 3."""
        pytest.importorskip("openpyxl")
        from lib.rag_engine.excel_to_kb import parse_sheet_structure

        wb = __import__("openpyxl").load_workbook(str(EXCEL_PATH), read_only=True, data_only=True)
        sheet = None
        for name in wb.sheetnames:
            if "00" in name:
                sheet = wb[name]
                break
        assert sheet is not None

        structure = parse_sheet_structure(sheet, "00. 对照样例")
        assert structure.header_row == 2
        assert structure.data_start_row == 4
        assert structure.regulation_name != ""
        wb.close()

    def test_detect_regulation_boundaries_with_owner(self):
        """Sheets with '产品开发责任人' row (01, 06-08) have headers in row 3, data in row 5."""
        pytest.importorskip("openpyxl")
        from lib.rag_engine.excel_to_kb import parse_sheet_structure

        wb = __import__("openpyxl").load_workbook(str(EXCEL_PATH), read_only=True, data_only=True)
        sheet = None
        for name in wb.sheetnames:
            if "01" in name and "负面" in name:
                sheet = wb[name]
                break
        assert sheet is not None

        structure = parse_sheet_structure(sheet, "01. 对照样例")
        assert structure.header_row == 3
        assert structure.data_start_row == 5
        wb.close()

    def test_detect_sub_regulations_in_sheet_10(self):
        """Sheet 10 has multiple regulation boundaries detected by non-numeric column A."""
        pytest.importorskip("openpyxl")
        from lib.rag_engine.excel_to_kb import parse_sheet_structure

        wb = __import__("openpyxl").load_workbook(str(EXCEL_PATH), read_only=True, data_only=True)
        sheet = None
        for name in wb.sheetnames:
            if "10" in name and "其他" in name:
                sheet = wb[name]
                break
        assert sheet is not None

        structure = parse_sheet_structure(sheet, "10. 对照样例")
        # Sheet 10 should have multiple sub-regulations
        assert len(structure.sub_regulations) >= 5
        wb.close()

    def test_extract_metadata_columns(self):
        """Should correctly identify metadata column indices (B-G)."""
        pytest.importorskip("openpyxl")
        from lib.rag_engine.excel_to_kb import parse_sheet_structure

        wb = __import__("openpyxl").load_workbook(str(EXCEL_PATH), read_only=True, data_only=True)
        sheet = None
        for name in wb.sheetnames:
            if "00" in name:
                sheet = wb[name]
                break
        assert sheet is not None

        structure = parse_sheet_structure(sheet, "00. 对照样例")
        headers = structure.headers
        assert "项目" in headers.values() or any("项目" in str(v) for v in headers.values())
        wb.close()


class TestClauseExtraction:
    """Tests for clause extraction and sub-regulation filtering."""

    def test_extract_clauses_returns_entries(self):
        """Should extract non-empty clause entries with sequence numbers."""
        pytest.importorskip("openpyxl")
        from lib.rag_engine.excel_to_kb import parse_sheet_structure, extract_clauses

        wb = __import__("openpyxl").load_workbook(str(EXCEL_PATH), read_only=True, data_only=True)
        sheet = None
        for name in wb.sheetnames:
            if "00" in name:
                sheet = wb[name]
                break
        assert sheet is not None

        structure = parse_sheet_structure(sheet, "00. 对照样例")
        clauses = extract_clauses(sheet, structure)
        assert len(clauses) > 0
        assert all(c.sequence > 0 for c in clauses)
        assert all(c.content for c in clauses)
        assert all(c.row > 0 for c in clauses)
        wb.close()

    def test_extract_clauses_includes_metadata(self):
        """Should extract metadata columns when present."""
        pytest.importorskip("openpyxl")
        from lib.rag_engine.excel_to_kb import parse_sheet_structure, extract_clauses

        wb = __import__("openpyxl").load_workbook(str(EXCEL_PATH), read_only=True, data_only=True)
        sheet = None
        for name in wb.sheetnames:
            if "00" in name:
                sheet = wb[name]
                break

        structure = parse_sheet_structure(sheet, "00. 对照样例")
        clauses = extract_clauses(sheet, structure)
        clauses_with_meta = [c for c in clauses if c.metadata]
        assert len(clauses_with_meta) > 0
        wb.close()

    def test_sheet_10_sub_regulation_filtering(self):
        """Sheet 10 sub-regulations should produce separate clause groups."""
        pytest.importorskip("openpyxl")
        from lib.rag_engine.excel_to_kb import (
            parse_sheet_structure, extract_clauses, _filter_clauses_for_sub_reg,
        )

        wb = __import__("openpyxl").load_workbook(str(EXCEL_PATH), read_only=True, data_only=True)
        sheet = None
        for name in wb.sheetnames:
            if "10" in name and "其他" in name:
                sheet = wb[name]
                break

        structure = parse_sheet_structure(sheet, "10. 对照样例")
        all_clauses = extract_clauses(sheet, structure)

        total_filtered = 0
        for sub_reg in structure.sub_regulations:
            filtered = _filter_clauses_for_sub_reg(all_clauses, sub_reg, structure)
            total_filtered += len(filtered)

        assert total_filtered == len(all_clauses)
        wb.close()


class TestMarkdownGeneration:
    """Tests for Markdown output formatting."""

    def test_generate_frontmatter_yaml(self):
        """Should produce valid YAML frontmatter block."""
        from lib.rag_engine.excel_to_kb import generate_frontmatter

        fm = generate_frontmatter(
            collection="00_保险法",
            regulation="保险法",
            source_sheet='00. 对照"保险法"等法规检查',
            tags=["保险法", "人身保险"],
        )
        assert fm.startswith("---\n")
        assert fm.endswith("---\n")
        assert "collection: 00_保险法" in fm
        assert "regulation: 保险法" in fm
        assert "source_sheet:" in fm

    def test_clauses_to_markdown_structure(self):
        """Generated Markdown should have frontmatter, H1 title, and H2 clauses."""
        from lib.rag_engine.excel_to_kb import clauses_to_markdown, ClauseEntry, generate_frontmatter

        fm = generate_frontmatter("01_负面清单检查", "负面清单", "01.sheet", [])
        clauses = [
            ClauseEntry(sequence=1, content="第一条内容", metadata={"险种大类": "人身保险"}),
            ClauseEntry(sequence=2, content="第二条内容", metadata={}),
        ]
        md = clauses_to_markdown(clauses, fm, "负面清单")

        assert md.startswith("---\n")
        assert "# 负面清单" in md
        assert "## 第1项" in md
        assert "## 第2项" in md
        assert "> **元数据**: 险种大类=人身保险" in md
        assert "第一条内容" in md

    def test_clauses_to_markdown_no_metadata_no_blockquote(self):
        """Clauses without metadata should not produce blockquote lines."""
        from lib.rag_engine.excel_to_kb import clauses_to_markdown, ClauseEntry, generate_frontmatter

        fm = generate_frontmatter("00_保险法", "保险法", "00.sheet", [])
        clauses = [ClauseEntry(sequence=1, content="无标签条款")]
        md = clauses_to_markdown(clauses, fm, "保险法")

        assert "> **元数据**:" not in md

    def test_format_metadata_block(self):
        """Metadata block should use pipe separator."""
        from lib.rag_engine.excel_to_kb import format_metadata_block

        result = format_metadata_block({"险种大类": "人身保险", "险种类型": "寿险"})
        assert "险种大类=人身保险 | 险种类型=寿险" in result

    def test_format_metadata_block_empty(self):
        """Empty metadata should return empty string."""
        from lib.rag_engine.excel_to_kb import format_metadata_block

        assert format_metadata_block({}) == ""

    def test_safe_filename(self):
        """Should remove unsafe characters and replace spaces."""
        from lib.rag_engine.excel_to_kb import _safe_filename

        assert _safe_filename('关于"分红险"的规定（2025年）') == "关于分红险的规定2025年"
        assert _safe_filename("  extra  spaces  ") == "extra_spaces"


class TestFullPipeline:
    """End-to-end conversion tests (skip OCR)."""

    def test_convert_excel_to_kb_generates_files(self):
        """Full pipeline should generate markdown files in correct directory structure."""
        import tempfile
        pytest.importorskip("openpyxl")
        from lib.rag_engine.excel_to_kb import convert_excel_to_kb

        with tempfile.TemporaryDirectory() as tmpdir:
            output = convert_excel_to_kb(
                excel_path=str(EXCEL_PATH),
                output_dir=tmpdir,
                skip_ocr=True,
            )

            refs_dir = output / "references"
            assert refs_dir.exists()

            subdirs = [d for d in refs_dir.iterdir() if d.is_dir()]
            assert len(subdirs) >= 10

            meta_path = output / "meta.json"
            assert meta_path.exists()
            import json
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            assert meta["version_id"] == "v4"
            assert meta["document_count"] > 0

    def test_convert_output_valid_markdown(self):
        """Generated files should be valid Markdown with frontmatter."""
        import tempfile
        pytest.importorskip("openpyxl")
        from lib.rag_engine.excel_to_kb import convert_excel_to_kb

        with tempfile.TemporaryDirectory() as tmpdir:
            convert_excel_to_kb(excel_path=str(EXCEL_PATH), output_dir=tmpdir, skip_ocr=True)

            refs_dir = Path(tmpdir) / "references"
            md_files = list(refs_dir.rglob("*.md"))
            assert len(md_files) > 0

            content = md_files[0].read_text(encoding="utf-8")
            assert content.startswith("---\n")
            assert "# " in content

    def test_convert_sheet_10_multiple_files(self):
        """Sheet 10 (其他监管规定) should generate multiple files for sub-regulations."""
        import tempfile
        pytest.importorskip("openpyxl")
        from lib.rag_engine.excel_to_kb import convert_excel_to_kb

        with tempfile.TemporaryDirectory() as tmpdir:
            convert_excel_to_kb(excel_path=str(EXCEL_PATH), output_dir=tmpdir, skip_ocr=True)

            refs_dir = Path(tmpdir) / "references"
            other_dir = refs_dir / "10_其他监管规定"
            if other_dir.exists():
                md_files = list(other_dir.glob("*.md"))
                assert len(md_files) >= 2, f"Expected >= 2 files, got {len(md_files)}"

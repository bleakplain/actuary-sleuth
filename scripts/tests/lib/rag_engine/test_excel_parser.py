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
        assert structure["header_row"] == 2
        assert structure["data_start_row"] == 4
        assert structure["regulation_name"] != ""
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
        assert structure["header_row"] == 3
        assert structure["data_start_row"] == 5
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
        assert len(structure.get("sub_regulations", [])) >= 5
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
        headers = structure["headers"]
        assert "项目" in headers.values() or any("项目" in str(v) for v in headers.values())
        wb.close()

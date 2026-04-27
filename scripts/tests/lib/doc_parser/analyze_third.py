#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析第三个 PDF 的所有表格"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pdfplumber

PRODUCTS_DIR = Path("/Users/plain/work/actuary-assets/products/")


def analyze_third_pdf():
    """分析第三个 PDF 的表格"""
    pdf_files = list(PRODUCTS_DIR.glob("*.pdf"))
    pdf_path = pdf_files[2]  # 第三个文件

    print(f"\n文件: {pdf_path.name}")
    print('='*70)

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            tables = page.find_tables()
            if tables:
                print(f"\n第 {page_idx + 1} 页，发现 {len(tables)} 个表格:")
                for table_idx, table in enumerate(tables):
                    rows = table.extract()
                    if rows and len(rows) >= 2:
                        print(f"\n  表格 {table_idx + 1} (行数: {len(rows)}):")
                        print(f"    表头: {[str(c).replace(chr(10), ' ')[:20] if c else '' for c in rows[0]]}")
                        print(f"    第 2 行: {[str(c).replace(chr(10), ' ')[:20] if c else '' for c in rows[1]]}")


if __name__ == "__main__":
    analyze_third_pdf()

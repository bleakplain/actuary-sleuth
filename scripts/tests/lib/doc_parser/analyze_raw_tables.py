#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF 表格深度分析 - 查看所有表格原始数据"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import pdfplumber

PRODUCTS_DIR = Path("/Users/plain/work/actuary-assets/products/")


def analyze_all_tables():
    """分析 PDF 中所有表格的原始数据"""
    pdf_files = list(PRODUCTS_DIR.glob("*.pdf"))

    for pdf_path in pdf_files[:1]:  # 只分析第一个文件
        print(f"\n{'='*70}")
        print(f"文件: {pdf_path.name}")
        print('='*70)

        with pdfplumber.open(str(pdf_path)) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                tables = page.find_tables()
                if tables:
                    print(f"\n📄 第 {page_idx + 1} 页，发现 {len(tables)} 个表格:")
                    for table_idx, table in enumerate(tables):
                        rows = table.extract()
                        bbox = getattr(table, 'bbox', None)
                        edges = getattr(table, 'edges', [])

                        print(f"\n  表格 {table_idx + 1}:")
                        print(f"    bbox: {bbox}")
                        print(f"    edges 数量: {len(edges) if edges else 0}")

                        if rows:
                            print(f"    行数: {len(rows)}")
                            print(f"    列数: {len(rows[0]) if rows else 0}")
                            print(f"\n    原始数据 (前 5 行):")
                            for i, row in enumerate(rows[:5]):
                                cells = [str(c).replace('\n', ' ')[:20] if c else '' for c in row]
                                print(f"      行{i}: {cells}")
                        else:
                            print("    无法提取表格数据")


if __name__ == "__main__":
    analyze_all_tables()

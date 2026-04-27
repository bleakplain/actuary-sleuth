#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""表格解析深度分析脚本

重点验证：
1. 表格识别准确率
2. Markdown 输出质量
3. 表格分类器效果
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from lib.doc_parser import parse_product_document

PRODUCTS_DIR = Path("/Users/plain/work/actuary-assets/products/")


def analyze_tables():
    """分析真实文档的表格解析结果"""
    pdf_files = list(PRODUCTS_DIR.glob("*.pdf"))

    for pdf_path in pdf_files:
        print(f"\n{'='*60}")
        print(f"文件: {pdf_path.name}")
        print('='*60)

        doc = parse_product_document(str(pdf_path))

        print(f"\n📊 解析统计:")
        print(f"  - 条款数量: {len(doc.clauses)}")
        print(f"  - 费率表数量: {len(doc.premium_tables)}")
        print(f"  - 告知事项: {len(doc.notices)}")
        print(f"  - 责任免除: {len(doc.exclusions)}")
        print(f"  - Warnings: {len(doc.warnings)}")

        if doc.warnings:
            print(f"\n⚠️ Warnings:")
            for w in doc.warnings:
                print(f"  - {w}")

        # 详细分析每个表格
        for i, table in enumerate(doc.premium_tables):
            print(f"\n📋 表格 #{i+1} (页码: {table.page_number}):")
            print(f"  - 行数: {len(table.data)}")
            print(f"  - 列数: {len(table.data[0]) if table.data else 0}")

            # 打印表头
            if table.data:
                headers = [str(c).replace('\n', ' ')[:20] for c in table.data[0]]
                print(f"  - 表头: {headers}")

            # 打印前 3 行数据
            print(f"\n  前 3 行数据:")
            for j, row in enumerate(table.data[:4]):
                cells = [str(c).replace('\n', ' ')[:15] for c in row]
                print(f"    行{j}: {cells}")

            # Markdown 输出
            md = table.to_markdown()
            print(f"\n  Markdown 输出 (前 500 字符):")
            print("  " + "\n  ".join(md[:500].split('\n')))


if __name__ == "__main__":
    analyze_tables()

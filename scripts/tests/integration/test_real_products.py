#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实保险产品文档解析测试"""
import os
import sys
from pathlib import Path
from typing import List, Dict, Any

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from lib.doc_parser import parse_product_document, DocumentParseError
from lib.doc_parser.pd.content_classifier import ContentClassifier
from lib.doc_parser.models import SectionType


PRODUCTS_DIR = Path("/mnt/d/work/actuary-assets/products")


def get_product_files() -> List[Path]:
    """获取所有产品文档文件"""
    files = []
    for ext in ['.docx', '.pdf']:
        files.extend(PRODUCTS_DIR.glob(f"*{ext}"))
    # 排除 .doc 文件（不支持）
    return [f for f in files if not f.name.endswith('.doc')]


def parse_file(file_path: Path) -> Dict[str, Any]:
    """解析单个文件，返回结果摘要"""
    result = {
        'file': file_path.name,
        'type': file_path.suffix,
        'success': False,
        'clauses': 0,
        'premium_tables': 0,
        'notices': 0,
        'health_disclosures': 0,
        'exclusions': 0,
        'rider_clauses': 0,
        'warnings': [],
        'error': None,
    }

    try:
        doc = parse_product_document(str(file_path))
        result['success'] = True
        result['clauses'] = len(doc.clauses)
        result['premium_tables'] = len(doc.premium_tables)
        result['notices'] = len(doc.notices)
        result['health_disclosures'] = len(doc.health_disclosures)
        result['exclusions'] = len(doc.exclusions)
        result['rider_clauses'] = len(doc.rider_clauses)
        result['warnings'] = doc.warnings[:5]  # 只保留前5条警告
    except DocumentParseError as e:
        result['error'] = str(e)
    except Exception as e:
        result['error'] = f"Unexpected error: {e}"

    return result


def print_result(result: Dict[str, Any], index: int, total: int):
    """打印单个结果"""
    status = "✅" if result['success'] else "❌"
    print(f"\n[{index}/{total}] {status} {result['file']}")

    if result['success']:
        print(f"    条款: {result['clauses']} 条")
        print(f"    费率表: {result['premium_tables']} 个")
        print(f"    投保须知: {result['notices']} 段")
        print(f"    健康告知: {result['health_disclosures']} 段")
        print(f"    责任免除: {result['exclusions']} 段")
        print(f"    附加险条款: {result['rider_clauses']} 条")

        if result['warnings']:
            print(f"    ⚠️ 警告: {len(result['warnings'])} 条")
            for w in result['warnings'][:2]:
                print(f"       - {w[:50]}...")
    else:
        print(f"    ❌ 错误: {result['error']}")


def test_clause_number_formats():
    """测试条款编号格式识别"""
    from lib.doc_parser.pd.section_detector import SectionDetector

    detector = SectionDetector()

    test_cases = [
        ("1", True, "数字格式"),
        ("1.1", True, "数字层级"),
        ("1.2.3", True, "三级编号"),
        ("第一条", True, "中文条款"),
        ("一、", True, "中文顿号"),
        ("（一）", True, "中文括号"),
        ("(1)", True, "英文括号"),
        ("条款", False, "非编号"),
        ("", False, "空字符串"),
    ]

    print("\n" + "=" * 60)
    print("条款编号格式识别测试")
    print("=" * 60)

    passed = 0
    for text, expected, desc in test_cases:
        result = detector.is_clause_table(text)
        status = "✅" if result == expected else "❌"
        print(f"  {status} '{text}' -> {result} ({desc})")
        if result == expected:
            passed += 1

    print(f"\n通过: {passed}/{len(test_cases)}")
    return passed == len(test_cases)


def test_content_classifier():
    """测试内容类型检测"""
    classifier = ContentClassifier(
        section_keywords={
            'notice': ['投保须知', '重要提示', '投保说明'],
            'exclusion': ['责任免除', '免责条款', '除外责任'],
            'health_disclosure': ['健康告知', '健康声明', '告知事项'],
            'rider': ['附加险', '附加条款'],
        },
        llm_enabled=False
    )

    test_cases = [
        ("投保须知：本产品仅限...", SectionType.NOTICE),
        ("责任免除条款如下...", SectionType.EXCLUSION),
        ("健康告知：被保险人...", SectionType.HEALTH_DISCLOSURE),
        ("附加险条款说明...", SectionType.RIDER),
        ("第一条 保险责任...", SectionType.CLAUSE),
    ]

    print("\n" + "=" * 60)
    print("内容类型检测测试")
    print("=" * 60)

    passed = 0
    for text, expected in test_cases:
        result = classifier.classify(text)
        status = "✅" if result.section_type == expected else "❌"
        print(f"  {status} '{text[:20]}...' -> {result.section_type.value} "
              f"(置信度: {result.confidence:.2f}, 方法: {result.method.value})")
        if result.section_type == expected:
            passed += 1

    print(f"\n通过: {passed}/{len(test_cases)}")
    return passed == len(test_cases)


def main():
    """主测试函数"""
    print("=" * 60)
    print("保险产品文档解析集成测试")
    print("=" * 60)

    # 1. 单元测试
    test_clause_number_formats()
    test_content_classifier()

    # 2. 真实文档测试
    print("\n" + "=" * 60)
    print("真实文档解析测试")
    print("=" * 60)

    files = get_product_files()
    print(f"\n找到 {len(files)} 个文档文件")

    results = []
    stats = {
        'total': 0,
        'success': 0,
        'total_clauses': 0,
        'total_premium_tables': 0,
        'total_notices': 0,
        'total_exclusions': 0,
        'docx_count': 0,
        'pdf_count': 0,
    }

    for i, file_path in enumerate(files, 1):
        result = parse_file(file_path)
        results.append(result)
        print_result(result, i, len(files))

        stats['total'] += 1
        if result['success']:
            stats['success'] += 1
            stats['total_clauses'] += result['clauses']
            stats['total_premium_tables'] += result['premium_tables']
            stats['total_notices'] += result['notices']
            stats['total_exclusions'] += result['exclusions']
            if file_path.suffix == '.docx':
                stats['docx_count'] += 1
            elif file_path.suffix == '.pdf':
                stats['pdf_count'] += 1

    # 3. 统计摘要
    print("\n" + "=" * 60)
    print("测试摘要")
    print("=" * 60)
    print(f"总文件数: {stats['total']}")
    print(f"成功解析: {stats['success']} ({stats['success']/stats['total']*100:.1f}%)")
    print(f"  - Word 文档: {stats['docx_count']}")
    print(f"  - PDF 文档: {stats['pdf_count']}")
    print(f"总条款数: {stats['total_clauses']}")
    print(f"总费率表: {stats['total_premium_tables']}")
    print(f"总投保须知: {stats['total_notices']}")
    print(f"总责任免除: {stats['total_exclusions']}")

    # 4. 失败详情
    failed = [r for r in results if not r['success']]
    if failed:
        print(f"\n失败文件 ({len(failed)}):")
        for r in failed:
            print(f"  - {r['file']}: {r['error']}")

    return stats['success'] == stats['total']


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

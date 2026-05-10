#!/usr/bin/env python3
"""全量产品合规检查端到端测试"""
import sys
import time
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent))

from lib.compliance.checker import identify_category, check_negative_list, load_audit_sources, format_context_for_llm, run_compliance_check, CheckResult
from lib.doc_parser import parse_product_document, DocumentParseError
from lib.rag_engine import init_engine
from lib.compliance.prompts import COMPLIANCE_PROMPT_DOCUMENT

PRODUCTS_DIR = Path("/Users/plain/work/actuary-assets/products")


@dataclass
class TestResult:
    file_name: str
    file_type: str
    category: Optional[str]
    category_method: str
    items_count: int
    non_compliant: int
    negative_list_result: str
    elapsed_seconds: float
    error: Optional[str] = None


def test_product(file_path: Path) -> TestResult:
    start = time.time()
    file_name = file_path.name
    file_type = file_path.suffix.lower()

    try:
        audit_doc = parse_product_document(str(file_path))
        if audit_doc is None:
            return TestResult(
                file_name=file_name, file_type=file_type,
                category=None, category_method="parse_failed",
                items_count=0, non_compliant=0,
                negative_list_result=CheckResult.SKIPPED,
                elapsed_seconds=time.time() - start,
                error="文档解析返回 None",
            )

        doc_content = getattr(audit_doc, "combined_text", "")

        # 险种识别
        category_result = identify_category(doc_content[:5000], product_name=file_name)

        # 构建法规上下文并检查
        sources = load_audit_sources(category=category_result.category)
        context = format_context_for_llm(sources)
        truncated = doc_content[:150000]
        prompt = COMPLIANCE_PROMPT_DOCUMENT.format(
            document_content=truncated,
            context=context,
        )
        result_data = run_compliance_check(prompt, num_sources=len(sources))
        items = result_data.get("items", [])
        summary = result_data.get("summary", {})

        # 负面清单检查
        negative_items, negative_result, _negative_sources = check_negative_list(doc_content)
        if negative_items:
            items.extend(negative_items)
            summary["non_compliant"] = summary.get("non_compliant", 0) + len(negative_items)

        elapsed = time.time() - start
        return TestResult(
            file_name=file_name, file_type=file_type,
            category=category_result.category,
            category_method=category_result.method,
            items_count=len(items),
            non_compliant=summary.get("non_compliant", 0),
            negative_list_result=negative_result,
            elapsed_seconds=elapsed,
        )

    except DocumentParseError as e:
        return TestResult(
            file_name=file_name, file_type=file_type,
            category=None, category_method="error",
            items_count=0, non_compliant=0,
            negative_list_result=CheckResult.SKIPPED,
            elapsed_seconds=time.time() - start,
            error=f"解析错误: {e}",
        )
    except Exception as e:
        return TestResult(
            file_name=file_name, file_type=file_type,
            category=None, category_method="error",
            items_count=0, non_compliant=0,
            negative_list_result=CheckResult.SKIPPED,
            elapsed_seconds=time.time() - start,
            error=f"运行时错误: {e}",
        )


def main():
    print("初始化 RAG 引擎...")
    engine = init_engine()
    if engine is None:
        print("❌ RAG 引擎初始化失败")
        return 1
    print("✅ RAG 引擎初始化成功\n")

    # 排除 3款word 子目录（与主目录重复），排除 .doc 格式
    product_files = sorted([
        f for f in PRODUCTS_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in [".docx", ".pdf"]
    ])
    doc_files = sorted([
        f for f in PRODUCTS_DIR.iterdir()
        if f.is_file() and f.suffix.lower() == ".doc"
    ])

    all_files = product_files + doc_files
    print("=" * 80)
    print(f"保险产品合规检查全量验证 ({len(all_files)} 个产品)")
    print(f"  .docx/.pdf: {len(product_files)} 个 | .doc: {len(doc_files)} 个（不支持）")
    print("=" * 80 + "\n")

    results: List[TestResult] = []
    for i, file_path in enumerate(all_files, 1):
        print(f"[{i}/{len(all_files)}] {file_path.name[:50]}...")
        result = test_product(file_path)
        results.append(result)

        if result.error:
            print(f"   ❌ {result.error}")
        else:
            cat = result.category or "未知"
            print(f"   ✅ {cat} ({result.category_method})")
            print(f"      检查项: {result.items_count}, 违规: {result.non_compliant}")
            print(f"      负面清单: {result.negative_list_result}, 耗时: {result.elapsed_seconds:.1f}s")
        print()

    # 汇总
    success = sum(1 for r in results if r.error is None)
    failed = sum(1 for r in results if r.error is not None)
    total_time = sum(r.elapsed_seconds for r in results)
    total_items = sum(r.items_count for r in results)
    total_violations = sum(r.non_compliant for r in results)

    print("=" * 80)
    print("测试汇总")
    print("=" * 80)
    print(f"成功: {success}, 失败: {failed}")
    print(f"总耗时: {total_time:.1f}s, 总检查项: {total_items}, 总违规: {total_violations}\n")

    by_category = {}
    for r in results:
        if r.error is None:
            cat = r.category or "未知"
            by_category.setdefault(cat, []).append(r)

    print("险种分布:")
    for cat, items in sorted(by_category.items()):
        print(f"  {cat}: {len(items)} 个产品")

    print("\n详细结果:")
    print("-" * 80)
    print(f"{'文件名':<40} {'险种':<8} {'违规':<4} {'耗时':<6}")
    print("-" * 80)
    for r in results:
        name = r.file_name[:37] + "..." if len(r.file_name) > 40 else r.file_name
        cat = (r.category or "错误")[:6]
        if r.error:
            print(f"{name:<40} {cat:<8} ERROR")
        else:
            print(f"{name:<40} {cat:<8} {r.non_compliant:<4} {r.elapsed_seconds:.1f}s")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
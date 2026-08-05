#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实文档集成测试

使用 /Users/plain/work/actuary-assets/products/ 目录下的真实保险产品文档进行验证。
"""
from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path

import pytest

from lib.doc_parser import parse_product_document
from lib.doc_parser.models import AuditDocument

PRODUCTS_DIR = Path("/Users/plain/work/actuary-assets/products/")
ACCEPTANCE_MANIFEST = (
    Path(__file__).parents[2]
    / "fixtures"
    / "compliance_audit"
    / "v1"
    / "manifest.json"
)
PRODUCT_ARCHIVE = PRODUCTS_DIR / "条款(1).zip"


def _assert_full_source_coverage(
    document: AuditDocument,
    source_name: str,
) -> None:
    """真实产品的每条有效来源记录必须恰好归属一个审核块。"""
    attestation = document.coverage_attestation
    assert attestation.coverage_attested, source_name
    assert attestation.source_record_count > 0, source_name
    assert attestation.assigned_record_count == attestation.source_record_count, (
        source_name
    )
    assert attestation.unassigned_orders == (), source_name
    assert attestation.multiply_assigned_orders == (), source_name
    assert attestation.duplicate_source_orders == (), source_name
    assert attestation.truncated_orders == (), source_name


def _require_product(path: Path) -> None:
    if not path.is_file():
        pytest.skip(f"真实产品不存在: {path}")


@pytest.fixture
def real_pdf_files():
    """真实 PDF 文件列表"""
    if not PRODUCTS_DIR.exists():
        pytest.skip(f"产品目录不存在: {PRODUCTS_DIR}")
    return list(PRODUCTS_DIR.glob("*.pdf"))


@pytest.fixture
def real_docx_files():
    """真实 DOCX 文件列表"""
    if not PRODUCTS_DIR.exists():
        pytest.skip(f"产品目录不存在: {PRODUCTS_DIR}")
    return list(PRODUCTS_DIR.glob("*.docx"))


class TestRealDocuments:
    """真实文档集成测试"""

    def test_parse_all_acceptance_products_without_llm(self):
        """验收清单中的23份 DOC/DOCX/PDF 必须全部走确定性解析。"""
        if not PRODUCTS_DIR.exists():
            pytest.skip(f"产品目录不存在: {PRODUCTS_DIR}")
        if not ACCEPTANCE_MANIFEST.exists():
            pytest.fail(f"验收清单不存在: {ACCEPTANCE_MANIFEST}")
        manifest = json.loads(ACCEPTANCE_MANIFEST.read_text(encoding="utf-8"))
        products = manifest["products"]
        if any(product["format"] == "doc" for product in products):
            if not (shutil.which("soffice") or shutil.which("libreoffice")):
                pytest.skip("旧版 DOC 解析需要 LibreOffice")

        assert len(products) == 23
        missing = [
            product["file_name"]
            for product in products
            if not (PRODUCTS_DIR / product["file_name"]).is_file()
        ]
        if missing:
            pytest.skip(f"验收产品资产缺失: {', '.join(missing)}")
        parsed_legacy_docs = 0
        for product in products:
            path = PRODUCTS_DIR / product["file_name"]
            document = parse_product_document(str(path))
            audit_content_count = sum(
                len(items)
                for items in (
                    document.clauses,
                    document.tables,
                    document.notices,
                    document.health_disclosures,
                    document.exclusions,
                    document.rider_clauses,
                )
            )
            assert document.file_name == path.name
            assert document.file_type == path.suffix.lower()
            assert audit_content_count > 0, f"{path.name} 未提取到审核内容"
            _assert_full_source_coverage(document, path.name)
            if path.suffix.lower() == ".doc":
                parsed_legacy_docs += 1
                assert any("临时转换" in warning for warning in document.warnings)

        assert parsed_legacy_docs == 9

    def test_all_twelve_legacy_docs_in_source_archive_are_parseable(
        self,
        tmp_path,
    ):
        """归档中的12份旧 DOC 均可转换；其中3份是主目录其他格式的重复版本。"""
        if not PRODUCT_ARCHIVE.exists():
            pytest.skip(f"产品归档不存在: {PRODUCT_ARCHIVE}")
        if not (shutil.which("soffice") or shutil.which("libreoffice")):
            pytest.skip("旧版 DOC 解析需要 LibreOffice")
        with zipfile.ZipFile(PRODUCT_ARCHIVE) as archive:
            members = [
                member
                for member in archive.infolist()
                if not member.is_dir() and member.filename.lower().endswith(".doc")
            ]
            assert len(members) == 12
            for index, member in enumerate(members):
                source = tmp_path / f"legacy-{index:02d}.doc"
                source.write_bytes(archive.read(member))
                document = parse_product_document(str(source))
                assert document.audit_blocks, member.filename
                assert document.product_tags.primary_subtype.value != "unknown"
                _assert_full_source_coverage(document, member.filename)

    @pytest.mark.parametrize(
        (
            "file_name", "out_of_hospital_drug", "cancer_specific",
            "specific_disease", "critical_illness_term",
        ),
        (
            (
                "125904《人保健康悠优保互联网医疗保险（费率可调）》条款v4.doc",
                True,
                False,
                False,
                True,
            ),
            (
                "《人保健康温暖常伴互联网意外伤害保险（2.0版）》条款.docx",
                False,
                False,
                False,
                False,
            ),
            (
                "《人保健康附加互联网恶性肿瘤特定药品费用医疗保险》条款.pdf",
                False,
                True,
                False,
                True,
            ),
            (
                "《人保健康附加互联网特定药品费用医疗保险（B款）》条款.doc",
                True,
                False,
                False,
                True,
            ),
            (
                "《人保健康附加团体终身重度恶性肿瘤疾病保险》条款.docx",
                False,
                True,
                True,
                True,
            ),
        ),
    )
    def test_real_product_risk_facts_follow_controlled_three_state_rules(
        self,
        file_name,
        out_of_hospital_drug,
        cancer_specific,
        specific_disease,
        critical_illness_term,
    ):
        path = PRODUCTS_DIR / file_name
        _require_product(path)
        if path.suffix.lower() == ".doc":
            if not (shutil.which("soffice") or shutil.which("libreoffice")):
                pytest.skip("旧版 DOC 解析需要 LibreOffice")

        tags = parse_product_document(str(path)).product_tags

        assert tags.mentions_out_of_hospital_drug is out_of_hospital_drug
        assert tags.is_cancer_specific_product is cancer_specific
        assert tags.is_specific_disease_product is specific_disease
        assert (
            tags.mentions_critical_illness_definition_term
            is critical_illness_term
        )

    @pytest.mark.parametrize(
        ("file_name", "number", "parent", "ancestors", "title"),
        (
            (
                "125904《人保健康悠优保互联网医疗保险（费率可调）》条款v4.doc",
                "2.5.4",
                "2.5",
                ("2", "2.5"),
                "特定药品费用保险金",
            ),
            (
                "《人保健康互联网失能收入损失保险（2025版）》条款.docx",
                "2.4.1",
                "2.4",
                ("2", "2.4"),
                "住院失能收入损失保险金",
            ),
            (
                "《人保健康互联网团体意外伤害保险（2025版）》条款.pdf",
                "2.3.1",
                "2.3",
                ("2", "2.3"),
                "基本部分",
            ),
        ),
    )
    def test_doc_docx_pdf_keep_golden_multilevel_hierarchy(
        self,
        file_name,
        number,
        parent,
        ancestors,
        title,
    ):
        """DOC、DOCX、PDF 各以一个真实三级编号锁定父子关系。"""
        path = PRODUCTS_DIR / file_name
        _require_product(path)
        if path.suffix.lower() == ".doc":
            if not (shutil.which("soffice") or shutil.which("libreoffice")):
                pytest.skip("旧版 DOC 解析需要 LibreOffice")

        document = parse_product_document(str(path))
        clause = next(
            (item for item in document.clauses if item.number == number),
            None,
        )

        assert clause is not None, f"{path.name} 缺少条款 {number}"
        assert clause.title == title
        assert clause.hierarchy_level == 3
        assert clause.parent_number == parent
        assert clause.ancestor_numbers == ancestors
        assert clause.hierarchy_path == " > ".join((*ancestors, number))
        _assert_full_source_coverage(document, path.name)

    def test_yoyou_numbered_rows_keep_continuations_and_hierarchy(self):
        """悠优保空编号续接行必须归回对应编号，合并格不得污染标题。"""
        path = PRODUCTS_DIR / (
            "125904《人保健康悠优保互联网医疗保险（费率可调）》条款v4.doc"
        )
        _require_product(path)
        if not (shutil.which("soffice") or shutil.which("libreoffice")):
            pytest.skip("旧版 DOC 解析需要 LibreOffice")

        document = parse_product_document(str(path))
        by_number = {clause.number: clause for clause in document.clauses}
        medicine_clause = by_number["2.5.4"]
        paragraphs = [
            line.strip()
            for line in medicine_clause.text.splitlines()
            if line.strip()
        ]

        assert len(document.clauses) == 99
        assert "住院医疗费用保险金" in by_number["2.5.3"].text
        assert "特殊门诊医疗费用保险金" in by_number["2.5.3"].text
        assert "住院前后门急诊医疗费用保险金" in by_number["2.5.3"].text
        assert "特定药品费用保险金年度累计给付限额" in medicine_clause.text
        assert paragraphs[0].startswith(
            "在本合同保险期间内，被保险人在等待期满后"
        )
        assert paragraphs[-1].startswith(
            "在本合同保险期间内，若本合同医疗费用保险金责任"
        )
        assert paragraphs[-1].endswith("本合同效力终止。")
        assert medicine_clause.source_start_order is not None
        assert medicine_clause.source_end_order is not None
        assert (
            medicine_clause.source_start_order
            < medicine_clause.source_end_order
        )
        assert "申请人和受益人的有效身份证件" in by_number["5.3"].text
        assert medicine_clause.parent_number == "2.5"
        assert medicine_clause.ancestor_numbers == ("2", "2.5")
        assert by_number["7.42"].title == (
            "因职业关系导致的感染艾滋病病毒或患艾滋病"
        )
        unclassified_text = "\n".join(
            section.content for section in document.unclassified_sections
        )
        assert "住院前后门急诊医疗费用保险金" not in unclassified_text
        positions = {
            block.number: index
            for index, block in enumerate(document.audit_blocks)
            if block.block_type.value == "clause"
        }
        assert positions["2"] < positions["2.1"] < positions["2.5.4"]
        _assert_full_source_coverage(document, path.name)

    def test_parse_real_pdfs(self, real_pdf_files):
        """测试解析真实 PDF 文件"""
        if not real_pdf_files:
            pytest.skip("无 PDF 文件")

        for pdf_path in real_pdf_files:
            doc = parse_product_document(str(pdf_path))
            assert doc.file_type == '.pdf'
            assert doc.file_name == pdf_path.name

            total_content = (
                len(doc.clauses) +
                len(doc.tables) +
                len(doc.notices) +
                len(doc.exclusions)
            )
            assert total_content > 0, f"{pdf_path.name} 未提取到任何内容"

            print(f"\n{pdf_path.name}:")
            print(f"  条款: {len(doc.clauses)}")
            print(f"  数据表格: {len(doc.tables)}")
            print(f"  告知事项: {len(doc.notices)}")
            print(f"  责任免除: {len(doc.exclusions)}")
            print(f"  Warnings: {len(doc.warnings)}")

    def test_parse_real_docx_files(self, real_docx_files):
        """测试解析真实 DOCX 文件"""
        if not real_docx_files:
            pytest.skip("无 DOCX 文件")

        for docx_path in real_docx_files:
            doc = parse_product_document(str(docx_path))
            assert doc.file_type == '.docx'
            assert doc.file_name == docx_path.name

            total_content = len(doc.clauses) + len(doc.tables)
            assert total_content > 0, f"{docx_path.name} 未提取到任何内容"

    def test_table_markdown(self, real_pdf_files):
        """测试数据表格 Markdown 输出"""
        if not real_pdf_files:
            pytest.skip("无 PDF 文件")

        for pdf_path in real_pdf_files:
            doc = parse_product_document(str(pdf_path))
            for table in doc.tables:
                md = table.to_markdown()
                if md:
                    assert md.startswith("|"), "Markdown 表格应以 | 开头"
                    assert "---" in md, "Markdown 表格应包含分隔行"

    def test_no_header_footer_in_content(self, real_pdf_files):
        """验证页眉页脚被过滤"""
        if not real_pdf_files:
            pytest.skip("无 PDF 文件")

        header_patterns = ["内部资料", "严禁外传"]

        for pdf_path in real_pdf_files:
            doc = parse_product_document(str(pdf_path))
            all_text = "\n".join(c.text for c in doc.clauses)

            for pattern in header_patterns:
                count = all_text.count(pattern)
                if count > 3:
                    doc.warnings.append(f"可能的页眉残留: '{pattern}' 出现 {count} 次")

            matches = re.findall(r'第\s*\d+\s*页', all_text)
            if len(matches) > 3:
                doc.warnings.append(f"可能的页脚残留: '第 X 页' 出现 {len(matches)} 次")

    def test_chunk_metadata(self, real_pdf_files):
        """测试 Chunk 元数据生成"""
        if not real_pdf_files:
            pytest.skip("无 PDF 文件")

        for pdf_path in real_pdf_files[:1]:
            doc = parse_product_document(str(pdf_path))

            if doc.clauses:
                metadata = doc.get_chunk_metadata(
                    section_path="条款",
                    chunk_index=0,
                    is_key_clause=True,
                )
                assert metadata.doc_id == pdf_path.name.replace('.', '_')
                assert metadata.doc_name == pdf_path.name
                assert metadata.doc_type == "insurance_contract"
                assert metadata.section_path == "条款"
                assert metadata.is_key_clause is True

from dataclasses import replace

import pytest
from fastapi import HTTPException

from api.routers.compliance import _audit_doc_to_response
from api.routers.compliance_v2 import _pipeline_request
from api.schemas.compliance import ComplianceReportDataResponse, DocumentCheckRequest
from lib.doc_parser.models import (
    AuditDocument,
    AuditBlockType,
    Clause,
    CoverageAttestation,
    DataTable,
    DocumentSection,
    TableType,
    render_audit_document_text,
)
from lib.doc_parser.pd.product_tagging import build_product_tags


def test_old_report_payload_remains_readable_with_safe_defaults() -> None:
    report = ComplianceReportDataResponse.model_validate({
        "summary": {"non_compliant": 0},
        "items": [],
        "regulations": [],
        "category": "健康险",
    })
    assert report.audit_status == "completed"
    assert report.compliance_conclusion == "undetermined"
    assert report.decisions == []
    assert report.failed_count == 0


def test_product_name_evidence_source_kind_survives_report_serialization() -> None:
    report = ComplianceReportDataResponse.model_validate({
        "decisions": [{
            "task_id": "task-1",
            "regulation_unit_id": "unit-1",
            "status": "compliant",
            "reasoning": "产品名称符合监管命名要求。",
            "product_evidence": [{
                "clause_id": "product-name",
                "quote": "测试医疗保险",
                "source_kind": "product_name",
            }],
        }],
    })

    serialized = report.model_dump()

    assert (
        serialized["decisions"][0]["product_evidence"][0]["source_kind"]
        == "product_name"
    )


def test_document_request_accepts_structured_audit_blocks() -> None:
    request = DocumentCheckRequest.model_validate({
        "document_content": "等待期为30天",
        "audit_blocks": [{
            "clause_id": "c-1",
            "block_type": "clause",
            "source_index": 0,
            "number": "1.1",
            "title": "等待期",
            "content": "等待期为30天",
            "topics": ["coverage.waiting_period"],
        }],
        "product_tags": {"line": "health"},
    })
    assert request.audit_blocks[0].clause_id == "c-1"


def test_parse_response_serializes_stable_ids_and_all_audit_blocks() -> None:
    product_name = "医疗保险条款"
    document = AuditDocument(
        file_name="医疗保险条款.docx",
        file_type=".docx",
        product_name=product_name,
        product_name_source="document_content",
        unclassified_sections=[
            DocumentSection("", "未编号产品原文", "unclassified"),
        ],
        clauses=[Clause("2.5.4", "等待期", "等待期为30天")],
        tables=[DataTable(
            [["年龄", "费率"], ["18", "100"]],
            TableType.PREMIUM,
            remark="保证续保期间为六年",
        )],
        coverage_attestation=CoverageAttestation(
            coverage_attested=True,
            source_record_count=3,
            assigned_record_count=3,
        ),
    )
    document = replace(
        document,
        product_tags=build_product_tags(
            product_name,
            document.canonical_text,
            product_name_source=document.product_name_source,
            complete_document=True,
        ),
    )

    response = _audit_doc_to_response(document, ".docx")

    assert response.document_fingerprint == document.document_fingerprint
    assert response.audit_input_fingerprint == document.audit_input_fingerprint
    assert response.parse_attestation
    assert response.product_name_source == document.product_name_source
    assert response.coverage_attested is True
    assert [block.clause_id for block in response.audit_blocks] == [
        block.clause_id for block in document.audit_blocks
    ]
    block_by_type = {block.block_type: block for block in document.audit_blocks}
    assert response.unclassified_sections[0].clause_id == block_by_type[
        AuditBlockType.UNCLASSIFIED
    ].clause_id
    assert response.clauses[0].clause_id == block_by_type[
        AuditBlockType.CLAUSE
    ].clause_id
    assert response.clauses[0].hierarchy_level == 3
    assert response.clauses[0].parent_number == "2.5"
    assert response.clauses[0].ancestor_numbers == ["2", "2.5"]
    assert response.clauses[0].hierarchy_path == "2 > 2.5 > 2.5.4"
    assert response.data_tables[0].clause_id == block_by_type[
        AuditBlockType.TABLE
    ].clause_id
    assert "【数据表 1】保证续保期间为六年" in response.combined_text
    assert response.combined_text == render_audit_document_text(
        (
            block.block_type.value,
            block.source_index,
            block.number,
            block.title,
            block.content,
        )
        for block in document.audit_blocks
    )
    request = DocumentCheckRequest(
        document_content=response.combined_text,
        parse_id=response.parse_id,
        parse_attestation=response.parse_attestation,
        document_fingerprint=response.document_fingerprint,
        audit_input_fingerprint=response.audit_input_fingerprint,
        product_name=response.product_name or "",
        product_name_source=response.product_name_source,
        coverage_attested=response.coverage_attested,
        parse_warnings=response.warnings,
        product_tags=response.product_tags,
        audit_blocks=response.audit_blocks,
    )
    pipeline_request = _pipeline_request(request)
    assert len(pipeline_request.clauses) == 3
    clause = next(
        item for item in pipeline_request.clauses
        if item.number == "2.5.4"
    )
    assert clause.parent_number == "2.5"
    assert clause.ancestor_numbers == ("2", "2.5")
    assert clause.hierarchy_path == "2 > 2.5 > 2.5.4"
    assert pipeline_request.product_tags.renewal_type.value == "guaranteed"

    table_block = next(
        block
        for block in request.audit_blocks
        if block.block_type == AuditBlockType.TABLE.value
    )
    table_block.title = "不保证续保"
    with pytest.raises(HTTPException, match="document_fingerprint"):
        _pipeline_request(request)

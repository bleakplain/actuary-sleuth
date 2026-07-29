import ast
import asyncio
import json
import threading
from dataclasses import replace
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List

import pytest
from fastapi import HTTPException

from api.routers import compliance_v2
from api.routers.compliance_v2 import _pipeline_request, build_report_data
from api.schemas.compliance import DocumentCheckRequest
from api.database import get_compliance_report
from lib.auth.parse_attestation import issue_parse_attestation
from lib.common.compliance_audit import (
    AuditStatus,
    RegulationAuditDecision,
    RegulationDecisionStatus,
)
from lib.compliance.audit_pipeline import run_audit_pipeline
from lib.compliance.regulation_retrieval import RegulationRetrievalOutcome
from lib.compliance.regulation_units import RegulationChunk, RegulationUnit
from lib.doc_parser.models import (
    calculate_audit_input_fingerprint,
    calculate_clause_ids,
    calculate_document_fingerprint,
    render_audit_document_text,
)
from lib.doc_parser.pd.product_tagging import build_product_tags


def _request(user_subject: str = "") -> DocumentCheckRequest:
    block = {
        "block_type": "clause",
        "source_index": 0,
        "number": "2.1",
        "title": "等待期",
        "content": "等待期为30日。",
        "topics": ["coverage.waiting_period"],
        "hierarchy_level": 2,
        "parent_number": "2",
        "ancestor_numbers": ["2"],
        "hierarchy_path": "2 > 2.1",
        "container_only": False,
    }
    identity = (
        block["block_type"],
        block["number"],
        block["title"],
        block["content"],
    )
    block["clause_id"] = calculate_clause_ids((identity,))[0]
    document_content = render_audit_document_text(((
        block["block_type"],
        block["source_index"],
        block["number"],
        block["title"],
        block["content"],
    ),))
    document_fingerprint = calculate_document_fingerprint((identity,))
    product_name = "测试医疗保险"
    product_tags = build_product_tags(
        product_name,
        document_content,
        complete_document=True,
    )
    parse_id = "pd_test"
    product_name_source = "document_content"
    attestation = issue_parse_attestation(
        parse_id,
        document_fingerprint,
        calculate_audit_input_fingerprint(
            document_fingerprint,
            product_name,
        ),
        product_name_source,
        user_subject=user_subject,
        coverage_attested=True,
    )
    return DocumentCheckRequest(
        document_content=document_content,
        parse_id=parse_id,
        parse_attestation=attestation.token,
        document_fingerprint=document_fingerprint,
        audit_input_fingerprint=calculate_audit_input_fingerprint(
            document_fingerprint,
            product_name,
        ),
        product_name=product_name,
        product_name_source=product_name_source,
        coverage_attested=True,
        category="健康险",
        product_tags=product_tags.to_dict(),
        audit_blocks=[block],
    )


def _unit() -> RegulationUnit:
    return RegulationUnit(
        unit_id="unit-1",
        kb_version="v5",
        source_file="健康险.md",
        locator="第一条",
        locator_type="article_number",
        law_name="健康险规定",
        article_number="第一条",
        section_path="第一条",
        chunks=(RegulationChunk(
            chunk_id="chunk-1",
            law_name="健康险规定",
            article_number="第一条",
            section_path="第一条",
            source_file="健康险.md",
            chunk_index=0,
            content="等待期应符合要求。",
            regulation_topics=("coverage.waiting_period",),
            source_type="category",
        ),),
        applicability_status="applicable",
        regulation_topics=("coverage.waiting_period",),
    )


async def _event_payloads(response: Any) -> List[Dict[str, Any]]:
    payloads = []
    body: AsyncIterator[Dict[str, Any]] = response.body_iterator
    async for event in body:
        payloads.append(json.loads(event["data"]))
    return payloads


def test_v2_request_rebuilds_authoritative_tags_and_keeps_stable_blocks() -> None:
    request = _pipeline_request(_request())

    assert request.product_tags.line.value == "health"
    assert request.product_tags.primary_subtype.value == "medical"
    assert {
        evidence.source for evidence in request.product_tags.evidence
        if evidence.field_name in {"line", "primary_subtype"}
    } == {"document_content"}
    assert request.clauses[0].clause_id.startswith("clause_")
    assert request.clauses[0].topics == ("coverage.waiting_period",)
    assert request.clauses[0].hierarchy_level == 2
    assert request.clauses[0].parent_number == "2"
    assert request.clauses[0].ancestor_numbers == ("2",)
    assert request.clauses[0].hierarchy_path == "2 > 2.1"


def test_v2_request_rejects_tampered_clause_hierarchy() -> None:
    request = _request()
    request.audit_blocks[0].parent_number = "9"

    with pytest.raises(HTTPException, match="编号层级"):
        _pipeline_request(request)


def test_v2_request_rejects_product_tags_from_another_document() -> None:
    request = _request()
    request.product_tags = {"line": "life", "primary_subtype": "term_life"}

    with pytest.raises(HTTPException, match="产品标签"):
        _pipeline_request(request)


def test_v2_request_rejects_missing_parse_attestation() -> None:
    request = _request()
    request.parse_attestation = ""

    with pytest.raises(HTTPException, match="缺少解析凭证"):
        _pipeline_request(request)


def test_v2_request_rejects_missing_structured_blocks() -> None:
    request = _request()
    request.audit_blocks = []
    with pytest.raises(HTTPException, match="audit_blocks"):
        _pipeline_request(request)


def test_v2_request_rejects_stale_document_fingerprint() -> None:
    request = _request()
    request.document_fingerprint = "stale"

    with pytest.raises(HTTPException, match="解析凭证"):
        _pipeline_request(request)


def test_v2_request_rejects_product_name_changed_after_parsing() -> None:
    request = _request()
    request.product_name = "另一款保险"

    with pytest.raises(HTTPException, match="审核输入指纹"):
        _pipeline_request(request)


def test_v2_request_rejects_self_consistent_deleted_block_forgery() -> None:
    request = _request()
    original = request.audit_blocks[0]
    second = original.model_copy(update={
        "source_index": 1,
        "number": "2.2",
        "title": "其他约定",
        "content": "其他约定正文。",
    })
    identities = tuple(
        (
            block.block_type,
            block.number,
            block.title,
            block.content,
        )
        for block in (original, second)
    )
    ids = calculate_clause_ids(identities)
    request.audit_blocks = [
        original.model_copy(update={"clause_id": ids[0]}),
        second.model_copy(update={"clause_id": ids[1]}),
    ]
    request.document_fingerprint = calculate_document_fingerprint(identities)
    request.audit_input_fingerprint = calculate_audit_input_fingerprint(
        request.document_fingerprint,
        request.product_name,
    )
    request.document_content = render_audit_document_text(tuple(
        (
            block.block_type,
            block.source_index,
            block.number,
            block.title,
            block.content,
        )
        for block in request.audit_blocks
    ))
    request.product_tags = build_product_tags(
        request.product_name,
        request.document_content,
        complete_document=True,
    ).to_dict()
    valid = issue_parse_attestation(
        request.parse_id,
        request.document_fingerprint,
        request.audit_input_fingerprint,
        request.product_name_source,
        coverage_attested=request.coverage_attested,
    )
    request.parse_attestation = valid.token

    kept = request.audit_blocks[:1]
    kept_identity = ((
        kept[0].block_type,
        kept[0].number,
        kept[0].title,
        kept[0].content,
    ),)
    request.audit_blocks = kept
    request.document_fingerprint = calculate_document_fingerprint(kept_identity)
    request.audit_input_fingerprint = calculate_audit_input_fingerprint(
        request.document_fingerprint,
        request.product_name,
    )
    request.document_content = render_audit_document_text(((
        kept[0].block_type,
        kept[0].source_index,
        kept[0].number,
        kept[0].title,
        kept[0].content,
    ),))
    request.product_tags = build_product_tags(
        request.product_name,
        request.document_content,
        complete_document=True,
    ).to_dict()

    with pytest.raises(HTTPException, match="解析凭证"):
        _pipeline_request(request)


def test_v2_request_rejects_expired_parse_attestation() -> None:
    request = _request()
    request.parse_attestation = issue_parse_attestation(
        request.parse_id,
        request.document_fingerprint,
        request.audit_input_fingerprint,
        request.product_name_source,
        coverage_attested=request.coverage_attested,
        now=1,
        ttl_seconds=1,
    ).token

    with pytest.raises(HTTPException, match="已过期"):
        _pipeline_request(request)


def test_v2_request_rejects_tampered_parse_attestation() -> None:
    request = _request()
    payload, signature = request.parse_attestation.split(".", 1)
    request.parse_attestation = (
        f"{payload}.{'A' if signature[0] != 'A' else 'B'}{signature[1:]}"
    )

    with pytest.raises(HTTPException, match="签名无效"):
        _pipeline_request(request)


def test_v2_request_rejects_removed_parse_warning() -> None:
    request = _request()
    request.parse_warnings = ["一段内容无法分类，审核时已保守保留"]
    request.parse_attestation = issue_parse_attestation(
        request.parse_id,
        request.document_fingerprint,
        request.audit_input_fingerprint,
        request.product_name_source,
        request.parse_warnings,
        coverage_attested=request.coverage_attested,
    ).token
    request.parse_warnings = []

    with pytest.raises(HTTPException, match="审核输入身份不一致"):
        _pipeline_request(request)


def test_v2_request_rejects_parse_attestation_from_another_user() -> None:
    request = _request()
    request.parse_attestation = issue_parse_attestation(
        request.parse_id,
        request.document_fingerprint,
        request.audit_input_fingerprint,
        request.product_name_source,
        user_subject="user-a",
        coverage_attested=request.coverage_attested,
    ).token

    with pytest.raises(HTTPException, match="审核输入身份不一致"):
        _pipeline_request(request, "user-b")


def test_v2_request_rejects_tampered_coverage_attestation() -> None:
    request = _request()
    request.coverage_attested = False

    with pytest.raises(HTTPException, match="审核输入身份不一致"):
        _pipeline_request(request)


def test_v2_request_disables_absence_inference_without_coverage_proof() -> None:
    request = _request()
    request.coverage_attested = False
    request.product_tags = build_product_tags(
        request.product_name,
        request.document_content,
        complete_document=False,
    ).to_dict()
    request.parse_attestation = issue_parse_attestation(
        request.parse_id,
        request.document_fingerprint,
        request.audit_input_fingerprint,
        request.product_name_source,
        coverage_attested=False,
    ).token

    pipeline_request = _pipeline_request(request)

    assert pipeline_request.product_tags.renewal_type.value == "unknown"


def test_v2_report_keeps_manual_review_and_incomplete_state() -> None:
    request = _pipeline_request(_request())

    def retriever(*args):
        return RegulationRetrievalOutcome(
            regulations=(),
            regulation_units=(_unit(),),
            candidate_count=1,
        )

    def auditor(packages, concurrency, deadline, callback):
        package = tuple(packages)[0]
        return (RegulationAuditDecision(
            task_id=package.task_id,
            regulation_unit_id=package.regulation.regulation_unit_id,
            status=RegulationDecisionStatus.MANUAL_REVIEW,
            reasoning="模型不可用。",
            suggestion="人工复核。",
            regulation_evidence=(),
            product_evidence=(),
            incomplete=True,
            error_code="llm_call_failed",
        ),)

    result = run_audit_pipeline(
        request,
        retriever=retriever,
        package_auditor=auditor,
    )
    report = build_report_data(result)

    assert result.summary.audit_status is AuditStatus.INCOMPLETE
    assert report["audit_status"] == "incomplete"
    assert report["compliance_conclusion"] == "undetermined"
    assert report["summary"]["attention"] == 1
    assert report["decisions"][0]["error_code"] == "llm_call_failed"
    assert report["items"][0]["status"] == "attention"
    assert report["evaluation_dataset_status"] == "pending"
    assert report["cutover_gate_status"] == "blocked"
    assert report["document_fingerprint"] == request.document_fingerprint
    assert report["audit_input_fingerprint"] == request.audit_input_fingerprint
    assert report["product_name_source"] == request.product_name_source


def test_negative_list_category_does_not_depend_on_law_name_text() -> None:
    request = _pipeline_request(_request())
    negative_unit = replace(
        _unit(),
        law_name="其他检查",
        source_file="其他检查.md",
        category="负面清单检查",
    )

    def retriever(*args):
        return RegulationRetrievalOutcome(
            regulations=(),
            regulation_units=(negative_unit,),
            candidate_count=1,
        )

    def auditor(packages, concurrency, deadline, callback):
        package = tuple(packages)[0]
        return (RegulationAuditDecision(
            task_id=package.task_id,
            regulation_unit_id=package.regulation.regulation_unit_id,
            status=RegulationDecisionStatus.COMPLIANT,
            reasoning="产品条款符合要求。",
            suggestion="",
            regulation_evidence=(),
            product_evidence=(),
        ),)

    result = run_audit_pipeline(
        request,
        retriever=retriever,
        package_auditor=auditor,
    )

    assert build_report_data(result)["negative_list_result"] == "passed"


@pytest.mark.asyncio
async def test_v2_pipeline_failure_is_saved_as_one_incomplete_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved = []
    request = _request()

    def fail_pipeline(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(compliance_v2, "run_audit_pipeline", fail_pipeline)
    monkeypatch.setattr(
        compliance_v2,
        "save_compliance_report",
        lambda *args: saved.append(args),
    )

    response = await compliance_v2.check_document_v2_stream(request, user={})
    payloads = await _event_payloads(response)

    terminal = [item for item in payloads if item["type"] in {"done", "error"}]
    assert [item["type"] for item in terminal] == ["done"]
    assert terminal[0]["data"]["audit_status"] == "incomplete"
    assert terminal[0]["data"]["compliance_conclusion"] == "undetermined"
    assert terminal[0]["data"]["product_tags"]["line"] == "health"
    assert terminal[0]["data"]["product_tags"]["primary_subtype"] == "medical"
    assert len(saved) == 1
    assert saved[0][3] == "document"
    assert saved[0][4]["audit_status"] == "incomplete"
    assert saved[0][4]["product_tags"] == terminal[0]["data"]["product_tags"]


@pytest.mark.asyncio
async def test_v2_candidate_report_persists_with_database_mode_constraint(
    monkeypatch: pytest.MonkeyPatch,
    _patch_database: None,
) -> None:
    def fail_pipeline(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(compliance_v2, "run_audit_pipeline", fail_pipeline)

    response = await compliance_v2.check_document_v2_stream(
        _request("user-a"),
        user={"user_id": "user-a"},
    )
    payloads = await _event_payloads(response)

    terminal = [item for item in payloads if item["type"] in {"done", "error"}]
    assert [item["type"] for item in terminal] == ["done"]
    report = get_compliance_report(terminal[0]["data"]["report_id"])
    assert report is not None
    assert report["mode"] == "document"
    assert report["owner_user_id"] == "user-a"
    assert report["result"]["audit_status"] == "incomplete"


@pytest.mark.asyncio
async def test_v2_persistence_failure_emits_only_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_pipeline(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    def fail_save(*args):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(compliance_v2, "run_audit_pipeline", fail_pipeline)
    monkeypatch.setattr(compliance_v2, "save_compliance_report", fail_save)

    response = await compliance_v2.check_document_v2_stream(_request(), user={})
    payloads = await _event_payloads(response)

    terminal = [item for item in payloads if item["type"] in {"done", "error"}]
    assert terminal == [{
        "type": "error",
        "data": "报告生成或保存失败，审核结果未形成可信终态",
    }]


@pytest.mark.asyncio
async def test_v2_thread_start_failure_still_emits_one_incomplete_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved = []
    original_start = threading.Thread.start

    def fail_start(self):
        if self.name == "compliance-v2-audit":
            raise RuntimeError("thread resources exhausted")
        return original_start(self)

    monkeypatch.setattr(threading.Thread, "start", fail_start)
    monkeypatch.setattr(
        compliance_v2,
        "save_compliance_report",
        lambda *args: saved.append(args),
    )

    response = await compliance_v2.check_document_v2_stream(_request(), user={})
    payloads = await _event_payloads(response)

    terminal = [item for item in payloads if item["type"] in {"done", "error"}]
    assert [item["type"] for item in terminal] == ["done"]
    assert terminal[0]["data"]["audit_status"] == "incomplete"
    assert terminal[0]["data"]["failure_reasons"] == [
        "审核主链异常：审核主链无法启动：thread resources exhausted",
    ]
    assert len(saved) == 1


@pytest.mark.asyncio
async def test_v2_producer_watchdog_saves_one_incomplete_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = threading.Event()
    producer_finished = threading.Event()
    saved = []

    def hanging_pipeline(*args, **kwargs):
        release.wait(timeout=1)
        producer_finished.set()
        return None

    monkeypatch.setattr(
        compliance_v2,
        "AUDIT_TOTAL_DEADLINE_SECONDS",
        0.4,
    )
    monkeypatch.setattr(
        compliance_v2,
        "AUDIT_REPORT_PERSISTENCE_RESERVE_SECONDS",
        0.2,
    )
    monkeypatch.setattr(
        compliance_v2,
        "run_audit_pipeline",
        hanging_pipeline,
    )
    monkeypatch.setattr(
        compliance_v2,
        "save_compliance_report",
        lambda *args: saved.append(args),
    )

    response = await compliance_v2.check_document_v2_stream(_request(), user={})
    payloads = await _event_payloads(response)
    release.set()
    producer_finished.wait(timeout=0.2)

    terminal = [item for item in payloads if item["type"] in {"done", "error"}]
    assert [item["type"] for item in terminal] == ["done"]
    assert terminal[0]["data"]["audit_status"] == "incomplete"
    assert terminal[0]["data"]["compliance_conclusion"] == "undetermined"
    assert terminal[0]["data"]["failure_reasons"] == [
        "审核主链异常：审核主链超过端到端时间预算",
    ]
    assert terminal[0]["data"]["product_tags"]["line"] == "health"
    assert terminal[0]["data"]["product_tags"]["primary_subtype"] == "medical"
    assert len(saved) == 1
    assert saved[0][4]["audit_status"] == "incomplete"
    assert saved[0][4]["product_tags"] == terminal[0]["data"]["product_tags"]


@pytest.mark.asyncio
async def test_v2_waits_for_persistence_truth_before_terminal_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = threading.Event()
    persistence_started = threading.Event()
    persistence_finished = threading.Event()

    def fail_pipeline(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    def hanging_save(*args):
        persistence_started.set()
        release.wait(timeout=1)
        persistence_finished.set()

    monkeypatch.setattr(
        compliance_v2,
        "AUDIT_TOTAL_DEADLINE_SECONDS",
        0.3,
    )
    monkeypatch.setattr(
        compliance_v2,
        "AUDIT_REPORT_PERSISTENCE_RESERVE_SECONDS",
        0.15,
    )
    monkeypatch.setattr(compliance_v2, "run_audit_pipeline", fail_pipeline)
    monkeypatch.setattr(compliance_v2, "save_compliance_report", hanging_save)

    response = await compliance_v2.check_document_v2_stream(_request(), user={})
    consume_task = asyncio.create_task(_event_payloads(response))
    assert await asyncio.to_thread(persistence_started.wait, 0.2)
    await asyncio.sleep(0.2)
    assert not consume_task.done()
    release.set()
    payloads = await consume_task

    terminal = [item for item in payloads if item["type"] in {"done", "error"}]
    assert [item["type"] for item in terminal] == ["done"]
    assert persistence_finished.is_set()


def test_new_production_modules_do_not_import_legacy_rule_engine() -> None:
    project_root = Path(__file__).resolve().parents[2]
    for relative in (
        "lib/compliance/audit_pipeline.py",
        "lib/compliance/regulation_retrieval.py",
        "api/routers/compliance_v2.py",
    ):
        source = (project_root / relative).read_text(encoding="utf-8")
        imports = [
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        rendered = " ".join(ast.unparse(node) for node in imports)
        assert "rule_engine" not in rendered
        assert "lib.compliance.checker" not in rendered


def test_pipeline_request_domain_module_has_no_http_dependencies() -> None:
    module_path = (
        Path(__file__).parents[2]
        / "lib"
        / "compliance"
        / "pipeline_request.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }

    assert not any(
        module == "fastapi" or module.startswith("api.")
        for module in imported_modules
    )

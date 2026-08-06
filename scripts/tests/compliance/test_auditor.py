import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Dict, List

import pytest

from lib.common.compliance_audit import (
    AuditClauseSnapshot,
    RegulationAuditPackage,
    RegulationChunkSnapshot,
    RegulationDecisionStatus,
    RegulationUnitSnapshot,
    RoutedClause,
    RoutedClauseRelation,
)
from lib.common.product_tags import ProductTags
from lib.compliance.auditor import (
    _merge_segment_decisions,
    audit_regulation_package_batch,
    audit_regulation_package,
    audit_regulation_packages,
    build_audit_messages,
    split_audit_package,
)
from lib.llm.base import BaseLLMClient


class _Client(BaseLLMClient):
    def __init__(self, response: str, delay: float = 0.0):
        super().__init__("test")
        self.response = response
        self.delay = delay

    def _do_generate(self, prompt: str, **kwargs) -> str:
        return self.response

    def _do_chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        if self.delay:
            time.sleep(self.delay)
        return self.response

    def health_check(self) -> bool:
        return True


class _SegmentClient(BaseLLMClient):
    def __init__(self):
        super().__init__("test")
        self.calls = 0

    def _do_generate(self, prompt: str, **kwargs) -> str:
        return "{}"

    def _do_chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        self.calls += 1
        payload = json.loads(messages[1]["content"].split("审核包：\n", 1)[1])
        chunk = payload["regulation_unit"]["chunks"][0]
        clause = payload["product"]["clauses"][0]
        non_compliant = payload["task_id"].endswith(":segment:1")
        return json.dumps({
            "task_id": payload["task_id"],
            "regulation_unit_id": payload["regulation_unit"]["regulation_unit_id"],
            "status": "non_compliant" if non_compliant else "compliant",
            "reasoning": "分段判断",
            "suggestion": "修改" if non_compliant else "",
            "regulation_evidence": [{
                "evidence_id": chunk["chunk_id"],
                "quote": chunk["content"][:12],
            }],
            "product_evidence": ([{
                "evidence_id": clause["clause_id"],
                "quote": clause["text"][:12],
            }] if non_compliant else []),
            "applicability_dispute": False,
            "confidence": 0.9,
        }, ensure_ascii=False)

    def health_check(self) -> bool:
        return True


class _TaskAwareClient(BaseLLMClient):
    def __init__(self):
        super().__init__("test")

    def _do_generate(self, prompt: str, **kwargs) -> str:
        return "{}"

    def _do_chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        payload = json.loads(messages[1]["content"].split("审核包：\n", 1)[1])
        index = int(payload["task_id"].rsplit("-", 1)[1])
        time.sleep((2 - index) * 0.002)
        chunk = payload["regulation_unit"]["chunks"][0]
        clause = payload["product"]["clauses"][0]
        return json.dumps({
            "task_id": payload["task_id"],
            "regulation_unit_id": payload["regulation_unit"]["regulation_unit_id"],
            "status": "non_compliant",
            "reasoning": "稳定判断",
            "suggestion": "修改",
            "regulation_evidence": [{
                "evidence_id": chunk["chunk_id"],
                "quote": chunk["content"][:12],
            }],
            "product_evidence": [{
                "evidence_id": clause["clause_id"],
                "quote": clause["text"][:12],
            }],
            "applicability_dispute": False,
            "confidence": 0.9,
        }, ensure_ascii=False)

    def health_check(self) -> bool:
        return True


class _CloseFailureClient(_Client):
    def close(self) -> None:
        raise RuntimeError("close failed")


class _BatchClient(BaseLLMClient):
    def __init__(self, omit_first: str = ""):
        super().__init__("test")
        self.omit_first = omit_first
        self.calls = 0
        self.last_prompt = ""

    def _do_generate(self, prompt: str, **kwargs) -> str:
        return "{}"

    def _do_chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        self.calls += 1
        self.last_prompt = messages[1]["content"]
        payload = json.loads(messages[1]["content"].split("审核包：\n", 1)[1])
        results = []
        for task in payload["regulation_tasks"]:
            unit_id = task["regulation_unit"]["regulation_unit_id"]
            if self.calls == 1 and unit_id == self.omit_first:
                continue
            results.append({
                "task_id": task["task_id"],
                "regulation_unit_id": unit_id,
                "status": "insufficient_information",
                "reasoning": "产品条款不足以判断",
                "suggestion": "人工补充材料",
                "regulation_evidence": [],
                "product_evidence": [],
                "applicability_dispute": False,
                "confidence": 0.8,
            })
        return json.dumps({"results": results}, ensure_ascii=False)

    def health_check(self) -> bool:
        return True


class _FailingBatchClient(_BatchClient):
    def _do_chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        self.calls += 1
        raise RuntimeError("provider unavailable")


def _package(index: int = 0) -> RegulationAuditPackage:
    regulation = RegulationUnitSnapshot(
        regulation_unit_id=f"v5:law:{index}",
        kb_version="v5",
        law_name="测试法规",
        source_file="law.md",
        article_number="第一条",
        section_path="第一条",
        topics=("coverage.waiting_period",),
        chunks=(RegulationChunkSnapshot("r-1", "等待期不得超过180天。", 0),),
        applicability_status="applicable",
        applicability_reasons=("产品为健康险",),
    )
    clause = AuditClauseSnapshot(
        clause_id=f"c-{index}",
        number="2.1",
        title="等待期",
        text="本合同等待期为270天。",
        block_type="clause",
        topics=("coverage.waiting_period",),
    )
    return RegulationAuditPackage(
        task_id=f"task-{index}",
        input_index=index,
        product_name="测试医疗保险",
        product_tags=ProductTags(),
        regulation=regulation,
        clauses=(RoutedClause(
            clause, RoutedClauseRelation.DIRECT, ("主题精确匹配",),
        ),),
        facts=(),
    )


def test_batch_audit_requires_and_returns_every_unit() -> None:
    packages = (_package(0), _package(1), _package(2))
    client = _BatchClient()

    decisions = audit_regulation_package_batch(packages, client, 5)

    assert client.calls == 1
    assert [item.regulation_unit_id for item in decisions] == [
        "v5:law:0", "v5:law:1", "v5:law:2",
    ]


def test_audit_prompts_do_not_anchor_confidence_at_zero() -> None:
    from lib.compliance.auditor import build_batch_audit_messages

    assert '"confidence": 0.0' not in build_audit_messages(_package())[1]["content"]
    assert '"confidence": 0.0' not in build_batch_audit_messages(
        (_package(),),
    )[1]["content"]


def test_short_evidence_refs_map_back_to_real_ids() -> None:
    package = _package()
    payload = json.loads(
        build_audit_messages(package)[1]["content"].split("审核包：\n", 1)[1],
    )
    assert payload["regulation_unit"]["chunks"][0]["evidence_ref"] == "R001"
    assert payload["product"]["clauses"][0]["evidence_ref"] == "P001"
    response = json.dumps({
        "task_id": package.task_id,
        "regulation_unit_id": package.regulation.regulation_unit_id,
        "status": "non_compliant",
        "reasoning": "等待期超过法规上限。",
        "suggestion": "修改等待期。",
        "regulation_evidence": [{
            "evidence_id": "R001",
            "quote": package.regulation.chunks[0].content[:12],
        }],
        "product_evidence": [{
            "evidence_id": "P001",
            "quote": package.clauses[0].clause.text,
        }],
        "confidence": 0.95,
    }, ensure_ascii=False)

    decision = audit_regulation_package(package, _Client(response), 5)

    assert decision.regulation_evidence[0].chunk_id == "r-1"
    assert decision.product_evidence[0].clause_id == "c-0"


def test_batch_audit_reasks_only_missing_units() -> None:
    packages = (_package(0), _package(1), _package(2))
    client = _BatchClient(omit_first="v5:law:1")
    traces = []

    decisions = audit_regulation_package_batch(
        packages, client, 5, on_attempt=traces.append,
    )

    assert client.calls == 2
    assert len(decisions) == 3
    assert all(not item.incomplete for item in decisions)
    assert traces[0].attempt == 1
    assert any("v5:law:1" in error for error in traces[0].validation_errors)
    assert "上一轮回答未通过程序校验" in client.last_prompt


def test_batch_audit_rejects_cross_document_group() -> None:
    packages = (_package(0), replace(
        _package(1),
        regulation=replace(_package(1).regulation, source_file="other.md"),
    ))

    try:
        audit_regulation_package_batch(packages, _BatchClient(), 5)
    except ValueError as exc:
        assert "同一法规文件" in str(exc)
    else:
        raise AssertionError("跨法规文件批次必须被拒绝")


def test_batch_audit_rejects_different_product_context() -> None:
    packages = (
        _package(0),
        replace(_package(1), product_name="另一份产品条款"),
    )

    with pytest.raises(ValueError, match="同一份产品事实"):
        audit_regulation_package_batch(packages, _BatchClient(), 5)


def test_batch_provider_failure_does_not_fan_out_to_single_calls() -> None:
    client = _FailingBatchClient()

    decisions = audit_regulation_package_batch(
        (_package(0), _package(1), _package(2)), client, 5,
    )

    assert client.calls == 2
    assert {item.error_code for item in decisions} == {"batch_llm_call_failed"}
    assert all(item.incomplete for item in decisions)


def _response(package: RegulationAuditPackage, **overrides) -> str:
    payload = {
        "task_id": package.task_id,
        "regulation_unit_id": package.regulation.regulation_unit_id,
        "status": "non_compliant",
        "reasoning": "等待期超过法规上限。",
        "suggestion": "修改为不超过180天。",
        "regulation_evidence": [
            {"evidence_id": "r-1", "quote": "等待期不得超过180天"}
        ],
        "product_evidence": [
            {"evidence_id": package.clauses[0].clause.clause_id, "quote": "等待期为270天"}
        ],
        "applicability_dispute": False,
        "confidence": 0.99,
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def test_prompt_contains_only_one_regulation_unit() -> None:
    package = _package()
    messages = build_audit_messages(package)
    assert len(messages) == 2
    assert package.regulation.regulation_unit_id in messages[1]["content"]
    assert package.clauses[0].clause.clause_id in messages[1]["content"]
    assert "风险触发标签只表示该法规必须进入审核" in messages[0]["content"]


def test_valid_non_compliance_requires_both_evidence_types() -> None:
    package = _package()
    decision = audit_regulation_package(package, _Client(_response(package)), 10)
    assert decision.status is RegulationDecisionStatus.NON_COMPLIANT
    assert decision.regulation_evidence[0].chunk_id == "r-1"
    assert decision.product_evidence[0].clause_id == "c-0"
    assert not decision.incomplete


def test_product_name_cannot_prove_non_name_regulation() -> None:
    package = _package()
    response = _response(package, product_evidence=[{
        "evidence_id": "product-name",
        "quote": "测试医疗保险",
    }])

    decision = audit_regulation_package(package, _Client(response), 10)

    assert decision.status is RegulationDecisionStatus.MANUAL_REVIEW
    assert decision.error_code == "invalid_structured_output"


def test_product_name_can_prove_contract_name_regulation() -> None:
    package = _package()
    package = replace(
        package,
        regulation=replace(package.regulation, topics=("contract.name",)),
    )
    response = _response(package, product_evidence=[{
        "evidence_id": "product-name",
        "quote": "测试医疗保险",
    }])

    decision = audit_regulation_package(package, _Client(response), 10)

    assert decision.status is RegulationDecisionStatus.NON_COMPLIANT
    assert decision.product_evidence[0].source_kind == "product_name"


def test_missing_product_evidence_downgrades_to_manual_review() -> None:
    package = _package()
    response = _response(package, product_evidence=[])
    decision = audit_regulation_package(package, _Client(response), 10)
    assert decision.status is RegulationDecisionStatus.MANUAL_REVIEW
    assert decision.incomplete
    assert decision.error_code == "missing_non_compliance_evidence"


def test_compliant_without_product_evidence_is_not_green() -> None:
    package = _package()
    response = _response(
        package,
        status="compliant",
        suggestion="",
        product_evidence=[],
    )

    decision = audit_regulation_package(package, _Client(response), 10)

    assert decision.status is RegulationDecisionStatus.MANUAL_REVIEW
    assert decision.incomplete
    assert decision.error_code == "missing_compliance_evidence"


def test_compliant_cannot_use_clause_title_as_body_evidence() -> None:
    package = _package()
    response = _response(
        package,
        status="compliant",
        suggestion="",
        product_evidence=[{
            "evidence_id": package.clauses[0].clause.clause_id,
            "quote": "等待期",
        }],
    )

    decision = audit_regulation_package(package, _Client(response), 10)

    assert decision.status is RegulationDecisionStatus.MANUAL_REVIEW
    assert decision.incomplete
    assert decision.error_code == "invalid_structured_output"


def test_low_confidence_cannot_form_automated_conclusion() -> None:
    package = _package()
    response = _response(package, status="compliant", confidence=0.0)

    decision = audit_regulation_package(package, _Client(response), 10)

    assert decision.status is RegulationDecisionStatus.MANUAL_REVIEW
    assert not decision.incomplete
    assert decision.error_code == "low_model_confidence"


def test_fabricated_quote_is_rejected() -> None:
    package = _package()
    response = _response(package, regulation_evidence=[
        {"evidence_id": "r-1", "quote": "不存在的法规摘录"},
    ])
    decision = audit_regulation_package(package, _Client(response), 10)
    assert decision.status is RegulationDecisionStatus.MANUAL_REVIEW
    assert decision.error_code == "invalid_structured_output"


def test_empty_evidence_quotes_are_rejected() -> None:
    package = _package()
    response = _response(
        package,
        regulation_evidence=[{"evidence_id": "r-1", "quote": ""}],
        product_evidence=[{
            "evidence_id": package.clauses[0].clause.clause_id,
            "quote": " ",
        }],
    )

    decision = audit_regulation_package(package, _Client(response), 10)

    assert decision.status is RegulationDecisionStatus.MANUAL_REVIEW
    assert decision.incomplete
    assert decision.error_code == "invalid_structured_output"


def test_whitespace_only_reasoning_is_rejected() -> None:
    package = _package()
    response = _response(package, reasoning=" ")

    decision = audit_regulation_package(package, _Client(response), 10)

    assert decision.status is RegulationDecisionStatus.MANUAL_REVIEW
    assert decision.error_code == "invalid_structured_output"


def test_invalid_json_is_explicit_incomplete() -> None:
    package = _package()
    decision = audit_regulation_package(package, _Client("not json"), 10)
    assert decision.status is RegulationDecisionStatus.MANUAL_REVIEW
    assert decision.incomplete


def test_applicability_dispute_cannot_become_non_compliant() -> None:
    package = _package()
    response = _response(package, applicability_dispute=True)
    decision = audit_regulation_package(package, _Client(response), 10)
    assert decision.status is RegulationDecisionStatus.MANUAL_REVIEW
    assert decision.applicability_dispute


def test_concurrent_results_keep_input_order_and_evidence() -> None:
    packages = (_package(0), _package(1), _package(2))
    responses = {
        package.task_id: _response(package) for package in packages
    }
    clients = iter([
        _Client(responses["task-0"], 0.03),
        _Client(responses["task-1"], 0.01),
        _Client(responses["task-2"], 0.0),
    ])
    decisions = audit_regulation_packages(
        packages,
        client_factory=lambda: next(clients),
        max_concurrency=3,
        deadline_seconds=2,
    )
    assert [item.task_id for item in decisions] == ["task-0", "task-1", "task-2"]
    assert [item.product_evidence[0].clause_id for item in decisions] == [
        "c-0", "c-1", "c-2",
    ]


def test_concurrent_repeated_runs_keep_identical_decisions_and_evidence() -> None:
    packages = (_package(0), _package(1), _package(2))
    signatures = []
    for _ in range(3):
        decisions = audit_regulation_packages(
            packages,
            client_factory=_TaskAwareClient,
            max_concurrency=3,
            deadline_seconds=2,
        )
        signatures.append(tuple(
            (
                decision.task_id,
                decision.status,
                tuple(item.chunk_id for item in decision.regulation_evidence),
                tuple(item.clause_id for item in decision.product_evidence),
            )
            for decision in decisions
        ))

    assert signatures[0] == signatures[1] == signatures[2]


def test_global_model_slots_cap_concurrency_across_audit_requests(
    monkeypatch,
) -> None:
    import lib.compliance.auditor as auditor_module

    state = {"active": 0, "peak": 0}
    lock = threading.Lock()

    class TrackingClient(_TaskAwareClient):
        def _do_chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
            with lock:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
            try:
                time.sleep(0.03)
                return super()._do_chat(messages, **kwargs)
            finally:
                with lock:
                    state["active"] -= 1

    monkeypatch.setattr(
        auditor_module,
        "_GLOBAL_AUDIT_SLOTS",
        threading.BoundedSemaphore(1),
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                audit_regulation_packages,
                (_package(index),),
                TrackingClient,
                1,
                2,
            )
            for index in range(2)
        ]
        decisions = [future.result() for future in futures]

    assert state["peak"] == 1
    assert all(
        result[0].status is RegulationDecisionStatus.NON_COMPLIANT
        for result in decisions
    )


def test_deadline_marks_unfinished_unit_incomplete() -> None:
    package = _package()
    decisions = audit_regulation_packages(
        (package,),
        client_factory=lambda: _Client(_response(package), 0.2),
        max_concurrency=1,
        deadline_seconds=0.01,
    )
    assert decisions[0].incomplete
    assert decisions[0].error_code == "audit_deadline_exceeded"


def test_oversized_unit_splits_at_clause_boundaries_and_merges_by_priority() -> None:
    package = _package()
    clauses = tuple(
        replace(
            package.clauses[0],
            clause=replace(
                package.clauses[0].clause,
                clause_id=f"large-clause-{index}",
                text=f"第{index}段" + "产品条款内容" * 1200,
            ),
        )
        for index in range(30)
    )
    oversized = replace(package, clauses=clauses)
    segments = split_audit_package(oversized, max_prompt_length=30_000)

    assert len(segments) > 1
    assert all(segment.task_id.startswith(f"{package.task_id}:segment:") for segment in segments)
    assert {
        routed.clause.clause_id
        for segment in segments
        for routed in segment.clauses
        if routed.submitted
    } == {routed.clause.clause_id for routed in clauses}

    client = _SegmentClient()
    decision = audit_regulation_package(oversized, client, timeout_seconds=10)

    assert client.calls > 1
    assert decision.task_id == package.task_id
    assert decision.status is RegulationDecisionStatus.NON_COMPLIANT
    assert decision.product_evidence


def test_segment_applicability_dispute_overrides_non_compliance() -> None:
    package = _package()
    non_compliant = audit_regulation_package(
        package,
        _Client(_response(package)),
        10,
    )
    disputed = replace(
        non_compliant,
        status=RegulationDecisionStatus.MANUAL_REVIEW,
        applicability_dispute=True,
    )

    merged = _merge_segment_decisions(
        package,
        (non_compliant, disputed),
    )

    assert merged.status is RegulationDecisionStatus.MANUAL_REVIEW
    assert merged.applicability_dispute


def test_progress_callback_receives_each_completed_unit() -> None:
    packages = (_package(0), _package(1))
    responses = iter(_Client(_response(package)) for package in packages)
    progress = []

    decisions = audit_regulation_packages(
        packages,
        client_factory=lambda: next(responses),
        max_concurrency=1,
        deadline_seconds=2,
        on_decision=lambda decision, completed, total: progress.append(
            (decision.task_id, completed, total)
        ),
    )

    assert len(decisions) == 2
    assert progress == [
        ("task-0", 1, 2),
        ("task-1", 2, 2),
    ]


def test_client_initialization_failure_is_explicit_incomplete() -> None:
    package = _package()

    def fail_factory() -> BaseLLMClient:
        raise RuntimeError("provider unavailable")

    decisions = audit_regulation_packages(
        (package,),
        client_factory=fail_factory,
        max_concurrency=1,
        deadline_seconds=2,
    )

    assert decisions[0].incomplete
    assert decisions[0].error_code == "llm_client_initialization_failed"


def test_client_close_failure_does_not_override_completed_decision() -> None:
    package = _package()

    decisions = audit_regulation_packages(
        (package,),
        client_factory=lambda: _CloseFailureClient(_response(package)),
        max_concurrency=1,
        deadline_seconds=2,
    )

    assert decisions[0].status is RegulationDecisionStatus.NON_COMPLIANT
    assert not decisions[0].incomplete

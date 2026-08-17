import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import Dict, List

import pytest

from lib.common.compliance_audit import (
    AuditClauseSnapshot,
    BatchAuditAttemptTrace,
    FactTruth,
    ProductFact,
    ProductFactEvidence,
    ProductEvidenceCandidate,
    ProductEvidenceStrength,
    RegulationAuditPackage,
    RegulationChunkSnapshot,
    RegulationDecisionStatus,
    RegulationObligation,
    RegulationObligationAssessment,
    RegulationObligationStatus,
    RegulationTriggerSpec,
    RegulationUnitSnapshot,
    RoutedClause,
    RoutedClauseRelation,
    TriggerEvaluation,
    TriggerFactName,
    TriggerOperator,
    TriggerStatus,
)
from lib.common.product_tags import ProductTags
from lib.compliance.auditor import (
    _merge_segment_decisions,
    _request_batch_decisions,
    audit_regulation_package_batch,
    audit_regulation_package,
    audit_regulation_packages,
    build_audit_messages,
    build_batch_audit_messages,
    split_audit_package,
)
from lib.llm.base import BaseLLMClient
from lib.llm.call_budget import (
    CallBudgetSnapshot,
    CallTokenBudgetExceededError,
)


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


class _TimeoutRecordingClient(_Client):
    def __init__(self, response: str):
        super().__init__(response)
        self.request_timeouts: List[float] = []

    def _do_chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        timeout = kwargs.get("timeout")
        if not isinstance(timeout, (int, float)):
            raise AssertionError("audit request must include a numeric timeout")
        self.request_timeouts.append(float(timeout))
        return self.response


class _SequenceClient(BaseLLMClient):
    def __init__(self, responses: List[str]):
        super().__init__("test")
        self.responses = list(responses)
        self.prompts: List[str] = []
        self.calls = 0

    def _do_generate(self, prompt: str, **kwargs) -> str:
        return "{}"

    def _do_chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        self.calls += 1
        self.prompts.append(messages[1]["content"])
        return self.responses.pop(0)

    def health_check(self) -> bool:
        return True


class _BudgetSequenceClient(BaseLLMClient):
    def __init__(self, outcomes: List[object]):
        super().__init__("test")
        self.outcomes = list(outcomes)
        self.calls = 0

    def _do_generate(self, prompt: str, **kwargs) -> str:
        return "{}"

    def _do_chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if not isinstance(outcome, str):
            raise AssertionError("test outcome must be a string or exception")
        return outcome

    def health_check(self) -> bool:
        return True


def _budget_error() -> CallTokenBudgetExceededError:
    return CallTokenBudgetExceededError(
        CallBudgetSnapshot(
            deadline=10.0,
            observed_at=9.0,
            max_total_tokens=100,
            consumed_tokens=90,
            reserved_tokens=0,
            remaining_tokens=10,
            max_physical_calls=10,
            physical_calls=1,
            active_leases=0,
        ),
        requested_tokens=20,
    )


class _SegmentClient(BaseLLMClient):
    def __init__(self):
        super().__init__("test")
        self.calls = 0
        self.task_ids: List[str] = []

    def _do_generate(self, prompt: str, **kwargs) -> str:
        return "{}"

    def _do_chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        self.calls += 1
        payload = json.loads(messages[1]["content"].split("审核包：\n", 1)[1])
        self.task_ids.append(payload["task_id"])
        chunk = payload["regulation_unit"]["chunks"][0]
        product_evidence_id = payload["product"]["product_evidence_catalog"][0][
            "evidence_id"
        ]
        non_compliant = payload["task_id"].endswith(":segment:1")
        return json.dumps({
            "task_id": payload["task_id"],
            "regulation_unit_id": payload["regulation_unit"]["regulation_unit_id"],
            "status": "non_compliant" if non_compliant else "compliant",
            "reasoning": "分段判断",
            "suggestion": "修改" if non_compliant else "",
            "regulation_evidence_ids": [chunk["evidence_id"]],
            "product_evidence_ids": (
                [product_evidence_id] if non_compliant else []
            ),
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
        product_evidence_id = payload["product"]["product_evidence_catalog"][0][
            "evidence_id"
        ]
        return json.dumps({
            "task_id": payload["task_id"],
            "regulation_unit_id": payload["regulation_unit"]["regulation_unit_id"],
            "status": "non_compliant",
            "reasoning": "稳定判断",
            "suggestion": "修改",
            "regulation_evidence_ids": [chunk["evidence_id"]],
            "product_evidence_ids": [product_evidence_id],
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
                "regulation_evidence_ids": [],
                "product_evidence_ids": [],
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
        product_evidence_candidates=(ProductEvidenceCandidate(
            clause_id=clause.clause_id,
            strength=ProductEvidenceStrength.STRONG,
            source_layers=("exact_topic",),
        ),),
    )


def _same_product_packages(count: int) -> tuple[RegulationAuditPackage, ...]:
    """批量审核单元共享同一份产品条款，仅法规不同。"""
    shared = _package(0)
    return tuple(
        replace(
            _package(index),
            clauses=shared.clauses,
            facts=shared.facts,
            product_facts=shared.product_facts,
            product_evidence_candidates=shared.product_evidence_candidates,
        )
        for index in range(count)
    )


def _package_with_unsubmitted(count: int = 1) -> RegulationAuditPackage:
    package = _package()
    initial = replace(
        package.clauses[0],
        clause=replace(
            package.clauses[0].clause,
            text="等待期的具体约定详见补充条款。",
        ),
    )
    unsubmitted = tuple(
        RoutedClause(
            clause=AuditClauseSnapshot(
                clause_id=f"hidden-{index}",
                number=f"3.{index}",
                title=f"等待期补充约定{index}",
                text=f"本合同补充等待期为{270 + index}天。",
                block_type="clause",
                topics=("coverage.waiting_period",),
                hierarchy_level=2,
                parent_number="3",
                ancestor_numbers=("3",),
                hierarchy_path=f"3 > 3.{index}",
            ),
            relation=RoutedClauseRelation.UNKNOWN,
            reasons=("首轮未命中",),
            submitted=False,
        )
        for index in range(1, count + 1)
    )
    return replace(
        package,
        clauses=(initial, *unsubmitted),
        product_evidence_candidates=(
            *package.product_evidence_candidates,
            *(
                ProductEvidenceCandidate(
                    clause_id=item.clause.clause_id,
                    strength=ProductEvidenceStrength.STRONG,
                    source_layers=("exact_topic",),
                )
                for item in unsubmitted
            ),
        ),
    )


def _context_request_response(
    package: RegulationAuditPackage,
    refs: List[str],
    *,
    status: str = "insufficient_information",
) -> str:
    return json.dumps({
        "task_id": package.task_id,
        "regulation_unit_id": package.regulation.regulation_unit_id,
        "status": status,
        "reasoning": "需要补充目录中的相关条款正文。",
        "suggestion": "",
        "regulation_evidence_ids": [],
        "product_evidence_ids": [],
        "applicability_dispute": False,
        "confidence": 0.8,
        "needs_more_context": True,
        "requested_outline_refs": refs,
    }, ensure_ascii=False)


def _batch_insufficient_response(
    packages: tuple[RegulationAuditPackage, ...],
    omitted_unit_ids: tuple[str, ...] = (),
) -> str:
    omitted = frozenset(omitted_unit_ids)
    return json.dumps({
        "results": [
            {
                "task_id": package.task_id,
                "regulation_unit_id": package.regulation.regulation_unit_id,
                "status": "insufficient_information",
                "reasoning": "产品条款不足以判断",
                "suggestion": "人工补充材料",
                "regulation_evidence_ids": [],
                "product_evidence_ids": [],
                "applicability_dispute": False,
                "confidence": 0.8,
            }
            for package in packages
            if package.regulation.regulation_unit_id not in omitted
        ]
    }, ensure_ascii=False)


def test_single_audit_budget_rejection_is_explicit_incomplete() -> None:
    package = _package()
    client = _BudgetSequenceClient([_budget_error()])

    decision = audit_regulation_package(package, client, 5)

    assert client.calls == 1
    assert decision.status is RegulationDecisionStatus.MANUAL_REVIEW
    assert decision.incomplete
    assert decision.error_code == "audit_budget_exhausted"


def test_context_expansion_budget_rejection_does_not_retry() -> None:
    package = _package_with_unsubmitted()
    client = _BudgetSequenceClient([
        _context_request_response(package, ["O002"]),
        _budget_error(),
    ])

    decision = audit_regulation_package(package, client, 5)

    assert client.calls == 2
    assert decision.incomplete
    assert decision.error_code == "audit_budget_exhausted"


def test_batch_initial_budget_rejection_does_not_fan_out() -> None:
    packages = _same_product_packages(3)
    client = _BudgetSequenceClient([_budget_error()])

    decisions = audit_regulation_package_batch(packages, client, 5)

    assert client.calls == 1
    assert len(decisions) == 3
    assert all(item.incomplete for item in decisions)
    assert all(item.error_code == "audit_budget_exhausted" for item in decisions)


def test_batch_repair_budget_rejection_keeps_accepted_and_stops_fanout() -> None:
    packages = _same_product_packages(3)
    omitted = packages[1].regulation.regulation_unit_id
    client = _BudgetSequenceClient([
        _batch_insufficient_response(packages, (omitted,)),
        _budget_error(),
    ])

    decisions = audit_regulation_package_batch(packages, client, 5)

    assert client.calls == 2
    by_unit = {item.regulation_unit_id: item for item in decisions}
    assert not by_unit[packages[0].regulation.regulation_unit_id].incomplete
    assert not by_unit[packages[2].regulation.regulation_unit_id].incomplete
    assert by_unit[omitted].incomplete
    assert by_unit[omitted].error_code == "audit_budget_exhausted"


def test_batch_repairs_multiple_invalid_units_one_at_a_time() -> None:
    packages = _same_product_packages(3)
    first_unit = packages[0].regulation.regulation_unit_id
    second_unit = packages[1].regulation.regulation_unit_id
    client = _SequenceClient([
        _batch_insufficient_response(packages, (first_unit, second_unit)),
        _batch_insufficient_response((packages[0],)),
        _batch_insufficient_response((packages[1],)),
    ])
    traces: List[BatchAuditAttemptTrace] = []

    decisions = audit_regulation_package_batch(
        packages, client, 5, on_attempt=traces.append,
    )

    assert client.calls == 3
    assert all(not decision.incomplete for decision in decisions)
    assert [trace.requested_unit_ids for trace in traces] == [
        tuple(package.regulation.regulation_unit_id for package in packages),
        (first_unit,),
        (second_unit,),
    ]
    assert [trace.attempt for trace in traces] == [1, 2, 2]


def test_first_unit_repair_budget_rejection_stops_later_repairs() -> None:
    packages = _same_product_packages(3)
    first_unit = packages[0].regulation.regulation_unit_id
    second_unit = packages[1].regulation.regulation_unit_id
    client = _BudgetSequenceClient([
        _batch_insufficient_response(packages, (first_unit, second_unit)),
        _budget_error(),
        _batch_insufficient_response((packages[1],)),
    ])

    decisions = audit_regulation_package_batch(packages, client, 5)

    assert client.calls == 2
    by_unit = {item.regulation_unit_id: item for item in decisions}
    assert by_unit[first_unit].error_code == "audit_budget_exhausted"
    assert by_unit[second_unit].error_code == "audit_budget_exhausted"
    assert not by_unit[packages[2].regulation.regulation_unit_id].incomplete


def test_first_single_fallback_budget_rejection_stops_later_fallbacks() -> None:
    packages = _same_product_packages(3)
    first_unit = packages[0].regulation.regulation_unit_id
    second_unit = packages[1].regulation.regulation_unit_id
    client = _BudgetSequenceClient([
        _batch_insufficient_response(packages, (first_unit, second_unit)),
        _batch_insufficient_response((packages[0],), (first_unit,)),
        _batch_insufficient_response((packages[1],), (second_unit,)),
        _budget_error(),
        _batch_insufficient_response((packages[1],)),
    ])

    decisions = audit_regulation_package_batch(packages, client, 5)

    assert client.calls == 4
    by_unit = {item.regulation_unit_id: item for item in decisions}
    assert by_unit[first_unit].error_code == "audit_budget_exhausted"
    assert by_unit[second_unit].error_code == "audit_budget_exhausted"
    assert not by_unit[packages[2].regulation.regulation_unit_id].incomplete


def test_segment_budget_rejection_stops_later_segments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import lib.compliance.auditor as auditor_module

    package = _package()
    segments = (
        replace(package, task_id=f"{package.task_id}:segment:1"),
        replace(package, task_id=f"{package.task_id}:segment:2"),
    )
    monkeypatch.setattr(
        auditor_module,
        "split_audit_package",
        lambda _package, **_kwargs: segments,
    )
    client = _BudgetSequenceClient([_budget_error()])

    decision = audit_regulation_package(package, client, 5)

    assert client.calls == 1
    assert decision.incomplete
    assert decision.error_code == "audit_budget_exhausted"


def test_obligation_mode_fails_closed_before_unsafe_segment_merge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import lib.compliance.auditor as auditor_module

    package = _obligation_package()
    segments = (
        replace(package, task_id=f"{package.task_id}:segment:1"),
        replace(package, task_id=f"{package.task_id}:segment:2"),
    )
    monkeypatch.setattr(
        auditor_module,
        "split_audit_package",
        lambda _package, **_kwargs: segments,
    )
    client = _BudgetSequenceClient([])

    decision = audit_regulation_package(package, client, 5)

    assert client.calls == 0
    assert decision.status is RegulationDecisionStatus.MANUAL_REVIEW
    assert decision.incomplete
    assert decision.error_code == "obligation_segmentation_unsupported"
    assert decision.obligation_assessments == ()


def test_batch_audit_requires_and_returns_every_unit() -> None:
    packages = _same_product_packages(3)
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


def test_single_prompt_uses_task_scoped_id_only_evidence() -> None:
    package = _package()
    payload = json.loads(
        build_audit_messages(package)[1]["content"].split("审核包：\n", 1)[1],
    )
    prompt = build_audit_messages(package)[1]["content"]

    assert payload["evidence_protocol_version"] == "task-scoped-evidence-id-v1"
    assert payload["regulation_unit"]["chunks"][0]["evidence_id"] == (
        "U0001-R001"
    )
    assert payload["product"]["clauses"][0]["context_ref"] == "C001"
    assert "evidence_id" not in payload["product"]["clauses"][0]
    assert payload["product"]["product_evidence_catalog"] == [{
        "evidence_id": "U0001-P001",
        "context_ref": "C001",
        "clause_id": "c-0",
        "strength": "strong",
        "source_layers": ["exact_topic"],
    }]
    assert payload["product"]["name_evidence_id"] is None
    assert '"regulation_evidence_ids"' in prompt
    assert '"product_evidence_ids"' in prompt
    assert '"quote": "<逐字摘录>"' not in prompt


def test_id_only_response_backfills_complete_canonical_sources() -> None:
    package = _package()

    decision = audit_regulation_package(package, _Client(_response(package)), 5)

    assert decision.regulation_evidence[0].chunk_id == "r-1"
    assert decision.regulation_evidence[0].quote == (
        package.regulation.chunks[0].content
    )
    assert decision.product_evidence[0].clause_id == "c-0"
    assert decision.product_evidence[0].quote == package.clauses[0].clause.text


@pytest.mark.parametrize(
    "candidates",
    [
        (),
        (ProductEvidenceCandidate(
            clause_id="c-0",
            strength=ProductEvidenceStrength.WEAK,
            source_layers=("bm25",),
        ),),
    ],
)
def test_context_without_strong_candidate_never_receives_product_id(
    candidates,
) -> None:
    package = replace(_package(), product_evidence_candidates=candidates)
    payload = json.loads(
        build_audit_messages(package)[1]["content"].split("审核包：\n", 1)[1]
    )

    assert payload["product"]["clauses"][0]["context_ref"] == "C001"
    assert payload["product"]["product_evidence_catalog"] == []
    decision = audit_regulation_package(
        package,
        _Client(_response(package, product_evidence_ids=["U0001-P001"])),
        5,
    )
    assert decision.error_code == "invalid_structured_output"
    assert "无效产品证据ID" in decision.reasoning


def test_exact_scoped_legacy_fields_are_backfilled_without_quote_rebinding() -> None:
    package = _package()
    response = _response(
        package,
        regulation_evidence=[{
            "evidence_ref": "U0001-R001",
            "quote": "等待期不得超过180天",
        }],
        product_evidence=[{
            "evidence_id": "U0001-P001",
            "quote": "等待期为270天",
        }],
    )

    decision = audit_regulation_package(
        package, _Client(response), 5,
    )

    assert decision.status is RegulationDecisionStatus.NON_COMPLIANT
    assert decision.regulation_evidence[0].quote == "等待期不得超过180天。"
    assert decision.product_evidence[0].quote == "本合同等待期为270天。"


def test_exact_legacy_id_with_foreign_quote_is_rejected_without_rebinding() -> None:
    package = _package()
    response = _response(
        package,
        regulation_evidence=[{
            "evidence_id": "U0001-R001",
            "quote": "当前法规中不存在的摘录",
        }],
    )

    decision = audit_regulation_package(package, _Client(response), 5)

    assert decision.error_code == "invalid_structured_output"
    assert "不同源" in decision.reasoning


def test_wrong_evidence_id_is_not_repaired_by_matching_quote() -> None:
    package = _package()
    response = _response(
        package,
        regulation_evidence=[{
            "evidence_id": "regulation-placeholder",
            "quote": "等待期不得超过180天",
        }],
        product_evidence=[{
            "evidence_id": "product-placeholder",
            "quote": "等待期为270天",
        }],
    )

    decision = audit_regulation_package(package, _Client(response), 5)

    assert decision.status is RegulationDecisionStatus.MANUAL_REVIEW
    assert decision.error_code == "invalid_structured_output"
    assert "精确证据ID" in decision.reasoning


def test_unknown_task_scoped_evidence_id_is_rejected() -> None:
    package = _package()
    response = _response(
        package,
        regulation_evidence_ids=["U0001-R999"],
    )

    decision = audit_regulation_package(package, _Client(response), 5)

    assert decision.error_code == "invalid_structured_output"
    assert "无效法规证据ID" in decision.reasoning


def test_duplicate_or_excessive_evidence_ids_are_rejected() -> None:
    package = _package()
    duplicate = _response(
        package,
        regulation_evidence_ids=["U0001-R001", "U0001-R001"],
    )
    excessive = _response(
        package,
        regulation_evidence_ids=[f"U0001-R{index:03d}" for index in range(1, 10)],
    )
    decisions = (
        audit_regulation_package(package, _Client(duplicate), 5),
        audit_regulation_package(package, _Client(excessive), 5),
    )

    assert all(item.error_code == "invalid_structured_output" for item in decisions)
    assert "不得重复" in decisions[0].reasoning


def test_id_only_validation_rejects_cross_domain_ids() -> None:
    package = _package()
    regulation_uses_product_id = _response(
        package,
        regulation_evidence_ids=["U0001-P001"],
    )
    product_uses_regulation_id = _response(
        package,
        product_evidence_ids=["U0001-R001"],
    )

    decisions = (
        audit_regulation_package(package, _Client(regulation_uses_product_id), 5),
        audit_regulation_package(package, _Client(product_uses_regulation_id), 5),
    )

    assert all(
        decision.error_code == "invalid_structured_output"
        for decision in decisions
    )
    assert "不得引用产品证据ID" in decisions[0].reasoning
    assert "不得引用法规证据ID" in decisions[1].reasoning


def test_unoffered_product_name_id_is_rejected() -> None:
    package = replace(
        _package(), product_name="测试医疗保险",
    )
    response = _response(package, product_evidence_ids=["U0001-PNAME"])

    decision = audit_regulation_package(package, _Client(response), 5)

    assert decision.error_code == "invalid_structured_output"
    assert "不允许使用产品名称" in decision.reasoning


def test_new_and_legacy_evidence_fields_cannot_be_mixed() -> None:
    package = _package()
    response = json.loads(_response(package))
    response["regulation_evidence"] = [{
        "evidence_id": "U0001-R001",
        "quote": "等待期不得超过180天",
    }]

    decision = audit_regulation_package(
        package,
        _Client(json.dumps(response, ensure_ascii=False)),
        5,
    )

    assert decision.error_code == "invalid_structured_output"
    assert "不得同时返回" in decision.reasoning


def test_batch_uses_globally_unique_task_scoped_evidence_ids() -> None:
    first, second = _same_product_packages(2)
    first = replace(first, regulation=replace(
        first.regulation,
        chunks=(RegulationChunkSnapshot(
            "r-first", "等待期不得超过180天。", 0,
        ),),
    ))
    second = replace(second, regulation=replace(
        second.regulation,
        chunks=(RegulationChunkSnapshot(
            "r-second", "等待期不得超过90天。", 0,
        ),),
    ))
    prompt = build_batch_audit_messages((first, second))[1]["content"]
    payload = json.loads(prompt.split("审核包：\n", 1)[1])
    assert payload["evidence_protocol_version"] == "task-scoped-evidence-id-v1"
    assert '"quote"' not in prompt.split("审核包：\n", 1)[0]
    assert payload["product"]["clauses"][0]["context_ref"] == "C001"
    assert payload["product"]["clauses"][0].get("evidence_id") is None
    assert [
        task["regulation_unit"]["chunks"][0]["evidence_id"]
        for task in payload["regulation_tasks"]
    ] == ["U0001-R001", "U0002-R001"]
    assert [
        task["product_evidence_catalog"][0]["evidence_id"]
        for task in payload["regulation_tasks"]
    ] == ["U0001-P001", "U0002-P001"]
    response = {
        "results": [
            {
                "task_id": package.task_id,
                "regulation_unit_id": package.regulation.regulation_unit_id,
                "status": "non_compliant",
                "reasoning": "等待期超过法规上限。",
                "suggestion": "修改等待期。",
                "regulation_evidence_ids": [
                    f"U{package.input_index + 1:04d}-R001"
                ],
                "product_evidence_ids": [
                    f"U{package.input_index + 1:04d}-P001"
                ],
                "confidence": 0.95,
            }
            for package in (first, second)
        ],
    }

    result = _request_batch_decisions(
        (first, second),
        _Client(json.dumps(response, ensure_ascii=False)),
        5,
        attempt=1,
    )

    assert result.trace.validation_errors == ()
    assert result.decisions[first.regulation.regulation_unit_id].regulation_evidence[
        0
    ].chunk_id == "r-first"
    assert result.decisions[second.regulation.regulation_unit_id].regulation_evidence[
        0
    ].chunk_id == "r-second"


def test_batch_rejects_evidence_id_from_another_task() -> None:
    first, second = _same_product_packages(2)
    first = replace(first, regulation=replace(
        first.regulation,
        chunks=(RegulationChunkSnapshot("r-first", "第一条法规专属原文。", 0),),
    ))
    second = replace(second, regulation=replace(
        second.regulation,
        chunks=(RegulationChunkSnapshot("r-second", "第二条法规专属原文。", 0),),
    ))
    response = {
        "results": [
            {
                "task_id": first.task_id,
                "regulation_unit_id": first.regulation.regulation_unit_id,
                "status": "non_compliant",
                "reasoning": "引用了另一任务的法规。",
                "suggestion": "修改等待期。",
                "regulation_evidence_ids": ["U0002-R001"],
                "product_evidence_ids": ["U0002-P001"],
                "confidence": 0.95,
            },
            {
                "task_id": second.task_id,
                "regulation_unit_id": second.regulation.regulation_unit_id,
                "status": "non_compliant",
                "reasoning": "引用当前任务法规。",
                "suggestion": "修改等待期。",
                "regulation_evidence_ids": ["U0002-R001"],
                "product_evidence_ids": ["U0002-P001"],
                "confidence": 0.95,
            },
        ],
    }

    result = _request_batch_decisions(
        (first, second),
        _Client(json.dumps(response, ensure_ascii=False)),
        5,
        attempt=1,
    )

    assert first.regulation.regulation_unit_id not in result.decisions
    assert second.regulation.regulation_unit_id in result.decisions
    assert any(
        first.regulation.regulation_unit_id in error and "无效法规证据ID" in error
        for error in result.trace.validation_errors
    )


def test_batch_rejects_product_evidence_id_from_another_task() -> None:
    first, second = _same_product_packages(2)
    response = {
        "results": [
            {
                "task_id": first.task_id,
                "regulation_unit_id": first.regulation.regulation_unit_id,
                "status": "non_compliant",
                "reasoning": "错误引用另一任务的产品证据。",
                "suggestion": "修改等待期。",
                "regulation_evidence_ids": ["U0001-R001"],
                "product_evidence_ids": ["U0002-P001"],
                "confidence": 0.95,
            },
            {
                "task_id": second.task_id,
                "regulation_unit_id": second.regulation.regulation_unit_id,
                "status": "non_compliant",
                "reasoning": "引用当前任务证据。",
                "suggestion": "修改等待期。",
                "regulation_evidence_ids": ["U0002-R001"],
                "product_evidence_ids": ["U0002-P001"],
                "confidence": 0.95,
            },
        ],
    }

    result = _request_batch_decisions(
        (first, second),
        _Client(json.dumps(response, ensure_ascii=False)),
        5,
        attempt=1,
    )

    assert first.regulation.regulation_unit_id not in result.decisions
    assert second.regulation.regulation_unit_id in result.decisions
    assert any(
        first.regulation.regulation_unit_id in error and "无效产品证据ID" in error
        for error in result.trace.validation_errors
    )


def test_batch_audit_reasks_only_missing_units() -> None:
    packages = _same_product_packages(3)
    client = _BatchClient(omit_first="v5:law:1")
    traces: List[BatchAuditAttemptTrace] = []

    decisions = audit_regulation_package_batch(
        packages, client, 5, on_attempt=traces.append,
    )

    assert client.calls == 2
    assert len(decisions) == 3
    assert all(not item.incomplete for item in decisions)
    assert traces[0].attempt == 1
    assert any("v5:law:1" in error for error in traces[0].validation_errors)
    assert "上一轮回答未通过程序校验" in client.last_prompt


def test_controlled_probe_does_not_resend_full_text_for_structural_repair() -> None:
    packages = _same_product_packages(3)
    client = _BatchClient(omit_first="v5:law:1")

    decisions = audit_regulation_package_batch(
        packages,
        client,
        5,
        allow_full_repair=False,
    )

    assert client.calls == 1
    by_unit = {item.regulation_unit_id: item for item in decisions}
    assert by_unit["v5:law:1"].error_code == "full_repair_disabled"


def test_batch_repairs_invalid_evidence_without_resending_full_document() -> None:
    package = _package()
    unrelated_marker = "UNRELATED-FULL-DOCUMENT-BODY"
    unrelated = RoutedClause(
        AuditClauseSnapshot(
            clause_id="c-unrelated",
            number="9.9",
            title="其他条款",
            text=unrelated_marker * 100,
            block_type="clause",
        ),
        RoutedClauseRelation.UNKNOWN,
        ("与本法规无直接关系",),
    )
    package = replace(package, clauses=(*package.clauses, unrelated))
    invalid = json.loads(_response(package))
    invalid["product_evidence_ids"] = ["U0001-P999"]
    repaired = {
        "task_id": package.task_id,
        "regulation_unit_id": package.regulation.regulation_unit_id,
        "regulation_evidence_ids": ["U0001-R001"],
        "product_evidence_ids": ["U0001-P001"],
    }
    client = _SequenceClient([
        json.dumps({"results": [invalid]}, ensure_ascii=False),
        json.dumps({"results": [repaired]}, ensure_ascii=False),
    ])
    traces: List[BatchAuditAttemptTrace] = []

    decisions = audit_regulation_package_batch(
        (package,), client, 5, on_attempt=traces.append,
    )

    assert client.calls == 2
    assert decisions[0].status is RegulationDecisionStatus.NON_COMPLIANT
    assert traces[1].stage == "model_evidence_recovery"
    assert "只修复证据" in client.prompts[1]
    assert "U0001-P999" not in client.prompts[1]
    assert unrelated_marker not in client.prompts[1]
    assert "本合同等待期为270天" in client.prompts[1]


def test_compact_repair_includes_strong_unknown_relation_source() -> None:
    package = _package()
    package = replace(
        package,
        clauses=(replace(
            package.clauses[0],
            relation=RoutedClauseRelation.UNKNOWN,
            reasons=("动态包合并后关系未知",),
        ),),
    )
    invalid = json.loads(_response(package))
    invalid["product_evidence_ids"] = ["C001"]
    repaired = {
        "task_id": package.task_id,
        "regulation_unit_id": package.regulation.regulation_unit_id,
        "regulation_evidence_ids": ["U0001-R001"],
        "product_evidence_ids": ["U0001-P001"],
    }
    client = _SequenceClient([
        json.dumps({"results": [invalid]}, ensure_ascii=False),
        json.dumps({"results": [repaired]}, ensure_ascii=False),
    ])

    decisions = audit_regulation_package_batch((package,), client, 5)

    assert decisions[0].status is RegulationDecisionStatus.NON_COMPLIANT
    repair_payload = json.loads(
        client.prompts[1].split("证据修复包：\n", 1)[1]
    )
    assert repair_payload["tasks"][0]["product_evidence_catalog"] == [{
        "evidence_id": "U0001-P001",
        "clause_id": "c-0",
        "number": "2.1",
        "title": "等待期",
        "text": "本合同等待期为270天。",
    }]


def test_compact_repair_feedback_does_not_echo_pydantic_input_value() -> None:
    package = _package()
    poison = "POISON-CITATION-ANCHOR"
    invalid = json.loads(_response(package))
    invalid["product_evidence_ids"] = [poison]
    repaired = {
        "task_id": package.task_id,
        "regulation_unit_id": package.regulation.regulation_unit_id,
        "regulation_evidence_ids": ["U0001-R001"],
        "product_evidence_ids": ["U0001-P001"],
    }
    client = _SequenceClient([
        json.dumps({"results": [invalid]}, ensure_ascii=False),
        json.dumps({"results": [repaired]}, ensure_ascii=False),
    ])

    decisions = audit_regulation_package_batch((package,), client, 5)

    assert decisions[0].status is RegulationDecisionStatus.NON_COMPLIANT
    assert poison not in client.prompts[1]
    assert "decision_validation_failed" in client.prompts[1]


def test_invalid_evidence_keeps_structurally_valid_draft_status() -> None:
    package = _package()
    invalid = json.loads(_response(package))
    invalid["product_evidence_ids"] = ["U0001-P999"]

    result = _request_batch_decisions(
        (package,),
        _Client(json.dumps({"results": [invalid]}, ensure_ascii=False)),
        5,
        attempt=1,
    )

    assert package.regulation.regulation_unit_id not in result.decisions
    assert result.draft_statuses[package.regulation.regulation_unit_id] is (
        RegulationDecisionStatus.NON_COMPLIANT
    )


def test_compact_repair_batches_multiple_units_once() -> None:
    packages = _same_product_packages(2)
    invalid_items = []
    repaired_items = []
    for package in packages:
        invalid = json.loads(_response(package))
        scope = f"U{package.input_index + 1:04d}"
        invalid["product_evidence_ids"] = [f"{scope}-P999"]
        invalid_items.append(invalid)
        repaired_items.append({
            "task_id": package.task_id,
            "regulation_unit_id": package.regulation.regulation_unit_id,
            "regulation_evidence_ids": [f"{scope}-R001"],
            "product_evidence_ids": [f"{scope}-P001"],
        })
    client = _SequenceClient([
        json.dumps({"results": invalid_items}, ensure_ascii=False),
        json.dumps({"results": repaired_items}, ensure_ascii=False),
    ])
    traces: List[BatchAuditAttemptTrace] = []

    decisions = audit_regulation_package_batch(
        packages, client, 5, on_attempt=traces.append,
    )

    assert client.calls == 2
    assert all(
        decision.status is RegulationDecisionStatus.NON_COMPLIANT
        for decision in decisions
    )
    assert traces[1].stage == "model_evidence_recovery"
    assert traces[1].requested_unit_ids == tuple(
        package.regulation.regulation_unit_id for package in packages
    )


def test_compact_repair_rejects_cross_task_ids_per_unit() -> None:
    first, second = _same_product_packages(2)
    invalid_items = []
    for package in (first, second):
        item = json.loads(_response(package))
        scope = f"U{package.input_index + 1:04d}"
        item["product_evidence_ids"] = [f"{scope}-P999"]
        invalid_items.append(item)
    repaired_items = [
        {
            "task_id": first.task_id,
            "regulation_unit_id": first.regulation.regulation_unit_id,
            "regulation_evidence_ids": ["U0002-R001"],
            "product_evidence_ids": ["U0002-P001"],
        },
        {
            "task_id": second.task_id,
            "regulation_unit_id": second.regulation.regulation_unit_id,
            "regulation_evidence_ids": ["U0002-R001"],
            "product_evidence_ids": ["U0002-P001"],
        },
    ]
    client = _SequenceClient([
        json.dumps({"results": invalid_items}, ensure_ascii=False),
        json.dumps({"results": repaired_items}, ensure_ascii=False),
    ])

    decisions = audit_regulation_package_batch((first, second), client, 5)

    assert decisions[0].error_code == "model_evidence_recovery_failed"
    assert decisions[1].status is RegulationDecisionStatus.NON_COMPLIANT


def test_compact_repair_cannot_override_locked_core_fields() -> None:
    package = _package()
    invalid = json.loads(_response(package))
    invalid["product_evidence_ids"] = ["U0001-P999"]
    repair_with_status = {
        "task_id": package.task_id,
        "regulation_unit_id": package.regulation.regulation_unit_id,
        "status": "compliant",
        "regulation_evidence_ids": ["U0001-R001"],
        "product_evidence_ids": ["U0001-P001"],
    }
    client = _SequenceClient([
        json.dumps({"results": [invalid]}, ensure_ascii=False),
        json.dumps({"results": [repair_with_status]}, ensure_ascii=False),
    ])

    decisions = audit_regulation_package_batch((package,), client, 5)

    assert client.calls == 2
    assert decisions[0].status is RegulationDecisionStatus.MANUAL_REVIEW
    assert decisions[0].error_code == "model_evidence_recovery_failed"


def test_compact_repair_preserves_original_low_confidence_gate() -> None:
    package = _package()
    invalid = json.loads(_response(package))
    invalid["confidence"] = 0.5
    invalid["product_evidence_ids"] = ["U0001-P999"]
    repaired = {
        "task_id": package.task_id,
        "regulation_unit_id": package.regulation.regulation_unit_id,
        "regulation_evidence_ids": ["U0001-R001"],
        "product_evidence_ids": ["U0001-P001"],
    }
    client = _SequenceClient([
        json.dumps({"results": [invalid]}, ensure_ascii=False),
        json.dumps({"results": [repaired]}, ensure_ascii=False),
    ])

    decisions = audit_regulation_package_batch((package,), client, 5)

    assert decisions[0].status is RegulationDecisionStatus.MANUAL_REVIEW
    assert decisions[0].error_code == "low_model_confidence"
    assert decisions[0].confidence == 0.5


def test_compact_evidence_repair_rejects_unsent_ref_without_full_fallback() -> None:
    package = _package()
    unrelated = RoutedClause(
        AuditClauseSnapshot(
            clause_id="c-unrelated",
            number="9.9",
            title="其他条款",
            text="本条是完整审核包中存在但未发送给证据修复的原文。",
            block_type="clause",
        ),
        RoutedClauseRelation.UNKNOWN,
        ("与本法规无直接关系",),
    )
    package = replace(package, clauses=(*package.clauses, unrelated))
    invalid = json.loads(_response(package))
    invalid["product_evidence_ids"] = ["U0001-P999"]
    outside_catalog = {
        "task_id": package.task_id,
        "regulation_unit_id": package.regulation.regulation_unit_id,
        "regulation_evidence_ids": ["U0001-R001"],
        "product_evidence_ids": ["U0001-P002"],
    }
    client = _SequenceClient([
        json.dumps({"results": [invalid]}, ensure_ascii=False),
        json.dumps({"results": [outside_catalog]}, ensure_ascii=False),
    ])

    decisions = audit_regulation_package_batch((package,), client, 5)

    assert client.calls == 2
    assert decisions[0].status is RegulationDecisionStatus.MANUAL_REVIEW
    assert decisions[0].error_code == "model_evidence_recovery_failed"


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

    with pytest.raises(ValueError, match="同一份产品基础上下文"):
        audit_regulation_package_batch(packages, _BatchClient(), 5)


@pytest.mark.parametrize(
    ("second", "message"),
    [
        (lambda package: replace(package, input_index=0), "任务证据域"),
        (lambda package: replace(package, task_id="task-0"), "重复task_id"),
        (
            lambda package: replace(
                package,
                regulation=replace(
                    package.regulation,
                    regulation_unit_id="v5:law:0",
                ),
            ),
            "重复regulation_unit_id",
        ),
    ],
)
def test_batch_rejects_duplicate_task_identity(second, message: str) -> None:
    packages = (_package(0), second(_package(1)))

    with pytest.raises(ValueError, match=message):
        audit_regulation_package_batch(packages, _BatchClient(), 5)


def test_batch_keeps_product_facts_scoped_to_each_regulation_unit() -> None:
    from lib.compliance.auditor import build_batch_audit_messages

    first, second = _same_product_packages(2)
    waiting_fact = ProductFact(
        name=TriggerFactName.HAS_WAITING_PERIOD,
        truth=FactTruth.TRUE,
        value=True,
        method="deterministic_clause_scan",
        confidence=0.95,
        evidence=(ProductFactEvidence("c-0", "本合同等待期为270天"),),
        reason="条款明确约定等待期",
    )
    loan_fact = ProductFact(
        name=TriggerFactName.HAS_POLICY_LOAN,
        truth=FactTruth.FALSE,
        value=False,
        method="controlled_classification",
        confidence=0.95,
        reason="本法规单元只需要保单贷款事实",
    )
    packages = (
        replace(first, product_facts=(waiting_fact,)),
        replace(second, product_facts=(loan_fact,)),
    )

    messages = build_batch_audit_messages(packages)
    prompt = messages[1]["content"]
    payload = json.loads(prompt.split("审核包：\n", 1)[1])

    assert "不得跨任务引用" in messages[0]["content"]
    assert "只可用于本任务" in prompt
    assert "product_facts" not in payload["product"]
    assert [
        fact["name"] for fact in payload["regulation_tasks"][0]["product_facts"]
    ] == ["has_waiting_period"]
    assert [
        fact["name"] for fact in payload["regulation_tasks"][1]["product_facts"]
    ] == ["has_policy_loan"]
    decisions = audit_regulation_package_batch(packages, _BatchClient(), 5)
    assert len(decisions) == 2


def test_batch_shared_product_does_not_leak_first_units_routing() -> None:
    from lib.compliance.auditor import build_batch_audit_messages

    first, base_second = _same_product_packages(2)
    second = replace(
        base_second,
        clauses=(replace(
            base_second.clauses[0],
            relation=RoutedClauseRelation.RELATED,
            reasons=("第二条法规的关联路由",),
        ),),
    )
    payload = json.loads(
        build_batch_audit_messages((first, second))[1]["content"]
        .split("审核包：\n", 1)[1]
    )

    assert "relation" not in payload["product"]["clauses"][0]
    assert "routing_reasons" not in payload["product"]["clauses"][0]
    assert payload["regulation_tasks"][1]["priority_product_clauses"][0][
        "relation"
    ] == "related"


def test_batch_provider_failure_does_not_fan_out_to_single_calls() -> None:
    client = _FailingBatchClient()

    decisions = audit_regulation_package_batch(
        _same_product_packages(3), client, 5,
    )

    assert client.calls == 2
    assert {item.error_code for item in decisions} == {"batch_llm_call_failed"}
    assert all(item.incomplete for item in decisions)


def test_controlled_probe_does_not_retry_failed_full_batch() -> None:
    client = _FailingBatchClient()

    decisions = audit_regulation_package_batch(
        _same_product_packages(3),
        client,
        5,
        allow_full_repair=False,
    )

    assert client.calls == 1
    assert {item.error_code for item in decisions} == {"batch_llm_call_failed"}


def _response(package: RegulationAuditPackage, **overrides) -> str:
    scope = f"U{package.input_index + 1:04d}"
    default_product_evidence_ids = [f"{scope}-P001"] if package.clauses else []
    payload = {
        "task_id": package.task_id,
        "regulation_unit_id": package.regulation.regulation_unit_id,
        "status": "non_compliant",
        "reasoning": "等待期超过法规上限。",
        "suggestion": "修改为不超过180天。",
        "regulation_evidence_ids": [f"{scope}-R001"],
        "product_evidence_ids": default_product_evidence_ids,
        "applicability_dispute": False,
        "confidence": 0.99,
    }
    if "regulation_evidence" in overrides:
        payload.pop("regulation_evidence_ids")
    if "product_evidence" in overrides:
        payload.pop("product_evidence_ids")
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def _obligation_package() -> RegulationAuditPackage:
    return replace(
        _package(),
        obligations=(
            RegulationObligation(
                "OBL001",
                "等待期不得超过180天",
                automated_decision_allowed=True,
                insufficient_reason="",
            ),
            RegulationObligation(
                "OBL002",
                "条款应明确等待期天数",
                automated_decision_allowed=True,
                insufficient_reason="",
            ),
        ),
    )


def _obligation_response(
    package: RegulationAuditPackage,
    statuses: tuple[str, ...] = ("satisfied", "satisfied"),
    **overrides,
) -> str:
    scope = f"U{package.input_index + 1:04d}"
    payload = {
        "task_id": package.task_id,
        "regulation_unit_id": package.regulation.regulation_unit_id,
        "status": (
            "non_compliant"
            if "violated" in statuses
            else "insufficient_information"
            if "insufficient_information" in statuses
            else "compliant"
        ),
        "reasoning": "已逐项核对全部法规义务。",
        "suggestion": "",
        "regulation_evidence_ids": [],
        "product_evidence_ids": [],
        "obligation_assessments": [
            {
                "obligation_id": obligation.obligation_id,
                "status": status,
                "reasoning": f"{obligation.requirement}的独立判断。",
                "regulation_evidence_ids": [f"{scope}-R001"],
                "product_evidence_ids": [f"{scope}-P001"],
            }
            for obligation, status in zip(package.obligations, statuses)
        ],
        "applicability_dispute": False,
        "confidence": 0.95,
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def test_obligation_mode_requires_every_item_and_hydrates_stable_sources() -> None:
    package = _obligation_package()

    decision = audit_regulation_package(
        package,
        _Client(_obligation_response(package)),
        10,
    )

    assert decision.status is RegulationDecisionStatus.COMPLIANT
    assert [item.obligation_id for item in decision.obligation_assessments] == [
        "OBL001",
        "OBL002",
    ]
    assert all(
        item.status is RegulationObligationStatus.SATISFIED
        for item in decision.obligation_assessments
    )
    assert decision.obligation_assessments[0].regulation_chunk_ids == ("r-1",)
    assert decision.obligation_assessments[0].product_clause_ids == ("c-0",)
    assert tuple(item.chunk_id for item in decision.regulation_evidence) == ("r-1",)
    assert tuple(item.clause_id for item in decision.product_evidence) == ("c-0",)


def test_obligation_mode_derives_insufficient_overall_status() -> None:
    package = _obligation_package()
    response = _obligation_response(
        package,
        ("satisfied", "insufficient_information"),
    )

    decision = audit_regulation_package(package, _Client(response), 10)

    assert decision.status is RegulationDecisionStatus.INSUFFICIENT_INFORMATION
    assert decision.obligation_assessments[1].status is (
        RegulationObligationStatus.INSUFFICIENT_INFORMATION
    )


@pytest.mark.parametrize(
    "mutate",
    ("missing", "extra", "wrong_overall", "missing_evidence"),
)
def test_obligation_mode_fails_closed_on_incomplete_or_inconsistent_output(
    mutate: str,
) -> None:
    package = _obligation_package()
    payload = json.loads(_obligation_response(package))
    if mutate == "missing":
        payload["obligation_assessments"].pop()
    elif mutate == "extra":
        payload["obligation_assessments"].append({
            **payload["obligation_assessments"][0],
            "obligation_id": "OBL999",
        })
    elif mutate == "wrong_overall":
        payload["status"] = "non_compliant"
    elif mutate == "missing_evidence":
        payload["obligation_assessments"][0]["product_evidence_ids"] = []
    decision = audit_regulation_package(
        package,
        _Client(json.dumps(payload, ensure_ascii=False)),
        10,
    )

    assert decision.status is RegulationDecisionStatus.MANUAL_REVIEW
    assert decision.incomplete
    assert decision.error_code == "invalid_structured_output"


def test_obligation_mode_ignores_redundant_top_level_evidence_ids() -> None:
    package = _obligation_package()
    payload = json.loads(_obligation_response(package))
    payload["regulation_evidence_ids"] = ["U0001-R001"]
    payload["product_evidence_ids"] = ["U0001-P001"]

    decision = audit_regulation_package(
        package,
        _Client(json.dumps(payload, ensure_ascii=False)),
        10,
    )

    assert decision.status is RegulationDecisionStatus.COMPLIANT
    assert not decision.incomplete
    assert len(decision.obligation_assessments) == 2


def test_obligation_catalog_is_included_in_prompt() -> None:
    package = _obligation_package()
    payload = json.loads(
        build_audit_messages(package)[1]["content"].split("审核包：\n", 1)[1]
    )

    assert payload["regulation_unit"]["obligations"] == [
        {
            "obligation_id": "OBL001",
            "requirement": "等待期不得超过180天",
            "automated_decision_allowed": True,
            "insufficient_reason": "",
        },
        {
            "obligation_id": "OBL002",
            "requirement": "条款应明确等待期天数",
            "automated_decision_allowed": True,
            "insufficient_reason": "",
        },
    ]


def test_obligation_without_approved_evidence_scope_is_deterministically_incomplete() -> None:
    package = replace(
        _obligation_package(),
        obligations=(
            RegulationObligation(
                "OBL001",
                "分组方式应与产品定价政策一致",
                automated_decision_allowed=False,
                insufficient_reason="审核包未包含产品定价政策。",
            ),
        ),
    )
    response = _obligation_response(package, ("satisfied",))

    decision = audit_regulation_package(package, _Client(response), 10)

    assert decision.status is RegulationDecisionStatus.INSUFFICIENT_INFORMATION
    assert decision.confidence is None
    assert decision.obligation_assessments == (
        RegulationObligationAssessment(
            obligation_id="OBL001",
            requirement="分组方式应与产品定价政策一致",
            status=RegulationObligationStatus.INSUFFICIENT_INFORMATION,
            reasoning="审核包未包含产品定价政策。",
        ),
    )
    assert decision.regulation_evidence == ()
    assert decision.product_evidence == ()


def test_approved_violation_remains_non_compliant_with_an_unresolved_obligation() -> None:
    package = replace(
        _obligation_package(),
        obligations=(
            RegulationObligation(
                "OBL001",
                "费率调整间隔不得短于1年",
                automated_decision_allowed=True,
                insufficient_reason="",
            ),
            RegulationObligation(
                "OBL002",
                "分组方式应与产品定价政策一致",
                automated_decision_allowed=False,
                insufficient_reason="审核包未包含产品定价政策。",
            ),
        ),
    )
    response = _obligation_response(package, ("violated", "satisfied"))

    decision = audit_regulation_package(package, _Client(response), 10)

    assert decision.status is RegulationDecisionStatus.NON_COMPLIANT
    assert decision.confidence == 0.95
    assert [item.status for item in decision.obligation_assessments] == [
        RegulationObligationStatus.VIOLATED,
        RegulationObligationStatus.INSUFFICIENT_INFORMATION,
    ]


def test_single_audit_uses_remaining_deadline_unless_explicitly_capped() -> None:
    package = _package()
    default_client = _TimeoutRecordingClient(_response(package))
    single_client = _TimeoutRecordingClient(_response(package))

    default_decision = audit_regulation_package(
        package,
        default_client,
        timeout_seconds=285,
    )
    single_decision = audit_regulation_package(
        package,
        single_client,
        timeout_seconds=285,
        request_timeout_cap_seconds=75,
    )

    assert default_decision.status is RegulationDecisionStatus.NON_COMPLIANT
    assert single_decision.status is RegulationDecisionStatus.NON_COMPLIANT
    assert default_client.request_timeouts == [pytest.approx(285, abs=0.1)]
    assert single_client.request_timeouts == [75.0]


def test_prompt_contains_full_outline_without_unsubmitted_body() -> None:
    package = replace(_package_with_unsubmitted(), complete_document=True)
    prompt = build_audit_messages(package)[1]["content"]
    payload = json.loads(prompt.split("审核包：\n", 1)[1])

    assert [item["number"] for item in payload["product"]["clause_outline"]] == [
        "2.1", "3.1",
    ]
    assert payload["product"]["clause_outline"][1] == {
        "outline_ref": "O002",
        "number": "3.1",
        "title": "等待期补充约定1",
        "hierarchy_level": 2,
        "parent_number": "3",
        "ancestor_numbers": ["3"],
        "hierarchy_path": "3 > 3.1",
        "body_submitted": False,
        "body_available": True,
        "container_only": False,
    }
    assert len(payload["product"]["clauses"]) == 1
    assert payload["product"]["complete_document"] is False
    assert package.clauses[1].clause.text not in prompt


def test_prompt_serializes_product_fact_and_trigger_traces() -> None:
    package = replace(
        _package(),
        product_facts=(ProductFact(
            name=TriggerFactName.HAS_WAITING_PERIOD,
            truth=FactTruth.TRUE,
            value=True,
            method="deterministic_clause_scan",
            confidence=0.95,
            evidence=(ProductFactEvidence("c-0", "本合同等待期为270天"),),
            reason="条款明确约定等待期",
        ),),
        trigger_evaluation=TriggerEvaluation(
            status=TriggerStatus.TRIGGERED,
            fact_names=(TriggerFactName.HAS_WAITING_PERIOD,),
            reasons=("已明确设置等待期",),
            evidence_clause_ids=("c-0",),
        ),
    )

    payload = json.loads(
        build_audit_messages(package)[1]["content"].split("审核包：\n", 1)[1],
    )

    assert payload["product"]["product_facts"][0]["truth"] == "true"
    assert payload["regulation_unit"]["trigger_evaluation"]["status"] == "triggered"


def test_context_request_rejects_fabricated_outline_ref() -> None:
    package = _package_with_unsubmitted()
    client = _SequenceClient([
        _context_request_response(package, ["O999"]),
    ])

    decision = audit_regulation_package(package, client, 5)

    assert client.calls == 1
    assert decision.status is RegulationDecisionStatus.MANUAL_REVIEW
    assert decision.error_code == "invalid_structured_output"


def test_controlled_probe_can_disable_context_expansion() -> None:
    package = _package_with_unsubmitted()
    client = _SequenceClient([
        _context_request_response(package, ["O002"]),
        _response(package),
    ])

    decision = audit_regulation_package(
        package,
        client,
        5,
        allow_context_expansion=False,
    )

    assert client.calls == 1
    assert decision.status is RegulationDecisionStatus.INSUFFICIENT_INFORMATION
    assert decision.error_code == "context_expansion_exhausted"


def test_context_request_rejects_more_than_five_numbers() -> None:
    package = _package_with_unsubmitted(6)
    client = _SequenceClient([
        _context_request_response(
            package,
            [f"O{index:03d}" for index in range(2, 8)],
        ),
    ])

    decision = audit_regulation_package(package, client, 5)

    assert client.calls == 1
    assert decision.status is RegulationDecisionStatus.MANUAL_REVIEW
    assert decision.error_code == "invalid_structured_output"


def test_context_request_rejects_duplicate_numbers() -> None:
    package = _package_with_unsubmitted()
    client = _SequenceClient([
        _context_request_response(package, ["O002", "O002"]),
    ])

    decision = audit_regulation_package(package, client, 5)

    assert client.calls == 1
    assert decision.error_code == "invalid_structured_output"


def test_context_request_cannot_form_definitive_status() -> None:
    package = _package_with_unsubmitted()
    client = _SequenceClient([
        _context_request_response(package, ["O002"], status="compliant"),
    ])

    decision = audit_regulation_package(package, client, 5)

    assert client.calls == 1
    assert decision.status is RegulationDecisionStatus.MANUAL_REVIEW
    assert decision.error_code == "invalid_structured_output"


def test_context_request_expands_once_and_accepts_verified_evidence() -> None:
    package = _package_with_unsubmitted()
    final_response = _response(
        package,
        product_evidence_ids=["U0001-P002"],
    )
    client = _SequenceClient([
        _context_request_response(package, ["O002"]),
        final_response,
    ])

    decision = audit_regulation_package(package, client, 5)

    assert client.calls == 2
    assert package.clauses[1].clause.text not in client.prompts[0]
    assert package.clauses[1].clause.text in client.prompts[1]
    assert "本轮已是唯一一次上下文扩展" in client.prompts[1]
    initial_payload = json.loads(client.prompts[0].split("审核包：\n", 1)[1])
    expanded_payload = json.loads(client.prompts[1].split("审核包：\n", 1)[1])
    assert [
        item["evidence_id"]
        for item in initial_payload["product"]["product_evidence_catalog"]
    ] == ["U0001-P001"]
    assert [
        item["evidence_id"]
        for item in expanded_payload["product"]["product_evidence_catalog"]
    ] == ["U0001-P001", "U0001-P002"]
    assert decision.status is RegulationDecisionStatus.NON_COMPLIANT
    assert decision.product_evidence[0].clause_id == "hidden-1"


def test_outline_ref_expands_only_one_clause_when_numbers_repeat() -> None:
    package = _package_with_unsubmitted(2)
    duplicate_number = replace(
        package.clauses[2],
        clause=replace(package.clauses[2].clause, number="3.1"),
    )
    package = replace(package, clauses=(*package.clauses[:2], duplicate_number))
    final_response = _response(
        package,
        product_evidence_ids=["U0001-P002"],
    )
    client = _SequenceClient([
        _context_request_response(package, ["O002"]),
        final_response,
    ])

    decision = audit_regulation_package(package, client, 5)

    assert decision.status is RegulationDecisionStatus.NON_COMPLIANT
    assert package.clauses[1].clause.text in client.prompts[1]
    assert package.clauses[2].clause.text not in client.prompts[1]


def test_context_request_rejects_container_without_body() -> None:
    package = _package_with_unsubmitted()
    container = RoutedClause(
        clause=AuditClauseSnapshot(
            clause_id="container",
            number="3",
            title="保险责任",
            text="",
            block_type="clause",
            container_only=True,
        ),
        relation=RoutedClauseRelation.UNKNOWN,
        reasons=("目录父节点",),
        submitted=False,
    )
    package = replace(package, clauses=(package.clauses[0], container, package.clauses[1]))
    client = _SequenceClient([_context_request_response(package, ["O002"])])

    decision = audit_regulation_package(package, client, 5)

    assert client.calls == 1
    assert decision.error_code == "invalid_structured_output"


def test_context_request_validates_task_and_unit_identity_before_expansion() -> None:
    package = _package_with_unsubmitted()
    response = json.loads(_context_request_response(package, ["O002"]))
    response["task_id"] = "other-task"
    client = _SequenceClient([json.dumps(response, ensure_ascii=False)])

    decision = audit_regulation_package(package, client, 5)

    assert client.calls == 1
    assert decision.error_code == "invalid_structured_output"


def test_second_context_request_returns_insufficient_without_third_call() -> None:
    package = _package_with_unsubmitted(2)
    client = _SequenceClient([
        _context_request_response(package, ["O002"]),
        _context_request_response(package, ["O003"]),
    ])

    decision = audit_regulation_package(package, client, 5)

    assert client.calls == 2
    assert decision.status is RegulationDecisionStatus.INSUFFICIENT_INFORMATION
    assert decision.error_code == "context_expansion_exhausted"


def test_second_context_request_can_repeat_expanded_ref_without_third_call() -> None:
    package = _package_with_unsubmitted()
    repeated = _context_request_response(package, ["O002"])
    client = _SequenceClient([repeated, repeated])

    decision = audit_regulation_package(package, client, 5)

    assert client.calls == 2
    assert decision.status is RegulationDecisionStatus.INSUFFICIENT_INFORMATION
    assert decision.error_code == "context_expansion_exhausted"


def test_second_context_request_with_wrong_identity_is_rejected() -> None:
    package = _package_with_unsubmitted(2)
    second = json.loads(_context_request_response(package, ["O003"]))
    second["regulation_unit_id"] = "wrong-unit"
    client = _SequenceClient([
        _context_request_response(package, ["O002"]),
        json.dumps(second, ensure_ascii=False),
    ])

    decision = audit_regulation_package(package, client, 5)

    assert client.calls == 2
    assert decision.error_code == "invalid_structured_output"


def test_second_decision_with_missing_evidence_returns_insufficient() -> None:
    package = _package_with_unsubmitted()
    missing_evidence = _response(package, product_evidence=[])
    client = _SequenceClient([
        _context_request_response(package, ["O002"]),
        missing_evidence,
    ])

    decision = audit_regulation_package(package, client, 5)

    assert client.calls == 2
    assert decision.status is RegulationDecisionStatus.INSUFFICIENT_INFORMATION
    assert decision.error_code == "context_expansion_exhausted"


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


def test_pname_alias_cannot_prove_non_name_regulation() -> None:
    package = _package()
    response = _response(package, product_evidence=[{
        "evidence_id": "PNAME",
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
    response = _response(package, product_evidence_ids=["U0001-PNAME"])

    decision = audit_regulation_package(package, _Client(response), 10)

    assert decision.status is RegulationDecisionStatus.NON_COMPLIANT
    assert decision.product_evidence[0].source_kind == "product_name"


def test_trigger_target_controls_product_name_evidence_boundary() -> None:
    package = _package()
    name_spec = RegulationTriggerSpec(
        fact_name=TriggerFactName.IS_RATE_ADJUSTABLE,
        operator=TriggerOperator.EQUALS,
        expected_value=True,
        target_topics=("contract.name", "premium.rate_adjustment"),
    )
    name_package = replace(
        package,
        regulation=replace(
            package.regulation,
            topics=(),
            trigger_specs=(name_spec,),
        ),
    )
    payload = json.loads(
        build_audit_messages(name_package)[1]["content"].split(
            "审核包：\n", 1,
        )[1]
    )

    assert payload["product"]["name_evidence_id"] == "U0001-PNAME"
    name_decision = audit_regulation_package(
        name_package,
        _Client(_response(
            name_package,
            product_evidence_ids=["U0001-PNAME"],
        )),
        10,
    )
    assert name_decision.status is RegulationDecisionStatus.NON_COMPLIANT
    assert name_decision.product_evidence[0].source_kind == "product_name"

    body_spec = replace(
        name_spec,
        target_topics=("premium.rate_adjustment",),
    )
    body_package = replace(
        package,
        regulation=replace(
            package.regulation,
            topics=("premium.rate_adjustment",),
            trigger_specs=(body_spec,),
        ),
    )
    body_prompt = build_audit_messages(body_package)[1]["content"]
    assert "不得用产品名称证明条款正文必须包含的表述" in body_prompt
    body_decision = audit_regulation_package(
        body_package,
        _Client(_response(
            body_package,
            product_evidence_ids=["U0001-PNAME"],
        )),
        10,
    )
    assert body_decision.status is RegulationDecisionStatus.MANUAL_REVIEW
    assert body_decision.error_code == "invalid_structured_output"


def test_exact_scoped_legacy_pname_is_accepted_for_name_regulation() -> None:
    package = _package()
    package = replace(
        package,
        regulation=replace(package.regulation, topics=("contract.name",)),
    )
    response = _response(package, product_evidence=[{
        "evidence_id": "U0001-PNAME",
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


def test_complete_document_prohibition_allows_zero_hit_compliance() -> None:
    package = replace(
        _package(),
        complete_document=True,
        regulation=replace(
            _package().regulation,
            chunks=(RegulationChunkSnapshot(
                chunk_id="r-prohibition",
                content="条款中不得包含续保时重新核保等类似表述。",
                chunk_index=0,
            ),),
        ),
    )
    response = _response(
        package,
        status="compliant",
        reasoning="已检查完整产品条款，未发现法规禁止的相关表述。",
        suggestion="",
        regulation_evidence_ids=["U0001-R001"],
        product_evidence_ids=[],
    )

    decision = audit_regulation_package(package, _Client(response), 10)

    assert decision.status is RegulationDecisionStatus.COMPLIANT
    assert not decision.incomplete
    assert decision.error_code == ""
    assert decision.product_evidence == ()


def test_prohibition_zero_hit_requires_complete_document() -> None:
    package = replace(
        _package(),
        regulation=replace(
            _package().regulation,
            chunks=(RegulationChunkSnapshot(
                chunk_id="r-prohibition",
                content="条款中不得出现误导性表述。",
                chunk_index=0,
            ),),
        ),
    )
    response = _response(
        package,
        status="compliant",
        reasoning="未发现误导性表述。",
        suggestion="",
        regulation_evidence_ids=["U0001-R001"],
        product_evidence_ids=[],
    )

    decision = audit_regulation_package(package, _Client(response), 10)

    assert decision.status is RegulationDecisionStatus.MANUAL_REVIEW
    assert decision.error_code == "missing_compliance_evidence"


def test_empty_complete_document_cannot_use_prohibition_zero_hit() -> None:
    base = _package()
    package = replace(
        base,
        clauses=(),
        complete_document=True,
        regulation=replace(
            base.regulation,
            chunks=(RegulationChunkSnapshot(
                chunk_id="r-prohibition",
                content="条款中不得出现误导性表述。",
                chunk_index=0,
            ),),
        ),
    )
    response = _response(
        package,
        status="compliant",
        reasoning="已检查完整产品条款，未发现误导性表述。",
        suggestion="",
        regulation_evidence_ids=["U0001-R001"],
        product_evidence_ids=[],
    )

    decision = audit_regulation_package(package, _Client(response), 10)

    assert decision.status is RegulationDecisionStatus.MANUAL_REVIEW
    assert decision.error_code == "missing_compliance_evidence"


def test_numeric_prohibition_cannot_use_zero_hit_exception() -> None:
    package = replace(_package(), complete_document=True)
    response = _response(
        package,
        status="compliant",
        reasoning="已检查完整产品条款，未发现等待期超过限制。",
        suggestion="",
        product_evidence=[],
    )

    decision = audit_regulation_package(package, _Client(response), 10)

    assert decision.status is RegulationDecisionStatus.MANUAL_REVIEW
    assert decision.error_code == "missing_compliance_evidence"


def test_prohibited_design_allows_zero_hit_compliance() -> None:
    package = replace(
        _package(),
        complete_document=True,
        regulation=replace(
            _package().regulation,
            chunks=(RegulationChunkSnapshot(
                chunk_id="r-design-prohibition",
                content="保险产品不得通过调整保险金额变相延长等待期。",
                chunk_index=0,
            ),),
        ),
    )
    response = _response(
        package,
        status="compliant",
        reasoning="已检查完整产品条款，未通过调整保险金额变相延长等待期。",
        suggestion="",
        regulation_evidence_ids=["U0001-R001"],
        product_evidence_ids=[],
    )

    decision = audit_regulation_package(package, _Client(response), 10)

    assert decision.status is RegulationDecisionStatus.COMPLIANT
    assert decision.error_code == ""


def test_compound_positive_obligation_cannot_use_zero_hit_exception() -> None:
    package = replace(
        _package(),
        complete_document=True,
        regulation=replace(
            _package().regulation,
            chunks=(RegulationChunkSnapshot(
                chunk_id="r-compound",
                content="产品不得包含误导表述，并且必须明确列明等待期。",
                chunk_index=0,
            ),),
        ),
    )
    response = _response(
        package,
        status="compliant",
        reasoning="已检查完整产品条款，未发现误导表述。",
        suggestion="",
        regulation_evidence_ids=["U0001-R001"],
        product_evidence_ids=[],
    )

    decision = audit_regulation_package(package, _Client(response), 10)

    assert decision.status is RegulationDecisionStatus.MANUAL_REVIEW
    assert decision.error_code == "missing_compliance_evidence"


def test_compound_short_positive_obligation_cannot_use_zero_hit_exception() -> None:
    package = replace(
        _package(),
        complete_document=True,
        regulation=replace(
            _package().regulation,
            chunks=(RegulationChunkSnapshot(
                chunk_id="r-compound-short",
                content="不得包含自动续保表述；续保条件应明确说明。",
                chunk_index=0,
            ),),
        ),
    )
    response = _response(
        package,
        status="compliant",
        reasoning="已检查完整产品条款，未发现自动续保表述。",
        suggestion="",
        regulation_evidence_ids=["U0001-R001"],
        product_evidence_ids=[],
    )

    decision = audit_regulation_package(package, _Client(response), 10)

    assert decision.status is RegulationDecisionStatus.MANUAL_REVIEW
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


def test_segment_execution_starts_with_largest_utf8_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import lib.compliance.auditor as auditor_module

    package = _package()
    smaller = replace(
        package,
        task_id=f"{package.task_id}:segment:1",
        clauses=(replace(
            package.clauses[0],
            clause=replace(package.clauses[0].clause, text="A" * 100),
        ),),
    )
    larger = replace(
        package,
        task_id=f"{package.task_id}:segment:2",
        clauses=(replace(
            package.clauses[0],
            clause=replace(package.clauses[0].clause, text="条款" * 200),
        ),),
    )
    monkeypatch.setattr(
        auditor_module,
        "split_audit_package",
        lambda _package, **_kwargs: (smaller, larger),
    )
    client = _SegmentClient()

    decision = audit_regulation_package(package, client, 5)

    assert client.task_ids == [larger.task_id, smaller.task_id]
    assert "源分段2（执行顺序1）" in decision.reasoning
    assert "源分段1（执行顺序2）" in decision.reasoning


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
    oversized = replace(
        package,
        clauses=clauses,
        product_evidence_candidates=tuple(
            ProductEvidenceCandidate(
                clause_id=routed.clause.clause_id,
                strength=ProductEvidenceStrength.STRONG,
                source_layers=("exact_topic",),
            )
            for routed in clauses
        ),
    )
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

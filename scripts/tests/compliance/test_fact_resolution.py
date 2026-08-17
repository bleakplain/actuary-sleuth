import json
import time
from typing import Dict, List

from lib.common.compliance_audit import (
    AuditClauseSnapshot,
    FactTruth,
    ProductFact,
    ProductFactEvidence,
    TriggerFactName,
)
from lib.llm.product_fact_resolution import (
    build_fact_resolution_messages,
    resolve_unknown_product_facts,
    resolve_unknown_product_facts_with_audit_llm,
)
from lib.llm.base import BaseLLMClient


class _Client(BaseLLMClient):
    def __init__(self, response: object, *, fail: bool = False):
        super().__init__("test")
        self.response = response
        self.fail = fail
        self.calls = 0
        self.messages: List[Dict[str, str]] = []
        self.chat_kwargs: Dict[str, object] = {}
        self.closed = False

    def _do_generate(self, prompt: str, **kwargs: object) -> str:
        return "{}"

    def _do_chat(
        self,
        messages: List[Dict[str, str]],
        **kwargs: object,
    ) -> str:
        self.calls += 1
        self.messages = messages
        self.chat_kwargs = kwargs
        if self.fail:
            raise RuntimeError("provider unavailable")
        if isinstance(self.response, str):
            return self.response
        return json.dumps(self.response, ensure_ascii=False)

    def health_check(self) -> bool:
        return True

    def close(self) -> None:
        self.closed = True
        super().close()


def _fact(
    name: TriggerFactName,
    truth: FactTruth = FactTruth.UNKNOWN,
) -> ProductFact:
    return ProductFact(
        name=name,
        truth=truth,
        value=(truth is FactTruth.TRUE if truth is not FactTruth.UNKNOWN else None),
        method="deterministic_scan",
        confidence=1.0 if truth is not FactTruth.UNKNOWN else 0.0,
        evidence=(
            (ProductFactEvidence("known", "已有明确证据"),)
            if truth is FactTruth.TRUE
            else ()
        ),
        safe_for_exclusion=truth is FactTruth.FALSE,
    )


def _clauses() -> tuple[AuditClauseSnapshot, ...]:
    return (
        AuditClauseSnapshot(
            clause_id="clause-loan",
            number="5.2",
            title="保单贷款",
            text="经我们审核同意，您可以申请保单贷款。",
            block_type="clause",
            topics=("policy.loan",),
        ),
        AuditClauseSnapshot(
            clause_id="clause-renewal",
            number="6.1",
            title="续保",
            text="本合同保险期间届满后不提供续保。",
            block_type="clause",
            topics=("renewal.non_guaranteed",),
        ),
    )


def _payload(client: _Client) -> Dict[str, object]:
    content = client.messages[1]["content"]
    return json.loads(content.split("事实补充包：\n", 1)[1])


def test_build_messages_deduplicates_unknown_facts_and_candidate_clauses() -> None:
    unknown = _fact(TriggerFactName.HAS_POLICY_LOAN)
    messages = build_fact_resolution_messages(
        (unknown, unknown, _fact(TriggerFactName.HAS_CASH_VALUE, FactTruth.TRUE)),
        (*_clauses(), _clauses()[0]),
    )
    payload = json.loads(messages[1]["content"].split("事实补充包：\n", 1)[1])

    assert payload["required_fact_names"] == ["has_policy_loan"]
    assert len(payload["fact_tasks"]) == 1
    assert "现金价值不等于有保单贷款" in payload["fact_tasks"][0]["definition"]
    assert [item["evidence_id"] for item in payload["product_clauses"]] == [
        "P001", "P002",
    ]
    assert "法规" not in payload


def test_build_messages_isolates_candidate_clauses_for_each_fact() -> None:
    facts = (
        _fact(TriggerFactName.HAS_POLICY_LOAN),
        _fact(TriggerFactName.HAS_RENEWAL),
    )
    messages = build_fact_resolution_messages(
        facts,
        _clauses(),
        {
            TriggerFactName.HAS_POLICY_LOAN: ("clause-loan",),
            TriggerFactName.HAS_RENEWAL: ("clause-renewal",),
        },
    )
    payload = json.loads(messages[1]["content"].split("事实补充包：\n", 1)[1])

    assert payload["fact_tasks"][0]["allowed_evidence_ids"] == ["P001"]
    assert payload["fact_tasks"][1]["allowed_evidence_ids"] == ["P002"]
    assert [item["evidence_id"] for item in payload["product_clauses"]] == [
        "P001", "P002",
    ]


def test_resolves_all_unknowns_in_one_call_and_preserves_known_fact() -> None:
    facts = (
        _fact(TriggerFactName.HAS_POLICY_LOAN),
        _fact(TriggerFactName.HAS_RENEWAL),
        _fact(TriggerFactName.HAS_CASH_VALUE, FactTruth.TRUE),
    )
    client = _Client({
        "results": [
            {
                "fact_name": "has_policy_loan",
                "truth": "true",
                "confidence": 0.92,
                "evidence": [{
                    "evidence_id": "P001",
                    "quote": "您可以申请保单贷款",
                }],
            },
            {
                "fact_name": "has_renewal",
                "truth": "false",
                "confidence": 0.91,
                "evidence": [{
                    "evidence_id": "P002",
                    "quote": "保险期间届满后不提供续保",
                }],
            },
        ],
    })

    result = resolve_unknown_product_facts(facts, _clauses(), client)

    assert client.calls == 1
    assert _payload(client)["required_fact_names"] == [
        "has_policy_loan", "has_renewal",
    ]
    assert result.validation_errors == ()
    assert result.resolved_fact_names == (
        TriggerFactName.HAS_POLICY_LOAN,
        TriggerFactName.HAS_RENEWAL,
    )
    assert result.facts[0].truth is FactTruth.TRUE
    assert result.facts[0].evidence == (
        ProductFactEvidence("clause-loan", "您可以申请保单贷款"),
    )
    assert result.facts[1].truth is FactTruth.FALSE
    assert result.facts[1].safe_for_exclusion is False
    assert result.facts[1].method == "semantic_fact"
    assert result.facts[2] is facts[2]


def test_policy_loan_resolution_accepts_controlled_pledge_borrowing_term() -> None:
    fact = _fact(TriggerFactName.HAS_POLICY_LOAN)
    clause = AuditClauseSnapshot(
        clause_id="clause-pledge-loan",
        number="5.3",
        title="合同权益",
        text="经审核同意，投保人可以申请保险单质押借款。",
        block_type="clause",
        topics=("policy.loan",),
    )
    client = _Client({
        "results": [{
            "fact_name": "has_policy_loan",
            "truth": "true",
            "confidence": 0.95,
            "evidence": [{
                "evidence_id": "P001",
                "quote": "投保人可以申请保险单质押借款",
            }],
        }],
    })

    result = resolve_unknown_product_facts((fact,), (clause,), client)

    assert result.validation_errors == ()
    assert result.resolved_fact_names == (TriggerFactName.HAS_POLICY_LOAN,)
    assert result.facts[0].truth is FactTruth.TRUE
    assert result.facts[0].evidence == (
        ProductFactEvidence(
            "clause-pledge-loan",
            "投保人可以申请保险单质押借款",
        ),
    )


def test_missing_duplicate_and_added_tasks_do_not_change_unknowns() -> None:
    facts = (
        _fact(TriggerFactName.HAS_POLICY_LOAN),
        _fact(TriggerFactName.HAS_RENEWAL),
    )
    duplicate = {
        "fact_name": "has_policy_loan",
        "truth": "true",
        "confidence": 0.9,
        "evidence": [{
            "evidence_id": "P001",
            "quote": "申请保单贷款",
        }],
    }
    client = _Client({
        "results": [
            duplicate,
            duplicate,
            {
                "fact_name": "has_cash_value",
                "truth": "true",
                "confidence": 0.9,
                "evidence": [],
            },
        ],
    })

    result = resolve_unknown_product_facts(facts, _clauses(), client)

    assert result.facts == facts
    assert result.resolved_fact_names == ()
    assert any("重复回答" in error for error in result.validation_errors)
    assert any("未请求" in error for error in result.validation_errors)
    assert any("未回答产品事实: has_renewal" in error for error in result.validation_errors)


def test_invalid_evidence_id_or_non_verbatim_quote_keeps_unknown() -> None:
    facts = (
        _fact(TriggerFactName.HAS_POLICY_LOAN),
        _fact(TriggerFactName.HAS_RENEWAL),
    )
    client = _Client({
        "results": [
            {
                "fact_name": "has_policy_loan",
                "truth": "true",
                "confidence": 0.9,
                "evidence": [{
                    "evidence_id": "P999",
                    "quote": "申请保单贷款",
                }],
            },
            {
                "fact_name": "has_renewal",
                "truth": "false",
                "confidence": 0.9,
                "evidence": [{
                    "evidence_id": "P002",
                    "quote": "本产品永不保证续保",
                }],
            },
        ],
    })

    result = resolve_unknown_product_facts(facts, _clauses(), client)

    assert result.facts == facts
    assert len(result.validation_errors) == 2
    assert "证据 ID 无效" in result.validation_errors[0]
    assert "逐字子串" in result.validation_errors[1]


def test_evidence_from_another_fact_candidate_is_rejected() -> None:
    clauses = (
        _clauses()[0],
        AuditClauseSnapshot(
            clause_id="clause-other",
            number="6.2",
            title="其他约定",
            text="本合同另行说明保单贷款事项。",
            block_type="clause",
            topics=(),
        ),
    )
    fact = _fact(TriggerFactName.HAS_POLICY_LOAN)
    client = _Client({
        "results": [{
            "fact_name": "has_policy_loan",
            "truth": "true",
            "confidence": 0.95,
            "evidence": [{
                "evidence_id": "P002",
                "quote": "另行说明保单贷款事项",
            }],
        }],
    })

    result = resolve_unknown_product_facts(
        (fact,),
        clauses,
        client,
        candidate_clause_ids_by_fact={
            TriggerFactName.HAS_POLICY_LOAN: ("clause-loan",),
        },
    )

    assert result.facts == (fact,)
    assert any(
        "不属于该事实的候选条款" in error
        for error in result.validation_errors
    )


def test_one_character_quote_cannot_resolve_semantic_fact() -> None:
    fact = _fact(TriggerFactName.HAS_POLICY_LOAN)
    client = _Client({
        "results": [{
            "fact_name": "has_policy_loan",
            "truth": "true",
            "confidence": 0.95,
            "evidence": [{"evidence_id": "P001", "quote": "您"}],
        }],
    })

    result = resolve_unknown_product_facts((fact,), _clauses(), client)

    assert result.facts == (fact,)
    assert any("摘录过短" in error for error in result.validation_errors)


def test_low_confidence_missing_evidence_and_unknown_keep_originals() -> None:
    facts = (
        _fact(TriggerFactName.HAS_POLICY_LOAN),
        _fact(TriggerFactName.HAS_RENEWAL),
        _fact(TriggerFactName.HAS_GRACE_PERIOD),
    )
    client = _Client({
        "results": [
            {
                "fact_name": "has_policy_loan",
                "truth": "true",
                "confidence": 0.79,
                "evidence": [{
                    "evidence_id": "P001",
                    "quote": "申请保单贷款",
                }],
            },
            {
                "fact_name": "has_renewal",
                "truth": "false",
                "confidence": 0.9,
                "evidence": [],
            },
            {
                "fact_name": "has_grace_period",
                "truth": "unknown",
                "confidence": 0.2,
                "evidence": [],
            },
        ],
    })

    result = resolve_unknown_product_facts(facts, _clauses(), client)

    assert result.facts == facts
    assert result.resolved_fact_names == ()
    assert len(result.validation_errors) == 2
    assert any("置信度" in error for error in result.validation_errors)
    assert any("缺少产品条款证据" in error for error in result.validation_errors)


def test_client_failure_is_attempted_once_and_keeps_all_unknowns() -> None:
    facts = (
        _fact(TriggerFactName.HAS_POLICY_LOAN),
        _fact(TriggerFactName.HAS_RENEWAL),
    )
    client = _Client({}, fail=True)

    result = resolve_unknown_product_facts(facts, _clauses(), client)

    assert client.calls == 1
    assert result.attempted is True
    assert result.facts == facts
    assert result.resolved_fact_names == ()
    assert result.validation_errors == (
        "事实补充模型调用失败: RuntimeError",
    )


def test_timeout_budget_is_forwarded_to_client_and_retry_deadline() -> None:
    fact = _fact(TriggerFactName.HAS_POLICY_LOAN)
    client = _Client({
        "results": [{
            "fact_name": "has_policy_loan",
            "truth": "unknown",
            "confidence": 0.2,
            "evidence": [],
        }],
    })
    before = time.monotonic()

    result = resolve_unknown_product_facts(
        (fact,),
        _clauses(),
        client,
        timeout_seconds=12.5,
    )

    assert result.attempted is True
    assert client.chat_kwargs["timeout"] == 12.5
    retry_deadline = client.chat_kwargs["_retry_deadline"]
    assert isinstance(retry_deadline, float)
    assert before + 12.0 <= retry_deadline <= time.monotonic() + 12.5


def test_malformed_response_keeps_all_unknowns() -> None:
    fact = _fact(TriggerFactName.HAS_POLICY_LOAN)
    client = _Client("not json")

    result = resolve_unknown_product_facts((fact,), _clauses(), client)

    assert result.facts == (fact,)
    assert result.resolved_fact_names == ()
    assert any("不是有效 JSON" in error for error in result.validation_errors)
    assert any("未回答产品事实" in error for error in result.validation_errors)


def test_no_client_or_no_unknown_does_not_attempt_model_call() -> None:
    unknown = _fact(TriggerFactName.HAS_POLICY_LOAN)
    without_client = resolve_unknown_product_facts((unknown,), _clauses())
    client = _Client({"results": []})
    known = _fact(TriggerFactName.HAS_CASH_VALUE, FactTruth.TRUE)
    without_unknown = resolve_unknown_product_facts((known,), _clauses(), client)

    assert without_client.attempted is False
    assert without_client.facts == (unknown,)
    assert without_unknown.attempted is False
    assert without_unknown.facts == (known,)
    assert client.calls == 0


def test_default_audit_llm_wrapper_closes_created_client() -> None:
    fact = _fact(TriggerFactName.HAS_POLICY_LOAN)
    client = _Client({
        "results": [{
            "fact_name": "has_policy_loan",
            "truth": "true",
            "confidence": 0.95,
            "evidence": [{
                "evidence_id": "P001",
                "quote": "您可以申请保单贷款",
            }],
        }],
    })

    result = resolve_unknown_product_facts_with_audit_llm(
        (fact,),
        _clauses(),
        client_factory=lambda: client,
    )

    assert result.facts[0].truth is FactTruth.TRUE
    assert client.calls == 1
    assert client.closed is True


def test_default_audit_llm_wrapper_keeps_unknown_on_initialization_failure() -> None:
    fact = _fact(TriggerFactName.HAS_POLICY_LOAN)

    def fail_factory() -> BaseLLMClient:
        raise RuntimeError("invalid config")

    result = resolve_unknown_product_facts_with_audit_llm(
        (fact,),
        _clauses(),
        client_factory=fail_factory,
    )

    assert result.facts == (fact,)
    assert result.attempted is True
    assert result.requested_fact_names == (TriggerFactName.HAS_POLICY_LOAN,)
    assert result.validation_errors == (
        "事实补充模型客户端初始化失败: RuntimeError",
    )


def test_default_audit_llm_wrapper_closes_client_after_call_failure() -> None:
    fact = _fact(TriggerFactName.HAS_POLICY_LOAN)
    client = _Client({}, fail=True)

    result = resolve_unknown_product_facts_with_audit_llm(
        (fact,),
        _clauses(),
        client_factory=lambda: client,
    )

    assert result.facts == (fact,)
    assert result.attempted is True
    assert result.validation_errors == (
        "事实补充模型调用失败: RuntimeError",
    )
    assert client.closed is True


def test_invalid_candidate_clause_id_skips_call_and_keeps_unknown() -> None:
    fact = _fact(TriggerFactName.HAS_POLICY_LOAN)
    client = _Client({"results": []})

    result = resolve_unknown_product_facts(
        (fact,),
        _clauses(),
        client,
        candidate_clause_ids_by_fact={
            TriggerFactName.HAS_POLICY_LOAN: ("missing-clause",),
        },
    )

    assert result.facts == (fact,)
    assert result.requested_fact_names == ()
    assert result.attempted is False
    assert client.calls == 0
    assert result.validation_errors == (
        "产品事实 has_policy_loan 的候选条款 ID 不存在: missing-clause",
    )


def test_numeric_unknown_is_not_sent_to_semantic_boolean_protocol() -> None:
    numeric = ProductFact(
        name=TriggerFactName.WAITING_PERIOD_DAYS,
        truth=FactTruth.UNKNOWN,
        unit="day",
        method="numeric_fact",
        confidence=0.0,
    )
    client = _Client({"results": []})

    result = resolve_unknown_product_facts((numeric,), _clauses(), client)

    assert result.facts == (numeric,)
    assert result.requested_fact_names == ()
    assert result.attempted is False
    assert client.calls == 0

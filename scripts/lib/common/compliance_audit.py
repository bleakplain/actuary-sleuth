"""产品条款法规级审核的数据合同。"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple, TypeAlias, Union

from lib.common.product_tags import ProductTags


class AuditStatus(str, Enum):
    COMPLETED = "completed"
    DEGRADED = "degraded"
    INCOMPLETE = "incomplete"


class ComplianceConclusion(str, Enum):
    NON_COMPLIANT = "non_compliant"
    NO_VIOLATION_FOUND = "no_violation_found"
    NO_APPLICABLE_REGULATIONS = "no_applicable_regulations"
    UNDETERMINED = "undetermined"


class RegulationDecisionStatus(str, Enum):
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    INSUFFICIENT_INFORMATION = "insufficient_information"
    MANUAL_REVIEW = "manual_review"


class FactKind(str, Enum):
    WAITING_PERIOD = "waiting_period"
    HESITATION_PERIOD = "hesitation_period"
    RENEWAL_ARRANGEMENT = "renewal_arrangement"
    NON_GUARANTEED_RENEWAL = "non_guaranteed_renewal"
    PROHIBITED_RENEWAL_LANGUAGE = "prohibited_renewal_language"
    RATE_ADJUSTABLE = "rate_adjustable"
    FIRST_RATE_ADJUSTMENT_INTERVAL = "first_rate_adjustment_interval"
    SUBSEQUENT_RATE_ADJUSTMENT_INTERVAL = "subsequent_rate_adjustment_interval"


class TriggerFactName(str, Enum):
    """法规触发条件可引用的受控产品事实。"""

    HAS_WAITING_PERIOD = "has_waiting_period"
    HAS_HESITATION_PERIOD = "has_hesitation_period"
    HAS_POLICY_LOAN = "has_policy_loan"
    HAS_CASH_VALUE = "has_cash_value"
    HAS_GRACE_PERIOD = "has_grace_period"
    HAS_RENEWAL = "has_renewal"
    IS_RATE_ADJUSTABLE = "is_rate_adjustable"
    MENTIONS_OUT_OF_HOSPITAL_DRUG = "mentions_out_of_hospital_drug"
    HAS_DEATH_BENEFIT = "has_death_benefit"
    MENTIONS_CRITICAL_ILLNESS_DEFINITION_TERM = (
        "mentions_critical_illness_definition_term"
    )
    WAITING_PERIOD_DAYS = "waiting_period_days"
    HESITATION_PERIOD_DAYS = "hesitation_period_days"
    FIRST_RATE_ADJUSTMENT_INTERVAL_YEARS = (
        "first_rate_adjustment_interval_years"
    )
    SUBSEQUENT_RATE_ADJUSTMENT_INTERVAL_YEARS = (
        "subsequent_rate_adjustment_interval_years"
    )


class TriggerOperator(str, Enum):
    EQUALS = "equals"
    EXISTS = "exists"
    CONTAINS_ANY = "contains_any"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"


class ProofStrategy(str, Enum):
    EXPLICIT_PRESENCE = "explicit_presence"
    EXPLICIT_NEGATION = "explicit_negation"
    CONTROLLED_CLASSIFICATION = "controlled_classification"
    CLOSED_PHRASE_SCAN = "closed_phrase_scan"
    NUMERIC_FACT = "numeric_fact"
    SEMANTIC_FACT = "semantic_fact"


class FactTruth(str, Enum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class TriggerStatus(str, Enum):
    TRIGGERED = "triggered"
    NOT_TRIGGERED = "not_triggered"
    INDETERMINATE = "indeterminate"


TriggerScalar: TypeAlias = Union[bool, int, float, str]
TriggerValue: TypeAlias = Union[TriggerScalar, Tuple[str, ...]]


@dataclass(frozen=True)
class RegulationTriggerSpec:
    """一个受控触发条件；多个条件由求值器按 AND 组合。

    ``required_facts`` 只声明最终判断和证据检索还需要哪些辅助事实，不是
    额外的触发谓词；真正参与 AND 求值的条件必须各自成为一个 spec。
    ``exclusion_approved`` 只是逐条精算验收标记，仍需全局切换门禁开启后
    才允许在生产中排除法规。
    """

    fact_name: TriggerFactName
    operator: TriggerOperator
    expected_value: Optional[TriggerValue] = None
    target_topics: Tuple[str, ...] = ()
    required_facts: Tuple[TriggerFactName, ...] = ()
    proof_strategy: ProofStrategy = ProofStrategy.EXPLICIT_PRESENCE
    search_all_terms: Tuple[str, ...] = ()
    search_any_terms: Tuple[str, ...] = ()
    description: str = ""
    exclusion_approved: bool = False


@dataclass(frozen=True)
class ProductFactEvidence:
    clause_id: str
    quote: str


@dataclass(frozen=True)
class ProductFact:
    """一次产品审核共享的三态事实及其逐字证据。

    ``safe_for_exclusion`` 必须由事实提取器基于完整文档封闭扫描或受控
    互斥分类显式设置。v1 中，明确否定可以证明“期望值为 false”
    的正向触发，但不得单独用于排除法规。数值事实可证明条件满足，但在没有精算确认
    “该阈值只表示适用范围”前，数值不满足不得排除法规。求值器不会通过 method 字符串
    猜测负向证明是否安全，避免把“没有搜到”误当成 false 而漏检法规。
    """

    name: TriggerFactName
    truth: FactTruth
    value: Optional[TriggerValue] = None
    unit: str = ""
    method: str = ""
    confidence: float = 1.0
    evidence: Tuple[ProductFactEvidence, ...] = ()
    reason: str = ""
    safe_for_exclusion: bool = False
    proof_strategy: Optional[ProofStrategy] = None
    proof_terms: Tuple[str, ...] = ()
    complete_document_proof: bool = False

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence 必须介于 0 和 1 之间")


@dataclass(frozen=True)
class TriggerEvaluation:
    status: TriggerStatus
    fact_names: Tuple[TriggerFactName, ...]
    reasons: Tuple[str, ...]
    evidence_clause_ids: Tuple[str, ...]


class RoutedClauseRelation(str, Enum):
    DIRECT = "direct"
    RELATED = "related"
    UNKNOWN = "unknown"
    NOT_RELEVANT = "not_relevant"


@dataclass(frozen=True)
class AuditClauseSnapshot:
    clause_id: str
    number: str
    title: str
    text: str
    block_type: str
    topics: Tuple[str, ...] = ()
    hierarchy_level: int = 0
    parent_number: Optional[str] = None
    ancestor_numbers: Tuple[str, ...] = ()
    hierarchy_path: str = ""
    container_only: bool = False


@dataclass(frozen=True)
class RoutedClause:
    clause: AuditClauseSnapshot
    relation: RoutedClauseRelation
    reasons: Tuple[str, ...]
    submitted: bool = True


@dataclass(frozen=True)
class ExtractedFact:
    kind: FactKind
    value: str
    unit: str
    clause_id: str
    evidence: str
    confidence: float


@dataclass(frozen=True)
class RegulationChunkSnapshot:
    chunk_id: str
    content: str
    chunk_index: int


@dataclass(frozen=True)
class RegulationUnitSnapshot:
    regulation_unit_id: str
    kb_version: str
    law_name: str
    source_file: str
    article_number: str
    section_path: str
    topics: Tuple[str, ...]
    chunks: Tuple[RegulationChunkSnapshot, ...]
    applicability_status: str
    applicability_reasons: Tuple[str, ...]
    category: str = ""
    trigger_specs: Tuple[RegulationTriggerSpec, ...] = ()


@dataclass(frozen=True)
class RegulationAuditPackage:
    task_id: str
    input_index: int
    product_name: str
    product_tags: ProductTags
    regulation: RegulationUnitSnapshot
    clauses: Tuple[RoutedClause, ...]
    facts: Tuple[ExtractedFact, ...]
    complete_document: bool = False
    product_facts: Tuple[ProductFact, ...] = ()
    trigger_evaluation: Optional[TriggerEvaluation] = None


@dataclass(frozen=True)
class RegulationEvidence:
    chunk_id: str
    quote: str


@dataclass(frozen=True)
class ProductClauseEvidence:
    clause_id: str
    quote: str
    source_kind: str = "clause_body"


@dataclass(frozen=True)
class RegulationAuditDecision:
    task_id: str
    regulation_unit_id: str
    status: RegulationDecisionStatus
    reasoning: str
    suggestion: str
    regulation_evidence: Tuple[RegulationEvidence, ...]
    product_evidence: Tuple[ProductClauseEvidence, ...]
    applicability_dispute: bool = False
    confidence: Optional[float] = None
    incomplete: bool = False
    error_code: str = ""


@dataclass(frozen=True)
class BatchAuditAttemptTrace:
    attempt: int
    requested_unit_ids: Tuple[str, ...]
    returned_unit_ids: Tuple[str, ...]
    validation_errors: Tuple[str, ...]
    raw_response: str


@dataclass(frozen=True)
class AuditRunSummary:
    audit_status: AuditStatus
    compliance_conclusion: ComplianceConclusion
    candidate_count: int
    excluded_count: int
    completed_count: int
    failed_count: int
    decisions: Tuple[RegulationAuditDecision, ...]
    warnings: Tuple[str, ...] = ()

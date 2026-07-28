"""产品条款法规级审核的数据合同。"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

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


@dataclass(frozen=True)
class RegulationAuditPackage:
    task_id: str
    input_index: int
    product_name: str
    product_tags: ProductTags
    regulation: RegulationUnitSnapshot
    clauses: Tuple[RoutedClause, ...]
    facts: Tuple[ExtractedFact, ...]


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
class AuditRunSummary:
    audit_status: AuditStatus
    compliance_conclusion: ComplianceConclusion
    candidate_count: int
    excluded_count: int
    completed_count: int
    failed_count: int
    decisions: Tuple[RegulationAuditDecision, ...]
    warnings: Tuple[str, ...] = ()

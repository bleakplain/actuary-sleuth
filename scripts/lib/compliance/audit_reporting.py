"""法规级决策到整份审核状态的确定性汇总。"""
from __future__ import annotations

from typing import Iterable, Tuple

from lib.common.compliance_audit import (
    AuditRunSummary,
    AuditStatus,
    ComplianceConclusion,
    RegulationAuditDecision,
    RegulationDecisionStatus,
)


def summarize_audit_run(
    decisions: Iterable[RegulationAuditDecision],
    candidate_count: int,
    excluded_count: int,
    retrieval_degraded: bool = False,
    retrieval_complete: bool = True,
    warnings: Tuple[str, ...] = (),
) -> AuditRunSummary:
    ordered = tuple(decisions)
    decision_failure_count = sum(item.incomplete for item in ordered)
    candidate_scope_known = candidate_count > 0 or excluded_count > 0
    failed_count = (
        decision_failure_count
        + (0 if retrieval_complete else 1)
        + (1 if retrieval_complete and not candidate_scope_known else 0)
    )
    completed_count = len(ordered) - decision_failure_count
    if failed_count or not retrieval_complete:
        audit_status = AuditStatus.INCOMPLETE
    elif retrieval_degraded:
        audit_status = AuditStatus.DEGRADED
    else:
        audit_status = AuditStatus.COMPLETED

    if any(
        item.status is RegulationDecisionStatus.NON_COMPLIANT for item in ordered
    ):
        conclusion = ComplianceConclusion.NON_COMPLIANT
    elif (
        audit_status is AuditStatus.COMPLETED
        and candidate_count == 0
        and excluded_count > 0
    ):
        conclusion = ComplianceConclusion.NO_APPLICABLE_REGULATIONS
    elif (
        audit_status is AuditStatus.COMPLETED
        and candidate_count > 0
        and len(ordered) == candidate_count
        and all(
            item.status is RegulationDecisionStatus.COMPLIANT for item in ordered
        )
    ):
        conclusion = ComplianceConclusion.NO_VIOLATION_FOUND
    else:
        conclusion = ComplianceConclusion.UNDETERMINED
    return AuditRunSummary(
        audit_status=audit_status,
        compliance_conclusion=conclusion,
        candidate_count=candidate_count,
        excluded_count=excluded_count,
        completed_count=completed_count,
        failed_count=failed_count,
        decisions=ordered,
        warnings=warnings,
    )

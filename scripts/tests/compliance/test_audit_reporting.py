from lib.common.compliance_audit import (
    AuditStatus,
    ComplianceConclusion,
    RegulationAuditDecision,
    RegulationDecisionStatus,
)
from lib.compliance.audit_reporting import summarize_audit_run


def _decision(
    status: RegulationDecisionStatus,
    incomplete: bool = False,
) -> RegulationAuditDecision:
    return RegulationAuditDecision(
        task_id="task",
        regulation_unit_id="unit",
        status=status,
        reasoning="reason",
        suggestion="",
        regulation_evidence=(),
        product_evidence=(),
        incomplete=incomplete,
    )


def test_all_units_compliant_is_no_violation_found() -> None:
    result = summarize_audit_run(
        (_decision(RegulationDecisionStatus.COMPLIANT),),
        candidate_count=1,
        excluded_count=2,
    )
    assert result.audit_status is AuditStatus.COMPLETED
    assert result.compliance_conclusion is ComplianceConclusion.NO_VIOLATION_FOUND


def test_incomplete_zero_violation_is_not_compliant() -> None:
    result = summarize_audit_run(
        (_decision(RegulationDecisionStatus.MANUAL_REVIEW, incomplete=True),),
        candidate_count=1,
        excluded_count=0,
    )
    assert result.audit_status is AuditStatus.INCOMPLETE
    assert result.compliance_conclusion is ComplianceConclusion.UNDETERMINED


def test_known_non_compliance_survives_partial_failure() -> None:
    result = summarize_audit_run(
        (
            _decision(RegulationDecisionStatus.NON_COMPLIANT),
            _decision(RegulationDecisionStatus.MANUAL_REVIEW, incomplete=True),
        ),
        candidate_count=2,
        excluded_count=0,
    )
    assert result.audit_status is AuditStatus.INCOMPLETE
    assert result.compliance_conclusion is ComplianceConclusion.NON_COMPLIANT


def test_information_insufficient_is_undetermined() -> None:
    result = summarize_audit_run(
        (_decision(RegulationDecisionStatus.INSUFFICIENT_INFORMATION),),
        candidate_count=1,
        excluded_count=0,
    )
    assert result.audit_status is AuditStatus.COMPLETED
    assert result.compliance_conclusion is ComplianceConclusion.UNDETERMINED


def test_retrieval_degraded_prevents_no_violation_conclusion() -> None:
    result = summarize_audit_run(
        (_decision(RegulationDecisionStatus.COMPLIANT),),
        candidate_count=1,
        excluded_count=0,
        retrieval_degraded=True,
    )
    assert result.audit_status is AuditStatus.DEGRADED
    assert result.compliance_conclusion is ComplianceConclusion.UNDETERMINED


def test_incomplete_candidate_freeze_is_fatal_even_with_zero_units() -> None:
    result = summarize_audit_run(
        (),
        candidate_count=0,
        excluded_count=0,
        retrieval_degraded=True,
        retrieval_complete=False,
    )

    assert result.audit_status is AuditStatus.INCOMPLETE
    assert result.compliance_conclusion is ComplianceConclusion.UNDETERMINED
    assert result.failed_count == 1


def test_zero_candidates_with_no_exclusion_scope_is_incomplete() -> None:
    result = summarize_audit_run(
        (),
        candidate_count=0,
        excluded_count=0,
    )

    assert result.audit_status is AuditStatus.INCOMPLETE
    assert result.compliance_conclusion is ComplianceConclusion.UNDETERMINED


def test_all_explicitly_excluded_is_not_no_violation_found() -> None:
    result = summarize_audit_run(
        (),
        candidate_count=0,
        excluded_count=171,
    )

    assert result.audit_status is AuditStatus.COMPLETED
    assert (
        result.compliance_conclusion
        is ComplianceConclusion.NO_APPLICABLE_REGULATIONS
    )

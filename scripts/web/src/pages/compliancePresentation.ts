import type { DoneData } from '../api/compliance';
import type {
  AuditResultItem,
  AuditStatus,
  ComplianceConclusion,
  ComplianceReport,
} from '../types';

export type CompletionNoticeKind = 'success' | 'warning' | 'error';

export interface CompletionNotice {
  kind: CompletionNoticeKind;
  text: string;
}

export function buildComplianceReport(
  data: DoneData & { items: AuditResultItem[] },
): ComplianceReport {
  return {
    id: data.report_id,
    product_name: data.product_name,
    category: data.category,
    mode: 'document',
    result: {
      summary: data.summary,
      items: data.items,
      regulations: data.regulations,
      excluded_regulations: data.excluded_regulations,
      decisions: data.decisions,
      product_tags: data.product_tags,
      document_fingerprint: data.document_fingerprint,
      audit_input_fingerprint: data.audit_input_fingerprint,
      product_name_source: data.product_name_source,
      parse_warnings: data.parse_warnings,
      regulation_sources: data.regulation_sources,
      category: data.category,
      negative_list_result: data.negative_list_result,
      retrieval_degraded: data.retrieval_degraded,
      retrieval_warnings: data.retrieval_warnings,
      audit_status: data.audit_status,
      compliance_conclusion: data.compliance_conclusion,
      kb_version: data.kb_version,
      topic_taxonomy_version: data.topic_taxonomy_version,
      topic_relations_version: data.topic_relations_version,
      evaluation_dataset_version: data.evaluation_dataset_version,
      evaluation_dataset_status: data.evaluation_dataset_status,
      cutover_gate_status: data.cutover_gate_status,
      candidate_count: data.candidate_count,
      excluded_count: data.excluded_count,
      completed_count: data.completed_count,
      failed_count: data.failed_count,
      failure_reasons: data.failure_reasons,
      clause_coverage: data.clause_coverage,
    },
    created_at: '',
  };
}

export function getCompletionNotice(
  auditStatus: AuditStatus | undefined,
  conclusion: ComplianceConclusion | undefined,
  nonCompliantCount: number,
): CompletionNotice {
  if (auditStatus !== 'completed') {
    return {
      kind: 'warning',
      text: '审查未完整完成，请查看失败原因并人工复核',
    };
  }
  if (conclusion === 'non_compliant' || nonCompliantCount > 0) {
    return {
      kind: 'error',
      text: `审查完成，发现 ${nonCompliantCount} 条不合规`,
    };
  }
  if (conclusion === 'no_violation_found') {
    return {
      kind: 'success',
      text: '审查完成，未发现违规',
    };
  }
  if (conclusion === 'no_applicable_regulations') {
    return {
      kind: 'warning',
      text: '审查完成，但没有法规进入实质审核',
    };
  }
  return {
    kind: 'warning',
    text: '审查完成，但结论仍需人工复核',
  };
}

export function mergeAuditWarnings(
  failureReasons: string[] | undefined,
  retrievalWarnings: string[] | undefined,
): string[] {
  return Array.from(new Set([
    ...(failureReasons ?? []),
    ...(retrievalWarnings ?? []),
  ].filter(Boolean)));
}

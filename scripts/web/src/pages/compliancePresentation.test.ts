import { describe, expect, it } from 'vitest';
import type { DoneData } from '../api/compliance';
import {
  buildComplianceReport,
  getCompletionNotice,
  mergeAuditWarnings,
} from './compliancePresentation';

describe('compliance result presentation', () => {
  it('does not use a success notice for completed non-compliance', () => {
    expect(getCompletionNotice('completed', 'non_compliant', 2)).toEqual({
      kind: 'error',
      text: '审查完成，发现 2 条不合规',
    });
  });

  it('only uses a success notice for a completed no-violation conclusion', () => {
    expect(getCompletionNotice('completed', 'no_violation_found', 0)).toEqual({
      kind: 'success',
      text: '审查完成，未发现违规',
    });
    expect(getCompletionNotice('completed', 'undetermined', 0).kind).toBe('warning');
    expect(
      getCompletionNotice('completed', 'no_applicable_regulations', 0),
    ).toEqual({
      kind: 'warning',
      text: '审查完成，但没有法规进入实质审核',
    });
  });

  it('merges and deduplicates failure and retrieval warnings', () => {
    expect(mergeAuditWarnings(
      ['LLM 调用失败', '共同原因'],
      ['RAG 检索降级', '共同原因'],
    )).toEqual(['LLM 调用失败', '共同原因', 'RAG 检索降级']);
    expect(mergeAuditWarnings([], ['RAG 检索降级'])).toEqual(['RAG 检索降级']);
  });

  it('preserves parse identity metadata in the immediate stream report', () => {
    const done = {
      report_id: 'report-1',
      product_name: '测试医疗保险',
      category: '健康险',
      summary: { compliant: 1, non_compliant: 0, attention: 0 },
      negative_list_result: null,
      regulations: [],
      excluded_regulations: [],
      decisions: [],
      product_tags: {},
      document_fingerprint: 'document-sha256',
      audit_input_fingerprint: 'audit-input-sha256',
      product_name_source: 'document_content',
      parse_warnings: ['未识别章节已保守纳入'],
      regulation_sources: {},
      retrieval_degraded: false,
      retrieval_warnings: [],
      audit_status: 'completed',
      compliance_conclusion: 'no_violation_found',
      kb_version: 'v5',
      topic_taxonomy_version: '1.0.0',
      topic_relations_version: '1.0.0',
      evaluation_dataset_version: 'acceptance-v1',
      candidate_count: 1,
      excluded_count: 0,
      completed_count: 1,
      failed_count: 0,
      failure_reasons: [],
      items: [],
      clause_coverage: null,
    } as DoneData & { items: [] };

    const report = buildComplianceReport(done);

    expect(report.result).toMatchObject({
      document_fingerprint: 'document-sha256',
      audit_input_fingerprint: 'audit-input-sha256',
      product_name_source: 'document_content',
      parse_warnings: ['未识别章节已保守纳入'],
    });
  });
});

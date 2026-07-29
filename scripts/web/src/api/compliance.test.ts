import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  fetchComplianceReports,
  fetchComplianceReport,
  deleteComplianceReport,
  parseFile,
  parseRichText,
  fetchCategories,
  checkDocumentStream,
  checkDocumentV2Stream,
} from './compliance';

vi.mock('./client', () => {
  const mockGet = vi.fn();
  const mockPost = vi.fn();
  const mockDelete = vi.fn();
  return { default: { get: mockGet, post: mockPost, delete: mockDelete } };
});

import client from './client';
const mockedClient = vi.mocked(client);

describe('compliance API', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetchComplianceReports returns report list', async () => {
    const reports = [{ id: 'cr1', product_name: '测试' }];
    mockedClient.get.mockResolvedValueOnce({ data: reports });

    const result = await fetchComplianceReports();
    expect(result).toEqual(reports);
    expect(mockedClient.get).toHaveBeenCalledWith('/api/compliance/reports');
  });

  it('fetchComplianceReport returns single report', async () => {
    const report = { id: 'cr1', product_name: '测试' };
    mockedClient.get.mockResolvedValueOnce({ data: report });

    const result = await fetchComplianceReport('cr1');
    expect(result).toEqual(report);
    expect(mockedClient.get).toHaveBeenCalledWith('/api/compliance/reports/cr1');
  });

  it('deleteComplianceReport calls delete', async () => {
    mockedClient.delete.mockResolvedValueOnce({ data: null });
    await deleteComplianceReport('cr1');
    expect(mockedClient.delete).toHaveBeenCalledWith('/api/compliance/reports/cr1');
  });

  it('parseFile posts form data', async () => {
    const parsed = { combined_text: 'test' };
    mockedClient.post.mockResolvedValueOnce({ data: parsed });

    const file = new File(['content'], 'test.docx');
    const result = await parseFile(file);
    expect(result).toEqual(parsed);
    expect(mockedClient.post).toHaveBeenCalledWith(
      '/api/compliance/parse-file',
      expect.any(FormData),
      expect.objectContaining({ headers: { 'Content-Type': 'multipart/form-data' } }),
    );
  });

  it('parseRichText posts html content', async () => {
    const parsed = { combined_text: 'test' };
    mockedClient.post.mockResolvedValueOnce({ data: parsed });

    const result = await parseRichText('<p>test</p>', '产品名');
    expect(result).toEqual(parsed);
    expect(mockedClient.post).toHaveBeenCalledWith(
      '/api/compliance/parse-rich-text',
      { html_content: '<p>test</p>', product_name: '产品名' },
      expect.objectContaining({ timeout: 180000 }),
    );
  });

  it('fetchCategories returns category list', async () => {
    mockedClient.get.mockResolvedValueOnce({ data: { categories: ['重疾险', '医疗险'] } });

    const result = await fetchCategories();
    expect(result).toEqual(['重疾险', '医疗险']);
    expect(mockedClient.get).toHaveBeenCalledWith('/api/compliance/categories');
  });
});

describe('checkDocumentStream', () => {
  const mockFetch = vi.fn();
  vi.stubGlobal('fetch', mockFetch);
  vi.stubGlobal('localStorage', { getItem: vi.fn(() => null) });

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls onViolation for violation events', async () => {
    const violationData = { clause_number: '3.2', clause_content: 'test', status: 'non_compliant' };
    const doneData = {
      report_id: 'r1',
      summary: { compliant: 0, non_compliant: 1, attention: 0 },
      regulation_sources: {},
      regulations: [{ chunk_id: 'chunk-1', law_name: '法规', article_number: '第一条', content: '原文', source_type: 'category' }],
      decisions: [{ task_id: 'task-1', regulation_unit_id: 'unit-1', status: 'non_compliant' }],
      audit_status: 'completed',
      compliance_conclusion: 'non_compliant',
    };
    const sseData = `data: ${JSON.stringify({ type: 'violation', data: violationData })}\n\ndata: ${JSON.stringify({ type: 'done', data: doneData })}\n\n`;

    const reader = {
      read: vi.fn()
        .mockResolvedValueOnce({ done: false, value: new TextEncoder().encode(sseData) })
        .mockResolvedValueOnce({ done: true }),
    };
    mockFetch.mockResolvedValueOnce({ ok: true, body: { getReader: () => reader }, status: 200 });

    const onViolation = vi.fn();
    const onDone = vi.fn();
    const onProgress = vi.fn();
    const onError = vi.fn();

    checkDocumentStream(
      { document_content: 'test' },
      { onViolation, onProgress, onDone, onError },
    );

    await vi.waitFor(() => expect(onDone).toHaveBeenCalled());

    expect(onViolation).toHaveBeenCalledWith(expect.objectContaining({ clause_number: '3.2' }));
    expect(onDone).toHaveBeenCalledWith(expect.objectContaining({
      report_id: 'r1',
      regulations: expect.arrayContaining([expect.objectContaining({ chunk_id: 'chunk-1' })]),
      decisions: expect.arrayContaining([expect.objectContaining({ regulation_unit_id: 'unit-1' })]),
      items: [expect.objectContaining({ clause_number: '3.2' })],
    }));
    expect(onError).not.toHaveBeenCalled();
  });

  it('reports incomplete when the stream ends before a terminal event', async () => {
    const reader = {
      read: vi.fn()
        .mockResolvedValueOnce({
          done: false,
          value: new TextEncoder().encode('data: {"type":"progress","data":"处理中"}\n\n'),
        })
        .mockResolvedValueOnce({ done: true }),
    };
    mockFetch.mockResolvedValueOnce({ ok: true, body: { getReader: () => reader }, status: 200 });
    const onError = vi.fn();
    const onDone = vi.fn();

    checkDocumentStream(
      { document_content: 'test' },
      { onViolation: vi.fn(), onProgress: vi.fn(), onDone, onError },
    );

    await vi.waitFor(() => expect(onError).toHaveBeenCalledWith(
      '审核连接在终态前结束，审核结果不完整',
    ));
    expect(onDone).not.toHaveBeenCalled();
  });

  it('treats malformed data events as terminal errors', async () => {
    const reader = {
      read: vi.fn().mockResolvedValueOnce({
        done: false,
        value: new TextEncoder().encode('data: {not-json}\n\n'),
      }),
    };
    mockFetch.mockResolvedValueOnce({ ok: true, body: { getReader: () => reader }, status: 200 });
    const onError = vi.fn();

    checkDocumentStream(
      { document_content: 'test' },
      { onViolation: vi.fn(), onProgress: vi.fn(), onDone: vi.fn(), onError },
    );

    await vi.waitFor(() => expect(onError).toHaveBeenCalledWith(
      '审核服务返回了无法解析的事件，审核结果不完整',
    ));
    expect(onError).toHaveBeenCalledTimes(1);
  });

  it('sends parsed blocks and product tags to the audit endpoint', async () => {
    const reader = {
      read: vi.fn()
        .mockResolvedValueOnce({
          done: false,
          value: new TextEncoder().encode(
            `data: ${JSON.stringify({ type: 'error', data: 'stop' })}\n\n`,
          ),
        }),
    };
    mockFetch.mockResolvedValueOnce({ ok: true, body: { getReader: () => reader }, status: 200 });
    const params = {
      document_content: 'test',
      audit_blocks: [{
        clause_id: 'doc:clause:0',
        block_type: 'clause',
        source_index: 0,
        number: '1',
        title: '等待期',
        content: '等待期为30日',
        topics: ['waiting_period'],
        hierarchy_level: 1,
        parent_number: null,
        ancestor_numbers: [],
        hierarchy_path: '1',
        container_only: false,
      }],
      product_tags: { line: 'health' },
    };

    checkDocumentStream(
      params,
      { onViolation: vi.fn(), onProgress: vi.fn(), onDone: vi.fn(), onError: vi.fn() },
    );

    await vi.waitFor(() => expect(mockFetch).toHaveBeenCalled());
    expect(JSON.parse(mockFetch.mock.calls[0][1].body as string)).toEqual(params);
  });

  it('streams regulation decisions from the candidate endpoint', async () => {
    const candidateFreeze = {
      candidate_count: 2,
      excluded_count: 3,
      degraded: false,
      warnings: [],
    };
    const decision = {
      task_id: 'task-1',
      regulation_unit_id: 'unit-1',
      status: 'manual_review',
      completed: 1,
      total: 2,
    };
    const sseData = [
      `data: ${JSON.stringify({ type: 'candidate_freeze', data: candidateFreeze })}`,
      `data: ${JSON.stringify({ type: 'regulation_decision', data: decision })}`,
      `data: ${JSON.stringify({
        type: 'done',
        data: {
          report_id: 'r1',
          items: [{
            clause_number: '2.1',
            check_type: 'regulation_unit',
            clause_content: '等待期为30日',
            status: 'non_compliant',
            chunk_id: 'chunk-1',
            suggestion: '修改等待期',
          }],
        },
      })}`,
      '',
    ].join('\n\n');
    const reader = {
      read: vi.fn()
        .mockResolvedValueOnce({ done: false, value: new TextEncoder().encode(sseData) })
        .mockResolvedValueOnce({ done: true }),
    };
    mockFetch.mockResolvedValueOnce({ ok: true, body: { getReader: () => reader }, status: 200 });
    const onDecision = vi.fn();
    const onCandidateFreeze = vi.fn();
    const onDone = vi.fn();

    checkDocumentV2Stream(
      { document_content: 'test' },
      {
        onViolation: vi.fn(),
        onCandidateFreeze,
        onDecision,
        onProgress: vi.fn(),
        onDone,
        onError: vi.fn(),
      },
    );

    await vi.waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/compliance/check/document/v2/stream',
      expect.any(Object),
    );
    expect(onDecision).toHaveBeenCalledWith(expect.objectContaining({
      regulation_unit_id: 'unit-1',
      completed: 1,
      total: 2,
    }));
    expect(onCandidateFreeze).toHaveBeenCalledWith(candidateFreeze);
    expect(onDone).toHaveBeenCalledWith(expect.objectContaining({
      items: [expect.objectContaining({
        clause_number: '2.1',
        chunk_id: 'chunk-1',
      })],
    }));
  });

  it('prefers final server items over locally streamed items', async () => {
    const streamedItem = {
      clause_number: '1.1',
      check_type: 'legacy',
      clause_content: '流式旧明细',
      status: 'non_compliant',
      chunk_id: 'old-chunk',
      suggestion: '',
    };
    const serverItem = {
      clause_number: '2.1',
      check_type: 'regulation_unit',
      clause_content: '服务端最终明细',
      status: 'non_compliant',
      chunk_id: 'server-chunk',
      suggestion: '按法规修改',
    };
    const sseData = [
      `data: ${JSON.stringify({ type: 'violation', data: streamedItem })}`,
      `data: ${JSON.stringify({
        type: 'done',
        data: { report_id: 'r1', items: [serverItem] },
      })}`,
      '',
    ].join('\n\n');
    const reader = {
      read: vi.fn()
        .mockResolvedValueOnce({ done: false, value: new TextEncoder().encode(sseData) })
        .mockResolvedValueOnce({ done: true }),
    };
    mockFetch.mockResolvedValueOnce({
      ok: true,
      body: { getReader: () => reader },
      status: 200,
    });
    const onDone = vi.fn();

    checkDocumentV2Stream(
      { document_content: 'test' },
      {
        onViolation: vi.fn(),
        onProgress: vi.fn(),
        onDone,
        onError: vi.fn(),
      },
    );

    await vi.waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(onDone).toHaveBeenCalledWith(expect.objectContaining({
      items: [expect.objectContaining({
        clause_number: '2.1',
        chunk_id: 'server-chunk',
      })],
    }));
  });

  it('calls onError on fetch failure', async () => {
    mockFetch.mockRejectedValueOnce(new Error('Network error'));

    const onError = vi.fn();
    const onDone = vi.fn();
    const onViolation = vi.fn();
    const onProgress = vi.fn();

    checkDocumentStream(
      { document_content: 'test' },
      { onViolation, onProgress, onDone, onError },
    );

    await vi.waitFor(() => expect(onError).toHaveBeenCalledWith('Network error'));
  });

  it('calls onError on non-ok response', async () => {
    mockFetch.mockResolvedValueOnce({ ok: false, status: 500, statusText: 'Internal Error' });

    const onError = vi.fn();
    const onDone = vi.fn();
    const onViolation = vi.fn();
    const onProgress = vi.fn();

    checkDocumentStream(
      { document_content: 'test' },
      { onViolation, onProgress, onDone, onError },
    );

    await vi.waitFor(() => expect(onError).toHaveBeenCalledWith('HTTP 500: Internal Error'));
  });

  it('returns an AbortController', () => {
    const reader = {
      read: vi.fn().mockResolvedValue({ done: true }),
    };
    mockFetch.mockResolvedValueOnce({ ok: true, body: { getReader: () => reader }, status: 200 });

    const controller = checkDocumentStream(
      { document_content: 'test' },
      { onViolation: vi.fn(), onProgress: vi.fn(), onDone: vi.fn(), onError: vi.fn() },
    );

    expect(controller).toBeInstanceOf(AbortController);
  });
});

import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  fetchComplianceReports,
  fetchComplianceReport,
  deleteComplianceReport,
  parseFile,
  parseRichText,
  fetchCategories,
  checkDocumentStream,
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

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls onViolation for violation events', async () => {
    const violationData = { clause_number: '3.2', clause_content: 'test', status: 'non_compliant' };
    const sseData = `data: ${JSON.stringify({ type: 'violation', data: violationData })}\n\ndata: ${JSON.stringify({ type: 'done', data: { report_id: 'r1', summary: { compliant: 0, non_compliant: 1, attention: 0 }, regulation_sources: {} } })}\n\n`;

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
    expect(onDone).toHaveBeenCalledWith(expect.objectContaining({ report_id: 'r1' }));
    expect(onError).not.toHaveBeenCalled();
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

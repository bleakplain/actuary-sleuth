import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  checkDocument,
  fetchComplianceReports,
  fetchComplianceReport,
} from './compliance';

vi.mock('./client', () => {
  const mockGet = vi.fn();
  const mockPost = vi.fn();
  return { default: { get: mockGet, post: mockPost } };
});

import client from './client';
const mockedClient = vi.mocked(client);

describe('compliance API', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('checkDocument posts document check', async () => {
    const report = {
      id: 'cr2',
      product_name: '未命名产品',
      category: '',
      mode: 'document',
      result: { summary: { compliant: 1, non_compliant: 0, attention: 0 }, items: [] },
      created_at: '',
    };
    mockedClient.post.mockResolvedValueOnce({ data: report });

    const result = await checkDocument({
      document_content: '等待期：90天',
    });
    expect(result).toEqual(report);
    expect(mockedClient.post).toHaveBeenCalledWith('/api/compliance/check/document', {
      document_content: '等待期：90天',
    });
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
});

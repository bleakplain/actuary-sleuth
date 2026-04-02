import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  fetchDocuments,
  importDocuments,
  rebuildIndex,
  fetchTaskStatus,
  fetchDocumentPreview,
  fetchIndexStatus,
} from './knowledge';

vi.mock('./client', () => {
  const mockGet = vi.fn();
  const mockPost = vi.fn();
  return { default: { get: mockGet, post: mockPost } };
});

import client from './client';
const mockedClient = vi.mocked(client);

describe('knowledge API', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetchDocuments returns document list', async () => {
    const docs = [{ name: '01_保险法.md', file_size: 1234, clause_count: 10 }];
    mockedClient.get.mockResolvedValueOnce({ data: docs });

    const result = await fetchDocuments();
    expect(result).toEqual(docs);
    expect(mockedClient.get).toHaveBeenCalledWith('/api/kb/documents');
  });

  it('importDocuments sends import request', async () => {
    mockedClient.post.mockResolvedValueOnce({ data: { task_id: 't1' } });

    const result = await importDocuments('*.md');
    expect(result).toEqual({ task_id: 't1' });
    expect(mockedClient.post).toHaveBeenCalledWith('/api/kb/documents/import', {
      file_path: undefined,
      file_pattern: '*.md',
    });
  });

  it('importDocuments passes file_path when provided', async () => {
    mockedClient.post.mockResolvedValueOnce({ data: { task_id: 't2' } });

    await importDocuments('*.md', '01_保险法.md');
    expect(mockedClient.post).toHaveBeenCalledWith('/api/kb/documents/import', {
      file_path: '01_保险法.md',
      file_pattern: '*.md',
    });
  });

  it('rebuildIndex sends rebuild request', async () => {
    mockedClient.post.mockResolvedValueOnce({ data: { task_id: 't3' } });

    const result = await rebuildIndex('*.md', true);
    expect(result).toEqual({ task_id: 't3' });
    expect(mockedClient.post).toHaveBeenCalledWith('/api/kb/documents/rebuild', {
      file_pattern: '*.md',
      force: true,
    });
  });

  it('fetchTaskStatus returns task status', async () => {
    const status = { task_id: 't1', status: 'completed', progress: 'done' };
    mockedClient.get.mockResolvedValueOnce({ data: status });

    const result = await fetchTaskStatus('t1');
    expect(result).toEqual(status);
    expect(mockedClient.get).toHaveBeenCalledWith('/api/kb/tasks/t1');
  });

  it('fetchDocumentPreview returns document preview', async () => {
    const preview = { name: '01_保险法.md', content: '# 保险法...', total_chars: 5000 };
    mockedClient.get.mockResolvedValueOnce({ data: preview });

    const result = await fetchDocumentPreview('01_保险法.md');
    expect(result).toEqual(preview);
    expect(mockedClient.get).toHaveBeenCalledWith('/api/kb/documents/01_%E4%BF%9D%E9%99%A9%E6%B3%95.md/preview');
  });

  it('fetchIndexStatus returns index status', async () => {
    const status = { vector_db: { doc_count: 100 }, bm25: { loaded: true, doc_count: 100 }, document_count: 100 };
    mockedClient.get.mockResolvedValueOnce({ data: status });

    const result = await fetchIndexStatus();
    expect(result).toEqual(status);
    expect(mockedClient.get).toHaveBeenCalledWith('/api/kb/status');
  });
});

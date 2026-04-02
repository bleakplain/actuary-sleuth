import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  fetchEvalSamples,
  createEvalSample,
  updateEvalSample,
  deleteEvalSample,
  importEvalSamples,
  fetchSnapshots,
  createSnapshot,
  restoreSnapshot,
  createEvalRun,
  fetchEvalRunStatus,
  fetchEvalRunReport,
  fetchEvalRunDetails,
  fetchEvalRuns,
  compareEvalRuns,
  exportEvalReport,
} from './eval';

vi.mock('./client', () => {
  const mockGet = vi.fn();
  const mockPost = vi.fn();
  const mockPut = vi.fn();
  const mockDelete = vi.fn();
  return { default: { get: mockGet, post: mockPost, put: mockPut, delete: mockDelete } };
});

import client from './client';
const mockedClient = vi.mocked(client);

describe('eval API', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetchEvalSamples returns samples', async () => {
    const samples = [{ id: 'f001', question: 'q1' }];
    mockedClient.get.mockResolvedValueOnce({ data: samples });

    const result = await fetchEvalSamples({ question_type: 'factual' });
    expect(result).toEqual(samples);
    expect(mockedClient.get).toHaveBeenCalledWith('/api/eval/dataset', {
      params: { question_type: 'factual' },
    });
  });

  it('fetchEvalSamples without params', async () => {
    mockedClient.get.mockResolvedValueOnce({ data: [] });

    await fetchEvalSamples();
    expect(mockedClient.get).toHaveBeenCalledWith('/api/eval/dataset', { params: undefined });
  });

  it('createEvalSample creates a sample', async () => {
    const sample = { id: 'f001', question: 'q1', question_type: 'factual' };
    mockedClient.post.mockResolvedValueOnce({ data: sample });

    const result = await createEvalSample(sample);
    expect(result).toEqual(sample);
    expect(mockedClient.post).toHaveBeenCalledWith('/api/eval/dataset/samples', sample);
  });

  it('updateEvalSample updates a sample', async () => {
    const sample = { id: 'f001', question: 'q1-updated' };
    mockedClient.put.mockResolvedValueOnce({ data: sample });

    const result = await updateEvalSample('f001', { question: 'q1-updated' });
    expect(result).toEqual(sample);
    expect(mockedClient.put).toHaveBeenCalledWith('/api/eval/dataset/samples/f001', {
      question: 'q1-updated',
      id: 'f001',
    });
  });

  it('deleteEvalSample deletes a sample', async () => {
    mockedClient.delete.mockResolvedValueOnce({});

    await deleteEvalSample('f001');
    expect(mockedClient.delete).toHaveBeenCalledWith('/api/eval/dataset/samples/f001');
  });

  it('importEvalSamples imports samples', async () => {
    mockedClient.post.mockResolvedValueOnce({ data: { imported: 2, total: 3 } });

    const result = await importEvalSamples([{ id: 'f001', question: 'q1' }]);
    expect(result).toEqual({ imported: 2, total: 3 });
    expect(mockedClient.post).toHaveBeenCalledWith('/api/eval/dataset/import', {
      samples: [{ id: 'f001', question: 'q1' }],
    });
  });

  it('fetchSnapshots returns snapshot list', async () => {
    const snapshots = [{ id: 's1', name: 'v1' }];
    mockedClient.get.mockResolvedValueOnce({ data: snapshots });

    const result = await fetchSnapshots();
    expect(result).toEqual(snapshots);
  });

  it('createSnapshot creates a snapshot', async () => {
    mockedClient.post.mockResolvedValueOnce({ data: { snapshot_id: 's1' } });

    const result = await createSnapshot('v1', 'desc');
    expect(result).toEqual({ snapshot_id: 's1' });
  });

  it('restoreSnapshot restores a snapshot', async () => {
    mockedClient.post.mockResolvedValueOnce({ data: { restored: 10 } });

    const result = await restoreSnapshot('s1');
    expect(result).toEqual({ restored: 10 });
  });

  it('createEvalRun creates an eval run', async () => {
    mockedClient.post.mockResolvedValueOnce({ data: { run_id: 'r1' } });

    const result = await createEvalRun({ mode: 'retrieval', top_k: 5 });
    expect(result).toEqual({ run_id: 'r1' });
  });

  it('fetchEvalRunStatus returns run status', async () => {
    const status = { run_id: 'r1', mode: 'retrieval', status: 'completed' };
    mockedClient.get.mockResolvedValueOnce({ data: status });

    const result = await fetchEvalRunStatus('r1');
    expect(result).toEqual(status);
  });

  it('fetchEvalRunReport returns report', async () => {
    const report = { retrieval: { precision_at_k: 0.8 } };
    mockedClient.get.mockResolvedValueOnce({ data: report });

    const result = await fetchEvalRunReport('r1');
    expect(result).toEqual(report);
  });

  it('fetchEvalRunDetails returns details', async () => {
    const details = { run_id: 'r1', details: [] };
    mockedClient.get.mockResolvedValueOnce({ data: details });

    const result = await fetchEvalRunDetails('r1');
    expect(result).toEqual(details);
  });

  it('fetchEvalRuns returns run list', async () => {
    const runs = [{ id: 'r1', status: 'completed' }];
    mockedClient.get.mockResolvedValueOnce({ data: runs });

    const result = await fetchEvalRuns();
    expect(result).toEqual(runs);
  });

  it('compareEvalRuns compares two runs', async () => {
    const diff = { improved: ['retrieval.precision_at_k'], regressed: [] };
    mockedClient.post.mockResolvedValueOnce({ data: diff });

    const result = await compareEvalRuns('r1', 'r2');
    expect(result).toEqual(diff);
    expect(mockedClient.post).toHaveBeenCalledWith('/api/eval/runs/compare', {
      baseline_id: 'r1',
      compare_id: 'r2',
    });
  });

  it('exportEvalReport returns blob for json', async () => {
    const blob = new Blob(['{"report":{}}'], { type: 'application/json' });
    mockedClient.get.mockResolvedValueOnce({ data: blob });

    const result = await exportEvalReport('r1', 'json');
    expect(result).toBe(blob);
    expect(mockedClient.get).toHaveBeenCalledWith('/api/eval/runs/r1/export', {
      params: { format: 'json' },
      responseType: 'blob',
    });
  });
});

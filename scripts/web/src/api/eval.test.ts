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
  createEvaluation,
  fetchEvaluationStatus,
  fetchEvaluationReport,
  fetchEvaluationDetails,
  fetchEvaluations,
  compareEvaluations,
  exportEvaluationReport,
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

  it('createEvaluation creates an evaluation', async () => {
    mockedClient.post.mockResolvedValueOnce({ data: { evaluation_id: 'e1' } });

    const result = await createEvaluation({ mode: 'retrieval', top_k: 5 });
    expect(result).toEqual({ evaluation_id: 'e1' });
  });

  it('fetchEvaluationStatus returns evaluation status', async () => {
    const status = { id: 'e1', mode: 'retrieval', status: 'completed' };
    mockedClient.get.mockResolvedValueOnce({ data: status });

    const result = await fetchEvaluationStatus('e1');
    expect(result).toEqual(status);
  });

  it('fetchEvaluationReport returns report', async () => {
    const report = { retrieval: { precision_at_k: 0.8 } };
    mockedClient.get.mockResolvedValueOnce({ data: report });

    const result = await fetchEvaluationReport('e1');
    expect(result).toEqual(report);
  });

  it('fetchEvaluationDetails returns details', async () => {
    const details = { evaluation_id: 'e1', details: [] };
    mockedClient.get.mockResolvedValueOnce({ data: details });

    const result = await fetchEvaluationDetails('e1');
    expect(result).toEqual(details);
  });

  it('fetchEvaluations returns evaluation list', async () => {
    const evaluations = [{ id: 'e1', status: 'completed' }];
    mockedClient.get.mockResolvedValueOnce({ data: evaluations });

    const result = await fetchEvaluations();
    expect(result).toEqual(evaluations);
  });

  it('compareEvaluations compares two evaluations', async () => {
    const diff = { improved: ['retrieval.precision_at_k'], regressed: [] };
    mockedClient.post.mockResolvedValueOnce({ data: diff });

    const result = await compareEvaluations('e1', 'e2');
    expect(result).toEqual(diff);
    expect(mockedClient.post).toHaveBeenCalledWith('/api/eval/evaluations/compare', {
      baseline_id: 'e1',
      compare_id: 'e2',
    });
  });

  it('exportEvaluationReport returns blob for json', async () => {
    const blob = new Blob(['{"report":{}}'], { type: 'application/json' });
    mockedClient.get.mockResolvedValueOnce({ data: blob });

    const result = await exportEvaluationReport('e1', 'json');
    expect(result).toBe(blob);
    expect(mockedClient.get).toHaveBeenCalledWith('/api/eval/evaluations/e1/export', {
      params: { format: 'json' },
      responseType: 'blob',
    });
  });
});

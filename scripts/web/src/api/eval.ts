import client from './client';
import type { EvalSample, EvalSnapshot, Evaluation, SampleResult } from '../types';

export async function fetchEvalSamples(params?: {
  question_type?: string;
  difficulty?: string;
  topic?: string;
}): Promise<EvalSample[]> {
  const { data } = await client.get('/api/eval/dataset', { params });
  return data;
}

export async function createEvalSample(sample: Partial<EvalSample>): Promise<EvalSample> {
  const { data } = await client.post('/api/eval/dataset/samples', sample);
  return data;
}

export async function updateEvalSample(id: string, sample: Partial<EvalSample>): Promise<EvalSample> {
  const { data } = await client.put(`/api/eval/dataset/samples/${id}`, { ...sample, id });
  return data;
}

export async function deleteEvalSample(id: string): Promise<void> {
  await client.delete(`/api/eval/dataset/samples/${id}`);
}

export async function importEvalSamples(samples: Partial<EvalSample>[]): Promise<{ imported: number; total: number }> {
  const { data } = await client.post('/api/eval/dataset/import', { samples });
  return data;
}

export async function fetchSnapshots(): Promise<EvalSnapshot[]> {
  const { data } = await client.get('/api/eval/dataset/snapshots');
  return data;
}

export async function createSnapshot(name: string, description: string): Promise<{ snapshot_id: string }> {
  const { data } = await client.post('/api/eval/dataset/snapshots', { name, description });
  return data;
}

export async function restoreSnapshot(snapshotId: string): Promise<{ restored: number }> {
  const { data } = await client.post(`/api/eval/dataset/snapshots/${snapshotId}/restore`);
  return data;
}

export async function createEvaluation(config: {
  mode: 'retrieval' | 'generation' | 'full';
  top_k?: number;
  chunking?: string;
}): Promise<{ evaluation_id: string }> {
  const { data } = await client.post('/api/eval/evaluations', config);
  return data;
}

export async function fetchEvaluationStatus(evaluationId: string): Promise<Evaluation> {
  const { data } = await client.get(`/api/eval/evaluations/${evaluationId}/status`);
  return data;
}

export async function fetchEvaluationReport(evaluationId: string): Promise<Record<string, Record<string, number>>> {
  const { data } = await client.get(`/api/eval/evaluations/${evaluationId}/report`);
  return data;
}

export async function fetchEvaluationDetails(evaluationId: string): Promise<{
  evaluation_id: string;
  mode: string;
  status: string;
  total_samples: number;
  details: SampleResult[];
}> {
  const { data } = await client.get(`/api/eval/evaluations/${evaluationId}/details`);
  return data;
}

export async function fetchEvaluations(): Promise<Evaluation[]> {
  const { data } = await client.get('/api/eval/evaluations');
  return data;
}

export async function compareEvaluations(baselineId: string, compareId: string): Promise<{
  metrics_diff: Record<string, { baseline: number; compare: number; delta: number; pct_change: number }>;
  improved: string[];
  regressed: string[];
}> {
  const { data } = await client.post('/api/eval/evaluations/compare', { baseline_id: baselineId, compare_id: compareId });
  return data;
}

export async function exportEvaluationReport(evaluationId: string, format: 'json' | 'md' = 'json'): Promise<Blob> {
  const { data } = await client.get(`/api/eval/evaluations/${evaluationId}/export`, {
    params: { format },
    responseType: 'blob',
  });
  return data;
}

import client from './client';
import type { EvalSample, EvalSnapshot, EvalRun, SampleResult } from '../types';

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

export async function createEvalRun(config: {
  mode: 'retrieval' | 'generation' | 'full';
  top_k?: number;
  chunking?: string;
}): Promise<{ run_id: string }> {
  const { data } = await client.post('/api/eval/runs', config);
  return data;
}

export async function fetchEvalRunStatus(runId: string): Promise<EvalRun> {
  const { data } = await client.get(`/api/eval/runs/${runId}/status`);
  return data;
}

export async function fetchEvalRunReport(runId: string): Promise<Record<string, Record<string, number>>> {
  const { data } = await client.get(`/api/eval/runs/${runId}/report`);
  return data;
}

export async function fetchEvalRunDetails(runId: string): Promise<{
  run_id: string;
  mode: string;
  status: string;
  total_samples: number;
  details: SampleResult[];
}> {
  const { data } = await client.get(`/api/eval/runs/${runId}/details`);
  return data;
}

export async function fetchEvalRuns(): Promise<EvalRun[]> {
  const { data } = await client.get('/api/eval/runs');
  return data;
}

export async function compareEvalRuns(baselineId: string, compareId: string): Promise<{
  metrics_diff: Record<string, { baseline: number; compare: number; delta: number; pct_change: number }>;
  improved: string[];
  regressed: string[];
}> {
  const { data } = await client.post('/api/eval/runs/compare', { baseline_id: baselineId, compare_id: compareId });
  return data;
}

export async function exportEvalReport(runId: string, format: 'json' | 'md' = 'json'): Promise<Blob> {
  const { data } = await client.get(`/api/eval/runs/${runId}/export`, {
    params: { format },
    responseType: 'blob',
  });
  return data;
}

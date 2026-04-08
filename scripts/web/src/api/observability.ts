import client from './client';
import type { TraceListResponse, TraceData, CleanupRequest, CleanupResponse } from '../types';

export interface TraceSearchParams {
  trace_id?: string;
  session_id?: string;
  message_id?: string;
  status?: string;
  start_date?: string;
  end_date?: string;
  page?: number;
  size?: number;
}

export async function fetchTraces(params: TraceSearchParams = {}): Promise<TraceListResponse> {
  const { data } = await client.get('/api/observability/traces', { params });
  return data;
}

export async function fetchTraceDetail(traceId: string): Promise<TraceData> {
  const { data } = await client.get(`/api/observability/traces/${traceId}`);
  return data;
}

export async function batchDeleteTraces(ids: string[]): Promise<{ deleted: number }> {
  const { data } = await client.delete('/api/observability/traces', {
    params: { ids: ids.join(',') },
  });
  return data;
}

export async function cleanupTraces(req: CleanupRequest): Promise<CleanupResponse> {
  const { data } = await client.post('/api/observability/traces/cleanup', req);
  return data;
}

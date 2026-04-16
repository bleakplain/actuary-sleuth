import client from './client';
import type { TraceListResponse, TraceData, CleanupRequest, CleanupResponse, CacheStats, CacheEntryListResponse, CacheTrendResponse } from '../types';

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

export async function fetchCacheStats(): Promise<CacheStats | { status: string }> {
  const { data } = await client.get('/api/observability/cache/stats');
  return data;
}

export async function fetchCacheEntries(params: {
  namespace?: string;
  page?: number;
  size?: number;
} = {}): Promise<CacheEntryListResponse> {
  const { data } = await client.get('/api/observability/cache/entries', { params });
  return data;
}

export async function fetchCacheTrend(rangeHours: number = 24): Promise<CacheTrendResponse> {
  const { data } = await client.get('/api/observability/cache/trend', {
    params: { range_hours: rangeHours },
  });
  return data;
}

export async function cleanupCache(): Promise<{ deleted: number }> {
  const { data } = await client.post('/api/observability/cache/cleanup');
  return data;
}

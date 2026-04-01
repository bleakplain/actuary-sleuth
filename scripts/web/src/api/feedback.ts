import client from './client';
import type { Feedback, FeedbackStats, FeedbackActionLog, Source, Citation } from '../types';

export async function submitFeedback(params: {
  message_id: number;
  rating: 'up' | 'down';
  reason?: string;
  correction?: string;
}): Promise<Feedback> {
  const { data } = await client.post('/api/feedback/submit', params);
  return data;
}

export async function fetchBadcases(params?: {
  status?: string;
  classified_type?: string;
  compliance_risk?: number;
}): Promise<Feedback[]> {
  const { data } = await client.get('/api/feedback/badcases', { params });
  return data;
}

export async function fetchBadcase(id: string): Promise<Feedback> {
  const { data } = await client.get(`/api/feedback/badcases/${id}`);
  return data;
}

export async function updateBadcase(
  id: string,
  updates: {
    status?: string;
    classified_type?: string;
    classified_reason?: string;
    classified_fix_direction?: string;
    compliance_risk?: number;
    fix_action?: string;
  },
): Promise<Feedback> {
  const { data } = await client.put(`/api/feedback/badcases/${id}`, updates);
  return data;
}

export async function fetchFeedbackStats(): Promise<FeedbackStats> {
  const { data } = await client.get('/api/feedback/stats');
  return data;
}

export async function verifyBadcase(id: string): Promise<{
  feedback_id: string;
  original_answer: string;
  new_answer: string;
  new_sources: Source[];
  new_citations: Citation[];
  new_faithfulness: number | null;
}> {
  const { data } = await client.post(`/api/feedback/badcases/${id}/verify`);
  return data;
}

export async function convertBadcase(id: string, ground_truth: string): Promise<{
  sample_id: string;
  feedback_id: string;
}> {
  const { data } = await client.post(`/api/feedback/badcases/${id}/convert`, null, {
    params: { ground_truth },
  });
  return data;
}

export async function fetchBadcaseHistory(id: string): Promise<FeedbackActionLog[]> {
  const { data } = await client.get(`/api/feedback/badcases/${id}/history`);
  return data;
}

export async function classifyBadcases(): Promise<void> {
  await client.post('/api/feedback/badcases/classify');
}

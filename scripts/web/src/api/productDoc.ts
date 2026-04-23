import client from './client';

export type ReviewStatus = 'pending' | 'approved' | 'rejected';

export interface ParsedDocument {
  id: string;
  file_name: string;
  file_path: string | null;
  file_type: string;
  clauses: Array<{ number: string; title: string; text: string }>;
  premium_tables: Array<{ raw_text: string; data: string[][] }>;
  notices: Array<{ title: string; content: string }>;
  health_disclosures: Array<{ title: string; content: string }>;
  exclusions: Array<{ title: string; content: string }>;
  rider_clauses: Array<{ number: string; title: string; text: string }>;
  raw_content: string | null;
  parse_time: string;
  warnings: string[];
  review_status: ReviewStatus;
  reviewer: string | null;
  reviewed_at: string | null;
  review_comment: string | null;
}

export async function fetchParsedDocuments(params?: {
  review_status?: ReviewStatus;
}): Promise<ParsedDocument[]> {
  const { data } = await client.get('/api/product-docs', { params });
  return data;
}

export async function fetchParsedDocument(docId: string): Promise<ParsedDocument> {
  const { data } = await client.get(`/api/product-docs/${docId}`);
  return data;
}

export async function reviewDocument(docId: string, request: {
  reviewer: string;
  comment?: string;
  status: Exclude<ReviewStatus, 'pending'>;
}): Promise<{ id: string; status: string }> {
  const { data } = await client.patch(`/api/product-docs/${docId}/review`, request);
  return data;
}
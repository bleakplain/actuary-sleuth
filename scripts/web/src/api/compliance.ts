import client from './client';
import type { ComplianceReport, AuditResultItem, AuditRegulationItem, ParsedDocument } from '../types';

interface DoneData {
  report_id: string;
  product_name: string;
  category: string;
  summary: { compliant: number; non_compliant: number; attention: number };
  negative_list_result: string;
  regulation_sources: Record<string, string[]>;
  regulations: AuditRegulationItem[];
  clause_coverage: {
    total: number;
    checked: number;
    flagged: number;
    unchecked: string[];
    all_total: number;
    definition_chapter?: string;
    has_notices?: boolean;
    has_health?: boolean;
    has_exclusions?: boolean;
    has_tables?: boolean;
  };
}

export function checkDocumentStream(
  params: { document_content: string; product_name?: string; category?: string },
  callbacks: {
    onViolation: (item: AuditResultItem) => void;
    onProgress: (msg: string) => void;
    onDone: (data: DoneData & { items: AuditResultItem[] }) => void;
    onError: (err: string) => void;
  },
): AbortController {
  const controller = new AbortController();

  fetch('/api/compliance/check/document/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }
      const reader = res.body?.getReader();
      if (!reader) throw new Error('No response body');
      const decoder = new TextDecoder();
      let buffer = '';
      const items: AuditResultItem[] = [];

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data:')) continue;
          try {
            const data = JSON.parse(line.slice(5).trim());
            if (data.type === 'violation') {
              const item = data.data as AuditResultItem;
              items.push(item);
              callbacks.onViolation(item);
            } else if (data.type === 'progress') {
              callbacks.onProgress(data.data);
            } else if (data.type === 'done') {
              callbacks.onDone({ ...data.data, items });
            } else if (data.type === 'error') {
              callbacks.onError(data.data);
            }
          } catch {
            // skip malformed SSE lines
          }
        }
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        callbacks.onError(err.message);
      }
    });

  return controller;
}

export async function fetchComplianceReports(): Promise<ComplianceReport[]> {
  const { data } = await client.get('/api/compliance/reports');
  return data;
}

export async function fetchComplianceReport(id: string): Promise<ComplianceReport> {
  const { data } = await client.get(`/api/compliance/reports/${id}`);
  return data;
}

export async function deleteComplianceReport(id: string): Promise<void> {
  await client.delete(`/api/compliance/reports/${id}`);
}

export async function parseFile(file: File): Promise<ParsedDocument> {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await client.post('/api/compliance/parse-file', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 180000,
  });
  return data;
}

export async function parseRichText(htmlContent: string, productName?: string): Promise<ParsedDocument> {
  const { data } = await client.post('/api/compliance/parse-rich-text', {
    html_content: htmlContent,
    product_name: productName,
  }, { timeout: 180000 });
  return data;
}

export async function fetchCategories(): Promise<string[]> {
  const { data } = await client.get('/api/compliance/categories');
  return data.categories;
}

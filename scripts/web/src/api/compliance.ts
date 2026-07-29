import client from './client';
import type {
  AuditRegulationItem,
  AuditResultItem,
  AuditStatus,
  CandidateFreezeProgress,
  ComplianceConclusion,
  ComplianceReport,
  ExcludedRegulationUnit,
  ParsedAuditBlock,
  ParsedDocument,
  RegulationDecision,
  RegulationDecisionProgress,
} from '../types';

export interface DoneData {
  report_id: string;
  product_name: string;
  category: string;
  summary: { compliant: number; non_compliant: number; attention: number };
  negative_list_result: string | null;
  regulations: AuditRegulationItem[];
  excluded_regulations: ExcludedRegulationUnit[];
  decisions: RegulationDecision[];
  product_tags: Record<string, unknown>;
  document_fingerprint: string;
  audit_input_fingerprint: string;
  product_name_source: string;
  parse_warnings: string[];
  regulation_sources: Record<string, string[]>;
  retrieval_degraded: boolean;
  retrieval_warnings: string[];
  audit_status: AuditStatus;
  compliance_conclusion: ComplianceConclusion;
  kb_version: string;
  topic_taxonomy_version: string;
  topic_relations_version: string;
  evaluation_dataset_version: string;
  evaluation_dataset_status?: string;
  cutover_gate_status?: string;
  candidate_count: number;
  excluded_count: number;
  completed_count: number;
  failed_count: number;
  failure_reasons: string[];
  items?: AuditResultItem[];
  clause_coverage: {
    total: number;
    checked: number;
    unchecked: string[];
    all_total: number;
    definition_chapter?: string;
    has_notices?: boolean;
    has_health?: boolean;
    has_exclusions?: boolean;
    has_tables?: boolean;
  } | null;
}

type StreamParams = {
  document_content: string;
  parse_id?: string;
  parse_attestation?: string;
  document_fingerprint?: string;
  audit_input_fingerprint?: string;
  product_name?: string;
  product_name_source?: string;
  coverage_attested?: boolean;
  parse_warnings?: string[];
  category?: string;
  clause_topics?: string[];
  audit_blocks?: ParsedAuditBlock[];
  product_tags?: Record<string, unknown>;
};

type StreamCallbacks = {
  onViolation: (item: AuditResultItem) => void;
  onCandidateFreeze?: (progress: CandidateFreezeProgress) => void;
  onDecision?: (decision: RegulationDecisionProgress) => void;
  onProgress: (msg: string) => void;
  onDone: (data: DoneData & { items: AuditResultItem[] }) => void;
  onError: (err: string) => void;
};

function startDocumentStream(
  endpoint: string,
  params: StreamParams,
  callbacks: StreamCallbacks,
): AbortController {
  const controller = new AbortController();
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  const token = localStorage.getItem('auth_token');
  if (token) headers['Authorization'] = `Bearer ${token}`;

  fetch(endpoint, {
    method: 'POST',
    headers,
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
      let terminalReceived = false;

      const failOnce = (error: string) => {
        if (terminalReceived) return;
        terminalReceived = true;
        callbacks.onError(error);
      };

      const processLine = (rawLine: string): boolean => {
        const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine;
        if (!line.startsWith('data:') || terminalReceived) return terminalReceived;
        const payload = line.slice(5).trim();
        if (!payload) return false;
        let event: { type?: string; data?: unknown };
        try {
          event = JSON.parse(payload) as { type?: string; data?: unknown };
        } catch {
          failOnce('审核服务返回了无法解析的事件，审核结果不完整');
          return true;
        }
        if (event.type === 'violation') {
          const item = event.data as AuditResultItem;
          items.push(item);
          callbacks.onViolation(item);
        } else if (event.type === 'progress') {
          callbacks.onProgress(String(event.data ?? ''));
        } else if (event.type === 'candidate_freeze') {
          callbacks.onCandidateFreeze?.(
            event.data as CandidateFreezeProgress,
          );
        } else if (event.type === 'regulation_decision') {
          callbacks.onDecision?.(
            event.data as RegulationDecisionProgress,
          );
        } else if (event.type === 'done') {
          const doneData = event.data as DoneData;
          const finalItems = Array.isArray(doneData.items)
            ? doneData.items
            : items;
          terminalReceived = true;
          callbacks.onDone({ ...doneData, items: finalItems });
        } else if (event.type === 'error') {
          failOnce(typeof event.data === 'string'
            ? event.data
            : '审核服务报告失败，审核结果不完整');
        }
        return terminalReceived;
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (processLine(line)) break;
        }
        if (terminalReceived) break;
      }
      buffer += decoder.decode();
      if (!terminalReceived && buffer.trim()) {
        processLine(buffer);
      }
      if (!terminalReceived) {
        failOnce('审核连接在终态前结束，审核结果不完整');
      }
    })
    .catch((err) => {
      if (err.name !== 'AbortError') {
        callbacks.onError(err.message);
      }
    });

  return controller;
}

export function checkDocumentStream(
  params: StreamParams,
  callbacks: StreamCallbacks,
): AbortController {
  return startDocumentStream(
    '/api/compliance/check/document/stream',
    params,
    callbacks,
  );
}

export function checkDocumentV2Stream(
  params: StreamParams,
  callbacks: StreamCallbacks,
): AbortController {
  return startDocumentStream(
    '/api/compliance/check/document/v2/stream',
    params,
    callbacks,
  );
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

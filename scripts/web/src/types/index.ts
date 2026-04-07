export interface Citation {
  source_idx: number;
  law_name: string;
  article_number: string;
  content: string;
}

export interface Source {
  law_name: string;
  article_number: string;
  category: string;
  content: string;
  source_file: string;
  hierarchy_path: string;
  doc_number?: string;
  effective_date?: string;
  issuing_authority?: string;
  score?: number;
}

export interface Message {
  id: number;
  conversation_id: string;
  role: 'user' | 'assistant';
  content: string;
  citations: Citation[];
  sources: Source[];
  timestamp: string;
  faithfulness_score?: number;
  unverified_claims?: string[];
  trace?: TraceData | null;
}

export interface Conversation {
  id: string;
  title: string;
  created_at: string;
  message_count: number;
}

export interface ChatRequest {
  question: string;
  conversation_id?: string;
  mode: 'qa' | 'search';
  debug?: boolean;
}

export interface Document {
  name: string;
  file_path: string;
  clause_count: number;
  file_size: number;
  indexed_at?: string;
  status: string;
}

export interface IndexStatus {
  vector_db: Record<string, string | number>;
  bm25: Record<string, string | number>;
  document_count: number;
}

export interface TaskStatus {
  task_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: string;
  result?: Record<string, string | number>;
}

export interface EvalSample {
  id: string;
  question: string;
  ground_truth: string;
  evidence_docs: string[];
  evidence_keywords: string[];
  question_type: 'factual' | 'multi_hop' | 'negative' | 'colloquial';
  difficulty: 'easy' | 'medium' | 'hard';
  topic: string;
  created_at: string;
  updated_at: string;
}

export interface EvalSnapshot {
  id: string;
  name: string;
  description: string;
  sample_count: number;
  created_at: string;
}

export interface Evaluation {
  id: string;
  mode: 'retrieval' | 'generation' | 'full' | 'llm_judge';
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: number;
  total: number;
  started_at: string;
  finished_at?: string;
  config?: {
    retrieval?: Record<string, string | number | boolean>;
    generation?: Record<string, string | number | boolean>;
    evaluation?: Record<string, string>;
    dataset?: Record<string, string | number | null>;
  };
}

export interface EvalConfig {
  id: number;
  name: string;
  version: number;
  description: string;
  is_active: number;
  created_at: string;
  config_json?: {
    retrieval?: Record<string, string | number | boolean>;
    rerank?: Record<string, string | number | boolean>;
    generation?: Record<string, string | number | boolean>;
  };
}

export interface SampleResult {
  id: number;
  evaluation_id: string;
  sample_id: string;
  retrieved_docs: Source[];
  generated_answer: string;
  retrieval_metrics: Record<string, number>;
  generation_metrics: Record<string, number>;
}

export interface MetricsDiff {
  baseline: number;
  compare: number;
  delta: number;
  pct_change: number;
}

export interface ComplianceItem {
  param: string;
  value?: string | number;
  requirement: string;
  status: 'compliant' | 'non_compliant' | 'attention';
  source?: string;
  source_excerpt?: string;
  suggestion?: string;
}

export interface ComplianceResult {
  summary: {
    compliant: number;
    non_compliant: number;
    attention: number;
  };
  items: ComplianceItem[];
  sources?: Source[];
  citations?: Citation[];
  extracted_params?: Record<string, string>;
}

export interface ComplianceReport {
  id: string;
  product_name: string;
  category: string;
  mode: 'product' | 'document';
  result: ComplianceResult;
  created_at: string;
}

export interface Feedback {
  id: string;
  message_id: number;
  conversation_id: string;
  rating: 'up' | 'down';
  reason: string;
  correction: string;
  source_channel: string;
  auto_quality_score: number | null;
  auto_quality_details: Record<string, number> | null;
  classified_type: string | null;
  classified_reason: string | null;
  classified_fix_direction: string | null;
  status: 'pending' | 'classified' | 'fixing' | 'fixed' | 'rejected' | 'converted';
  compliance_risk: number;
  created_at: string;
  updated_at: string;
  user_question: string;
  assistant_answer: string;
}

export interface FeedbackStats {
  total: number;
  up_count: number;
  down_count: number;
  satisfaction_rate: number;
  by_type: Record<string, number>;
  by_status: Record<string, number>;
  by_risk: Record<string, number>;
}

export interface TraceSpan {
  span_id: string;
  trace_id: string;
  parent_span_id: string | null;
  name: string;
  category: string;
  input: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  metadata: Record<string, unknown>;
  start_time: number;
  end_time: number;
  duration_ms: number;
  status: 'ok' | 'error';
  error: string | null;
  children: TraceSpan[];
}

export interface TraceSummary {
  total_duration_ms: number;
  span_count: number;
  llm_call_count: number;
  error_count: number;
}

export interface TraceData {
  trace_id: string;
  root: TraceSpan;
  spans: TraceSpan[];
  summary: TraceSummary;
}

// ── Observability ──

export interface TraceListItem {
  trace_id: string;
  message_id: number | null;
  conversation_id: string | null;
  created_at: string;
  status: 'ok' | 'error';
  total_duration_ms: number;
  span_count: number;
  llm_call_count: number;
  trace_name: string | null;
}

export interface TraceListResponse {
  items: TraceListItem[];
  total: number;
}

export interface CleanupRequest {
  start_date: string;
  end_date: string;
  status: string;
  preview: boolean;
}

export interface CleanupResponse {
  count?: number;
  deleted?: number;
}

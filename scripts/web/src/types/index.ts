export interface AuditRegulationItem {
  chunk_id: string;
  law_name: string;
  article_number: string;
  content: string;
  source_type: string;
  doc_number?: string;
  issuing_authority?: string;
  effective_date?: string;
}

export interface AuditResultItem {
  clause_number: string;
  check_type: string;
  clause_content: string;
  status: string;
  chunk_id: string | null;
  source_ref?: string;
  suggestion: string;
  conclusion?: string;
}

export interface ComplianceResult {
  summary: Record<string, number>;
  items: AuditResultItem[];
  regulations: AuditRegulationItem[];
  regulation_sources: Record<string, string[]>;
  category: string;
  negative_list_result: string;
  clause_coverage: {
    total: number;
    checked: number;
    unchecked: string[];
    has_notices?: boolean;
    has_health?: boolean;
    has_exclusions?: boolean;
    has_tables?: boolean;
  } | null;
}

export interface ComplianceReport {
  id: string;
  product_name: string;
  category: string;
  mode: string;
  result: ComplianceResult;
  created_at: string;
}

export interface ParsedClause {
  number: string;
  title: string;
  text: string;
}

export interface ParsedDataTable {
  table_type: string;
  remark: string;
  raw_text: string;
  data: string[][];
}

export interface ParsedSection {
  title: string;
  content: string;
}

export interface ParsedDocument {
  parse_id: string;
  file_name: string;
  file_type: string;
  clauses: ParsedClause[];
  data_tables: ParsedDataTable[];
  notices: ParsedSection[];
  health_disclosures: ParsedSection[];
  exclusions: ParsedSection[];
  rider_clauses: ParsedClause[];
  warnings: string[];
  combined_text: string;
  parse_time: string;
  identified_category: string | null;
  category_confidence: number;
  product_name?: string | null;
  is_rider?: boolean;
  group_or_individual?: string | null;
  duration_type?: string | null;
  design_type?: string | null;
  naming_warnings?: string[];
}

// ===== 法规问答（ask） =====

export interface Session {
  id: string;
  title: string;
  created_at: string;
  message_count: number;
}

export interface Source {
  law_name: string;
  article_number: string;
  category: string;
  content: string;
  source_file: string;
  hierarchy_path: string;
}

export interface Citation {
  source_idx: number;
  law_name: string;
  article_number: string;
  content: string;
}

export interface Message {
  id: number;
  session_id: string;
  role: string;
  content: string;
  citations: Citation[];
  sources: Source[];
  timestamp: string;
  trace?: TraceData | null;
}

// ===== Trace =====

export interface TraceSpan {
  span_id: string;
  trace_id: string;
  parent_span_id?: string | null;
  name: string;
  category: string;
  input?: Record<string, any> | null;
  output?: Record<string, any> | null;
  metadata?: Record<string, unknown>;
  start_time: number;
  end_time: number;
  duration_ms: number;
  status: string;
  error?: string | null;
  children: TraceSpan[];
}

export interface TraceData {
  trace_id: string;
  root: TraceSpan;
  spans: TraceSpan[];
  summary: {
    total_duration_ms: number;
    span_count: number;
    llm_call_count: number;
    error_count: number;
    status: string;
  };
}

export interface TraceListItem {
  trace_id: string;
  message_id?: number | null;
  session_id?: string | null;
  created_at: string;
  status: string;
  total_duration_ms: number;
  span_count: number;
  llm_call_count: number;
  trace_name?: string | null;
}

// ===== 可观测性（observability） =====

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

export interface CacheStats {
  memory_size: number;
  max_memory_entries: number;
  hits: number;
  misses: number;
  hit_rate: number;
  kb_version: string;
  evictions: number;
  l2_size: number;
  by_scope: Record<string, { hits: number; misses: number }>;
}

export interface CacheEntry {
  key: string;
  scope: string;
  created_at: number;
  ttl: number;
  kb_version: string;
  size_bytes: number;
}

export interface CacheEntryListResponse {
  items: CacheEntry[];
  total: number;
}

export interface CacheTrendPoint {
  timestamp: string;
  hits: number;
  misses: number;
  hit_rate: number;
  memory_size: number;
  evictions: number;
  l2_size: number;
}

export interface CacheTrendResponse {
  points: CacheTrendPoint[];
}

// ===== 知识库（knowledge） =====

export interface Document {
  name: string;
  file_path: string;
  clause_count: number;
  file_size: number;
  indexed_at: string | null;
  status: string;
}

export interface IndexStatus {
  vector_db: Record<string, unknown>;
  bm25: Record<string, unknown>;
  document_count: number;
}

export interface TaskStatus {
  task_id: string;
  status: string;
  progress: string;
  result?: Record<string, unknown> | null;
}

// ===== 反馈（feedback） =====

export interface Feedback {
  id: string;
  message_id: number;
  session_id: string;
  rating: string;
  reason: string;
  correction: string;
  source_channel: string;
  auto_quality_score: number | null;
  auto_quality_details: {
    faithfulness?: number;
    retrieval_relevance?: number;
    completeness?: number;
    [k: string]: unknown;
  } | null;
  classified_type: string | null;
  classified_reason: string | null;
  classified_fix_direction: string | null;
  status: string;
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

// ===== 评估（eval） =====

export interface RegulationRef {
  doc_name: string;
  article: string;
  excerpt: string;
  chunk_id: string;
}

export interface EvalSample {
  id: string;
  question: string;
  ground_truth: string;
  evidence_docs: string[];
  evidence_keywords: string[];
  question_type: string;
  difficulty: string;
  topic: string;
  regulation_refs: RegulationRef[];
  review_status: string;
  reviewer: string;
  reviewed_at: string;
  review_comment: string;
  created_by: string;
  kb_version: string;
  created_at: string;
  updated_at: string;
}

export interface EvalSnapshot {
  id: string;
  name: string;
  version: number;
  sample_count: number;
  created_at: string;
  hash_code?: string;
  description?: string;
}

export interface EvalConfig {
  id: number;
  version: number;
  description: string;
  is_active: boolean;
  created_at: string;
  config_json: {
    retrieval?: Record<string, any>;
    rerank?: Record<string, any>;
    generation?: Record<string, any>;
  } | null;
}

export interface Evaluation {
  id: string;
  mode: string;
  status: string;
  config_version?: number | null;
  dataset_version?: string;
  started_at: string;
  progress: number;
  total: number;
  config?: {
    retrieval?: unknown;
    rerank?: unknown;
    generation?: unknown;
  };
  report?: Record<string, Record<string, number>>;
}

export interface SampleResult {
  id: string;
  sample_id: string;
  retrieval_metrics: {
    precision: number | null;
    recall: number | null;
    mrr: number | null;
    ndcg: number | null;
    [k: string]: number | null;
  };
  generation_metrics: {
    faithfulness: number | null;
    [k: string]: number | null;
  };
  generated_answer?: string;
  retrieved_docs: {
    law_name: string;
    article_number: string;
    [k: string]: unknown;
  }[];
}

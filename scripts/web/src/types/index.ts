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
}

export interface Message {
  id: number;
  conversation_id: string;
  role: 'user' | 'assistant';
  content: string;
  citations: Citation[];
  sources: Source[];
  timestamp: string;
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

export interface EvalRun {
  id: string;
  mode: 'retrieval' | 'generation' | 'full';
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: number;
  total: number;
  started_at: string;
  finished_at?: string;
  config?: Record<string, string | number>;
}

export interface SampleResult {
  id: number;
  run_id: string;
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

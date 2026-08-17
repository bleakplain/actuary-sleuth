export interface AuditRegulationItem {
  chunk_id: string;
  chunk_ids?: string[];
  regulation_unit_id?: string;
  law_name: string;
  article_number: string;
  content: string;
  source_type: string;
  doc_number?: string;
  issuing_authority?: string;
  effective_date?: string;
  applicability_status?: 'applicable' | 'indeterminate' | '';
  matched_dimensions?: string[];
  matched_topics?: string[];
  fallback_layer?: string;
  retrieval_sources?: string[];
  kb_version?: string;
  source_file?: string;
  section_path?: string;
  chunk_index?: number | null;
  regulation_topics?: string[];
  applicability_reasons?: string[];
  indeterminate_dimensions?: string[];
  excluded_by?: string[];
  category?: string;
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
  regulation_unit_id?: string;
  regulation_chunk_ids?: string[];
  product_clause_ids?: string[];
  reasoning?: string;
  confidence?: number | null;
  applicability_dispute?: boolean;
  incomplete?: boolean;
  error_code?: string;
}

export type AuditStatus = 'completed' | 'degraded' | 'incomplete';
export type ComplianceConclusion =
  | 'non_compliant'
  | 'no_violation_found'
  | 'no_applicable_regulations'
  | 'undetermined';
export type RegulationDecisionStatus =
  | 'compliant'
  | 'non_compliant'
  | 'insufficient_information'
  | 'manual_review';

export interface RegulationEvidence {
  chunk_id: string;
  quote: string;
}

export interface ProductEvidence {
  clause_id: string;
  quote: string;
  source_kind: 'clause_body' | 'product_name';
}

export interface ExtractedFact {
  kind: string;
  value: string;
  unit: string;
  clause_id: string;
  evidence: string;
  confidence: number;
}

export type TriggerFactName =
  | 'has_waiting_period'
  | 'has_hesitation_period'
  | 'has_policy_loan'
  | 'has_cash_value'
  | 'has_grace_period'
  | 'has_renewal'
  | 'is_rate_adjustable'
  | 'mentions_out_of_hospital_drug'
  | 'has_death_benefit'
  | 'mentions_critical_illness_definition_term'
  | 'waiting_period_days'
  | 'hesitation_period_days'
  | 'first_rate_adjustment_interval_years'
  | 'subsequent_rate_adjustment_interval_years';

export type TriggerOperator =
  | 'equals'
  | 'exists'
  | 'contains_any'
  | 'less_than_or_equal';

export type ProofStrategy =
  | 'explicit_presence'
  | 'explicit_negation'
  | 'controlled_classification'
  | 'closed_phrase_scan'
  | 'numeric_fact'
  | 'semantic_fact';

export interface RegulationTriggerSpecTrace {
  fact_name: TriggerFactName;
  operator: TriggerOperator;
  expected_value: boolean | number | string | string[] | null;
  target_topics: string[];
  required_facts: TriggerFactName[];
  proof_strategy: ProofStrategy;
  search_all_terms: string[];
  search_any_terms: string[];
  description: string;
  exclusion_approved: boolean;
}

export interface ProductFactEvidenceTrace {
  clause_id: string;
  quote: string;
}

export interface ProductFactTrace {
  name: TriggerFactName;
  truth: 'true' | 'false' | 'unknown';
  value: boolean | number | string | string[] | null;
  unit: string;
  method: string;
  confidence: number;
  evidence: ProductFactEvidenceTrace[];
  reason: string;
  safe_for_exclusion: boolean;
  proof_strategy: ProofStrategy | null;
  proof_terms: string[];
  complete_document_proof: boolean;
}

export interface TriggerEvaluationTrace {
  status: 'triggered' | 'not_triggered' | 'indeterminate';
  fact_names: TriggerFactName[];
  reasons: string[];
  evidence_clause_ids: string[];
}

export interface RegulationTriggerRecordTrace {
  regulation_unit_id: string;
  kb_version: string;
  source_file: string;
  section_path: string;
  chunk_ids: string[];
  law_name: string;
  article_number: string;
  trigger_specs: RegulationTriggerSpecTrace[];
  evaluation: TriggerEvaluationTrace;
  exclusion_approved: boolean;
  exclusion_applied: boolean;
}

export interface ProductFactResolutionTrace {
  facts: ProductFactTrace[];
  requested_fact_names: TriggerFactName[];
  resolved_fact_names: TriggerFactName[];
  validation_errors: string[];
  attempted: boolean;
}

export interface DynamicEvidenceMatchTrace {
  clause_id: string;
  source_layer:
    | 'trigger_fact'
    | 'exact_topic'
    | 'related_topic'
    | 'business_terms'
    | 'bm25';
  selection_reason: string;
  score: number;
  matched_values: string[];
}

export interface DynamicEvidenceSelectionTrace {
  regulation_topics: string[];
  selected_clause_ids: string[];
  matches: DynamicEvidenceMatchTrace[];
  relation_schema_version: string;
  rule_schema_version: string;
  config_valid: boolean;
  warnings: string[];
}

export interface ProductClauseOutlineTrace {
  clause_id: string;
  number: string;
  title: string;
  topics: string[];
  parent_number: string | null;
  ancestor_numbers: string[];
  hierarchy_path: string;
}

export interface RoutedClause {
  clause_id: string;
  number: string;
  title: string;
  topics: string[];
  relation: 'direct' | 'related' | 'unknown' | 'not_relevant';
  reasons: string[];
  submitted: boolean;
}

export interface RegulationObligationAssessment {
  obligation_id: string;
  requirement: string;
  status: 'satisfied' | 'violated' | 'insufficient_information';
  reasoning: string;
  regulation_chunk_ids: string[];
  product_clause_ids: string[];
}

export interface RegulationDecision {
  task_id: string;
  regulation_unit_id: string;
  status: RegulationDecisionStatus;
  reasoning: string;
  suggestion: string;
  regulation_evidence: RegulationEvidence[];
  product_evidence: ProductEvidence[];
  applicability_dispute: boolean;
  confidence?: number | null;
  incomplete: boolean;
  error_code: string;
  obligation_assessments: RegulationObligationAssessment[];
  routed_clauses: RoutedClause[];
  facts: ExtractedFact[];
  trigger_evaluation?: TriggerEvaluationTrace | null;
  dynamic_evidence_shadow?: DynamicEvidenceSelectionTrace | null;
}

export type RegulationDecisionProgress = Omit<
  RegulationDecision,
  'routed_clauses' | 'facts'
> & {
  routed_clauses?: RoutedClause[];
  facts?: ExtractedFact[];
  completed: number;
  total: number;
};

export interface CandidateFreezeProgress {
  candidate_count: number;
  excluded_count: number;
  degraded: boolean;
  warnings: string[];
  coverage?: {
    complete_candidate_freeze: boolean;
    uncovered_scopes: string[];
  } | null;
}

export interface ExcludedRegulationUnit {
  regulation_unit_id: string;
  kb_version: string;
  source_file: string;
  section_path: string;
  law_name: string;
  article_number: string;
  chunk_ids: string[];
  regulation_topics: string[];
  excluded_by: string[];
  reasons: string[];
  category?: string;
}

export interface ComplianceResult {
  summary: Record<string, number>;
  items: AuditResultItem[];
  regulations: AuditRegulationItem[];
  retrieved_regulations?: AuditRegulationItem[];
  excluded_regulations?: ExcludedRegulationUnit[];
  decisions?: RegulationDecision[];
  product_tags?: Record<string, unknown>;
  product_fact_ledger?: ProductFactTrace[];
  product_fact_resolution?: ProductFactResolutionTrace | null;
  trigger_evaluations?: RegulationTriggerRecordTrace[];
  trigger_excluded_regulations?: RegulationTriggerRecordTrace[];
  trigger_exclusion_mode?: string;
  trigger_exclusion_ready?: boolean;
  trigger_exclusion_blockers?: string[];
  dynamic_evidence_mode?: string;
  dynamic_evidence_shadow_warnings?: string[];
  product_clause_outline?: ProductClauseOutlineTrace[];
  document_fingerprint?: string;
  audit_input_fingerprint?: string;
  product_name_source?: string;
  coverage_attested?: boolean;
  coverage_attested_facts?: string[];
  parse_warnings?: string[];
  regulation_sources: Record<string, string[]>;
  category: string | null;
  negative_list_result: string | null;
  retrieval_degraded?: boolean;
  retrieval_warnings?: string[];
  audit_status?: AuditStatus;
  compliance_conclusion?: ComplianceConclusion;
  kb_version?: string;
  topic_taxonomy_version?: string;
  topic_relations_version?: string;
  regulation_trigger_schema_version?: string;
  regulation_source_sha256?: string;
  regulation_catalog_sha256?: string;
  approved_regulation_trigger_source_sha256?: string;
  approved_regulation_trigger_catalog_sha256?: string;
  supported_regulation_trigger_schema_version?: string;
  evaluation_dataset_version?: string;
  evaluation_dataset_status?: string;
  cutover_gate_status?: string;
  candidate_count?: number;
  excluded_count?: number;
  completed_count?: number;
  failed_count?: number;
  failure_reasons?: string[];
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
  owner_user_id?: string;
  result: ComplianceResult;
  created_at: string;
}

export interface ParsedClause {
  clause_id: string;
  number: string;
  title: string;
  text: string;
  topics: string[];
  hierarchy_level: number;
  parent_number: string | null;
  ancestor_numbers: string[];
  hierarchy_path: string;
  container_only: boolean;
}

export interface ParsedDataTable {
  clause_id: string;
  table_type: string;
  remark: string;
  raw_text: string;
  data: string[][];
}

export interface ParsedSection {
  clause_id: string;
  title: string;
  content: string;
}

export interface ParsedDocumentAnnotation {
  kind: string;
  annotation_id: string;
  text: string;
  author: string | null;
  created_at: string | null;
  anchor_start_paragraph_index: number | null;
  anchor_end_paragraph_index: number | null;
  paragraph_index: number | null;
}

export interface CoverageAttestationTrace {
  coverage_attested: boolean;
  coverage_attested_facts: string[];
  source_record_count: number;
  assigned_record_count: number;
  unassigned_orders: number[];
  multiply_assigned_orders: number[];
  duplicate_source_orders: number[];
  truncated_orders: number[];
  unreadable_pages: number[];
  unparsed_text_box_count: number;
  unparsed_image_count: number;
  unparsed_header_footer_part_count: number;
  unparsed_auxiliary_part_count: number;
  ignored_header_footer_part_count: number;
  ignored_qr_image_count: number;
  ignored_navigation_text_box_count: number;
}

export interface ParsedAuditBlock {
  clause_id: string;
  block_type: string;
  source_index: number;
  number: string;
  title: string;
  content: string;
  topics: string[];
  hierarchy_level: number;
  parent_number: string | null;
  ancestor_numbers: string[];
  hierarchy_path: string;
  container_only: boolean;
}

export interface ParsedDocument {
  parse_id: string;
  parse_attestation: string;
  parse_attestation_expires_at: string;
  file_name: string;
  file_type: string;
  clauses: ParsedClause[];
  data_tables: ParsedDataTable[];
  notices: ParsedSection[];
  health_disclosures: ParsedSection[];
  exclusions: ParsedSection[];
  unclassified_sections: ParsedSection[];
  rider_clauses: ParsedClause[];
  annotations: ParsedDocumentAnnotation[];
  audit_blocks: ParsedAuditBlock[];
  document_fingerprint: string;
  audit_input_fingerprint: string;
  warnings: string[];
  combined_text: string;
  parse_time: string;
  identified_category: string | null;
  category_confidence: number;
  product_name?: string | null;
  product_name_source: string;
  coverage_attested: boolean;
  coverage_attested_facts: string[];
  coverage_attestation: CoverageAttestationTrace;
  is_rider?: boolean;
  group_or_individual?: string | null;
  duration_type?: string | null;
  design_type?: string | null;
  naming_warnings?: string[];
  product_tags: Record<string, unknown>;
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

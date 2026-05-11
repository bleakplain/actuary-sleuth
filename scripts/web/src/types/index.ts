export interface AuditSource {
  source_id: number;
  law_name: string;
  article_number: string;
  content: string;
  source_type: string;
  doc_number?: string;
  issuing_authority?: string;
  effective_date?: string;
}

export interface ComplianceItem {
  clause_number: string;
  check_type: string;
  param: string;
  value: string;
  requirement: string;
  status: string;
  source_id: number | null;
  source_type: string;
  source_excerpt: string;
  suggestion: string;
}

export interface ComplianceResult {
  summary: Record<string, number>;
  items: ComplianceItem[];
  sources: AuditSource[];
  regulation_sources: Record<string, string[]>;
  category: string;
  negative_list_result: string;
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
}

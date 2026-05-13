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
  param: string;
  value: string;
  requirement: string;
  status: string;
  chunk_id: string | null;
  source_type: string;
  source_excerpt: string;
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
}

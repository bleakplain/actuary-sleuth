"""合规检查相关 schema"""
from typing import Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class AuditRegulationItemResponse(BaseModel):
    model_config = ConfigDict(extra='ignore')
    chunk_id: str = ""
    law_name: str = ""
    article_number: str = ""
    content: str = ""
    source_type: str = ""
    doc_number: Optional[str] = None
    issuing_authority: Optional[str] = None
    effective_date: Optional[str] = None
    applicability_status: str = ""
    matched_dimensions: List[str] = Field(default_factory=list)
    matched_topics: List[str] = Field(default_factory=list)
    fallback_layer: str = ""
    retrieval_sources: List[str] = Field(default_factory=list)
    kb_version: str = ""
    source_file: str = ""
    section_path: str = ""
    chunk_index: Optional[int] = None
    regulation_unit_id: str = ""
    chunk_ids: List[str] = Field(default_factory=list)
    regulation_topics: List[str] = Field(default_factory=list)
    applicability_reasons: List[str] = Field(default_factory=list)
    indeterminate_dimensions: List[str] = Field(default_factory=list)
    excluded_by: List[str] = Field(default_factory=list)
    category: str = ""


class AuditResultItemResponse(BaseModel):
    model_config = ConfigDict(extra='ignore')

    clause_number: str = ""
    check_type: str = ""
    clause_content: str = ""
    status: str
    chunk_id: Optional[str] = None
    suggestion: str = ""
    conclusion: str = ""
    source_ref: str = ""
    regulation_unit_id: str = ""
    regulation_chunk_ids: List[str] = Field(default_factory=list)
    product_clause_ids: List[str] = Field(default_factory=list)
    reasoning: str = ""
    confidence: Optional[float] = None
    applicability_dispute: bool = False
    incomplete: bool = False
    error_code: str = ""


class ExcludedRegulationUnitResponse(BaseModel):
    regulation_unit_id: str
    kb_version: str = ""
    source_file: str = ""
    section_path: str = ""
    law_name: str = ""
    article_number: str = ""
    chunk_ids: List[str] = Field(default_factory=list)
    regulation_topics: List[str] = Field(default_factory=list)
    excluded_by: List[str] = Field(default_factory=list)
    reasons: List[str] = Field(default_factory=list)
    category: str = ""


class RegulationEvidenceResponse(BaseModel):
    chunk_id: str
    quote: str


class ProductEvidenceResponse(BaseModel):
    clause_id: str
    quote: str
    source_kind: str = "clause_body"


class ExtractedFactResponse(BaseModel):
    kind: str
    value: str
    unit: str = ""
    clause_id: str
    evidence: str
    confidence: float


class RoutedClauseResponse(BaseModel):
    clause_id: str
    number: str = ""
    title: str = ""
    topics: List[str] = Field(default_factory=list)
    relation: str
    reasons: List[str] = Field(default_factory=list)
    submitted: bool = True


class RegulationDecisionResponse(BaseModel):
    task_id: str
    regulation_unit_id: str
    status: Literal[
        "compliant",
        "non_compliant",
        "insufficient_information",
        "manual_review",
    ]
    reasoning: str
    suggestion: str = ""
    regulation_evidence: List[RegulationEvidenceResponse] = Field(default_factory=list)
    product_evidence: List[ProductEvidenceResponse] = Field(default_factory=list)
    applicability_dispute: bool = False
    confidence: Optional[float] = None
    incomplete: bool = False
    error_code: str = ""
    routed_clauses: List[RoutedClauseResponse] = Field(default_factory=list)
    facts: List[ExtractedFactResponse] = Field(default_factory=list)


class ComplianceReportDataResponse(BaseModel):
    model_config = ConfigDict(extra='ignore')
    summary: Dict[str, int] = Field(default_factory=dict)
    items: List[AuditResultItemResponse] = Field(default_factory=list)
    regulations: List[AuditRegulationItemResponse] = Field(default_factory=list)
    excluded_regulations: List[ExcludedRegulationUnitResponse] = Field(default_factory=list)
    decisions: List[RegulationDecisionResponse] = Field(default_factory=list)
    product_tags: Dict[str, object] = Field(default_factory=dict)
    document_fingerprint: str = ""
    audit_input_fingerprint: str = ""
    product_name_source: str = "unknown"
    parse_warnings: List[str] = Field(default_factory=list)
    regulation_sources: Dict[str, List[str]] = Field(default_factory=dict)
    category: Optional[str] = ""
    negative_list_result: Optional[str] = ""
    retrieval_degraded: bool = False
    retrieval_warnings: List[str] = Field(default_factory=list)
    clause_coverage: Optional[Dict] = None
    audit_status: Literal["completed", "degraded", "incomplete"] = "completed"
    compliance_conclusion: Literal[
        "non_compliant",
        "no_violation_found",
        "no_applicable_regulations",
        "undetermined",
    ] = "undetermined"
    kb_version: str = ""
    topic_taxonomy_version: str = ""
    topic_relations_version: str = ""
    evaluation_dataset_version: str = ""
    evaluation_dataset_status: str = ""
    cutover_gate_status: str = ""
    candidate_count: int = 0
    excluded_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    failure_reasons: List[str] = Field(default_factory=list)


class ComplianceReportResponse(BaseModel):
    id: str
    product_name: str
    category: str
    mode: str
    owner_user_id: str = ""
    result: ComplianceReportDataResponse
    created_at: str


class ParsedAuditBlock(BaseModel):
    clause_id: str
    block_type: str
    source_index: int
    number: str = ""
    title: str = ""
    content: str
    topics: List[str] = Field(default_factory=list)


class DocumentCheckRequest(BaseModel):
    document_content: str
    parse_id: str = ""
    parse_attestation: str = ""
    document_fingerprint: str = ""
    audit_input_fingerprint: str = ""
    product_name: str = ""
    product_name_source: str = "unknown"
    parse_warnings: List[str] = Field(default_factory=list)
    category: str = ""
    clause_topics: List[str] = Field(default_factory=list)
    audit_blocks: List[ParsedAuditBlock] = Field(default_factory=list)
    product_tags: Dict[str, object] = Field(default_factory=dict)


class ParsedClause(BaseModel):
    clause_id: str = ""
    number: str
    title: str
    text: str
    topics: List[str] = Field(default_factory=list)


class ParsedDataTable(BaseModel):
    clause_id: str = ""
    table_type: str
    remark: str = ""
    raw_text: str = ""
    data: List[List[str]] = Field(default_factory=list)


class ParsedSection(BaseModel):
    clause_id: str = ""
    title: str
    content: str


class ParsedDocumentResponse(BaseModel):
    parse_id: str
    parse_attestation: str
    parse_attestation_expires_at: str
    file_name: str
    file_type: str
    clauses: List[ParsedClause] = Field(default_factory=list)
    data_tables: List[ParsedDataTable] = Field(default_factory=list)
    unclassified_sections: List[ParsedSection] = Field(default_factory=list)
    notices: List[ParsedSection] = Field(default_factory=list)
    health_disclosures: List[ParsedSection] = Field(default_factory=list)
    exclusions: List[ParsedSection] = Field(default_factory=list)
    rider_clauses: List[ParsedClause] = Field(default_factory=list)
    audit_blocks: List[ParsedAuditBlock] = Field(default_factory=list)
    document_fingerprint: str = ""
    audit_input_fingerprint: str = ""
    warnings: List[str] = Field(default_factory=list)
    combined_text: str = ""
    parse_time: str = ""
    identified_category: Optional[str] = None
    category_confidence: float = 0.0
    # 产品名识别结果（从文档正文提取，区别于 file_name）
    product_name: Optional[str] = None
    product_name_source: str = "unknown"
    is_rider: bool = False
    # 结构化标签维度（供前端展示与后续标签化法规筛选）
    group_or_individual: Optional[str] = None
    duration_type: Optional[str] = None
    design_type: Optional[str] = None
    naming_warnings: List[str] = Field(default_factory=list)
    product_tags: Dict = Field(default_factory=dict)


class RichTextParseRequest(BaseModel):
    html_content: str
    product_name: str = ""

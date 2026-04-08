from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from lib.rag_engine.config import config_to_dict, RetrievalConfig, RerankConfig, GenerationConfig


class RegulationRefSchema(BaseModel):
    doc_name: str
    article: str
    excerpt: str
    relevance: float = 1.0
    chunk_id: str = ""


class EvalSampleCreate(BaseModel):
    id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    ground_truth: str = ""
    evidence_docs: List[str] = []
    evidence_keywords: List[str] = []
    question_type: str = Field("factual", pattern="^(factual|multi_hop|negative|colloquial)$")
    difficulty: str = Field("medium", pattern="^(easy|medium|hard)$")
    topic: str = ""
    regulation_refs: List[RegulationRefSchema] = []
    review_status: str = Field("pending", pattern="^(pending|approved)$")
    reviewer: str = ""
    review_comment: str = ""
    created_by: str = Field("human", pattern="^(human|llm)$")
    kb_version: str = ""


class EvalSampleOut(BaseModel):
    id: str
    question: str
    ground_truth: str
    evidence_docs: List[str]
    evidence_keywords: List[str]
    question_type: str
    difficulty: str
    topic: str
    regulation_refs: List[RegulationRefSchema]
    review_status: str
    reviewer: str
    reviewed_at: str
    review_comment: str
    created_by: str
    kb_version: str
    created_at: str
    updated_at: str


class ImportSamplesRequest(BaseModel):
    samples: List[EvalSampleCreate]


class EvaluationRequest(BaseModel):
    mode: str = Field("full", pattern="^(retrieval|generation|full|llm_judge)$")
    config_id: int
    snapshot_id: Optional[str] = None
    filters: Optional[Dict[str, str]] = None


class EvalConfigCreate(BaseModel):
    description: str = ""
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    rerank: RerankConfig = Field(default_factory=RerankConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)

    def to_config_dict(self) -> dict:
        return config_to_dict(self.retrieval, self.rerank, self.generation)


class CompareRequest(BaseModel):
    baseline_id: str
    compare_id: str


class SnapshotCreate(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = ""


class HumanReviewCreate(BaseModel):
    evaluation_id: str
    sample_id: str
    reviewer: str = ""
    faithfulness_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    correctness_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    relevancy_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    comment: str = ""


class ReviewSampleRequest(BaseModel):
    reviewer: str = ""
    comment: str = ""


class KbSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(10, ge=1, le=50)


class KbSearchResult(BaseModel):
    doc_name: str
    article: str
    excerpt: str
    relevance: float
    hierarchy_path: str = ""
    chunk_id: str = ""

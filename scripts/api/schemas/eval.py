from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from lib.rag_engine.config import config_to_dict, RetrievalConfig, RerankConfig, GenerationConfig


class EvalSampleCreate(BaseModel):
    id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    ground_truth: str = ""
    evidence_docs: List[str] = []
    evidence_keywords: List[str] = []
    question_type: str = Field("factual", pattern="^(factual|multi_hop|negative|colloquial)$")
    difficulty: str = Field("medium", pattern="^(easy|medium|hard)$")
    topic: str = ""


class EvalSampleOut(BaseModel):
    id: str
    question: str
    ground_truth: str
    evidence_docs: List[str]
    evidence_keywords: List[str]
    question_type: str
    difficulty: str
    topic: str
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
    name: str = Field(..., min_length=1)
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

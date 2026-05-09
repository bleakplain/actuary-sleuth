"""RAG 评测域 — 数据集、评估器、评级、质量检测、问题分析、样本合成。"""
__all__ = [
    "EvalSample", "QuestionType", "ReviewStatus", "RegulationRef",
    "load_eval_dataset", "save_eval_dataset",
    "RetrievalEvalReport", "GenerationEvalReport", "RAGEvalReport",
    "RetrievalEvaluator", "GenerationEvaluator",
    "evaluate_retrieval", "compute_faithfulness",
    "MetricThreshold", "EVAL_THRESHOLDS", "interpret_metric", "generate_eval_summary",
    "QualityIssue", "QualityAuditReport", "validate_dataset",
    "CoverageReport", "compute_coverage", "get_kb_doc_names",
    "detect_quality", "compute_retrieval_relevance", "compute_info_completeness",
    "classify_badcase", "assess_compliance_risk",
    "WeaknessReport", "generate_weakness_report",
    "SynthConfig", "SynthResult", "SynthQA",
]
from .dataset import EvalSample, QuestionType, ReviewStatus, RegulationRef, load_eval_dataset, save_eval_dataset
from .evaluator import (
    RetrievalEvalReport, GenerationEvalReport, RAGEvalReport,
    RetrievalEvaluator, GenerationEvaluator,
    evaluate_retrieval, compute_faithfulness,
)
from .rating import MetricThreshold, EVAL_THRESHOLDS, interpret_metric, generate_eval_summary
from .validator import QualityIssue, QualityAuditReport, validate_dataset
from .coverage import CoverageReport, compute_coverage, get_kb_doc_names
from .quality import detect_quality, compute_retrieval_relevance, compute_info_completeness
from .badcase import classify_badcase, assess_compliance_risk
from .weakness import WeaknessReport, generate_weakness_report
from .synthesizer import SynthConfig, SynthResult, SynthQA

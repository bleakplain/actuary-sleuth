#!/usr/bin/env python3
from dataclasses import dataclass
from typing import Dict, List, Any
from datetime import datetime

from lib.common.models import Product, ProductCategory

__all__ = [
    'PreprocessedResult',
    'CheckedResult',
    'AnalyzedResult',
    'EvaluationResult',
    'to_api_dict',
    'to_export_dict',
    'create_preprocessed_result'
]


@dataclass(frozen=True)
class PreprocessedResult:
    audit_id: str
    document_url: str
    timestamp: datetime
    product: Product
    clauses: List[Dict[str, Any]]
    pricing_params: Dict[str, Any]


@dataclass(frozen=True)
class CheckedResult:
    preprocessed: PreprocessedResult
    violations: List[Dict[str, Any]]

    @property
    def audit_id(self) -> str:
        return self.preprocessed.audit_id

    @property
    def product(self) -> Product:
        return self.preprocessed.product

    @property
    def clauses(self) -> List[Dict]:
        return self.preprocessed.clauses


@dataclass(frozen=True)
class AnalyzedResult:
    checked: CheckedResult
    pricing_analysis: Dict[str, Any]

    @property
    def audit_id(self) -> str:
        return self.checked.audit_id

    @property
    def product(self) -> Product:
        return self.checked.product

    @property
    def preprocessed(self) -> PreprocessedResult:
        return self.checked.preprocessed

    @property
    def violations(self) -> List[Dict]:
        return self.checked.violations


@dataclass(frozen=True)
class EvaluationResult:
    analyzed: AnalyzedResult
    score: int
    grade: str
    summary: Dict[str, Any]

    @property
    def audit_id(self) -> str:
        return self.analyzed.audit_id

    @property
    def product(self) -> Product:
        return self.analyzed.product

    @property
    def violations(self) -> List[Dict]:
        return self.analyzed.violations

    def get_violations(self) -> List[Dict[str, Any]]:
        return self.analyzed.violations

    def get_violation_count(self) -> int:
        return len(self.analyzed.violations)

    def get_violation_summary(self) -> Dict[str, int]:
        violations = self.analyzed.violations
        return {
            'high': sum(1 for v in violations if v.get('severity') == 'high'),
            'medium': sum(1 for v in violations if v.get('severity') == 'medium'),
            'low': sum(1 for v in violations if v.get('severity') == 'low'),
        }

    def to_dict(self) -> Dict[str, Any]:
        preprocessed = self.analyzed.preprocessed
        return {
            'success': True,
            'audit_id': self.audit_id,
            'violations': self.violations,
            'violation_count': self.get_violation_count(),
            'violation_summary': self.get_violation_summary(),
            'pricing': self.analyzed.pricing_analysis,
            'score': self.score,
            'grade': self.grade,
            'summary': self.summary,
        }


def create_preprocessed_result(audit_id: str, document_url: str) -> PreprocessedResult:
    return PreprocessedResult(
        audit_id=audit_id,
        document_url=document_url,
        timestamp=datetime.now(),
        product=Product(
            name="",
            company="",
            category=ProductCategory.OTHER,
            period=""
        ),
        clauses=[],
        pricing_params={}
    )


def get_violations(result: EvaluationResult) -> List[Dict[str, Any]]:
    return result.violations


def get_product(result: EvaluationResult) -> Product:
    return result.product


def get_clauses(result: EvaluationResult) -> List[Dict[str, Any]]:
    return result.analyzed.preprocessed.clauses


def get_pricing_analysis(result: EvaluationResult) -> Dict[str, Any]:
    return result.analyzed.pricing_analysis


def get_audit_id(result: EvaluationResult) -> str:
    return result.audit_id


def get_document_url(result: EvaluationResult) -> str:
    return result.analyzed.preprocessed.document_url


def get_timestamp(result: EvaluationResult) -> datetime:
    return result.analyzed.preprocessed.timestamp


def get_preprocess_id(result: EvaluationResult) -> str:
    return f"PRE-{result.audit_id.split('-')[1]}"


def to_api_dict(result: EvaluationResult) -> Dict[str, Any]:
    preprocessed = result.analyzed.preprocessed
    violations = result.violations
    total_violations = len(violations)

    return {
        'success': True,
        'audit_id': result.audit_id,
        'violations': violations,
        'violation_count': total_violations,
        'violation_summary': result.get_violation_summary(),
        'pricing': result.analyzed.pricing_analysis,
        'score': result.score,
        'grade': result.grade,
        'summary': result.summary,
        'report': '',
        'metadata': {
            'audit_type': 'full',
            'document_url': preprocessed.document_url,
            'timestamp': preprocessed.timestamp.isoformat(),
        },
        'details': {
            'preprocess_id': get_preprocess_id(result),
            'product_name': preprocessed.product.name,
            'product_type': preprocessed.product.type,
            'insurance_company': preprocessed.product.company,
            'clauses': preprocessed.clauses,
            'document_url': preprocessed.document_url
        },
    }


def to_export_dict(result: EvaluationResult) -> Dict[str, Any]:
    preprocessed = result.analyzed.preprocessed
    violations = result.violations

    return {
        'violations': violations,
        'high_violations': [v for v in violations if v.get('severity') == 'high'],
        'medium_violations': [v for v in violations if v.get('severity') == 'medium'],
        'low_violations': [v for v in violations if v.get('severity') == 'low'],
        'pricing_analysis': result.analyzed.pricing_analysis,
        'clauses': preprocessed.clauses,
        'product': preprocessed.product,
        'score': result.score,
        'grade': result.grade,
        'summary': result.summary,
    }

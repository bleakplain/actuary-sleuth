#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据集自动校验工具"""
from dataclasses import dataclass, field
from typing import List, Dict

from .eval_dataset import EvalSample, QuestionType


@dataclass(frozen=True)
class QualityIssue:
    sample_id: str
    issue_type: str
    severity: str
    description: str


@dataclass(frozen=True)
class QualityAuditReport:
    total_samples: int
    valid_samples: int
    issues: List[QualityIssue]
    distribution: Dict[str, Dict[str, int]]

    def to_dict(self) -> Dict:
        return {
            'total_samples': self.total_samples,
            'valid_samples': self.valid_samples,
            'issue_count': len(self.issues),
            'issues': [
                {'sample_id': i.sample_id, 'type': i.issue_type,
                 'severity': i.severity, 'description': i.description}
                for i in self.issues
            ],
            'distribution': self.distribution,
        }


def validate_dataset(samples: List[EvalSample]) -> QualityAuditReport:
    issues: List[QualityIssue] = []

    for sample in samples:
        if not sample.question.strip():
            issues.append(QualityIssue(sample.id, 'empty_field', 'error', 'question 为空'))
        if not sample.ground_truth.strip():
            issues.append(QualityIssue(sample.id, 'empty_field', 'warning', 'ground_truth 为空'))
        if not sample.evidence_docs:
            issues.append(QualityIssue(sample.id, 'no_evidence', 'error', 'evidence_docs 为空'))
        if not sample.evidence_keywords:
            issues.append(QualityIssue(sample.id, 'no_evidence', 'warning', 'evidence_keywords 为空'))

        short_keywords = [kw for kw in sample.evidence_keywords if len(kw) < 2]
        if short_keywords:
            issues.append(QualityIssue(
                sample.id, 'keyword_too_short', 'warning',
                f'过短关键词: {short_keywords}',
            ))

        if not sample.topic.strip():
            issues.append(QualityIssue(sample.id, 'missing_field', 'warning', 'topic 为空'))

    type_dist: Dict[str, int] = {}
    diff_dist: Dict[str, int] = {}
    topic_dist: Dict[str, int] = {}
    for s in samples:
        type_dist[s.question_type.value] = type_dist.get(s.question_type.value, 0) + 1
        diff_dist[s.difficulty] = diff_dist.get(s.difficulty, 0) + 1
        if s.topic:
            topic_dist[s.topic] = topic_dist.get(s.topic, 0) + 1

    error_count = sum(1 for i in issues if i.severity == 'error')
    return QualityAuditReport(
        total_samples=len(samples),
        valid_samples=len(samples) - error_count,
        issues=issues,
        distribution={
            'by_type': type_dist,
            'by_difficulty': diff_dist,
            'by_topic': topic_dist,
        },
    )

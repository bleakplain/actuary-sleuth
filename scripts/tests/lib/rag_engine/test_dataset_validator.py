#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据集校验器单元测试"""
import pytest

from lib.rag_engine.dataset_validator import validate_dataset, QualityIssue, QualityAuditReport
from lib.rag_engine.eval_dataset import EvalSample, QuestionType


def _make_sample(
    sid: str = "s1",
    question: str = "测试问题",
    ground_truth: str = "标准答案",
    evidence_docs: list = None,
    evidence_keywords: list = None,
    question_type: QuestionType = QuestionType.FACTUAL,
    difficulty: str = "easy",
    topic: str = "测试",
) -> EvalSample:
    return EvalSample(
        id=sid, question=question, ground_truth=ground_truth,
        evidence_docs=evidence_docs if evidence_docs is not None else ["a.md"],
        evidence_keywords=evidence_keywords if evidence_keywords is not None else ["关键词"],
        question_type=question_type, difficulty=difficulty, topic=topic,
    )


class TestValidateDataset:
    def test_valid_sample_no_issues(self):
        samples = [_make_sample()]
        report = validate_dataset(samples)
        assert report.total_samples == 1
        assert report.valid_samples == 1
        assert report.issues == []

    def test_empty_question(self):
        samples = [_make_sample(question="")]
        report = validate_dataset(samples)
        question_issues = [i for i in report.issues if i.issue_type == 'empty_field' and i.severity == 'error']
        assert len(question_issues) == 1

    def test_empty_ground_truth_warning(self):
        samples = [_make_sample(ground_truth="")]
        report = validate_dataset(samples)
        gt_issues = [i for i in report.issues if i.issue_type == 'empty_field' and i.severity == 'warning']
        assert gt_issues

    def test_empty_evidence_docs_error(self):
        samples = [_make_sample(evidence_docs=[])]
        report = validate_dataset(samples)
        errors = [i for i in report.issues if i.issue_type == 'no_evidence' and i.severity == 'error']
        assert errors

    def test_empty_evidence_keywords_warning(self):
        samples = [_make_sample(evidence_keywords=[])]
        report = validate_dataset(samples)
        warnings = [i for i in report.issues if i.issue_type == 'no_evidence' and i.severity == 'warning']
        assert warnings

    def test_short_keywords_warning(self):
        samples = [_make_sample(evidence_keywords=["a", "正常关键词"])]
        report = validate_dataset(samples)
        assert any(i.issue_type == 'keyword_too_short' for i in report.issues)

    def test_empty_topic_warning(self):
        samples = [_make_sample(topic="")]
        report = validate_dataset(samples)
        topic_issues = [i for i in report.issues if i.issue_type == 'missing_field' and 'topic' in i.description]
        assert topic_issues

    def test_distribution(self):
        samples = [
            _make_sample(sid="s1", question_type=QuestionType.FACTUAL, difficulty="easy", topic="A"),
            _make_sample(sid="s2", question_type=QuestionType.FACTUAL, difficulty="hard", topic="A"),
            _make_sample(sid="s3", question_type=QuestionType.NEGATIVE, difficulty="easy", topic="B"),
        ]
        report = validate_dataset(samples)
        assert report.distribution['by_type'] == {'factual': 2, 'negative': 1}
        assert report.distribution['by_difficulty'] == {'easy': 2, 'hard': 1}
        assert report.distribution['by_topic'] == {'A': 2, 'B': 1}

    def test_to_dict(self):
        samples = [_make_sample()]
        report = validate_dataset(samples)
        d = report.to_dict()
        assert d['total_samples'] == 1
        assert d['valid_samples'] == 1
        assert d['issue_count'] == 0
        assert 'distribution' in d

    def test_multiple_issues(self):
        samples = [_make_sample(question="", evidence_docs=[], evidence_keywords=[], topic="")]
        report = validate_dataset(samples)
        assert report.valid_samples < len(samples)
        assert len(report.issues) >= 3

    def test_empty_dataset(self):
        report = validate_dataset([])
        assert report.total_samples == 0
        assert report.valid_samples == 0
        assert report.issues == []


def test_validate_allows_empty_evidence_for_unanswerable():
    sample = EvalSample(
        id="u_test",
        question="保险公司可以投资股票吗？",
        ground_truth="知识库中无对应规定",
        evidence_docs=[],
        evidence_keywords=["投资", "股票"],
        question_type=QuestionType.UNANSWERABLE,
        difficulty="medium",
        topic="投资管理",
    )
    report = validate_dataset([sample])
    no_evidence_errors = [i for i in report.issues if i.issue_type == 'no_evidence']
    assert len(no_evidence_errors) == 0


def test_validate_detects_duplicates():
    samples = [
        EvalSample(
            id="dup_001",
            question="健康保险的等待期有什么规定？",
            ground_truth="等待期不超过90天",
            evidence_docs=["05_健康保险产品开发.md"],
            evidence_keywords=["等待期"],
            question_type=QuestionType.FACTUAL,
            difficulty="easy",
            topic="健康保险",
        ),
        EvalSample(
            id="dup_002",
            question="健康保险等待期有什么规定？",
            ground_truth="等待期不超过90天",
            evidence_docs=["05_健康保险产品开发.md"],
            evidence_keywords=["等待期"],
            question_type=QuestionType.FACTUAL,
            difficulty="easy",
            topic="健康保险",
        ),
    ]
    report = validate_dataset(samples)
    dup_issues = [i for i in report.issues if i.issue_type == 'duplicate_question']
    assert len(dup_issues) >= 1


def test_validate_detects_generic_keywords():
    sample = EvalSample(
        id="g_test",
        question="保险合同有什么规定？",
        ground_truth="保险合同应当包含基本条款",
        evidence_docs=["01_保险法.md"],
        evidence_keywords=["保险", "条款"],
        question_type=QuestionType.FACTUAL,
        difficulty="easy",
        topic="保险法",
    )
    report = validate_dataset([sample])
    generic_issues = [i for i in report.issues if i.issue_type == 'generic_keyword']
    assert len(generic_issues) >= 1

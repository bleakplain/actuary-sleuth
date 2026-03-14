# tests/lib/common/test_models.py

import pytest
from lib.common.models import RegulationStatus, RegulationLevel, RegulationRecord, ProcessingOutcome
from datetime import datetime


def test_regulation_status_values():
    """测试 RegulationStatus 枚举值"""
    assert RegulationStatus.RAW == "raw"
    assert RegulationStatus.CLEANED == "cleaned"
    assert RegulationStatus.EXTRACTED == "extracted"
    assert RegulationStatus.AUDITED == "audited"
    assert RegulationStatus.FAILED == "failed"


def test_regulation_level_values():
    """测试 RegulationLevel 枚举值"""
    assert RegulationLevel.LAW == "law"
    assert RegulationLevel.DEPARTMENT_RULE == "department_rule"
    assert RegulationLevel.NORMATIVE == "normative"
    assert RegulationLevel.OTHER == "other"


def test_regulation_status_is_string_enum():
    """测试 RegulationStatus 是字符串枚举"""
    status = RegulationStatus.RAW
    assert isinstance(status, str)
    assert status == "raw"


def test_regulation_record_defaults():
    """测试 RegulationRecord 默认值"""
    record = RegulationRecord(
        law_name="保险法",
        article_number="第十六条",
        category="健康保险"
    )
    assert record.law_name == "保险法"
    assert record.article_number == "第十六条"
    assert record.category == "健康保险"
    assert record.effective_date is None
    assert record.hierarchy_level is None
    assert record.issuing_authority is None
    assert record.status == RegulationStatus.RAW
    assert record.quality_score is None


def test_regulation_record_with_all_fields():
    """测试 RegulationRecord 完整字段"""
    record = RegulationRecord(
        law_name="保险法",
        article_number="第十六条",
        category="健康保险",
        effective_date="2023-01-01",
        hierarchy_level=RegulationLevel.LAW,
        issuing_authority="全国人大",
        status=RegulationStatus.EXTRACTED,
        quality_score=0.95
    )
    assert record.law_name == "保险法"
    assert record.effective_date == "2023-01-01"
    assert record.hierarchy_level == RegulationLevel.LAW
    assert record.quality_score == 0.95


def test_processing_outcome_defaults():
    """测试 ProcessingOutcome 默认值"""
    record = RegulationRecord(
        law_name="保险法",
        article_number="第十六条",
        category="健康保险"
    )
    outcome = ProcessingOutcome(
        success=True,
        regulation_id="abc123",
        record=record
    )
    assert outcome.success is True
    assert outcome.regulation_id == "abc123"
    assert outcome.errors == []
    assert outcome.warnings == []
    assert outcome.processor == ""
    assert isinstance(outcome.processed_at, datetime)


def test_processing_outcome_with_errors():
    """测试 ProcessingOutcome 带错误信息"""
    record = RegulationRecord(
        law_name="保险法",
        article_number="第十六条",
        category="健康保险"
    )
    outcome = ProcessingOutcome(
        success=False,
        regulation_id="",
        record=record,
        errors=["解析失败", "缺少必要字段"],
        warnings=["字段不完整"],
        processor="preprocessing.extractor"
    )
    assert outcome.success is False
    assert outcome.errors == ["解析失败", "缺少必要字段"]
    assert outcome.warnings == ["字段不完整"]
    assert outcome.processor == "preprocessing.extractor"

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from unittest.mock import MagicMock
import pytest

from lib.rag_engine.query_preprocessor import QueryPreprocessor, PreprocessedQuery


@pytest.fixture
def preprocessor():
    return QueryPreprocessor(llm_client=None)


@pytest.fixture
def preprocessor_with_llm():
    mock_llm = MagicMock()
    mock_llm.generate.return_value = '健康保险等待期规定'
    return QueryPreprocessor(llm_client=mock_llm)


def test_normalize_synonym(preprocessor):
    result = preprocessor.preprocess('退保流程')
    assert '解除保险合同' in result.normalized or '退保' in result.normalized


def test_expand_generates_variants(preprocessor):
    result = preprocessor.preprocess('退保')
    assert result.did_expand
    assert len(result.expanded) > 1


def test_expand_limit(preprocessor):
    result = preprocessor.preprocess('退保')
    assert len(result.expanded) <= 4


def test_no_expand_for_unknown_term(preprocessor):
    result = preprocessor.preprocess('这是一个没有同义词的问题')
    assert not result.did_expand
    assert len(result.expanded) == 1


def test_llm_rewrite_called_for_long_query(preprocessor_with_llm):
    result = preprocessor_with_llm.preprocess('健康保险产品的等待期有什么具体规定和要求')
    preprocessor_with_llm._llm.generate.assert_called_once()
    assert result.normalized == '健康保险等待期规定'


def test_llm_rewrite_skipped_for_short_query(preprocessor_with_llm):
    preprocessor_with_llm.preprocess('退保')
    preprocessor_with_llm._llm.generate.assert_not_called()


def test_llm_rewrite_failure_falls_back(preprocessor):
    mock_llm = MagicMock()
    mock_llm.generate.side_effect = RuntimeError("LLM 不可用")
    pp = QueryPreprocessor(llm_client=mock_llm)

    result = pp.preprocess('健康保险产品的等待期有什么具体规定和要求')
    assert result.normalized == '健康保险产品的等待期有什么具体规定和要求'


def test_expand_no_duplicates(preprocessor):
    result = preprocessor.preprocess('退保')
    assert len(result.expanded) == len(set(result.expanded))


def test_original_preserved(preprocessor):
    result = preprocessor.preprocess('退保流程')
    assert result.original == '退保流程'

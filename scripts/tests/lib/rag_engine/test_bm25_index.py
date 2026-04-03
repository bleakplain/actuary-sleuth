#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试 BM25Index 模块"""
import pytest
from pathlib import Path

from lib.rag_engine.bm25_index import BM25Index


def _bm25_path(temp_dir):
    """BM25 index path within temp_dir."""
    return temp_dir / "test_bm25_index.pkl"


class TestBM25IndexBuild:

    def test_build_creates_index_file(self, sample_documents, temp_dir):
        BM25Index.build(sample_documents, _bm25_path(temp_dir))
        assert _bm25_path(temp_dir).exists()

    def test_build_empty_documents(self, temp_dir):
        BM25Index.build([], _bm25_path(temp_dir))
        assert _bm25_path(temp_dir).exists()


class TestBM25IndexLoad:

    def test_load_returns_index(self, sample_documents, temp_dir):
        BM25Index.build(sample_documents, _bm25_path(temp_dir))
        idx = BM25Index.load(_bm25_path(temp_dir))
        assert idx is not None
        assert isinstance(idx, BM25Index)

    def test_load_missing_file(self):
        idx = BM25Index.load(Path("/nonexistent/bm25_index.pkl"))
        assert idx is None


class TestBM25IndexSearch:

    def test_search_returns_results(self, sample_documents, temp_dir):
        BM25Index.build(sample_documents, _bm25_path(temp_dir))
        idx = BM25Index.load(_bm25_path(temp_dir))
        results = idx.search("等待期", top_k=2)
        assert isinstance(results, list)
        assert len(results) <= 2

    def test_search_returns_node_and_score(self, sample_documents, temp_dir):
        BM25Index.build(sample_documents, _bm25_path(temp_dir))
        idx = BM25Index.load(_bm25_path(temp_dir))
        results = idx.search("保险费率", top_k=1)
        if results:
            node, score = results[0]
            assert hasattr(node, 'text')
            assert score > 0

    def test_search_no_match(self, sample_documents, temp_dir):
        BM25Index.build(sample_documents, _bm25_path(temp_dir))
        idx = BM25Index.load(_bm25_path(temp_dir))
        results = idx.search("xyz不存在的词汇123", top_k=3)
        if results:
            for _, score in results:
                assert score >= 0

    def test_search_respects_top_k(self, sample_documents, temp_dir):
        BM25Index.build(sample_documents, _bm25_path(temp_dir))
        idx = BM25Index.load(_bm25_path(temp_dir))
        for k in [1, 3, 5]:
            results = idx.search("保险", top_k=k)
            assert len(results) <= k

    def test_search_with_metadata_filter(self, sample_documents, temp_dir):
        BM25Index.build(sample_documents, _bm25_path(temp_dir))
        idx = BM25Index.load(_bm25_path(temp_dir))
        results = idx.search("保险", top_k=5, filters={'law_name': '保险法'})
        if results:
            for node, _ in results:
                assert node.metadata.get('law_name') == '保险法'


class TestBM25IndexVersionValidation:
    """测试 BM25 索引版本校验"""

    def test_load_invalid_format_returns_none(self, temp_dir):
        import joblib
        joblib.dump({'not_version': True, 'data': []}, _bm25_path(temp_dir), compress=3)
        idx = BM25Index.load(_bm25_path(temp_dir))
        assert idx is None

    def test_load_version_mismatch_returns_none(self, sample_documents, temp_dir):
        import joblib
        joblib.dump({
            'version': '0.9',
            'bm25': None,
            'nodes': [],
        }, _bm25_path(temp_dir), compress=3)
        idx = BM25Index.load(_bm25_path(temp_dir))
        assert idx is None

    def test_doc_count_property(self, sample_documents, temp_dir):
        BM25Index.build(sample_documents, _bm25_path(temp_dir))
        idx = BM25Index.load(_bm25_path(temp_dir))
        assert idx is not None
        assert idx.doc_count == len(sample_documents)

    def test_doc_count_empty_index(self, temp_dir):
        BM25Index.build([], _bm25_path(temp_dir))
        idx = BM25Index.load(_bm25_path(temp_dir))
        assert idx is not None
        assert idx.doc_count == 0

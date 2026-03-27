#!/usr/bin/env python3
"""测试 BM25Index 模块"""
import pytest
import tempfile
from pathlib import Path

from lib.rag_engine.bm25_index import BM25Index


@pytest.fixture
def sample_documents():
    """创建测试文档列表"""
    from llama_index.core import Document

    return [
        Document(
            text="健康保险产品的等待期不得超过90天",
            metadata={'law_name': '健康保险管理办法', 'article_number': '第一条'}
        ),
        Document(
            text="投保人应当如实告知被保险人的健康状况",
            metadata={'law_name': '保险法', 'article_number': '第十六条'}
        ),
        Document(
            text="意外伤害保险的保险期间不得少于1年",
            metadata={'law_name': '意外伤害保险管理办法', 'article_number': '第三条'}
        ),
        Document(
            text="保险公司应当公平合理地确定保险费率",
            metadata={'law_name': '保险法', 'article_number': '第一百三十五条'}
        ),
        Document(
            text="保险期间为1年的保险费应当一次性收取",
            metadata={'law_name': '保险费收取管理办法', 'article_number': '第五条'}
        ),
    ]


@pytest.fixture
def temp_index_path():
    """临时索引文件路径"""
    with tempfile.NamedTemporaryFile(suffix='.pkl', delete=False) as f:
        path = Path(f.name)
    yield path
    if path.exists():
        path.unlink()


class TestBM25IndexBuild:

    def test_build_creates_index_file(self, sample_documents, temp_index_path):
        BM25Index.build(sample_documents, temp_index_path)
        assert temp_index_path.exists()

    def test_build_empty_documents(self, temp_index_path):
        BM25Index.build([], temp_index_path)
        assert temp_index_path.exists()


class TestBM25IndexLoad:

    def test_load_returns_index(self, sample_documents, temp_index_path):
        BM25Index.build(sample_documents, temp_index_path)
        idx = BM25Index.load(temp_index_path)
        assert idx is not None
        assert isinstance(idx, BM25Index)

    def test_load_missing_file(self):
        idx = BM25Index.load(Path("/nonexistent/bm25_index.pkl"))
        assert idx is None


class TestBM25IndexSearch:

    def test_search_returns_results(self, sample_documents, temp_index_path):
        BM25Index.build(sample_documents, temp_index_path)
        idx = BM25Index.load(temp_index_path)
        results = idx.search("等待期", top_k=2)
        assert isinstance(results, list)
        assert len(results) <= 2

    def test_search_returns_node_and_score(self, sample_documents, temp_index_path):
        BM25Index.build(sample_documents, temp_index_path)
        idx = BM25Index.load(temp_index_path)
        results = idx.search("保险费率", top_k=1)
        if results:
            node, score = results[0]
            assert hasattr(node, 'text')
            assert score > 0

    def test_search_no_match(self, sample_documents, temp_index_path):
        BM25Index.build(sample_documents, temp_index_path)
        idx = BM25Index.load(temp_index_path)
        results = idx.search("xyz不存在的词汇123", top_k=3)
        if results:
            for _, score in results:
                assert score >= 0

    def test_search_respects_top_k(self, sample_documents, temp_index_path):
        BM25Index.build(sample_documents, temp_index_path)
        idx = BM25Index.load(temp_index_path)
        for k in [1, 3, 5]:
            results = idx.search("保险", top_k=k)
            assert len(results) <= k

    def test_search_with_metadata_filter(self, sample_documents, temp_index_path):
        BM25Index.build(sample_documents, temp_index_path)
        idx = BM25Index.load(temp_index_path)
        results = idx.search("保险", top_k=5, filters={'law_name': '保险法'})
        if results:
            for node, _ in results:
                assert node.metadata.get('law_name') == '保险法'

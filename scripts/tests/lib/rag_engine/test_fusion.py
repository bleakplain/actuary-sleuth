#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 fusion 模块 - 使用真实数据
"""
import pytest

from lib.rag_engine.fusion import _normalize_scores, compute_bm25_score, fuse_results
from lib.rag_engine.tokenizer import tokenize_chinese


class TestNormalizeScores:
    """测试分数归一化"""

    def test_normalize_empty_scores(self):
        """测试空分数列表"""
        result = _normalize_scores([])
        assert result == []

    def test_normalize_single_score(self):
        """测试单个分数"""
        result = _normalize_scores([0.5])
        assert result == [1.0]

    def test_normalize_multiple_scores(self):
        """测试多个分数"""
        result = _normalize_scores([0.5, 0.7, 0.9])
        assert len(result) == 3
        assert result[0] < result[1] < result[2]
        assert max(result) == 1.0

    def test_normalize_identical_scores(self):
        """测试相同分数"""
        result = _normalize_scores([0.5, 0.5, 0.5])
        assert result == [1.0, 1.0, 1.0]

    def test_normalize_with_zero(self):
        """测试包含零的分数"""
        result = _normalize_scores([0.0, 0.5, 1.0])
        assert len(result) == 3
        assert result[0] == 0.0
        assert result[-1] == 1.0


class TestBM25Score:
    """测试BM25分数计算"""

    def test_bm25_empty_tokens(self):
        """测试空分词"""
        result = compute_bm25_score([], ["test", "document"])
        assert result == 0.0

    def test_bm25_empty_doc_tokens(self):
        """测试空文档分词"""
        result = compute_bm25_score(["query"], [])
        assert result == 0.0

    def test_bm25_no_match(self):
        """测试无匹配"""
        result = compute_bm25_score(["query"], ["document", "text"])
        assert result == 0.0

    def test_bm25_with_match(self):
        """测试有匹配"""
        result = compute_bm25_score(["保险"], ["保险", "条款", "内容"])
        assert result > 0

    def test_bm25_multiple_matches(self):
        """测试多个匹配词"""
        result = compute_bm25_score(
            ["保险", "产品"],
            ["保险", "产品", "条款", "内容", "保险"]
        )
        assert result > 0
        # 多次匹配应该有更高分数
        result_single = compute_bm25_score(
            ["保险"],
            ["保险", "产品", "条款"]
        )
        assert result > result_single

    def test_bm25_with_tokens(self):
        """测试使用分词器的BM25计算"""
        query = ["保险", "产品"]
        doc = ["保险", "产品", "条款", "内容"]
        result = compute_bm25_score(query, doc)
        assert result > 0

    def test_bm25_avg_doc_length_impact(self):
        """测试平均文档长度影响"""
        tokens = ["保险", "产品"]

        # 较短的平均文档长度对相同文档产生的影响不同
        result_short_avg = compute_bm25_score(tokens, ["保险", "产品", "条款"], avg_doc_len=5)
        result_long_avg = compute_bm25_score(tokens, ["保险", "产品", "条款"], avg_doc_len=100)

        # 文档长度相同时，较大的平均长度应该产生较高分数（因为文档相对较短）
        assert result_long_avg >= result_short_avg


class TestFuseResults:
    """测试结果融合 - 使用真实的LlamaIndex节点"""

    def test_fuse_empty_results(self):
        """测试空结果融合"""
        result = fuse_results([], [], 0.5)
        assert result == []

    def test_fuse_results_from_real_index(self, real_vector_index):
        """测试使用真实索引结果进行融合"""
        from llama_index.core.schema import NodeWithScore
        from llama_index.core import Document

        # 创建真实的TextNode
        doc1 = Document(
            text="健康保险等待期为90天",
            metadata={'law_name': '健康保险办法', 'article_number': '第一条', 'category': '健康保险'}
        )
        doc2 = Document(
            text="保险费率应当公平合理",
            metadata={'law_name': '保险法', 'article_number': '第一百三十五条', 'category': '费率管理'}
        )

        # 创建NodeWithScore对象
        vector_node1 = NodeWithScore(node=doc1, score=0.9)
        vector_node2 = NodeWithScore(node=doc2, score=0.7)

        keyword_node1 = NodeWithScore(node=doc2, score=0.8)

        # 执行融合
        result = fuse_results([vector_node1, vector_node2], [keyword_node1], 0.5)

        assert isinstance(result, list)
        assert len(result) > 0

        # 验证结果格式
        for item in result:
            assert 'law_name' in item
            assert 'article_number' in item
            assert 'content' in item
            assert 'score' in item

    def test_fuse_alpha_weighting_with_real_nodes(self, real_vector_index):
        """测试alpha权重对融合的影响"""
        from llama_index.core.schema import NodeWithScore
        from llama_index.core import Document

        doc = Document(
            text="测试内容",
            metadata={'law_name': '测试法规', 'article_number': '第一条', 'category': '测试'}
        )

        vector_node = NodeWithScore(node=doc, score=1.0)
        keyword_node = NodeWithScore(node=doc, score=0.5)

        # alpha=1.0表示只使用向量分数
        result_vector_only = fuse_results([vector_node], [keyword_node], 1.0)
        assert len(result_vector_only) > 0

        # alpha=0.0表示只使用关键词分数
        result_keyword_only = fuse_results([vector_node], [keyword_node], 0.0)
        assert len(result_keyword_only) > 0

    def test_fuse_result_sorting_with_real_nodes(self):
        """测试结果按分数排序"""
        from llama_index.core.schema import NodeWithScore
        from llama_index.core import Document

        nodes = []
        for i in range(5):
            doc = Document(
                text=f"内容{i}",
                metadata={
                    "law_name": f"法规{i}",
                    "article_number": f"第{i}条",
                    "category": "测试"
                }
            )
            node = NodeWithScore(node=doc, score=i * 0.1)
            nodes.append(node)

        result = fuse_results(nodes, [], 1.0)

        # 验证结果按分数降序排列
        for i in range(len(result) - 1):
            assert result[i]['score'] >= result[i+1]['score']


class TestFusionIntegration:
    """融合算法集成测试"""

    def test_full_fusion_workflow(self, temp_lancedb_dir):
        """测试完整的融合工作流程"""
        from llama_index.core import Document, Settings, VectorStoreIndex
        from llama_index.vector_stores.lancedb import LanceDBVectorStore
        from llama_index.core.storage.storage_context import StorageContext
        from llama_index.core.schema import NodeWithScore
        from lib.rag_engine.retrieval import vector_search, keyword_search
        from lib.rag_engine.fusion import fuse_results

        try:
            from llama_index.embeddings.ollama import OllamaEmbedding
            embed_model = OllamaEmbedding(model_name="nomic-embed-text")
            Settings.embed_model = embed_model
        except Exception:
            try:
                from llama_index.embeddings.openai import OpenAIEmbedding
                embed_model = OpenAIEmbedding()
                Settings.embed_model = embed_model
            except Exception:
                pytest.skip("No embedding model available")

        # 1. 创建测试文档
        test_docs = [
            Document(
                text="健康保险等待期为90天，期间内不承担责任",
                metadata={'law_name': '健康保险办法', 'article_number': '第一条', 'category': '健康保险'}
            ),
            Document(
                text="保险费率应当公平合理，不得恶性竞争",
                metadata={'law_name': '保险法', 'article_number': '第一百三十五条', 'category': '费率管理'}
            ),
            Document(
                text="投保人如实告知健康状况，否则保险公司可以解除合同",
                metadata={'law_name': '保险法', 'article_number': '第十六条', 'category': '如实告知'}
            ),
        ]

        # 2. 创建向量索引
        vector_store = LanceDBVectorStore(
            uri=str(temp_lancedb_dir),
            table_name="test_fusion_workflow"
        )
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        index = VectorStoreIndex.from_documents(
            test_docs,
            storage_context=storage_context,
            show_progress=False
        )

        # 3. 执行向量搜索
        vector_results = vector_search(index, "保险等待期", top_k=2)
        assert isinstance(vector_results, list)

        # 4. 执行关键词搜索
        keyword_results = keyword_search(index, "保险等待期", top_k=2, avg_doc_len=30)
        assert isinstance(keyword_results, list)

        # 5. 融合结果
        if vector_results and keyword_results:
            fused_results = fuse_results(vector_results, keyword_results, alpha=0.5)

            assert isinstance(fused_results, list)
            if fused_results:
                assert 'law_name' in fused_results[0]
                assert 'content' in fused_results[0]
                assert 'score' in fused_results[0]

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
法规 RAG 引擎测试脚本

注意：这些测试需要 llama_index 模块。
如果未安装，这些测试将被跳过。
"""
import pytest

# Skip entire module if llama_index is not available
pytest.importorskip("llama_index", reason="llama_index not installed")

# Now import from RAG engine since we know llama_index is available
# 检查依赖
try:
    import llama_index
    HAS_LLAMA_INDEX = True
except ImportError:
    HAS_LLAMA_INDEX = False


@pytest.mark.skipif(not HAS_LLAMA_INDEX, reason="需要 llama_index 模块")
@pytest.mark.rag


@pytest.mark.skipif(not HAS_LLAMA_INDEX, reason="需要 llama_index 模块")
def test_user_qa():
    """测试用户问答功能"""
    print("=" * 60)
    print("测试用户问答引擎")
    print("=" * 60)

    from lib.rag_engine import create_qa_engine

    # 创建问答引擎
    print("\n1. 初始化问答引擎...")
    qa_engine = create_qa_engine()

    # 初始化索引
    print("\n2. 初始化向量索引...")
    assert qa_engine.initialize(force_rebuild=False), "索引初始化失败"

    # 测试查询
    print("\n3. 测试法规查询...")

    test_questions = [
        "健康保险产品的等待期有什么规定？",
        "保险法中关于如实告知义务是如何规定的？",
        "意外伤害保险的保险期限有什么要求？"
    ]

    for i, question in enumerate(test_questions, 1):
        print(f"\n问题 {i}: {question}")
        print("-" * 40)

        result = qa_engine.ask(question)

        print(f"\n回答:")
        print(result['answer'])

        # 验证返回结果结构
        assert 'answer' in result, "结果中缺少 'answer' 字段"
        assert 'sources' in result, "结果中缺少 'sources' 字段"

        if result['sources']:
            print(f"\n相关法规来源 ({len(result['sources'])} 条):")
            for j, source in enumerate(result['sources'][:3], 1):
                print(f"\n  {j}. [{source['law_name']}] - {source['article_number']}")
                print(f"     内容: {source['content']}")
                if source['score']:
                    print(f"     相似度: {source['score']:.4f}")

    print("\n" + "=" * 60)
    print("用户问答测试完成!")
    print("=" * 60)


@pytest.mark.skipif(not HAS_LLAMA_INDEX, reason="需要 llama_index 模块")
def test_audit_query():
    """测试审计查询功能"""
    print("\n" + "=" * 60)
    print("测试审计查询引擎")
    print("=" * 60)

    from lib.rag_engine import create_audit_engine

    # 创建审计查询引擎
    print("\n1. 初始化审计查询引擎...")
    audit_engine = create_audit_engine()

    # 初始化索引
    print("\n2. 初始化向量索引...")
    assert audit_engine.initialize(force_rebuild=False), "索引初始化失败"

    # 测试法规搜索
    print("\n3. 测试法规搜索...")

    test_queries = [
        "健康保险等待期",
        "如实告知义务",
        "意外伤害保险期限"
    ]

    for query in test_queries:
        print(f"\n搜索: {query}")
        print("-" * 40)

        results = audit_engine.search(query, top_k=3)

        print(f"找到 {len(results)} 条相关法规")
        assert isinstance(results, list), "结果应该是列表"
        for j, result in enumerate(results[:3], 1):
            print(f"\n  {j}. [{result['law_name']}] - {result['article_number']}")
            print(f"     类别: {result['category']}")
            print(f"     内容: {result['content'][:150]}...")
            if result['score']:
                print(f"     相似度: {result['score']:.4f}")

    print("\n" + "=" * 60)
    print("审计查询测试完成!")
    print("=" * 60)


@pytest.mark.skipif(not HAS_LLAMA_INDEX, reason="需要 llama_index 模块")
def test_data_importer():
    """测试数据导入功能"""
    print("\n" + "=" * 60)
    print("测试数据导入器")
    print("=" * 60)

    from lib.rag_engine import RegulationDataImporter

    # 创建导入器
    importer = RegulationDataImporter()

    # 测试文档解析
    print("\n1. 测试文档解析...")
    documents = importer.parse_single_file("02_负面清单.md")

    print(f"从 02_负面清单.md 解析了 {len(documents)} 条法规")
    assert isinstance(documents, list), "结果应该是列表"

    if documents:
        print("\n第一条法规示例:")
        print(f"  法律: {documents[0].metadata.get('law_name')}")
        print(f"  条款: {documents[0].metadata.get('article_number')}")
        print(f"  内容: {documents[0].text[:100]}...")

        # 验证文档结构
        assert 'law_name' in documents[0].metadata, "元数据中应包含 law_name"
        assert 'article_number' in documents[0].metadata, "元数据中应包含 article_number"

    print("\n" + "=" * 60)
    print("数据导入测试完成!")
    print("=" * 60)


@pytest.mark.skipif(not HAS_LLAMA_INDEX, reason="需要 llama_index 模块")
def test_async_query():
    """测试异步查询功能"""
    print("\n" + "=" * 60)
    print("测试异步查询功能")
    print("=" * 60)

    import asyncio
    from lib.rag_engine import create_qa_engine

    async def run_async_test():
        qa_engine = create_qa_engine()
        qa_engine.initialize()

        question = "健康保险产品的等待期有什么规定？"
        print(f"\n问题: {question}")

        result = await qa_engine.aask(question)
        print(f"\n回答: {result['answer']}")

        # 验证返回结果
        assert 'answer' in result, "结果中应包含 'answer' 字段"
        assert 'sources' in result, "结果中应包含 'sources' 字段"

        if result['sources']:
            print(f"\n找到 {len(result['sources'])} 个相关法规")

    asyncio.run(run_async_test())


if __name__ == '__main__':
    try:
        # 运行所有测试
        test_data_importer()
        test_user_qa()
        test_audit_query()
        # test_async_query()  # 可选

        print("\n" + "=" * 60)
        print("所有测试完成!")
        print("=" * 60)

    except Exception as e:
        print(f"\n测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

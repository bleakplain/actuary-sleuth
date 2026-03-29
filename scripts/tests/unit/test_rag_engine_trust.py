#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rag_engine trust 相关单元测试

通过直接读取源文件提取 _QA_PROMPT_TEMPLATE，避免触发 llama_index 导入链。
"""
import re
from pathlib import Path

import pytest

_RAG_ENGINE_PATH = Path(__file__).parent.parent.parent / 'lib' / 'rag_engine' / 'rag_engine.py'


def _extract_prompt_template() -> str:
    """从 rag_engine.py 源文件中提取 _QA_PROMPT_TEMPLATE 字符串。"""
    content = _RAG_ENGINE_PATH.read_text(encoding='utf-8')
    match = re.search(
        r'(_QA_PROMPT_TEMPLATE\s*=\s*f?"""(.+?)""")',
        content,
        re.DOTALL,
    )
    if match:
        return match.group(1)
    raise AssertionError(f'Could not find _QA_PROMPT_TEMPLATE in {_RAG_ENGINE_PATH}')


_QA_PROMPT_TEMPLATE = _extract_prompt_template()


class TestPromptCitationFormat:

    def test_prompt_requires_source_tags(self):
        assert '[来源X]' in _QA_PROMPT_TEMPLATE
        assert '事实性陈述' in _QA_PROMPT_TEMPLATE

    def test_prompt_has_few_shot_example(self):
        assert '回答示例' in _QA_PROMPT_TEMPLATE
        assert '[来源1]' in _QA_PROMPT_TEMPLATE

    def test_prompt_requires_only_based_on_sources(self):
        assert '仅依据' in _QA_PROMPT_TEMPLATE

    def test_prompt_has_conflict_handling(self):
        assert '矛盾' in _QA_PROMPT_TEMPLATE

    def test_prompt_has_expert_persona(self):
        assert '保险法规专家' in _QA_PROMPT_TEMPLATE

    def test_prompt_forbids_missing_info(self):
        assert '不存在的信息' in _QA_PROMPT_TEMPLATE


def _llama_index_available() -> bool:
    """Check if llama_index.vector_stores.lancedb is importable."""
    try:
        import llama_index.core  # noqa: F401
        import llama_index.vector_stores.lancedb  # noqa: F401
        return True
    except (ImportError, ModuleNotFoundError):
        return False


@pytest.mark.skipif(
    not _llama_index_available(),
    reason="llama_index not installed",
)
class TestBuildQaPrompt:

    def test_truncation_marks_incomplete_clause(self):
        from lib.rag_engine.rag_engine import RAGEngine
        from lib.rag_engine.config import RAGConfig
        engine = RAGEngine.__new__(RAGEngine)
        engine.config = RAGConfig()

        results = [
            {
                'law_name': '测试法规',
                'article_number': '第一条',
                'content': '短内容。' * 5,
            },
            {
                'law_name': '测试法规',
                'article_number': '第二条',
                'content': '这是一段非常长的内容。' * 200,
            },
        ]

        prompt = engine._build_qa_prompt('测试问题', results)
        assert '……' in prompt

    def test_short_content_not_truncated(self):
        from lib.rag_engine.rag_engine import RAGEngine
        from lib.rag_engine.config import RAGConfig
        engine = RAGEngine.__new__(RAGEngine)
        engine.config = RAGConfig()

        results = [
            {
                'law_name': '测试法规',
                'article_number': '第一条',
                'content': '短内容。',
            },
        ]

        prompt = engine._build_qa_prompt('测试问题', results)
        assert '……' not in prompt

    def test_empty_results(self):
        from lib.rag_engine.rag_engine import RAGEngine
        from lib.rag_engine.config import RAGConfig
        engine = RAGEngine.__new__(RAGEngine)
        engine.config = RAGConfig()

        prompt = engine._build_qa_prompt('测试问题', [])
        assert '用户问题' in prompt
        assert '测试问题' in prompt

    def test_context_numbered_correctly(self):
        from lib.rag_engine.rag_engine import RAGEngine
        from lib.rag_engine.config import RAGConfig
        engine = RAGEngine.__new__(RAGEngine)
        engine.config = RAGConfig()

        results = [
            {
                'law_name': '法规A',
                'article_number': '第一条',
                'content': '内容A。',
            },
            {
                'law_name': '法规B',
                'article_number': '第二条',
                'content': '内容B。',
            },
        ]

        prompt = engine._build_qa_prompt('测试', results)
        assert '1. 【法规A】第一条' in prompt
        assert '2. 【法规B】第二条' in prompt

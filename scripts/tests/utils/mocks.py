#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mock工具
"""
from unittest.mock import MagicMock
from typing import Dict, Any, List
from lib.llm.base import BaseLLMClient


class MockLLMClient(BaseLLMClient):
    """模拟LLM客户端"""

    def __init__(self, response: str = "", model: str = "mock-model"):
        super().__init__(model, timeout=30)
        self._response = response
        self.call_count = 0
        self.calls = []

    def generate(self, prompt: str, **kwargs) -> str:
        self.call_count += 1
        self.calls.append({"type": "generate", "prompt": prompt})
        return self._response

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        self.call_count += 1
        self.calls.append({"type": "chat", "messages": messages})
        return self._response

    def health_check(self) -> bool:
        return True


class MockRAGEngine:
    """模拟RAG引擎"""

    def __init__(self, results: List[Dict[str, Any]] = None):
        self._results = results or []
        self.search_calls = []
        self._initialized = False

    def initialize(self, force_rebuild: bool = False) -> bool:
        self._initialized = True
        return True

    def search(self, query_text: str, top_k: int = 3, **kwargs) -> List[Dict[str, Any]]:
        self.search_calls.append({"query": query_text, "top_k": top_k})
        return self._results[:top_k]

    def ask(self, question: str, top_k: int = 3) -> Dict[str, Any]:
        nodes = self.search(question, top_k)
        return {
            'answer': f"测试答案: {question}",
            'sources': [r.get('metadata', {}) for r in nodes]
        }


class MockDocumentFetcher:
    """模拟文档获取器"""

    def __init__(self, content: str = ""):
        self._content = content
        self.fetch_calls = []

    def fetch(self, url: str) -> str:
        self.fetch_calls.append(url)
        return self._content


class MockDatabase:
    """模拟数据库"""

    def __init__(self):
        self._records = []
        self.save_calls = []

    def save_audit_record(self, audit_id: str, document_url: str, violations: List, score: int) -> bool:
        self.save_calls.append({
            "audit_id": audit_id,
            "document_url": document_url,
            "violations": violations,
            "score": score
        })
        return True

    def get_audit_records(self, audit_id: str = None) -> List[Dict]:
        if audit_id:
            return [r for r in self.save_calls if r["audit_id"] == audit_id]
        return self.save_calls


def create_mock_audit_result(success: bool = True, score: int = 85) -> Dict[str, Any]:
    """创建模拟审核结果"""
    return {
        "success": success,
        "score": score,
        "grade": "良好" if score >= 75 else "不合格",
        "violations": [],
        "summary": {"total_violations": 0}
    }


def create_mock_preprocessed_result() -> Dict[str, Any]:
    """创建模拟预处理结果"""
    from lib.common.models import Product, ProductCategory
    from lib.common.audit import PreprocessedResult
    from lib.common.id_generator import IDGenerator
    from lib.common.date_utils import get_current_timestamp

    return PreprocessedResult(
        audit_id=IDGenerator.generate_audit(),
        document_url="https://test.feishu.cn/docx/test",
        timestamp=get_current_timestamp(),
        product=Product(
            name="测试产品",
            company="测试公司",
            category=ProductCategory.HEALTH,
            period="1年"
        ),
        clauses=[{"number": "第一条", "title": "测试", "text": "内容"}],
        pricing_params={}
    )

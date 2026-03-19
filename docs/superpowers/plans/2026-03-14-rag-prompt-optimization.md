# RAG Prompt 层优化实施计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为保险法规 RAG 系统添加自定义 Prompt 层，实现引用标注、自检反馈和 fallback 机制，解决幻觉问题。

**Architecture:** 新增三个模块（PromptBuilder、SelfCheckProcessor、CitationMapper），扩展现有 prompts.py 和 config.py，在 RAGEngine 中新增 ask_with_prompt() 方法。复用现有 search() 和 chat() 接口，保持向后兼容。

**Tech Stack:** Python 3.12, LlamaIndex, dataclasses, re, typing, logging

---

## 文件结构

```
scripts/lib/
├── rag_engine/
│   ├── models.py              # 新增：数据结构定义
│   ├── prompt_builder.py      # 新增：Prompt 构建器
│   ├── self_check.py          # 新增：自检与 fallback
│   ├── citation_mapper.py     # 新增：引用映射
│   ├── rag_engine.py          # 修改：新增 ask_with_prompt()
│   └── config.py              # 修改：添加 PromptConfig
├── prompts.py                 # 修改：新增 RAG 相关模板
└── tests/
    ├── rag_engine/
    │   ├── test_models.py           # 新增
    │   ├── test_prompt_builder.py   # 新增
    │   ├── test_self_check.py       # 新增
    │   └── test_citation_mapper.py  # 新增
    └── test_rag_engine_integration.py  # 新增
```

---

## Chunk 1: 数据结构定义 (models.py)

### Task 1: 创建 models.py

**Files:**
- Create: `scripts/lib/rag_engine/models.py`
- Test: `scripts/tests/rag_engine/test_models.py`

- [ ] **Step 1: 创建数据结构文件**

```python
# scripts/lib/rag_engine/models.py

from dataclasses import dataclass, field
from typing import List, Dict, Any
import re

@dataclass
class CheckResult:
    """自检结果"""
    is_sufficient: bool
    needs_fallback: bool
    issues: List[str] = field(default_factory=list)
    confidence: float = 0.0

    def __post_init__(self):
        if not 0 <= self.confidence <= 1:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")

@dataclass
class CitationResult:
    """引用映射结果"""
    answer_with_sources: str
    sources: List['SourceInfo']
    invalid_citations: List[int] = field(default_factory=list)

@dataclass
class SourceInfo:
    """单个来源信息"""
    index: int
    law_name: str
    article_number: str
    content: str
    score: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            'index': self.index,
            'law_name': self.law_name,
            'article_number': self.article_number,
            'content': self.content,
            'score': self.score
        }

@dataclass
class PromptConfig:
    """Prompt 配置"""
    max_contexts: int = 10
    enable_fallback: bool = True
    max_fallback_retries: int = 2
    fallback_confidence_threshold: float = 0.5
    citation_pattern: str = r'\[(\d+)\]'
    self_check_enabled: bool = True
    parse_json_fallback: bool = True
    self_check_timeout: int = 30
    use_cheap_model_for_fallback: bool = False

    def __post_init__(self):
        if self.max_contexts < 1:
            raise ValueError(f"max_contexts must be >= 1, got {self.max_contexts}")
        if self.max_fallback_retries < 0:
            raise ValueError(f"max_fallback_retries must be >= 0, got {self.max_fallback_retries}")
        if not 0 <= self.fallback_confidence_threshold <= 1:
            raise ValueError(f"fallback_confidence_threshold must be in [0, 1], got {self.fallback_confidence_threshold}")
        try:
            re.compile(self.citation_pattern)
        except re.error as e:
            raise ValueError(f"Invalid citation_pattern regex: {e}")
```

- [ ] **Step 2: 写数据结构测试**

```python
# scripts/tests/rag_engine/test_models.py

import pytest
from lib.rag_engine.models import CheckResult, CitationResult, SourceInfo, PromptConfig

def test_check_result_validation():
    with pytest.raises(ValueError):
        CheckResult(is_sufficient=True, needs_fallback=False, confidence=1.5)

def test_check_result_default_values():
    result = CheckResult(is_sufficient=True, needs_fallback=False)
    assert result.issues == []
    assert result.confidence == 0.0

def test_source_info_to_dict():
    source = SourceInfo(
        index=1,
        law_name="测试法规",
        article_number="第一条",
        content="测试内容",
        score=0.85
    )
    result = source.to_dict()
    assert result['index'] == 1
    assert result['law_name'] == "测试法规"

def test_prompt_config_validation():
    with pytest.raises(ValueError):
        PromptConfig(max_contexts=0)

    with pytest.raises(ValueError):
        PromptConfig(citation_pattern="[invalid")

def test_prompt_config_regex_validation():
    config = PromptConfig(citation_pattern=r'\[(\d+)\]')
    assert config.citation_pattern == r'\[(\d+)\]'
```

- [ ] **Step 3: 运行测试验证失败**

```bash
cd /root/.openclaw/workspace/skills/actuary-sleuth
source .venv/bin/activate
pytest tests/rag_engine/test_models.py -v
```

Expected: ModuleNotFoundError 或 ImportError（文件不存在）

- [ ] **Step 4: 创建测试目录**

```bash
mkdir -p scripts/tests/rag_engine
touch scripts/tests/rag_engine/__init__.py
```

- [ ] **Step 5: 再次运行测试验证失败**

```bash
pytest tests/rag_engine/test_models.py -v
```

Expected: ImportError (models.py 不存在)

- [ ] **Step 6: 创建 models.py 文件**

- [ ] **Step 7: 运行测试验证通过**

```bash
pytest tests/rag_engine/test_models.py -v
```

Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add scripts/lib/rag_engine/models.py scripts/tests/rag_engine/
git commit -m "feat: add RAG prompt layer data structures

- Add CheckResult, CitationResult, SourceInfo dataclasses
- Add PromptConfig with validation
- Add unit tests for data structures"
```

---

## Chunk 2: Prompt 模板扩展 (prompts.py)

### Task 2: 扩展 prompts.py

**Files:**
- Modify: `scripts/lib/prompts.py`
- Test: `scripts/tests/test_prompts.py`

- [ ] **Step 1: 添加 RAG 相关 prompt 模板**

在 `scripts/lib/prompts.py` 末尾添加：

```python
# RAG 系统提示词
RAG_SYSTEM_PROMPT = """你是一位保险监管法规专家，专门协助合规审计人员查询和分析保险相关法律法规。

【核心原则】
1. 仅依据提供的法规资料回答问题，不得编造或添加资料外的信息
2. 如果资料中没有相关信息，明确说明"提供的资料中未找到相关内容"
3. 专业严谨：使用法条原文，准确引用条款号和法规名称

【引用规范】
- 答案中必须使用 [1][2] 格式标注信息来源
- 每个关键断言都应有引用支撑
- 同一来源多次引用可重复使用同一编号

【冲突处理】
- 当不同法规对同一问题有不同规定时，优先参考高层级法规：
  法律 > 部门规章 > 规范性文件
- 如有必要，在答案中说明不同规定的差异

【输出格式】
- 结构清晰，分点论述
- 引用法条时注明：法规名称 + 条款号 + 核心内容"""

# 自检提示词
RAG_SELF_CHECK_PROMPT = """请检查以下答案是否符合要求：

【问题】{question}

【答案】{answer}

【检查要点】
1. 答案是否表明"未找到相关信息"或"资料不足"？
2. 答案中的关键断言是否有引用标注？
3. 引用编号是否在提供的资料范围内（1-{max_contexts}）？

请严格按照以下 JSON 格式返回，不要添加任何其他内容：
{{
  "is_sufficient": true|false,
  "needs_fallback": true|false,
  "issues": ["问题描述1", "问题描述2"],
  "confidence": 0.0-1.0
}}"""

# 查询重写提示词
RAG_QUERY_REWRITE_PROMPT = """请重写以下查询，提取关键词并添加相关同义词，以便更好地检索保险法规：

原始问题：{question}

请只返回重写后的问题，不要添加任何解释。

示例：
原始问题："这个怎么申请？"
重写后："保险产品申请流程和条件"

原始问题："等待期多久？"
重写后："健康保险等待期天数和相关规定"
"""

def format_rag_user_prompt(question: str, contexts: str) -> str:
    """格式化 RAG 用户提示词"""
    return f"""【问题】{question}

【法规资料】
{contexts}"""

def format_self_check_prompt(question: str, answer: str, max_contexts: int) -> str:
    """格式化自检提示词"""
    return RAG_SELF_CHECK_PROMPT.format(
        question=question,
        answer=answer,
        max_contexts=max_contexts
    )

def format_query_rewrite_prompt(question: str) -> str:
    """格式化查询重写提示词"""
    return RAG_QUERY_REWRITE_PROMPT.format(question=question)
```

- [ ] **Step 2: 写 prompts.py 测试**

```python
# scripts/tests/test_prompts.py (追加到现有文件)

import pytest
from lib.prompts import (
    format_rag_user_prompt,
    format_self_check_prompt,
    format_query_rewrite_prompt,
    RAG_SYSTEM_PROMPT
)

def test_format_rag_user_prompt():
    result = format_rag_user_prompt("测试问题", "[1] 测试内容")
    assert "【问题】测试问题" in result
    assert "[1] 测试内容" in result

def test_format_self_check_prompt():
    result = format_self_check_prompt("测试问题", "测试答案", 10)
    assert "{question}" not in result
    assert "测试问题" in result
    assert "1-10" in result

def test_format_query_rewrite_prompt():
    result = format_query_rewrite_prompt("等待期多久？")
    assert "等待期多久？" in result
    assert "重写后的问题" in result

def test_rag_system_prompt_contains_required_elements():
    assert "[1][2]" in RAG_SYSTEM_PROMPT
    assert "法律 > 部门规章" in RAG_SYSTEM_PROMPT
    assert "不得编造" in RAG_SYSTEM_PROMPT
```

- [ ] **Step 3: 运行测试验证通过**

```bash
pytest tests/test_prompts.py -v -k "rag"
```

Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add scripts/lib/prompts.py scripts/tests/test_prompts.py
git commit -m "feat: add RAG prompt templates

- Add RAG_SYSTEM_PROMPT with anti-hallucination instructions
- Add self-check prompt template with JSON output format
- Add query rewrite prompt template
- Add formatter functions for all templates
- Add unit tests for prompt formatting"
```

---

## Chunk 3: PromptBuilder 模块

### Task 3: 实现 PromptBuilder

**Files:**
- Create: `scripts/lib/rag_engine/prompt_builder.py`
- Test: `scripts/tests/rag_engine/test_prompt_builder.py`

- [ ] **Step 1: 写 PromptBuilder 测试**

```python
# scripts/tests/rag_engine/test_prompt_builder.py

import pytest
from lib.rag_engine.prompt_builder import PromptBuilder
from lib.rag_engine.models import PromptConfig

def test_build_context_basic():
    config = PromptConfig(max_contexts=10)
    builder = PromptBuilder(config)

    docs = [
        {'law_name': '保险法', 'article_number': '第十六条', 'content': '测试内容1', 'score': 0.9},
        {'law_name': '健康保险规定', 'article_number': '第二十七条', 'content': '测试内容2', 'score': 0.8}
    ]

    result = builder.build_context(docs, max_contexts=2)

    assert '[1] 来源：保险法 - 第十六条' in result
    assert '[2] 来源：健康保险规定 - 第二十七条' in result
    assert '测试内容1' in result

def test_build_context_with_missing_metadata():
    config = PromptConfig()
    builder = PromptBuilder(config)

    docs = [
        {'article_number': '第十六条', 'content': '测试', 'score': 0.9}  # 缺少 law_name
    ]

    result = builder.build_context(docs)
    assert '未知法规' in result

def test_build_context_max_contexts_limit():
    config = PromptConfig()
    builder = PromptBuilder(config)

    docs = [{'law_name': '测试', 'article_number': '1', 'content': f'内容{i}', 'score': 0.9} for i in range(20)]

    result = builder.build_context(docs, max_contexts=5)
    assert result.count('[1]') == 1
    assert result.count('[5]') == 1
    assert '[6]' not in result

def test_sort_by_hierarchy():
    config = PromptConfig()
    builder = PromptBuilder(config)

    docs = [
        {'law_name': '规范性文件通知', 'content': '低优先级', 'score': 0.9},
        {'law_name': '保险管理办法', 'content': '中优先级', 'score': 0.8},
        {'law_name': '保险法', 'content': '高优先级', 'score': 0.7}
    ]

    result = builder.sort_by_hierarchy(docs)

    assert result[0]['law_name'] == '保险法'
    assert result[1]['law_name'] == '保险管理办法'
    assert result[2]['law_name'] == '规范性文件通知'

def test_get_hierarchy_level():
    assert PromptBuilder._get_hierarchy_level('保险法') == 1
    assert PromptBuilder._get_hierarchy_level('管理办法') == 2
    assert PromptBuilder._get_hierarchy_level('通知') == 3
    assert PromptBuilder._get_hierarchy_level('其他') == 4
```

- [ ] **Step 2: 运行测试验证失败**

```bash
pytest tests/rag_engine/test_prompt_builder.py -v
```

Expected: ImportError

- [ ] **Step 3: 实现 PromptBuilder**

```python
# scripts/lib/rag_engine/prompt_builder.py

from typing import List, Dict
from .models import PromptConfig
from lib.prompts import RAG_SYSTEM_PROMPT, format_rag_user_prompt

class PromptBuilder:
    def __init__(self, config: PromptConfig = None):
        self.config = config or PromptConfig()

    def build_context(
        self,
        retrieved_docs: List[Dict],
        max_contexts: int = None
    ) -> str:
        if max_contexts is None:
            max_contexts = self.config.max_contexts
        if max_contexts < 1:
            raise ValueError(f"max_contexts must be >= 1, got {max_contexts}")

        docs_to_use = retrieved_docs[:max_contexts]

        context_parts = []
        for i, doc in enumerate(docs_to_use, 1):
            law_name = doc.get('law_name', '未知法规')
            article_number = doc.get('article_number', '未知条款')
            content = doc.get('content', '')

            part = f"[{i}] 来源：{law_name} - {article_number}\n内容：{content}"
            context_parts.append(part)

        return '\n\n'.join(context_parts)

    def build_system_prompt(self) -> str:
        return RAG_SYSTEM_PROMPT

    def build_user_prompt(self, question: str, contexts: str) -> str:
        return format_rag_user_prompt(question, contexts)

    def sort_by_hierarchy(self, docs: List[Dict]) -> List[Dict]:
        def get_level(doc):
            law_name = doc.get('law_name', '')
            return self._get_hierarchy_level(law_name)

        return sorted(docs, key=get_level)

    @staticmethod
    def _get_hierarchy_level(law_name: str) -> int:
        if not law_name:
            return 4

        name = law_name.lower()
        if '法' in name and '办法' not in name and '规定' not in name and '通知' not in name and '细则' not in name:
            return 1
        if any(kw in name for kw in ['办法', '规定', '细则', '规程']):
            return 2
        if any(kw in name for kw in ['通知', '指引', '意见', '批复']):
            return 3
        return 4
```

- [ ] **Step 4: 运行测试验证通过**

```bash
pytest tests/rag_engine/test_prompt_builder.py -v
```

Expected: PASS

- [ ] **Step 5: 更新 __init__.py 导出**

```python
# scripts/lib/rag_engine/__init__.py

from .prompt_builder import PromptBuilder
```

- [ ] **Step 6: 提交**

```bash
git add scripts/lib/rag_engine/prompt_builder.py scripts/tests/rag_engine/test_prompt_builder.py
git commit -m "feat: implement PromptBuilder for RAG context formatting

- Add build_context() to format retrieved docs with [1][2] numbering
- Add sort_by_hierarchy() for regulation priority sorting
- Add hierarchy detection based on law_name patterns
- Add system/user prompt builder methods
- Add unit tests"
```

---

## Chunk 4: CitationMapper 模块

### Task 4: 实现 CitationMapper

**Files:**
- Create: `scripts/lib/rag_engine/citation_mapper.py`
- Test: `scripts/tests/rag_engine/test_citation_mapper.py`

- [ ] **Step 1: 写 CitationMapper 测试**

```python
# scripts/tests/rag_engine/test_citation_mapper.py

import pytest
from lib.rag_engine.citation_mapper import CitationMapper
from lib.rag_engine.models import PromptConfig

def test_extract_citations():
    config = PromptConfig()
    mapper = CitationMapper(config)

    assert mapper.extract_citations("根据[1]规定") == [1]
    assert mapper.extract_citations("[1][2][3]") == [1, 2, 3]
    assert mapper.extract_citations("无引用") == []

def test_validate_citations():
    config = PromptConfig()
    mapper = CitationMapper(config)

    valid, invalid = mapper.validate_citations("[1][2]", 2)
    assert valid == [1, 2]
    assert invalid == []

    valid, invalid = mapper.validate_citations("[1][5]", 3)
    assert valid == [1]
    assert invalid == [5]

def test_map_citations_basic():
    config = PromptConfig()
    mapper = CitationMapper(config)

    docs = [
        {'law_name': '保险法', 'article_number': '第16条', 'content': '如实告知', 'score': 0.9},
        {'law_name': '健康规定', 'article_number': '第27条', 'content': '等待期180天', 'score': 0.8}
    ]

    result = mapper.map_citations("根据[1]规定，等待期[2]不得超过180天。", docs)

    assert '保险法' in result.answer_with_sources or '相关法规' in result.answer_with_sources
    assert len(result.sources) == 2
    assert result.sources[0].index == 1
    assert result.sources[1].index == 2
    assert result.invalid_citations == []

def test_map_citations_with_invalid():
    config = PromptConfig()
    mapper = CitationMapper(config)

    docs = [{'law_name': '测试', 'article_number': '1', 'content': '内容', 'score': 0.9}]

    result = mapper.map_citations("根据[5]规定", docs)

    assert result.invalid_citations == [5]
    assert len(result.sources) == 0

def test_map_citations_deduplication():
    config = PromptConfig()
    mapper = CitationMapper(config)

    docs = [{'law_name': '测试', 'article_number': '1', 'content': '内容', 'score': 0.9}]

    result = mapper.map_citations("[1][1][1]规定", docs)

    assert len(result.sources) == 1
    assert result.sources[0].index == 1
```

- [ ] **Step 2: 运行测试验证失败**

```bash
pytest tests/rag_engine/test_citation_mapper.py -v
```

Expected: ImportError

- [ ] **Step 3: 实现 CitationMapper**

```python
# scripts/lib/rag_engine/citation_mapper.py

from typing import List, Dict, Tuple
import re
from .models import CitationResult, SourceInfo, PromptConfig

class CitationMapper:
    def __init__(self, config: PromptConfig = None):
        self.config = config or PromptConfig()
        self.citation_pattern = re.compile(config.citation_pattern)

    def map_citations(
        self,
        answer: str,
        retrieved_docs: List[Dict]
    ) -> CitationResult:
        citation_numbers = self.extract_citations(answer)

        if not citation_numbers:
            return CitationResult(
                answer_with_sources=answer,
                sources=[],
                invalid_citations=[]
            )

        unique_citations = list(set(citation_numbers))
        valid, invalid = self.validate_citations(answer, len(retrieved_docs))

        used_docs = []
        for idx in unique_citations:
            if 1 <= idx <= len(retrieved_docs):
                doc = retrieved_docs[idx - 1]
                used_docs.append(SourceInfo(
                    index=idx,
                    law_name=doc.get('law_name', '未知法规'),
                    article_number=doc.get('article_number', '未知条款'),
                    content=doc.get('content', '')[:200],
                    score=doc.get('score', 0.0)
                ))

        sources_text = self.format_sources([d.to_dict() for d in used_docs])
        answer_with_sources = f"{answer}\n\n{sources_text}" if sources_text else answer

        return CitationResult(
            answer_with_sources=answer_with_sources,
            sources=used_docs,
            invalid_citations=invalid
        )

    def validate_citations(
        self,
        answer: str,
        max_index: int
    ) -> Tuple[List[int], List[int]]:
        citations = self.extract_citations(answer)
        valid = [c for c in citations if 1 <= c <= max_index]
        invalid = [c for c in citations if c < 1 or c > max_index]
        return valid, invalid

    def extract_citations(self, answer: str) -> List[int]:
        matches = self.citation_pattern.findall(answer)
        return [int(m) for m in matches]

    def format_sources(
        self,
        used_docs: List[Dict]
    ) -> str:
        if not used_docs:
            return ""

        lines = ["**相关法规**："]
        for doc in used_docs:
            lines.append(f"- [{doc['index']}] {doc['law_name']} - {doc['article_number']}")
            lines.append(f"  内容：{doc['content']}")
            lines.append(f"  相似度：{doc['score']:.2f}")

        return '\n'.join(lines)
```

- [ ] **Step 4: 运行测试验证通过**

```bash
pytest tests/rag_engine/test_citation_mapper.py -v
```

Expected: PASS

- [ ] **Step 5: 更新 __init__.py**

```python
# scripts/lib/rag_engine/__init__.py

from .citation_mapper import CitationMapper
```

- [ ] **Step 6: 提交**

```bash
git add scripts/lib/rag_engine/citation_mapper.py scripts/tests/rag_engine/test_citation_mapper.py
git commit -m "feat: implement CitationMapper for source mapping

- Add extract_citations() using regex pattern
- Add validate_citations() to check index bounds
- Add map_citations() to map [1][2] to actual sources
- Add format_sources() to generate readable sources list
- Add unit tests"
```

---

## Chunk 5: SelfCheckProcessor 模块

### Task 5: 实现 SelfCheckProcessor

**Files:**
- Create: `scripts/lib/rag_engine/self_check.py`
- Test: `scripts/tests/rag_engine/test_self_check.py`

- [ ] **Step 1: 写 SelfCheckProcessor 测试**

```python
# scripts/tests/rag_engine/test_self_check.py

import pytest
from unittest.mock import MagicMock, patch
from lib.rag_engine.self_check import SelfCheckProcessor
from lib.rag_engine.models import PromptConfig, CheckResult

def test_check_answer_with_json():
    config = PromptConfig()
    llm_provider = lambda: MagicMock(chat=lambda msgs: '{"is_sufficient": true, "needs_fallback": false, "issues": [], "confidence": 0.8}')
    processor = SelfCheckProcessor(llm_provider, config)

    result = processor.check_answer("问题", "答案[1]", "上下文")

    assert result.is_sufficient is True
    assert result.needs_fallback is False
    assert result.confidence == 0.8

def test_check_answer_with_invalid_json():
    config = PromptConfig(parse_json_fallback=True)
    llm_provider = lambda: MagicMock(chat=lambda msgs: "invalid json")
    processor = SelfCheckProcessor(llm_provider, config)

    result = processor.check_answer("问题", "答案", "上下文")

    assert result.is_sufficient is True  # 默认值
    assert result.confidence == 0.5

def test_should_trigger_fallback():
    config = PromptConfig(fallback_confidence_threshold=0.5)
    processor = SelfCheckProcessor(lambda: None, config)

    result1 = CheckResult(is_sufficient=False, needs_fallback=True, confidence=0.3)
    assert processor.should_trigger_fallback(result1) is True

    result2 = CheckResult(is_sufficient=True, needs_fallback=False, confidence=0.8)
    assert processor.should_trigger_fallback(result2) is False

@patch('lib.rag_engine.self_check.SelfCheckProcessor._rewrite_query')
def test_fallback_retrieve_widens(mock_rewrite):
    config = PromptConfig(max_fallback_retries=2)
    search_func = lambda q, **kw: [{'content': f'结果_{q}', 'score': 0.5}]
    processor = SelfCheckProcessor(lambda: None, config)

    results = processor.fallback_retrieve("测试问题", search_func, retry_count=0)

    assert len(results) > 0

def test_fallback_retrieve_exceeds_limit():
    config = PromptConfig(max_fallback_retries=1)
    search_func = lambda q, **kw: []
    processor = SelfCheckProcessor(lambda: None, config)

    results = processor.fallback_retrieve("测试问题", search_func, retry_count=2)

    assert results == []
```

- [ ] **Step 2: 运行测试验证失败**

```bash
pytest tests/rag_engine/test_self_check.py -v
```

Expected: ImportError

- [ ] **Step 3: 实现 SelfCheckProcessor**

```python
# scripts/lib/rag_engine/self_check.py

from typing import List, Dict, Callable
import json
import logging
from .models import CheckResult, PromptConfig
from lib.prompts import format_self_check_prompt, format_query_rewrite_prompt

logger = logging.getLogger(__name__)

class SelfCheckProcessor:
    def __init__(
        self,
        llm_provider: Callable[[], object],
        config: PromptConfig = None
    ):
        self.llm_provider = llm_provider
        self.config = config or PromptConfig()

    def check_answer(
        self,
        question: str,
        answer: str,
        contexts: str
    ) -> CheckResult:
        llm_client = self.llm_provider()

        try:
            prompt = format_self_check_prompt(question, answer, self.config.max_contexts)
            response = llm_client.chat([{'role': 'user', 'content': prompt}])
            return self._parse_check_response(response)
        except Exception as e:
            logger.warning(f"Self-check LLM call failed: {e}")
            return CheckResult(
                is_sufficient=True,
                needs_fallback=False,
                issues=["自检调用失败"],
                confidence=0.5
            )

    def should_trigger_fallback(self, check_result: CheckResult) -> bool:
        return (
            check_result.needs_fallback or
            check_result.confidence < self.config.fallback_confidence_threshold
        )

    def fallback_retrieve(
        self,
        question: str,
        search_func: Callable,
        retry_count: int = 0
    ) -> List[Dict]:
        if retry_count >= self.config.max_fallback_retries:
            return []

        if retry_count == 0:
            top_k = self.config.max_contexts * 2
            return search_func(question, top_k=top_k, use_hybrid=True)
        elif retry_count == 1:
            rewritten = self._rewrite_query(question)
            return search_func(rewritten, top_k=self.config.max_contexts, use_hybrid=True)

        return []

    def _rewrite_query(self, question: str) -> str:
        try:
            llm_client = self.llm_provider()
            prompt = format_query_rewrite_prompt(question)
            return llm_client.chat([{'role': 'user', 'content': prompt}])
        except Exception as e:
            logger.warning(f"Query rewrite failed: {e}")
            return question

    def _parse_check_response(self, response: str) -> CheckResult:
        try:
            data = json.loads(response)
            return CheckResult(
                is_sufficient=data.get('is_sufficient', True),
                needs_fallback=data.get('needs_fallback', False),
                issues=data.get('issues', []),
                confidence=data.get('confidence', 0.5)
            )
        except json.JSONDecodeError:
            if self.config.parse_json_fallback:
                return CheckResult(
                    is_sufficient=True,
                    needs_fallback=False,
                    issues=["JSON 解析失败"],
                    confidence=0.5
                )
            raise ValueError(f"Invalid JSON response: {response}")
```

- [ ] **Step 4: 运行测试验证通过**

```bash
pytest tests/rag_engine/test_self_check.py -v
```

Expected: PASS

- [ ] **Step 5: 更新 __init__.py**

```python
# scripts/lib/rag_engine/__init__.py

from .self_check import SelfCheckProcessor
```

- [ ] **Step 6: 提交**

```bash
git add scripts/lib/rag_engine/self_check.py scripts/tests/rag_engine/test_self_check.py
git commit -m "feat: implement SelfCheckProcessor for answer validation

- Add check_answer() using LLM to validate answer quality
- Add should_trigger_fallback() to determine if retrieval needed
- Add fallback_retrieve() with widen and query rewrite strategies
- Add _rewrite_query() to extract keywords and synonyms
- Add JSON parsing with fallback behavior
- Add unit tests with mocks"
```

---

## Chunk 6: 集成到 RAGEngine

### Task 6: 实现 ask_with_prompt() 方法

**Files:**
- Modify: `scripts/lib/rag_engine/rag_engine.py`
- Modify: `scripts/lib/rag_engine/config.py`
- Test: `scripts/tests/rag_engine/test_rag_engine_integration.py`

- [ ] **Step 1: 扩展 config.py**

在 `scripts/lib/rag_engine/config.py` 中添加：

```python
from .rag_engine.models import PromptConfig

@dataclass
class RAGConfig:
    # ... 现有字段 ...
    prompt_config: PromptConfig = None

    def __post_init__(self):
        # ... 现有逻辑 ...
        if self.prompt_config is None:
            self.prompt_config = PromptConfig()
```

- [ ] **Step 2: 写集成测试**

```python
# scripts/tests/rag_engine/test_rag_engine_integration.py

import pytest
from lib.rag_engine import create_qa_engine

def test_ask_with_prompt_basic():
    engine = create_qa_engine()
    engine.initialize()

    result = engine.ask_with_prompt("健康保险等待期有什么规定？")

    assert 'answer' in result
    assert 'sources' in result
    assert 'invalid_citations' in result
    assert 'fallback_triggered' in result
    assert 'confidence' in result
    assert isinstance(result['confidence'], float)

def test_ask_with_prompt_with_citations():
    engine = create_qa_engine()
    engine.initialize()

    result = engine.ask_with_prompt("如实告知义务")

    assert len(result['sources']) > 0
    assert any('[1]' in s['content'] for s in result['sources'])

def test_ask_with_prompt_backward_compatible():
    engine = create_qa_engine()
    engine.initialize()

    # 原 ask() 方法仍可用
    old_result = engine.ask("健康保险等待期")

    assert 'answer' in old_result
    assert 'sources' in old_result
```

- [ ] **Step 3: 运行测试验证失败**

```bash
pytest tests/rag_engine/test_rag_engine_integration.py -v
```

Expected: AttributeError (ask_with_prompt 不存在)

- [ ] **Step 4: 实现 ask_with_prompt() 方法**

在 `scripts/lib/rag_engine/rag_engine.py` 中添加：

```python
from .models import PromptConfig, CitationResult
from .prompt_builder import PromptBuilder
from .self_check import SelfCheckProcessor
from .citation_mapper import CitationMapper

class RAGEngine:
    # ... 现有代码 ...

    def __init__(self, ...):
        # ... 现有代码 ...
        if self.config.prompt_config is None:
            self.config.prompt_config = PromptConfig()

    def ask_with_prompt(
        self,
        question: str,
        include_sources: bool = True
    ) -> Dict[str, Any]:
        if self.query_engine is None:
            if not self.initialize():
                return self._error_result('引擎初始化失败')

        config = self.config.prompt_config

        retrieved_docs = self.search(question, top_k=config.max_contexts, use_hybrid=True)
        if not retrieved_docs:
            return self._error_result('未找到相关法规')

        prompt_builder = PromptBuilder(config)
        sorted_docs = prompt_builder.sort_by_hierarchy(retrieved_docs)
        contexts = prompt_builder.build_context(sorted_docs, max_contexts=config.max_contexts)
        system_prompt = prompt_builder.build_system_prompt()
        user_prompt = prompt_builder.build_user_prompt(question, contexts)

        llm_client = self.llm_provider()
        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt}
        ]

        try:
            answer = llm_client.chat(messages)
        except Exception as e:
            logger.error(f"LLM chat() failed: {e}")
            return self._error_result('生成答案时出错，请稍后重试')

        fallback_triggered = False
        final_answer = answer
        confidence = 0.5

        if config.enable_fallback and config.self_check_enabled:
            self_check = SelfCheckProcessor(self.llm_provider, config)
            check_result = self_check.check_answer(question, answer, contexts)
            confidence = check_result.confidence

            if self_check.should_trigger_fallback(check_result):
                try:
                    fallback_docs = self_check.fallback_retrieve(question, self.search, retry_count=0)
                    if fallback_docs:
                        fallback_triggered = True
                        retrieved_docs.extend(fallback_docs)
                        sorted_docs = prompt_builder.sort_by_hierarchy(retrieved_docs)
                        contexts = prompt_builder.build_context(sorted_docs, max_contexts=config.max_contexts)
                        user_prompt = prompt_builder.build_user_prompt(question, contexts)
                        messages = [
                            {'role': 'system', 'content': system_prompt},
                            {'role': 'user', 'content': user_prompt}
                        ]
                        final_answer = llm_client.chat(messages)

                        second_check = self_check.check_answer(question, final_answer, contexts)
                        if self_check.should_trigger_fallback(second_check):
                            fallback_docs_2 = self_check.fallback_retrieve(question, self.search, retry_count=1)
                            if fallback_docs_2:
                                retrieved_docs.extend(fallback_docs_2)
                                sorted_docs = prompt_builder.sort_by_hierarchy(retrieved_docs)
                                contexts = prompt_builder.build_context(sorted_docs, max_contexts=config.max_contexts)
                                user_prompt = prompt_builder.build_user_prompt(question, contexts)
                                messages = [
                                    {'role': 'system', 'content': system_prompt},
                                    {'role': 'user', 'content': user_prompt}
                                ]
                                final_answer = llm_client.chat(messages)
                except Exception as e:
                    logger.warning(f"Fallback failed: {e}, using original answer")

        citation_mapper = CitationMapper(config)
        citation_result = citation_mapper.map_citations(final_answer, sorted_docs)

        return {
            'answer': citation_result.answer_with_sources,
            'sources': [s.to_dict() for s in citation_result.sources],
            'invalid_citations': citation_result.invalid_citations,
            'fallback_triggered': fallback_triggered,
            'confidence': confidence
        }

    def _error_result(self, message: str) -> Dict[str, Any]:
        logger.error(f"RAG error: {message}")
        return {
            'answer': message,
            'sources': [],
            'invalid_citations': [],
            'fallback_triggered': False,
            'confidence': 0.0
        }
```

- [ ] **Step 5: 运行测试验证通过**

```bash
pytest tests/rag_engine/test_rag_engine_integration.py -v
```

Expected: PASS

- [ ] **Step 6: 更新 __init__.py 导出**

```python
# scripts/lib/rag_engine/__init__.py

from .rag_engine import RAGEngine, create_qa_engine, create_audit_engine
from .models import PromptConfig, CheckResult, CitationResult, SourceInfo
from .prompt_builder import PromptBuilder
from .self_check import SelfCheckProcessor
from .citation_mapper import CitationMapper
```

- [ ] **Step 7: 运行完整测试套件**

```bash
pytest tests/rag_engine/ -v
pytest tests/run_rag_tests.py
```

Expected: 全部 PASS

- [ ] **Step 8: 提交**

```bash
git add scripts/lib/rag_engine/ scripts/lib/rag_engine/config.py scripts/tests/rag_engine/
git commit -m "feat: add ask_with_prompt() method with citation and fallback

- Add ask_with_prompt() method with custom prompt layer
- Integrate PromptBuilder for context formatting and hierarchy sorting
- Integrate SelfCheckProcessor for answer validation and fallback
- Integrate CitationMapper for [1][2] citation mapping
- Extend RAGConfig with PromptConfig
- Add integration tests
- Maintain backward compatibility with existing ask() method"
```

---

## 验收标准

完成所有任务后，运行以下命令验证：

```bash
# 单元测试
pytest tests/rag_engine/ -v

# 集成测试
pytest tests/rag_engine/test_rag_engine_integration.py -v

# RAG 完整测试
pytest tests/run_rag_tests.py

# 功能测试
python3 << 'EOF'
from lib.rag_engine import create_qa_engine

engine = create_qa_engine()
engine.initialize()

# 测试新方法
result = engine.ask_with_prompt("健康保险等待期有什么规定？")
print(f"Answer: {result['answer'][:200]}...")
print(f"Sources: {len(result['sources'])}")
print(f"Confidence: {result['confidence']}")
print(f"Fallback: {result['fallback_triggered']}")

# 测试向后兼容
old_result = engine.ask("等待期")
print(f"Old method works: {len(old_result['sources'])} sources")
EOF
```

**预期输出**：
- 所有测试通过
- ask_with_prompt() 返回包含引用标注的答案
- confidence 在 [0, 1] 范围内
- 原 ask() 方法正常工作

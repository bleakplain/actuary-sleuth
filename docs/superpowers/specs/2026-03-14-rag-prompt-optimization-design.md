# RAG Prompt 层优化设计

## 概述

为保险法规 RAG 系统设计完全自定义的 Prompt 层，解决幻觉问题、实现引用标注、建立自检反馈机制。采用专业严谨风格，面向合规审计场景。

## 目标

1. **C - Prompt 优化**：控制上下文数量与排序、明确输出形式约束、处理冲突信息
2. **D - 引用标注**：在答案中标注 `[1][2]` 引用，映射回法规来源
3. **E - 自检与反馈**：答案质量自检、触发 fallback 检索、查询重写

## 设计决策

| 方面 | 决策 | 理由 |
|------|------|------|
| 答案风格 | 专业严谨，面向合规审计 | 用户是审计人员，需要法条级别精确度 |
| 引用格式 | 简洁引用 `[1][2]` | 答案可读性好，详情在 sources 列表 |
| Fallback 策略 | 混合：宽化检索 → 查询重写 | 平衡召回率和准确度 |
| 冲突处理 | 层级优先：法律 > 部门规章 > 规范性文件 | 法规效力层级决定优先级 |
| 多轮对话 | 不预留 | 专注单轮问答，降低复杂度 |
| 检索方式 | 复用现有 search() 方法 | 避免重构检索层，保持兼容 |
| Prompt 存储 | Python 字符串常量 | 与现有 prompts.py 保持一致 |

## 架构

### 整体流程

```
用户问题
    │
    ▼
┌─────────────────┐
│   search()      │ ← 复用现有混合检索
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  PromptBuilder  │ ← 格式化上下文、层级排序
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   LLM chat()    │ ← 使用 messages 数组
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│SelfCheckProcessor│ ← 自检、触发 fallback
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ CitationMapper  │ ← 映射引用编号
└────────┬────────┘
         │
         ▼
    最终答案
```

### 模块结构

```
scripts/lib/
├── rag_engine/
│   ├── rag_engine.py          # 修改：新增 ask_with_prompt() 方法
│   ├── models.py              # 新增：数据结构定义
│   ├── prompt_builder.py      # 新增：Prompt 构建器
│   ├── self_check.py          # 新增：自检与 fallback
│   └── citation_mapper.py     # 新增：引用映射
└── prompts.py                 # 修改：新增 RAG 相关 prompt 模板
```

**设计说明**：
- 保留现有 `ask()` 方法不变，新增 `ask_with_prompt()` 方法使用新功能
- 复用现有 `search()` 方法获取检索结果，无需修改检索层
- 使用 `chat()` 方法而非 `generate()`，支持 system message
- Prompt 模板添加到现有 `prompts.py`，保持代码风格一致
- 向后兼容，现有调用代码无需修改

## 数据结构

```python
# rag_engine/models.py

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
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

    # 引用提取配置
    citation_pattern: str = r'\[(\d+)\]'
    # 正则模式说明：匹配方括号内的单个数字，如 [1]、[2]
    # 不支持 [1,2,3] 或 [1-3] 等复杂格式

    # 自检配置
    self_check_enabled: bool = True
    parse_json_fallback: bool = True  # JSON 解析失败时：True 返回默认值，False 抛出异常

    # 性能配置
    self_check_timeout: int = 30  # 自检 LLM 超时（秒）
    use_cheap_model_for_fallback: bool = False  # fallback 是否使用更便宜的模型

    def __post_init__(self):
        if self.max_contexts < 1:
            raise ValueError(f"max_contexts must be >= 1, got {self.max_contexts}")
        if self.max_fallback_retries < 0:
            raise ValueError(f"max_fallback_retries must be >= 0, got {self.max_fallback_retries}")
        if not 0 <= self.fallback_confidence_threshold <= 1:
            raise ValueError(f"fallback_confidence_threshold must be in [0, 1], got {self.fallback_confidence_threshold}")
        # 验证正则表达式有效性
        try:
            re.compile(self.citation_pattern)
        except re.error as e:
            raise ValueError(f"Invalid citation_pattern regex: {e}")
```

## Prompt 模板

**扩展 prompts.py**：
```python
# prompts.py 新增内容

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

## 组件设计

### 1. PromptBuilder

**职责**：
- 构建系统提示词（防幻觉指令）
- 格式化检索上下文（带 `[1][2]` 编号）
- 按层级排序检索结果

**接口**：
```python
# rag_engine/prompt_builder.py

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
        """格式化检索上下文，返回带编号的文本

        每个文档格式：
        [1] 来源：{law_name} - {article_number}
        内容：{content}

        参数处理：
        - max_contexts=None：使用 self.config.max_contexts
        - max_contexts > len(retrieved_docs)：使用所有可用文档
        - max_contexts < 1：抛出 ValueError

        边界情况：
        - law_name 缺失时使用"未知法规"
        - article_number 缺失时使用"未知条款"
        """

    def build_system_prompt(self) -> str:
        """构建系统提示词"""
        return RAG_SYSTEM_PROMPT

    def build_user_prompt(self, question: str, contexts: str) -> str:
        """构建用户提示词"""
        return format_rag_user_prompt(question, contexts)

    def sort_by_hierarchy(self, docs: List[Dict]) -> List[Dict]:
        """按法规层级排序：法律 > 部门规章 > 规范性文件

        同层级内保持原始检索顺序（已按 score 排序）。
        """

    @staticmethod
    def _get_hierarchy_level(law_name: str) -> int:
        """根据法规名称推断层级

        优先级 1（法律）：包含"法"且不含"办法"/"规定"/"通知"/"细则"
        优先级 2（部门规章）：包含"办法"/"规定"/"细则"/"规程"
        优先级 3（规范性文件）：包含"通知"/"指引"/"意见"/"批复"
        优先级 4（其他）：其他情况

        注意：这是简化启发式规则，可能存在误分类。
        未来可通过添加 metadata.hierarchy_level 字段来改进。
        """
```

### 2. SelfCheckProcessor

**职责**：
- 验证答案质量
- 检测答案是否表明信息不足
- 触发 fallback 检索

**接口**：
```python
# rag_engine/self_check.py

from typing import List, Dict, Callable
from .models import CheckResult, PromptConfig
from lib.prompts import format_self_check_prompt, format_query_rewrite_prompt
from lib.llm_client import BaseLLMClient
import json
import logging

logger = logging.getLogger(__name__)

class SelfCheckProcessor:
    def __init__(
        self,
        llm_provider: Callable[[], BaseLLMClient],
        config: PromptConfig = None
    ):
        """
        llm_provider: 返回 LLM 客户端的可调用对象
                   使用 Callable 而非直接传入 BaseLLMClient，允许每次调用获取新实例
                   这与 RAGEngine 的设计保持一致
        """
        self.llm_provider = llm_provider
        self.config = config or PromptConfig()

    def check_answer(
        self,
        question: str,
        answer: str,
        contexts: str  # 格式化后的上下文字符串，用于自检提示词
    ) -> CheckResult:
        """自检答案质量

        调用 LLM 进行自检，解析返回的 JSON 结果。
        如果 JSON 解析失败，返回默认结果（不触发 fallback）。

        注意：contexts 参数用于自检提示词中，让 LLM 知道有多少资料可用。
        """

    def should_trigger_fallback(self, check_result: CheckResult) -> bool:
        """判断是否需要 fallback 检索

        触发条件：
        - check_result.needs_fallback == True
        - 或 check_result.confidence < fallback_confidence_threshold
        """

    def fallback_retrieve(
        self,
        question: str,
        search_func: Callable,
        retry_count: int = 0
    ) -> List[Dict]:
        """执行 fallback 检索（非递归实现）

        每次调用只执行当前 retry_count 对应的策略，返回该策略的结果。
        递归由调用方 ask_with_prompt() 控制。

        Fallback 策略：
        - retry_count=0：宽化检索（top_k * 2）
        - retry_count=1：查询重写（使用 LLM 重写查询，然后检索）

        如果 retry_count >= max_fallback_retries（默认 2），返回空列表。

        注意：max_fallback_retries=2 表示最多允许 2 次 fallback 调用。
        第一次 fallback (retry_count=0) 成功后，如果仍需 fallback，调用方会用 retry_count=1 再次调用。
        """

    def _rewrite_query(self, question: str) -> str:
        """使用 LLM 重写查询，提取关键词和同义词"""

    def _parse_check_response(self, response: str) -> CheckResult:
        """解析自检响应

        如果 JSON 解析失败且 parse_json_fallback=True，返回默认值：
        CheckResult(is_sufficient=True, needs_fallback=False, issues=["解析失败"], confidence=0.5)
        注意：confidence=0.5 是中性值，不会单独触发 fallback（需要配合 needs_fallback）

        如果 parse_json_fallback=False，抛出 ValueError。
        """
```

### 3. CitationMapper

**职责**：
- 验证答案中引用编号的有效性
- 将 `[1][2]` 映射回法规来源
- 生成最终的 sources 列表

**接口**：
```python
# rag_engine/citation_mapper.py

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
        """映射引用编号

        流程：
        1. 从答案中提取 [1][2] 引用编号
        2. 验证编号在有效范围内
        3. 收集被引用的文档
        4. 生成带 sources 列表的答案

        边界情况：
        - 无引用：返回原答案，sources 为空
        - 引用越界：记录到 invalid_citations
        - 重复引用：去重
        """

    def validate_citations(
        self,
        answer: str,
        max_index: int
    ) -> Tuple[List[int], List[int]]:
        """验证引用编号是否在有效范围内

        Returns:
            (valid_citations, invalid_citations)
        """

    def extract_citations(self, answer: str) -> List[int]:
        """从答案中提取所有引用编号

        支持格式：
        - [1] -> [1]
        - [2] -> [2]
        - [1][2] -> [1, 2] （多个独立引用）

        正则模式：r'\[(\d+)\]'
        匹配方括号内的单个数字。
        """

    def format_sources(
        self,
        used_docs: List[Dict]
    ) -> str:
        """格式化 sources 列表为可读文本

        返回格式：
        **相关法规**：
        - [1] 法规名称 - 条款号
          内容：摘要...
          相似度：0.xx

        注意：此方法返回的字符串会追加到 answer_with_sources 中。
        """
```

## 修改 RAGEngine

### 新增 ask_with_prompt() 方法

```python
# rag_engine/rag_engine.py 新增内容

from typing import Callable, Dict, Any
from .models import PromptConfig, CitationResult
from .prompt_builder import PromptBuilder
from .self_check import SelfCheckProcessor
from .citation_mapper import CitationMapper
from lib.llm_client import BaseLLMClient
import logging

logger = logging.getLogger(__name__)

class RAGEngine:
    # ... 现有代码 ...

    def __init__(self, ...):
        # ... 现有代码 ...
        # 扩展：添加 prompt_config
        if self.config.prompt_config is None:
            self.config.prompt_config = PromptConfig()

    def ask_with_prompt(
        self,
        question: str,
        include_sources: bool = True
    ) -> Dict[str, Any]:
        """
        使用自定义 Prompt 层的问答方法

        与 ask() 方法的区别：
        - 自定义 Prompt 模板（防幻觉指令）
        - 引用标注 [1][2]
        - 自检与 fallback 机制
        - 层级排序

        Args:
            question: 用户问题
            include_sources: 是否在结果中包含相关法规来源

        Returns:
            Dict: {
                'answer': str,                  # LLM 生成的答案
                'sources': List[Dict],          # 相关法规来源
                'invalid_citations': List[int], # 无效的引用编号
                'fallback_triggered': bool,     # 是否触发了 fallback
                'confidence': float             # 答案置信度
            }
        """
        if self.query_engine is None:
            if not self.initialize():
                return self._error_result('引擎初始化失败')

        config = self.config.prompt_config

        # 1. 执行检索（复用现有 search() 方法）
        retrieved_docs = self.search(
            question,
            top_k=config.max_contexts,
            use_hybrid=True
        )

        if not retrieved_docs:
            return self._error_result('未找到相关法规')

        # 2. 构建上下文
        prompt_builder = PromptBuilder(config)
        sorted_docs = prompt_builder.sort_by_hierarchy(retrieved_docs)
        contexts = prompt_builder.build_context(sorted_docs, max_contexts=config.max_contexts)
        system_prompt = prompt_builder.build_system_prompt()
        user_prompt = prompt_builder.build_user_prompt(question, contexts)

        # 3. 生成答案（使用 chat() 方法）
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

        # 4. 自检与 fallback
        fallback_triggered = False
        final_answer = answer
        confidence = 0.5

        if config.enable_fallback and config.self_check_enabled:
            self_check = SelfCheckProcessor(self.llm_provider, config)
            check_result = self_check.check_answer(question, answer, contexts)
            confidence = check_result.confidence

            if self_check.should_trigger_fallback(check_result):
                try:
                    fallback_docs = self_check.fallback_retrieve(
                        question,
                        self.search,
                        retry_count=0
                    )
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

                        # 如果答案仍不满足，进行第二次 fallback（查询重写）
                        second_check = self_check.check_answer(question, final_answer, contexts)
                        if self_check.should_trigger_fallback(second_check):
                            fallback_docs_2 = self_check.fallback_retrieve(
                                question,
                                self.search,
                                retry_count=1
                            )
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

        # 5. 映射引用
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
        """生成错误结果

        同时记录错误日志。
        """
        return {
            'answer': message,
            'sources': [],
            'invalid_citations': [],
            'fallback_triggered': False,
            'confidence': 0.0
        }

    # 保留原有 ask() 方法不变
    def ask(self, question: str, include_sources: bool = True) -> Dict[str, Any]:
        # ... 现有实现保持不变 ...
        pass
```

## 数据流

### 检索上下文格式

```
[1] 来源：保险法相关监管规定 - 第十六条
内容：订立保险合同，保险人就保险标的或者被保险人的有关情况提出询问的，投保人应当如实告知。
投保人故意或者因重大过失未履行前款规定的如实告知义务...

[2] 来源：健康保险产品开发相关监管规定 - 第二十七条
内容：疾病保险、医疗保险、护理保险产品的等待期不得超过 180 天。
```

### 答案格式

```
根据《保险法》第十六条，投保人在订立保险合同时应当如实告知[1]。
对于健康保险产品，等待期不得超过 180 天[2]。

**相关法规**：
- [1] 保险法相关监管规定 - 第十六条
  内容：订立保险合同，保险人就保险标的...
  相似度：0.85
- [2] 健康保险产品开发相关监管规定 - 第二十七条
  内容：疾病保险、医疗保险、护理保险产品的等待期...
  相似度：0.92
```

## 错误处理

| 场景 | 处理方式 | 日志级别 |
|------|----------|----------|
| 检索无结果 | 返回"未找到相关法规"，不调用 LLM | WARNING |
| LLM chat() 失败 | 返回错误提示，记录异常 | ERROR |
| 自检 LLM 失败 | 返回默认 CheckResult（不触发 fallback） | ERROR |
| 自检 JSON 解析失败 | 根据 parse_json_fallback 决定 | WARNING |
| Fallback chat() 失败 | 停止 fallback，使用首次答案 | WARNING |
| 引用编号越界 | 保留答案，记录到 invalid_citations | WARNING |
| 无引用编号 | 返回原答案，sources 为空 | INFO |
| 搜索结果不足 max_contexts | 使用所有可用结果 | INFO |
| 层级排序无匹配 | 保持原顺序 | INFO |

## 配置

**扩展 RAGConfig**：
```python
# config.py

@dataclass
class RAGConfig:
    # ... 现有字段 ...
    prompt_config: PromptConfig = None

    def __post_init__(self):
        # ... 现有逻辑 ...
        if self.prompt_config is None:
            self.prompt_config = PromptConfig()
```

**配置示例**：
```python
# 低延迟场景（禁用 fallback）
config = RAGConfig()
config.prompt_config.enable_fallback = False
config.prompt_config.self_check_enabled = False

# 高质量场景（增加上下文）
config.prompt_config.max_contexts = 15
config.prompt_config.fallback_confidence_threshold = 0.3

# 开发/测试场景
config.prompt_config.enable_fallback = True
config.prompt_config.parse_json_fallback = True
```

## 性能考虑

| 操作 | LLM 调用 | 预估额外耗时 | 搜索调用 | 总耗时影响 |
|------|----------|-------------|----------|-----------|
| 首次问答 | 1 (chat) | 基线 ~200ms | 1 (hybrid) | 基线 |
| 自检 | +1 (chat) | +100ms | 0 | +50% |
| Fallback 宽化 | +1 (chat) | +100ms | +1 (hybrid) | +100% |
| Fallback 重写 | +2 (chat + chat) | +200ms | +2 (rewrite + hybrid) | +200% |
| 最坏情况 | 4 | +400ms | +3 | +200% |

注：实际耗时取决于 LLM 提供商和模型选择（glm-z1-air 约为 200ms，glm-4-plus 约为 500ms）

**优化建议**：
- 对延迟敏感的场景：禁用 fallback 和自检
- 批量处理场景：可启用完整 fallback
- 可考虑用更便宜的模型做自检和查询重写
- 超时配置：self_check_timeout 防止长时间等待

## 测试计划

### 单元测试

1. **models.py**
   - 测试 CheckResult 置信度验证
   - 测试 SourceInfo.to_dict()
   - 测试 PromptConfig __post_init__ 验证

2. **prompt_builder.py**
   - 测试上下文格式化
   - 测试层级排序（各种 law_name）
   - 测试边界情况

3. **self_check.py**
   - 测试自检结果解析（正常、格式错误、缺失字段）
   - 测试 fallback 触发条件
   - 测试查询重写
   - Mock LLM 响应

4. **citation_mapper.py**
   - 测试引用提取（正则匹配）
   - 测试引用验证
   - 测试引用去重
   - 测试 sources 格式化

### 集成测试

1. 完整问答流程（正常路径）
2. Fallback 机制（宽化 → 重写 → 上限）
3. 边界条件：
   - 无结果、LLM 失败
   - JSON 解析失败、LLM 返回非 JSON
   - 引用越界、无引用编号
4. 层级排序效果
5. 与现有 ask() 方法对比

### 评估指标

- **答案质量**：法条引用准确率、信息覆盖率
- **防幻觉**：无依据断言数量
- **引用完整性**：引用标注覆盖率、引用准确率
- **Fallback 效果**：触发率、质量提升
- **性能**：平均/p95 响应时间、LLM 调用次数

## 实施步骤

1. 创建 models.py（数据结构）
2. 扩展 prompts.py（新增 RAG 相关模板）
3. 创建 prompt_builder.py
4. 创建 self_check.py
5. 创建 citation_mapper.py
6. 修改 rag_engine.py（新增 ask_with_prompt()）
7. 扩展 config.py（添加 PromptConfig）
8. 编写单元测试
9. 编写集成测试
10. 运行评估并调优

## 迁移指南

### 从 ask() 迁移到 ask_with_prompt()

**步骤 1：更新调用代码**
```python
# 之前
result = engine.ask("健康保险等待期有什么规定？")
print(result['answer'])
for source in result['sources']:
    print(source['law_name'], source['article_number'])

# 之后
result = engine.ask_with_prompt("健康保险等待期有什么规定？")
print(result['answer'])
for source in result['sources']:
    print(source['law_name'], source['article_number'])

# 新增功能
if result['invalid_citations']:
    # 处理无效引用
    pass
if result['fallback_triggered']:
    # 记录 fallback 使用情况
    pass
if result['confidence'] < 0.7:
    # 低置信度答案处理
    pass
```

**步骤 2：配置调优**
```python
# 根据场景调整配置
config = RAGConfig()

# 高质量优先（审计场景）
config.prompt_config.max_contexts = 15
config.prompt_config.enable_fallback = True
config.prompt_config.fallback_confidence_threshold = 0.3

# 低延迟优先（客服场景）
config.prompt_config.max_contexts = 5
config.prompt_config.enable_fallback = False
config.prompt_config.self_check_enabled = False
```

**步骤 3：监控指标**
- fallback_triggered 比率：过高可能需要优化检索
- confidence 分布：过低可能需要调整阈值
- invalid_citations 数量：过多可能需要优化 prompt

## 向后兼容

**保证兼容**：
- 保留 `ask()` 方法不变
- 新增 `ask_with_prompt()` 方法
- `search()` 方法保持不变
- 现有调用代码无需修改

**迁移示例**：
```python
# 现有代码（继续工作）
result = engine.ask("健康保险等待期有什么规定？")

# 新代码（使用增强功能）
result = engine.ask_with_prompt("健康保险等待期有什么规定？")
if result['invalid_citations']:
    logger.warning(f"Invalid citations: {result['invalid_citations']}")
if result['fallback_triggered']:
    logger.info("Fallback was triggered")
print(f"Confidence: {result['confidence']:.2f}")
```

## 未来扩展

**预留扩展点**：
- 多轮对话：在 PromptBuilder 添加 conversation_history 参数
- 异步支持：添加 aask_with_prompt() 方法
- 自定义层级规则：在 PromptConfig 添加自定义排序函数
- 更多引用格式：扩展 citation_pattern 支持 [1,2,3]
- 缓存机制：缓存常见问题和答案

## 其他考虑

### 线程安全

`ask_with_prompt()` 方法与现有 `ask()` 方法共享相同的 `RAGEngine` 实例。
在多线程环境下使用时，需要注意：
- 各组件（PromptBuilder、SelfCheckProcessor、CitationMapper）是无状态的，可以共享
- `llm_provider` 返回的 `BaseLLMClient` 实例需要线程安全（现有实现已支持）

### 日志策略

| 组件 | 日志级别 | 场景 |
|------|----------|------|
| PromptBuilder | DEBUG | 上下文构建、层级排序 |
| SelfCheckProcessor | INFO | 自检结果、fallback 触发 |
| CitationMapper | WARNING | 引用越界、无引用 |
| RAGEngine | ERROR | LLM 调用失败、检索失败 |

### 引用格式设计

选择 `r'\[(\d+)\]'` 正则表达式的原因：
- 简单明确：只匹配 `[数字]` 格式
- 避免误匹配：不会匹配 `[1,2,3]` 或 `[1-3]` 等复杂格式
- 易于扩展：未来可通过修改 `citation_pattern` 支持更多格式

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
│   LLM 生成      │ ← 直接调用 LLM client
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
scripts/lib/rag_engine/
├── rag_engine.py          # 修改：新增 ask_with_prompt() 方法
├── models.py              # 新增：数据结构定义
├── prompt_builder.py      # 新增：Prompt 构建器
├── self_check.py          # 新增：自检与 fallback
├── citation_mapper.py     # 新增：引用映射
└── prompts/
    ├── system_prompt.yaml         # 系统提示词模板
    ├── self_check_prompt.yaml     # 自检提示词模板
    └── query_rewrite_prompt.yaml  # 查询重写模板
```

**设计说明**：
- 保留现有 `ask()` 方法不变，新增 `ask_with_prompt()` 方法使用新功能
- 复用现有 `search()` 方法获取检索结果，无需修改检索层
- 向后兼容，现有调用代码无需修改

## 数据结构

```python
# models.py

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
    allow_multiple_citations: bool = True  # 支持 [1,2,3] 格式

    # 自检配置
    self_check_enabled: bool = True
    parse_json_fallback: bool = True  # JSON 解析失败时的行为

    def __post_init__(self):
        if self.max_contexts < 1:
            raise ValueError(f"max_contexts must be >= 1, got {self.max_contexts}")
        if not 0 <= self.fallback_confidence_threshold <= 1:
            raise ValueError(f"fallback_confidence_threshold must be in [0, 1], got {self.fallback_confidence_threshold}")
```

## 组件设计

### 1. PromptBuilder

**职责**：
- 构建系统提示词（防幻觉指令）
- 格式化检索上下文（带 `[1][2]` 编号）
- 按层级排序检索结果

**接口**：
```python
class PromptBuilder:
    def __init__(self, config: PromptConfig = None):
        self.config = config or PromptConfig()

    def build_context(
        self,
        retrieved_docs: List[Dict],
        max_contexts: int = None
    ) -> str:
        """格式化检索上下文，返回带编号的文本"""

    def build_system_prompt(self) -> str:
        """构建系统提示词"""

    def sort_by_hierarchy(self, docs: List[Dict]) -> List[Dict]:
        """按法规层级排序：法律 > 部门规章 > 规范性文件

        层级检测基于 law_name 字段：
        优先级 1（法律）：包含"法"且不含"办法"/"规定"/"通知"
        优先级 2（部门规章）：包含"办法"/"规定"/"细则"
        优先级 3（规范性文件）：包含"通知"/"指引"/"意见"
        优先级 4（其他）：其他情况
        """

    @staticmethod
    def _get_hierarchy_level(law_name: str) -> int:
        """根据法规名称推断层级"""
        if not law_name:
            return 4

        name = law_name.lower()
        # 法律：包含"法"但不是"办法"/"规定"
        if '法' in name and '办法' not in name and '规定' not in name:
            return 1
        # 部门规章
        if any(kw in name for kw in ['办法', '规定', '细则']):
            return 2
        # 规范性文件
        if any(kw in name for kw in ['通知', '指引', '意见']):
            return 3
        return 4
```

**系统提示词模板**：
```yaml
# prompts/system_prompt.yaml
role: >
  你是一位保险监管法规专家，专门协助合规审计人员查询和分析保险相关法律法规。

principles: |
  【核心原则】
  1. 仅依据提供的法规资料回答问题，不得编造或添加资料外的信息
  2. 如果资料中没有相关信息，明确说明"提供的资料中未找到相关内容"
  3. 专业严谨：使用法条原文，准确引用条款号和法规名称

citation_rules: |
  【引用规范】
  - 答案中必须使用 [1][2] 格式标注信息来源
  - 每个关键断言都应有引用支撑
  - 同一来源多次引用可重复使用同一编号

conflict_handling: |
  【冲突处理】
  - 当不同法规对同一问题有不同规定时，优先参考高层级法规：
    法律 > 部门规章 > 规范性文件
  - 如有必要，在答案中说明不同规定的差异

output_format: |
  【输出格式】
  - 结构清晰，分点论述
  - 引用法条时注明：法规名称 + 条款号 + 核心内容
```

### 2. SelfCheckProcessor

**职责**：
- 验证答案质量（是否充分利用资料、有无无依据断言）
- 检测答案是否表明信息不足
- 触发 fallback 检索（宽化 → 查询重写）

**接口**：
```python
class SelfCheckProcessor:
    def __init__(self, llm_provider: Callable[[], BaseLLMClient], config: PromptConfig = None):
        self.llm_provider = llm_provider
        self.config = config or PromptConfig()

    def check_answer(
        self,
        question: str,
        answer: str,
        contexts: List[str]
    ) -> CheckResult:
        """自检答案质量

        调用 LLM 进行自检，解析返回的 JSON 结果。
        如果 JSON 解析失败，返回默认结果（不触发 fallback）。
        """

    def should_trigger_fallback(self, check_result: CheckResult) -> bool:
        """判断是否需要 fallback 检索"""

    def fallback_retrieve(
        self,
        question: str,
        search_func: Callable,
        retry_count: int = 0
    ) -> List[Dict]:
        """执行 fallback 检索

        Fallback 策略：
        - 第1次 retry：宽化检索（top_k * 2）
        - 第2次 retry：查询重写（使用 LLM 重写查询）

        Args:
            question: 原始问题
            search_func: 检索函数（签名：search(query, top_k, use_hybrid) -> List[Dict]）
            retry_count: 当前重试次数

        Returns:
            额外的检索结果，如果达到最大重试次数则返回空列表
        """

    def _rewrite_query(self, question: str) -> str:
        """使用 LLM 重写查询，提取关键词和同义词"""
```

**自检提示词模板**：
```yaml
# prompts/self_check_prompt.yaml
template: |
  请检查以下答案是否符合要求：

  【问题】{question}

  【答案】{answer}

  【检查要点】
  1. 答案是否表明"未找到相关信息"或"资料不足"？
  2. 答案中的关键断言是否有引用标注？
  3. 引用编号是否在提供的资料范围内（1-{max_context}）？

  请严格按照以下 JSON 格式返回，不要添加任何其他内容：
  {{
    "is_sufficient": true|false,
    "needs_fallback": true|false,
    "issues": ["问题描述1", "问题描述2"],
    "confidence": 0.0-1.0
  }}

fallback_parse: |
  如果无法解析 JSON，使用以下默认值：
  {
    "is_sufficient": true,
    "needs_fallback": false,
    "issues": ["自检结果解析失败"],
    "confidence": 0.5
  }
```

**查询重写提示词模板**：
```yaml
# prompts/query_rewrite_prompt.yaml
template: |
  请重写以下查询，提取关键词并添加相关同义词，以便更好地检索保险法规：

  原始问题：{question}

  请只返回重写后的问题，不要添加任何解释。

  示例：
  原始问题："这个怎么申请？"
  重写后："保险产品申请流程和条件"

  原始问题："等待期多久？"
  重写后："健康保险等待期天数和相关规定"
```

**Fallback 流程**：
```
首次答案
    │
    ▼
┌───────────────────┐
│  自检答案质量      │
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│  判断是否需要 fallback  │ ← needs_fallback || confidence < threshold
└────────┬──────────┘
         │ No
         ▼
     返回答案
         │ Yes
         ▼
┌───────────────────┐
│  retry_count < max ?│
└────────┬──────────┘
         │ No
         ▼
     返回答案
         │ Yes
         ▼
┌───────────────────┐
│  retry_count == 0 ?│
└────────┬──────────┘
         │ Yes (宽化检索)
         ▼
┌───────────────────┐
│  search(q, top_k*2)│
└────────┬──────────┘
         │ No (查询重写)
         ▼
┌───────────────────┐
│  LLM 重写查询      │
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│  search(重写后查询)│
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│  重新生成答案      │
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│  递归自检          │ ← retry_count + 1
└───────────────────┘
```

### 3. CitationMapper

**职责**：
- 验证答案中引用编号的有效性
- 将 `[1][2]` 映射回法规来源
- 生成最终的 sources 列表

**接口**：
```python
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

        边界情况处理：
        - 无引用：返回原答案，sources 为空列表
        - 引用越界：记录到 invalid_citations，答案中标记为 [X-无效]
        - 重复引用：去重，每个 index 只出现一次
        """

    def validate_citations(
        self,
        answer: str,
        max_index: int
    ) -> tuple[List[int], List[int]]:
        """验证引用编号是否在有效范围内

        Returns:
            (valid_citations, invalid_citations)
        """

    def extract_citations(self, answer: str) -> List[int]:
        """从答案中提取所有引用编号

        支持格式：
        - [1] -> [1]
        - [1][2] -> [1, 2]
        - [1,2,3] -> [1, 2, 3]（如果 allow_multiple_citations=True）
        """

    def format_sources(
        self,
        used_docs: List[Dict]
    ) -> str:
        """格式化 sources 列表为可读文本

        格式：
        **相关法规**：
        - [1] 法规名称 - 条款号
          内容：摘要...
          相似度：0.xx
        """
```

**引用提取正则**：
```python
# 支持的格式
# [1] -> 1
# [1][2] -> 1, 2
# [1, 2, 3] -> 1, 2, 3 (如果启用)
CITATION_PATTERN = r'\[(\d+(?:,\s*\d+)*)\]'
```

## 修改 RAGEngine

### 新增 ask_with_prompt() 方法

```python
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
            'answer': str,              # LLM 生成的答案
            'sources': List[Dict],      # 相关法规来源（SourceInfo.to_dict()）
            'invalid_citations': List[int],  # 无效的引用编号
            'fallback_triggered': bool,  # 是否触发了 fallback
            'confidence': float         # 答案置信度
        }
    """
    if self.query_engine is None:
        if not self.initialize():
            return {
                'answer': '引擎初始化失败',
                'sources': [],
                'invalid_citations': [],
                'fallback_triggered': False,
                'confidence': 0.0
            }

    config = self.config.prompt_config

    # 1. 执行检索（复用现有 search() 方法）
    retrieved_docs = self.search(question, top_k=config.max_contexts, use_hybrid=True)

    if not retrieved_docs:
        return {
            'answer': '未找到相关法规',
            'sources': [],
            'invalid_citations': [],
            'fallback_triggered': False,
            'confidence': 0.0
        }

    # 2. 构建上下文
    prompt_builder = PromptBuilder(config)
    sorted_docs = prompt_builder.sort_by_hierarchy(retrieved_docs)
    contexts = prompt_builder.build_context(sorted_docs, max_contexts=config.max_contexts)
    system_prompt = prompt_builder.build_system_prompt()

    # 3. 生成答案
    llm_client = self.llm_provider()
    user_prompt = f"【问题】{question}\n\n【法规资料】\n{contexts}"

    answer = llm_client.generate(
        user_prompt,
        system_prompt=system_prompt
    )

    # 4. 自检与 fallback
    fallback_triggered = False
    final_answer = answer
    confidence = 0.5

    if config.enable_fallback and config.self_check_enabled:
        self_check = SelfCheckProcessor(self.llm_provider, config)
        check_result = self_check.check_answer(question, answer, contexts)
        confidence = check_result.confidence

        if self_check.should_trigger_fallback(check_result):
            fallback_docs = self_check.fallback_retrieve(
                question,
                self.search,  # 传入检索函数
                retry_count=0
            )
            if fallback_docs:
                fallback_triggered = True
                retrieved_docs.extend(fallback_docs)
                sorted_docs = prompt_builder.sort_by_hierarchy(retrieved_docs)
                contexts = prompt_builder.build_context(sorted_docs, max_contexts=config.max_contexts)
                final_answer = llm_client.generate(
                    f"【问题】{question}\n\n【法规资料】\n{contexts}",
                    system_prompt=system_prompt
                )

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

# 保留原有 ask() 方法不变，确保向后兼容
def ask(self, question: str, include_sources: bool = True) -> Dict[str, Any]:
    """
    原有问答方法（保持不变）

    Returns:
        Dict: {
            'answer': str,
            'sources': List[Dict]  # 原有格式
        }
    """
    # ... 现有实现 ...
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

### 引用映射示例

```python
# 输入
answer = "根据保险法第十六条[1]，投保人应当如实告知。等待期不得超过180天[2]。"
retrieved_docs = [
    {'law_name': '保险法相关监管规定', 'article_number': '第十六条', ...},
    {'law_name': '健康保险产品开发相关监管规定', 'article_number': '第二十七条', ...}
]

# 输出
CitationResult(
    answer_with_sources="根据保险法第十六条[1]，投保人应当如实告知。等待期不得超过180天[2]。\n\n**相关法规**：...",
    sources=[
        SourceInfo(index=1, law_name='保险法相关监管规定', article_number='第十六条', ...),
        SourceInfo(index=2, law_name='健康保险产品开发相关监管规定', article_number='第二十七条', ...)
    ],
    invalid_citations=[]
)
```

## 错误处理

| 场景 | 处理方式 |
|------|----------|
| 检索无结果 | 返回"未找到相关法规"，不调用 LLM |
| LLM 生成失败 | 记录错误，返回"生成答案时出错，请稍后重试" |
| 自检 LLM 失败 | 返回默认 CheckResult（不触发 fallback） |
| 自检 JSON 解析失败 | 根据 parse_json_fallback 配置决定是否使用默认值 |
| Fallback 生成失败 | 停止 fallback，返回首次答案 |
| 引用编号越界 | 保留答案，在 sources 中标注无效，记录到 invalid_citations |
| 无引用编号 | 返回原答案，sources 为空列表 |
| 重复引用编号 | 去重处理 |
| Fallback 达到上限 | 停止重试，返回当前最佳答案 |
| 层级排序无匹配 | 保持原顺序 |

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
# 禁用 fallback（低延迟场景）
config = RAGConfig()
config.prompt_config.enable_fallback = False

# 增加上下文数量
config.prompt_config.max_contexts = 15

# 调整 fallback 阈值
config.prompt_config.fallback_confidence_threshold = 0.3
```

## 性能考虑

| 操作 | 额外 LLM 调用 | 影响 |
|------|--------------|------|
| 首次问答 | 0 | 基线 |
| 自检 | 1 | +100ms |
| Fallback（宽化） | 1 | +100ms |
| Fallback（重写） | 2（重写 + 生成） | +200ms |
| 最坏情况 | 4 | +400ms |

**优化建议**：
- 对延迟敏感的场景：禁用 fallback（`enable_fallback=False`）
- 批量处理场景：可启用完整 fallback 机制
- 缓存场景：可缓存常见问题的答案

## 测试计划

### 单元测试

1. **models.py**
   - 测试 CheckResult 的置信度验证
   - 测试 SourceInfo.to_dict() 序列化
   - 测试 PromptConfig 的 __post_init__ 验证

2. **PromptBuilder**
   - 测试上下文格式化正确性
   - 测试层级排序逻辑（各种 law_name 模式）
   - 测试最大上下文数量限制
   - 测试边界情况（空列表、单条、超限）

3. **SelfCheckProcessor**
   - 测试自检结果解析（正常 JSON、格式错误、缺失字段）
   - 测试 fallback 触发条件（各阈值边界）
   - 测试 fallback 深度限制
   - 测试查询重写

4. **CitationMapper**
   - 测试引用编号提取（各种格式）
   - 测试引用验证（有效、无效、越界）
   - 测试引用去重
   - 测试 sources 格式化
   - 测试边界情况（无引用、全无效引用）

### 集成测试

1. 测试完整问答流程（正常路径）
2. 测试 fallback 机制（宽化 → 重写 → 上限）
3. 测试边界条件：
   - 无检索结果
   - LLM 生成失败
   - 自检 LLM 失败
   - JSON 解析失败
   - 引用编号越界
   - 无引用编号
4. 测试层级排序效果
5. 测试并发场景

### 评估指标

- **答案质量**：法条引用准确率、信息覆盖率
- **防幻觉**：无依据断言数量
- **引用完整性**：引用标注覆盖率、引用准确率
- **Fallback 效果**：fallback 触发率、fallback 后质量提升
- **性能**：平均响应时间、p95 响应时间

## 实施步骤

1. 创建 models.py（数据结构定义）
2. 创建 prompts/ 目录和 YAML 模板
3. 创建 PromptBuilder 模块
4. 创建 SelfCheckProcessor 模块
5. 创建 CitationMapper 模块
6. 修改 RAGEngine：新增 ask_with_prompt() 方法
7. 扩展 RAGConfig 添加 PromptConfig
8. 编写单元测试
9. 编写集成测试
10. 运行评估并调优

## 向后兼容

**保证向后兼容的决策**：
- 保留现有 `ask()` 方法不变
- 新增 `ask_with_prompt()` 方法使用新功能
- `search()` 方法保持不变
- 现有调用代码无需修改

**迁移路径**：
```python
# 现有代码（继续工作）
engine = create_qa_engine()
result = engine.ask("健康保险等待期有什么规定？")

# 新代码（使用增强功能）
result = engine.ask_with_prompt("健康保险等待期有什么规定？")
print(result['confidence'])  # 新增：置信度
print(result['fallback_triggered'])  # 新增：是否触发 fallback
print(result['invalid_citations'])  # 新增：无效引用
```

## 未来扩展

**预留扩展点**：
- 多轮对话：可在 PromptBuilder 中添加 conversation_history 参数
- 异步支持：可添加 aask_with_prompt() 异步方法
- 自定义层级规则：可在 PromptConfig 中添加自定义排序函数
- 更多引用格式：可在 CitationMapper 中扩展 citation_pattern

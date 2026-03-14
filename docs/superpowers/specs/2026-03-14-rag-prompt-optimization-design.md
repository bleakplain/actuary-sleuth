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

## 架构

### 整体流程

```
用户问题
    │
    ▼
┌─────────────────┐
│   向量检索      │ ← Hybrid Search (Vector + BM25)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  PromptBuilder  │ ← 格式化上下文、构建系统提示
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
├── rag_engine.py          # 修改：重构 ask() 方法
├── prompt_builder.py      # 新增：Prompt 构建器
├── self_check.py          # 新增：自检与 fallback
├── citation_mapper.py     # 新增：引用映射
└── prompts/
    ├── system_prompt.yaml     # 系统提示词模板
    ├── self_check_prompt.yaml # 自检提示词模板
    └── query_rewrite_prompt.yaml # 查询重写模板
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
    def build_context(
        self,
        retrieved_docs: List[Dict],
        max_contexts: int = 10
    ) -> str:
        """格式化检索上下文，返回带编号的文本"""

    def build_system_prompt(self) -> str:
        """构建系统提示词"""

    def sort_by_hierarchy(self, docs: List[Dict]) -> List[Dict]:
        """按法规层级排序：法律 > 部门规章 > 规范性文件"""
```

**系统提示词模板**：
```
你是一位保险监管法规专家，专门协助合规审计人员查询和分析保险相关法律法规。

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
    async def check_answer(
        self,
        question: str,
        answer: str,
        contexts: List[str]
    ) -> CheckResult:
        """自检答案质量"""

    def should_trigger_fallback(self, answer: str) -> bool:
        """判断是否需要 fallback 检索"""

    async def fallback_retrieve(
        self,
        question: str,
        engine: RAGEngine
    ) -> List[Dict]:
        """执行 fallback 检索"""
```

**自检提示词模板**：
```
请检查以下答案是否符合要求：

【问题】{question}

【答案】{answer}

【检查要点】
1. 答案是否表明"未找到相关信息"或"资料不足"？
2. 答案中的关键断言是否有引用标注？
3. 引用编号是否在提供的资料范围内？

请以 JSON 格式返回：
{
  "is_sufficient": true/false,
  "needs_fallback": true/false,
  "issues": ["问题描述1", "问题描述2"],
  "confidence": 0.0-1.0
}
```

**Fallback 流程**：
```
首次答案
    │
    ▼
┌───────────────────┐
│  判断是否需要 fallback  │ ← needs_fallback || confidence < 0.5
└────────┬──────────┘
         │ No
         ▼
     返回答案
         │ Yes
         ▼
┌───────────────────┐
│  宽化检索          │ ← top_k * 2, 降低阈值
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│  重新生成答案      │
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│  仍然不足？        │
└────────┬──────────┘
         │ Yes
         ▼
┌───────────────────┐
│  查询重写          │ ← LLM 提取关键词/同义词
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│  第三次检索        │
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│  最终答案          │
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
    def map_citations(
        self,
        answer: str,
        retrieved_docs: List[Dict]
    ) -> CitationResult:
        """映射引用编号"""

    def validate_citations(
        self,
        answer: str,
        max_index: int
    ) -> List[str]:
        """验证引用编号是否在有效范围内"""
```

**数据结构**：
```python
@dataclass
class CitationResult:
    answer_with_sources: str  # 带 sources 链接的答案
    sources: List[SourceInfo]  # 来源详情

@dataclass
class SourceInfo:
    index: int  # 编号
    law_name: str
    article_number: str
    content: str
    score: float
```

## 修改 RAGEngine

### 重构后的 ask() 方法

```python
def ask(self, question: str, include_sources: bool = True) -> Dict[str, Any]:
    """
    问答模式：返回自然语言答案（带引用标注）
    """
    if self.query_engine is None:
        if not self.initialize():
            return {'answer': '引擎初始化失败', 'sources': []}

    # 1. 执行检索
    retrieved_docs = self.search(question, top_k=10, use_hybrid=True)

    # 2. 构建上下文
    prompt_builder = PromptBuilder()
    contexts = prompt_builder.build_context(retrieved_docs, max_contexts=10)
    system_prompt = prompt_builder.build_system_prompt()

    # 3. 生成答案
    llm_client = self.llm_provider()
    user_prompt = f"【问题】{question}\n\n【法规资料】\n{contexts}"

    answer = llm_client.generate(
        user_prompt,
        system_prompt=system_prompt
    )

    # 4. 自检与 fallback
    self_check = SelfCheckProcessor(self)
    check_result = await self_check.check_answer(question, answer, contexts)

    if check_result.needs_fallback:
        fallback_docs = await self_check.fallback_retrieve(question, self)
        retrieved_docs.extend(fallback_docs)
        contexts = prompt_builder.build_context(retrieved_docs, max_contexts=10)
        answer = llm_client.generate(
            f"【问题】{question}\n\n【法规资料】\n{contexts}",
            system_prompt=system_prompt
        )

    # 5. 映射引用
    citation_mapper = CitationMapper()
    citation_result = citation_mapper.map_citations(answer, retrieved_docs)

    return {
        'answer': citation_result.answer_with_sources,
        'sources': citation_result.sources
    }
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
- [2] 健康保险产品开发相关监管规定 - 第二十七条
```

## 错误处理

| 场景 | 处理方式 |
|------|----------|
| 检索无结果 | 返回"未找到相关法规"，不调用 LLM |
| LLM 调用失败 | 记录错误，返回友好提示 |
| 引用编号越界 | 记录警告，保留答案但标注引用无效 |
| Fallback 达到上限 | 停止重试，返回当前最佳答案 |

## 配置

**新增配置项** (`RAGConfig`)：
```python
@dataclass
class PromptConfig:
    max_contexts: int = 10  # 传递给 LLM 的最大上下文数量
    enable_fallback: bool = True  # 是否启用 fallback
    max_fallback_retries: int = 2  # 最大 fallback 重试次数
    fallback_confidence_threshold: float = 0.5  # 触发 fallback 的置信度阈值

@dataclass
class RAGConfig:
    # ... 现有字段 ...
    prompt_config: PromptConfig = None
```

## 测试计划

### 单元测试

1. **PromptBuilder**
   - 测试上下文格式化正确性
   - 测试层级排序逻辑
   - 测试最大上下文数量限制

2. **SelfCheckProcessor**
   - 测试自检结果解析
   - 测试 fallback 触发条件
   - 测试查询重写

3. **CitationMapper**
   - 测试引用编号映射
   - 测试引用验证

### 集成测试

1. 测试完整问答流程
2. 测试 fallback 机制
3. 测试边界条件（无结果、LLM 失败等）

### 评估指标

- **答案质量**：法条引用准确率、信息覆盖率
- **防幻觉**：无依据断言数量
- **引用完整性**：引用标注覆盖率

## 实施步骤

1. 创建 PromptBuilder 模块和模板
2. 创建 SelfCheckProcessor 模块
3. 创建 CitationMapper 模块
4. 修改 RAGEngine.ask() 方法
5. 添加配置项
6. 编写测试
7. 运行评估

## 向后兼容

现有 `search()` 方法保持不变，仅重构 `ask()` 方法。
外部调用接口保持一致，返回格式增强（新增 sources 链接）。

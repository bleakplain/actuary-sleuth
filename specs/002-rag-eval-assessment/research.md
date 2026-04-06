# RAG 评估体系评估与改进 - 技术调研报告

生成时间: 2026-04-05
源规格: specs/002-rag-eval-assessment/spec.md

## 执行摘要

当前 RAG 评估体系在**检索指标层面已基本完备**（Precision@K, Recall@K, MRR, NDCG, Redundancy, Context Relevance），但在**生成指标**（依赖 token 级 bigram/Jaccard 匹配，缺乏语义理解）、**评测数据集规模**（仅 60 条）、**LLM-as-a-Judge**（完全缺失）三个核心维度存在较大差距。技术选型建议：LLM-as-a-Judge 直接使用项目已有的 `ZhipuClient` + `BaseLLMClient.chat()` 实现，不引入 RAGAS 依赖；数据集扩充通过手动编写 + LLM 辅助生成的组合方案；评估指南基于当前指标实际分布校准阈值。

---

## 一、现有代码分析

### 1.1 相关模块梳理

| 需求 | 对应模块 | 现状 |
|------|---------|------|
| FR-001 评估报告 | evaluator.py:148-183 (RAGEvalReport) | 有报告结构，但无"对照行业标准"的差距分析能力 |
| FR-002 数据集扩充 | eval_dataset.py (60 条) | 需新增 90+ 条样本 |
| FR-003 LLM-as-a-Judge | evaluator.py:429-687 (GenerationEvaluator) | 无 LLM Judge，仅有 token 级轻量指标 |
| FR-004 人工抽检 | 无 | 完全缺失 |
| FR-005 评估指南 | 无 | 完全缺失 |
| FR-006 增量评估 | evaluator.py:384-426 (evaluate_batch) | 仅支持全量评估 |
| FR-007 数据集校验 | eval_dataset.py:50-69 (load/save) | 仅有基础 JSON 序列化校验 |
| FR-008 Badcase 沉淀 | api/routers/eval.py:84-89 (import) | 有批量导入 API，无自动标注 |
| FR-009 LLM 模型配置 | lib/llm/factory.py:31-33, lib/config.py:402 | 已有 eval LLM 配置（glm-4-flash） |

### 1.2 可复用组件

- **`BaseLLMClient.chat()`** (`lib/llm/base.py:59`): LLM Judge 的核心调用接口，支持多轮对话，可直接用于评分 prompt
- **`ZhipuClient`** (`lib/llm/zhipu.py:19`): 已实现的智谱客户端，含重试、熔断、metrics（`lib/llm/metrics.py`），LLM Judge 直接复用
- **`LLMClientFactory.create_eval_llm()`** (`lib/llm/factory.py:31`): 评估专用 LLM 实例，配置在 `settings.json` 的 `llm.eval` 节
- **`ChatAdapter`** (`lib/llm/langchain_adapter.py:33`): LangChain 适配器，如需 RAGAS 集成可复用
- **`GenerationEvaluator._compute_faithfulness()`** (`evaluator.py:656-680`): 轻量忠实度计算，可作为 LLM Judge 的对照基线
- **`RetrievalEvaluator`** (`evaluator.py:305-426`): 检索评估器，已完备，不需要修改
- **`EvalSample`** (`eval_dataset.py:28-37`): frozen dataclass，字段完整，可直接扩展新样本
- **`_is_relevant()`** (`evaluator.py:190-227`): 多策略相关性判断（关键词 → source_file → law_name → embedding），设计合理
- **`tokenizer.py`**: 中文分词（jieba + 保险领域词典 + 停用词），可直接复用
- **`api/database.py`**: 完整的 eval_samples/eval_runs/eval_sample_results/eval_snapshots CRUD
- **`api/routers/eval.py`**: 完整的 REST API（数据集管理 + 评估运行 + 对比 + 导出）

### 1.3 需要新增/修改的模块

| 模块 | 操作 | 说明 |
|------|------|------|
| `lib/rag_engine/llm_judge.py` | **新增** | LLM-as-a-Judge 评估器，独立于 RAGAS |
| `lib/rag_engine/eval_dataset.py` | **修改** | 新增 90+ 条评测样本 |
| `lib/rag_engine/data/eval_dataset.json` | **修改** | 同步更新 JSON 数据文件 |
| `lib/rag_engine/evaluator.py` | **修改** | GenerationEvaluator 集成 LLM Judge 模式 |
| `lib/rag_engine/dataset_validator.py` | **新增** | 数据集自动校验工具 |
| `lib/rag_engine/eval_guide.py` | **新增** | 评估指标阈值和解读指南 |
| `evaluate_rag.py` | **修改** | 支持 LLM Judge 模式、增量评估 |
| `api/routers/eval.py` | **修改** | 新增 LLM Judge 评估模式、质量审查 API |
| `api/schemas/eval.py` | **修改** | 新增 LLM Judge 相关 schema |
| `api/database.py` | **修改** | 新增人工抽检记录表 |
| `tests/lib/rag_engine/test_llm_judge.py` | **新增** | LLM Judge 单元测试 |
| `tests/lib/rag_engine/test_dataset_validator.py` | **新增** | 数据集校验测试 |

---

## 二、技术选型研究

### 2.1 LLM-as-a-Judge 实现方案对比

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| **A: 直接使用 BaseLLMClient.chat()** | 零额外依赖；复用已有重试/熔断/metrics；prompt 完全可控 | 需要自己设计评分 prompt 和解析逻辑 | **✅ 推荐** |
| B: 集成 RAGAS | 开箱即用的 faithfulness/answer_relevancy/answer_correctness | 依赖重（ragas + datasets + langchain）；prompt 不可控；对中文保险领域优化不足 | ❌ |
| C: 使用 DeepEval | pytest 风格的断言式评估 | 引入新依赖；学习成本；与现有架构差异大 | ❌ |

**选择方案 A 的理由**：
1. 项目已有 `BaseLLMClient` 抽象和 `ZhipuClient` 实现，含完整的错误处理链路（重试、熔断、metrics）
2. `LLMClientFactory.create_eval_llm()` 已配置 `glm-4-flash`，直接可用
3. 保险精算领域的评分标准需要高度定制化 prompt，RAGAS 的通用 prompt 效果不佳
4. 符合 CLAUDE.md "Library-First" 原则——复用已有库，不引入新依赖

### 2.2 LLM Judge 评分维度设计

| 维度 | 评估目标 | 评分方法 |
|------|---------|---------|
| **忠实度 (Faithfulness)** | 答案中每个事实陈述是否都有检索上下文支撑 | 逐句检查：将答案拆为陈述 → 检查每条是否能在 context 中找到依据 → 0-1 分 |
| **正确性 (Correctness)** | 答案与 ground_truth 的事实一致性 | 对比评分：LLM 对比 answer 和 reference，判断关键信息点覆盖度 → 0-1 分 |
| **相关性 (Relevancy)** | 答案是否真正回答了用户问题 | 判断：LLM 判断 answer 是否针对 question 给出了有用回答 → 0-1 分 |

### 2.3 数据集扩充方案对比

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| **A: 手动编写 + LLM 辅助生成** | 质量可控；覆盖目标明确；支持 badcase 沉淀 | 耗时较长 | **✅ 推荐** |
| B: 纯 LLM 自动生成 | 速度快 | 质量参差不齐；需要大量筛选；领域准确性存疑 | ❌ |
| C: 从线上日志提取 | 真实场景 | 隐私风险；标注成本高；需额外 pipeline | ❌（P3 阶段考虑） |

### 2.4 依赖分析

| 依赖 | 版本 | 用途 | 兼容性 |
|------|------|------|--------|
| zhipu (已有) | glm-4-flash | LLM Judge 评分模型 | 已集成，无新依赖 |
| jieba (已有) | - | 中文分词 | 已集成 |
| pytest (已有) | - | 测试框架 | 已集成 |

**不引入新依赖**，所有改进基于现有技术栈。

---

## 三、数据流分析

### 3.1 现有评估数据流

```
CLI / Web API
    ↓
加载 EvalDataset (JSON/DB)
    ↓
┌─ 检索评估 ─────────────────────────┐
│  RAGEngine.search(query, top_k)     │
│  → _is_relevant() 判断相关性         │
│  → 计算 Precision/Recall/MRR/NDCG   │
│  → RetrievalEvalReport              │
└────────────────────────────────────┘
    ↓
┌─ 生成评估 ─────────────────────────┐
│  RAGEngine.ask(query)               │
│  → RAGAS / 轻量 token 指标          │
│  → GenerationEvalReport             │
└────────────────────────────────────┘
    ↓
RAGEvalReport → 打印/导出/对比
```

### 3.2 新增/变更的数据流

```
新增: LLM Judge 评估流
    ↓
┌─ LLM Judge 生成评估 ──────────────┐
│  RAGEngine.ask(query) → answer     │
│  LLM Judge (BaseLLMClient.chat)    │
│  ├─ Faithfulness: 逐句检查 prompt  │
│  ├─ Correctness: 对比 ground_truth │
│  └─ Relevancy: 回答相关性判断       │
│  → LLMPJudgeResult                 │
│  → 与轻量指标对比存储               │
└────────────────────────────────────┘

新增: 数据集质量审查流
    ↓
┌─ 数据集校验 ───────────────────────┐
│  加载全部 EvalSample               │
│  ├─ 字段完整性检查                  │
│  ├─ ground_truth ↔ evidence 一致性 │
│  ├─ 关键词有效性检查                │
│  └─ 题型/难度分布统计               │
│  → QualityAuditReport              │
└────────────────────────────────────┘

新增: 人工抽检流
    ↓
┌─ 抽检校准 ─────────────────────────┐
│  随机抽样 20% LLM Judge 结果       │
│  → 人工评分界面                    │
│  → 对比 LLM Judge vs 人工评分      │
│  → 计算偏差、校准                  │
└────────────────────────────────────┘
```

### 3.3 关键数据结构

```python
# 新增: LLM Judge 评分结果
@dataclass(frozen=True)
class LLMPJudgeResult:
    sample_id: str
    faithfulness_score: float      # 0.0-1.0
    correctness_score: float       # 0.0-1.0
    relevancy_score: float         # 0.0-1.0
    faithfulness_reason: str      # 评分理由
    correctness_reason: str
    relevancy_reason: str
    judge_model: str              # 使用的模型名
    judge_latency_ms: float       # 评分耗时

# 新增: 数据集质量审查报告
@dataclass(frozen=True)
class QualityAuditReport:
    total_samples: int
    valid_samples: int
    issues: List[QualityIssue]     # 问题列表
    distribution: Dict[str, int]   # 题型/难度分布

# 新增: 质量问题
@dataclass(frozen=True)
class QualityIssue:
    sample_id: str
    issue_type: str               # missing_field / keyword_invalid / evidence_mismatch
    severity: str                 # error / warning
    description: str

# 新增: 人工抽检记录（数据库表）
# human_reviews 表:
#   id, run_id, sample_id, llm_faithfulness, llm_correctness, llm_relevancy,
#   human_faithfulness, human_correctness, human_relevancy,
#   reviewer, reviewed_at
```

---

## 四、关键技术问题

### 4.1 需要验证的技术假设

- [ ] **LLM Judge 评分稳定性** — 同一输入多次调用 glm-4-flash，评分标准差是否 < 0.1？验证方式：选取 10 条样本，每条调用 5 次取均值和标准差
- [ ] **LLM Judge 与人工评分一致性** — 20% 抽检偏差 ≤ 10% 是否可达？验证方式：人工标注 30 条样本，与 LLM Judge 对比
- [ ] **轻量 token 指标 vs LLM Judge 相关性** — 两者评分的 Spearman 相关系数？验证方式：在全量数据集上同时运行两种评估
- [ ] **数据集扩充后的评估耗时** — 150 条样本全量评估（retrieval + generation）耗时是否可接受？验证方式：计时测试
- [ ] **glm-4-flash 评分质量** — glm-4-flash 作为 Judge 模型是否足够？还是需要 glm-4-air？验证方式：对比两个模型的评分与人工评分偏差

### 4.2 潜在风险和缓解措施

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| LLM Judge 评分不稳定 | 中 | 高 | 多次采样取均值（默认 3 次）；设计确定性评分 prompt（要求先列出事实点再逐个判断） |
| glm-4-flash 判断力不足 | 中 | 中 | 预留 glm-4-air 作为备选；评分 prompt 增加分步推理链 |
| 数据集扩充质量参差 | 低 | 高 | 每条样本人工审核；自动校验工具检查字段完整性 |
| 150 条样本评估耗时过长 | 低 | 低 | 增量评估（按题型/难度子集）；生成评估并行化 |
| 人工抽检主观偏差 | 中 | 中 | 制定评分 rubric（评分标准）；多人交叉验证 |

---

## 五、现有代码详细分析

### 5.1 生成评估指标的问题分析

**当前轻量指标实现** (`evaluator.py:593-686`):

```python
# faithfulness: 70% 句子覆盖率 + 30% bigram 重叠
def _compute_faithfulness(contexts, answer):
    # 拆句 → 计算每句 bigram 在 context bigram 中的覆盖率
    # 问题：纯 token 匹配，无法理解语义等价
    sentence_coverage = supported_count / len(sentences)
    bigram_overlap = _bigram_overlap(answer_bigrams, context_bigrams)
    return 0.7 * sentence_coverage + 0.3 * bigram_overlap

# answer_relevancy: token Jaccard 相似度
relevancy = _compute_token_jaccard(answer, sample.ground_truth)
# 问题：表述不同但语义相同的回答会得低分

# answer_correctness: bigram 从 ground_truth 到 answer 的覆盖率
correctness = _bigram_overlap(_token_bigrams(ground_truth), _token_bigrams(answer))
# 问题：只看 ground_truth 中有多少 bigram 出现在 answer 中，忽略了语义
```

**具体问题举例**：

| 场景 | ground_truth | 实际回答 | token 指标 | 预期 |
|------|-------------|---------|-----------|------|
| 同义替换 | "不得低于成本价销售" | "不能以低于成本的价格进行销售" | 低（bigram 不匹配） | 高 |
| 补充信息 | "犹豫期不少于15天" | "犹豫期为15天，年金保险同样适用" | 中（部分匹配） | 高 |
| 部分正确 | "分红水平不确定" | "分红水平不确定，根据实际经营确定" | 中 | 高 |
| 答非所问 | "万能险最低保证利率" | "分红险的分红水平不确定" | 低 | 低（正确） |

**结论**：token 级指标对中文保险术语的语义等价处理能力不足，需要 LLM Judge 补充。

### 5.2 评测数据集分析

**当前数据集统计**（60 条）：

| 题型 | 基础 | 扩展 | 合计 | 占比 |
|------|------|------|------|------|
| FACTUAL | 12 | 8 | 20 | 33.3% |
| MULTI_HOP | 8 | 8 | 16 | 26.7% |
| NEGATIVE | 6 | 8 | 14 | 23.3% |
| COLLOQUIAL | 4 | 6 | 10 | 16.7% |

**难度分布**：

| 难度 | 估计数量 | 占比 |
|------|---------|------|
| easy | ~25 | 41.7% |
| medium | ~22 | 36.7% |
| hard | ~13 | 21.7% |

**覆盖的 topic**：健康保险、分红型保险、普通型保险、短期健康险、意外伤害保险、互联网保险、万能型保险、税优健康险、年金保险、两全保险、负面清单、条款费率管理、信息披露、佣金管理、综合监管、退保、核保管理

**差距分析**（对照 spec.md FR-002 和参考文章）：
1. **规模不足**：60 条 vs 行业标准 200+ 条
2. **hard 题偏少**：仅 ~13 条（21.7%），需要更多复杂多跳推理和边界案例
3. **产品类型覆盖不全**：缺少重疾险、寿险（非年金）、医疗险（独立审核场景）、团体保险等
4. **审核点覆盖不全**：缺少保额计算、赔付比例、健康告知、犹豫期退保计算、保费计算等具体审核点
5. **无 badcase 样本**：缺少从线上实际错误中沉淀的"难题"

### 5.3 API 评估流程的问题分析

**`create_evaluation()`** (`api/routers/eval.py:118-213`):

```python
# 问题 1: 生成评估阶段重复调用 RAG
# 第一次：evaluate_batch 内部调用 rag_engine.ask()
# 第二次：循环中再次调用 rag_engine.ask()
if req.mode in ("generation", "full"):
    gen_eval = GenerationEvaluator(rag_engine=rag_engine)
    gen_report = gen_eval.evaluate_batch(samples, rag_engine=rag_engine)  # 内部调用 ask
    for i, sample in enumerate(samples):
        result = rag_engine.ask(sample.question)  # 又调用了一次 ask
```

**这是一个 bug**：生成评估阶段对每条样本调用了两次 `rag_engine.ask()`，既浪费资源又可能导致结果不一致。

**问题 2: 缺少 LLM Judge 注入**：`GenerationEvaluator` 在 API 路由中创建时未传入 `llm` 和 `embeddings` 参数，即使 RAGAS 可用也无法使用。

### 5.4 检索评估的合理性

**`_is_relevant()`** (`evaluator.py:190-227`) 的四层判断策略设计合理：

1. **关键词匹配**（优先）：≥2 个长关键词命中 → 相关。快速确定性检查
2. **source_file + 关键词**：文档来源匹配 + 内容含关键词 → 相关
3. **law_name + 关键词**：法规名称匹配 + 内容含关键词 → 相关
4. **Embedding 语义**（兜底）：余弦相似度 ≥ 0.65 → 相关。处理同义表达

这个策略符合 CLAUDE.md 的"Layered validation"原则（快速确定性检查优先，昂贵的概率检查兜底）。

**NDCG 计算注意点** (`evaluator.py:357-366`)：当前实现假设二值相关性（0/1），这在评估场景下是合理的，因为 `_is_relevant()` 返回的就是布尔值。

---

## 六、LLM-as-a-Judge 实现方案

### 6.1 评分 Prompt 设计

```python
FAITHFULNESS_PROMPT = """你是一位保险精算领域的审核专家。请评估以下回答的忠实度。

## 检索到的参考资料：
{contexts}

## 用户问题：
{question}

## 系统回答：
{answer}

## 评估步骤：
1. 将系统回答拆分为独立的事实陈述
2. 逐条检查每个事实陈述是否能在参考资料中找到依据
3. 统计有依据的陈述数量

## 输出格式（JSON）：
{{"statements": ["陈述1", "陈述2", ...], "supported": [true, false, ...], "score": 0.0-1.0, "reason": "评分理由"}}

评分规则：
- score = 有依据的陈述数 / 总陈述数
- 如果回答完全基于参考资料，score = 1.0
- 如果回答包含无法在参考资料中找到依据的内容，按比例扣分
- 如果回答与参考资料矛盾，score = 0.0"""

CORRECTNESS_PROMPT = """你是一位保险精算领域的审核专家。请评估以下回答的正确性。

## 参考答案（标准答案）：
{reference}

## 系统回答：
{answer}

## 评估步骤：
1. 从参考答案中提取关键信息点
2. 检查系统回答是否覆盖了每个关键信息点
3. 检查系统回答是否包含错误信息

## 输出格式（JSON）：
{{"key_points": ["要点1", "要点2", ...], "covered": [true, false, ...], "has_error": false, "score": 0.0-1.0, "reason": "评分理由"}}

评分规则：
- score = 覆盖的关键信息点数 / 总关键信息点数
- 如果包含错误信息，额外扣 0.2
- 语义等价视为覆盖（不要求字面匹配）"""

RELEVANCY_PROMPT = """你是一位保险精算领域的审核专家。请评估以下回答的相关性。

## 用户问题：
{question}

## 系统回答：
{answer}

## 输出格式（JSON）：
{{"score": 0.0-1.0, "reason": "评分理由"}}

评分规则：
- 1.0: 回答完全针对问题，信息充分
- 0.7: 回答基本针对问题，但有小部分偏题
- 0.4: 回答部分相关，但有明显偏题或信息不足
- 0.0: 回答完全无关或答非所问"""
```

### 6.2 架构设计

```
lib/rag_engine/llm_judge.py

class LLMPJudge:
    def __init__(self, llm_client: BaseLLMClient):
        self._llm = llm_client

    def judge(
        self,
        question: str,
        answer: str,
        contexts: List[str],
        ground_truth: str = "",
        dimensions: List[str] = ["faithfulness", "correctness", "relevancy"],
        num_samples: int = 1,  # 多次采样取均值
    ) -> LLMPJudgeResult

    def judge_batch(
        self,
        samples: List[EvalSample],
        rag_engine,
        dimensions: List[str] = ...,
    ) -> LLMPJudgeBatchReport
```

### 6.3 与现有 GenerationEvaluator 的集成

在 `GenerationEvaluator` 中增加 LLM Judge 作为第三种评估模式：

```python
class GenerationEvaluator:
    def __init__(self, rag_engine=None, llm=None, embeddings=None, llm_judge=None):
        # 优先级: llm_judge > ragas > lightweight
        self._llm_judge = llm_judge
        ...

    def evaluate_batch(self, samples, rag_engine=None):
        if self._llm_judge:
            return self._llm_judge_evaluate_batch(engine, samples)
        elif self._ragas_available:
            return self._ragas_evaluate_batch(engine, samples)
        else:
            return self._lightweight_evaluate_batch(engine, samples)
```

---

## 七、数据集扩充计划

### 7.1 扩充目标

从 60 条扩充到 150+ 条，新增 90+ 条。分布目标：

| 题型 | 当前 | 目标 | 新增 | 最低要求 |
|------|------|------|------|---------|
| FACTUAL | 20 | 45 | 25 | ≥ 35 |
| MULTI_HOP | 16 | 40 | 24 | ≥ 30 |
| NEGATIVE | 14 | 35 | 21 | ≥ 25 |
| COLLOQUIAL | 10 | 30 | 20 | ≥ 20 |
| **合计** | **60** | **150** | **90** | **≥ 120** |

| 难度 | 当前(估) | 目标 |
|------|---------|------|
| easy | ~25 | ~45 (30%) |
| medium | ~22 | ~60 (40%) |
| hard | ~13 | ~45 (30%) |

### 7.2 新增覆盖场景

**产品类型**（新增）：
- 重疾险：等待期、免责条款、理赔条件
- 定期寿险：保险期间、保费计算
- 医疗险（独立）：免赔额、赔付比例、限额
- 团体保险：投保规则、受益人
- 意外险（细分）：职业限制、高危运动

**审核点**（新增）：
- 健康告知：告知义务、未告知后果
- 保费计算：趸交/期交、年龄费率
- 保额限制：未成年保额上限、累计保额
- 犹豫期退保：退保金额计算
- 理赔流程：理赔时限、资料要求
- 产品组合：主险+附加险搭配规则

### 7.3 Badcase 样本来源

从现有评估失败样本（`evaluate_retrieval()` 返回的 `failed_samples`，recall < 0.5）中提取，人工编写标准答案和证据标注。

---

## 八、评估指南阈值设计

### 8.1 建议阈值（需在实际数据上校准）

| 指标 | 优秀 | 良好 | 需改进 | 说明 |
|------|------|------|--------|------|
| Recall@5 | ≥ 0.8 | 0.6-0.8 | < 0.6 | 关键文档是否被找到 |
| Precision@5 | ≥ 0.7 | 0.5-0.7 | < 0.5 | 检索结果噪音水平 |
| MRR | ≥ 0.8 | 0.5-0.8 | < 0.5 | 第一个正确结果的排名 |
| NDCG | ≥ 0.7 | 0.5-0.7 | < 0.5 | 整体排序质量 |
| Redundancy Rate | ≤ 0.1 | 0.1-0.3 | > 0.3 | 结果冗余程度（越低越好） |
| Faithfulness (LLM Judge) | ≥ 0.85 | 0.7-0.85 | < 0.7 | 答案是否有依据 |
| Correctness (LLM Judge) | ≥ 0.8 | 0.6-0.8 | < 0.6 | 答案是否正确 |
| Relevancy (LLM Judge) | ≥ 0.85 | 0.7-0.85 | < 0.7 | 是否回答了问题 |

### 8.2 按题型分级的预期

| 题型 | 预期 Recall@5 | 预期 Faithfulness | 说明 |
|------|--------------|-------------------|------|
| FACTUAL | ≥ 0.85 | ≥ 0.9 | 最简单，应达到最高标准 |
| MULTI_HOP | ≥ 0.6 | ≥ 0.7 | 需要多文档综合，难度较高 |
| NEGATIVE | ≥ 0.7 | ≥ 0.85 | 否定性查询容易被错误召回 |
| COLLOQUIAL | ≥ 0.6 | ≥ 0.75 | 口语化表述与知识库差异大 |

---

## 九、实现优先级和依赖关系

```
P1 阶段（核心）:
  US3 LLM-as-a-Judge ← 无依赖，可最先开始
  US2 数据集扩充     ← 无依赖，可与 US3 并行
  US1 评估报告       ← 依赖 US2、US3 完成

P2 阶段（增强）:
  US4 评估指南       ← 依赖 US3（需要 LLM Judge 数据校准阈值）
  US6 质量审查       ← 依赖 US2（需要对扩充后的数据集做审查）
  US5 流程优化       ← 依赖 US3（增量评估基于 LLM Judge 模式）

P3 阶段（闭环）:
  US7 Badcase 沉淀   ← 依赖 US2、US6
```

---

## 十、参考实现

- [RAGAS 评估框架](https://github.com/explodinggradients/ragas) — faithfulness/answer_relevancy/answer_correctness 指标实现参考
- [DeepEval](https://github.com/confident-ai/deepeval) — LLM-as-a-Judge 的 prompt 设计参考
- [LangSmith Evaluation](https://docs.smith.langchain.com/evaluation) — 评估流程和 UI 设计参考
- [TruLens](https://github.com/truera/trulens) — 线上监控架构参考（P3 阶段）

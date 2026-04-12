# 评测系统深度研究报告

生成时间: 2026-04-10
分析范围: `scripts/lib/rag_engine/evaluator.py`, `scripts/api/routers/eval.py`, `scripts/api/database.py`, `scripts/lib/rag_engine/eval_dataset.py`, `scripts/lib/rag_engine/quality_detector.py`, `scripts/lib/rag_engine/badcase_classifier.py`, `scripts/lib/rag_engine/dataset_validator.py`, `scripts/lib/rag_engine/eval_guide.py`

---

## 执行摘要

评测系统分为**检索评估（自研规则引擎）**和**生成评估（RAGAS）**两层。检索评估使用基于证据文档 + 关键词 + Embedding 相似度的分层判定，不依赖 LLM。生成评估使用 RAGAS 库的 faithfulness / answer_relevancy / answer_correctness 三个指标。存在若干问题：检索相关性判定逻辑脆弱、生成评估不保存逐题 detail、full 模式下检索 detail 缺少 retrieved_docs、零测试覆盖、NDCG 计算错误等。

---

## 一、系统架构

### 1.1 评测流程总览

```
前端发起评测 → POST /api/eval/evaluations
  → 加载 config (eval_configs 表) → 创建 eval_run 记录
  → asyncio.create_task(_run_eval)
    → 检索评估 (retrieval/full 模式)
      → RetrievalEvaluator.evaluate_batch()
        → 逐样本: RAGEngine.search() → _is_relevant() 判定相关性
        → 计算 Precision@K, Recall@K, MRR, NDCG, Redundancy, ContextRelevance
        → save_sample_result() 逐条写入 DB
    → 生成评估 (generation/full 模式)
      → GenerationEvaluator._ragas_evaluate_batch()
        → 逐样本: RAGEngine.ask() 生成答案
        → RAGAS evaluate() 计算 faithfulness, answer_relevancy, answer_correctness
        → 汇总为 GenerationEvalReport
    → 保存 report_json 到 eval_runs 表
```

### 1.2 核心文件

| 文件 | 职责 |
|------|------|
| `lib/rag_engine/evaluator.py` | 评估器核心：RetrievalEvaluator + GenerationEvaluator |
| `api/routers/eval.py` | API 路由：评测 CRUD、运行、导出 |
| `api/database.py` | 数据库：eval_runs, eval_sample_results, eval_configs |
| `lib/rag_engine/eval_dataset.py` | 数据集模型 + 150 条内置样本 |
| `lib/rag_engine/eval_guide.py` | 指标阈值解读 + 摘要生成 |
| `lib/rag_engine/quality_detector.py` | 线上质量检测（bigram 重叠） |
| `lib/rag_engine/badcase_classifier.py` | Badcase 三分类 + 合规风险评估 |
| `lib/rag_engine/dataset_validator.py` | 数据集质量校验 |

---

## 二、检索评估（自研）详细分析

### 2.1 相关性判定逻辑 — `_is_relevant()`

**位置**: `evaluator.py:190-227`

三层判定，任一满足即判定为相关：

1. **关键词匹配** — `evidence_keywords` 中 ≥2 个长度 ≥2 的关键词出现在检索结果 content 中
2. **文件名+关键词** — `source_file` 在 `evidence_docs` 中，且 content 包含 evidence_keywords
3. **法规名匹配** — `law_name` 中包含 evidence_doc 的词干（去除 .md 和下划线），且 content 包含 keywords
4. **Embedding 语义相似度** — 当上述规则均不满足时，计算 query keywords 拼接 vs content 的 cosine 相似度，≥0.65 即相关

**问题 1: 关键词匹配的 required 逻辑过于宽松**

```python
# evaluator.py:200-204
if evidence_keywords:
    long_keywords = [kw for kw in evidence_keywords if len(kw) >= 2]
    matched = sum(1 for kw in long_keywords if kw in content)
    required = min(2, len(long_keywords))  # 只要 2 个就算相关
    if matched >= required:
        return True
```

- 只有 2 个关键词匹配就算相关，可能产生误判
- 如果 evidence_keywords 只有 1 个长度 ≥2 的词，`required=1`，单个词匹配就判定相关

**问题 2: 法规名匹配逻辑绕过了关键词要求**

```python
# evaluator.py:211-218
if law_name and evidence_docs:
    for doc in evidence_docs:
        doc_stem = doc.replace('.md', '').replace('_', '')
        if doc_stem and len(doc_stem) >= 4 and doc_stem in law_name:
            if evidence_keywords:
                if _contains_keyword(content, evidence_keywords):
                    return True
            elif source_file and source_file in doc_set:
                return True  # 没有 keywords 也能通过！
```

当 `source_file` 在 `evidence_docs` 中且 `law_name` 包含词干时，即使没有关键词匹配也会判定为相关。

**问题 3: Embedding 回退使用关键词拼接而非原始 query**

```python
# evaluator.py:222-224
if evidence_keywords:
    query_text = ' '.join(evidence_keywords)  # 拼接关键词而非问题原文
    similarity = _compute_embedding_similarity(query_text, content)
```

语义相似度本应比较 query 和 content，但这里比较的是 keywords 拼接和 content，语义信息丢失。

### 2.2 NDCG 计算错误

**位置**: `evaluator.py:378-387`

```python
dcg = sum(rel / math.log2(rank + 1) for rank, rel in enumerate(relevance, 1))
n_relevant = min(sum(relevance), len(relevance))
ideal_relevance = [1] * n_relevant + [0] * (len(relevance) - n_relevant)
idcg = sum(rel / math.log2(rank + 1) for rank, rel in enumerate(ideal_relevance, 1))
```

**问题**: 二值相关性下 DCG ≠ IDCG，注释声称相等但实际不相等。NDCG 应该是 `dcg / idcg`，但由于二值相关性，当 `n_relevant == len(relevance)` 且所有结果都相关时 NDCG=1.0，这是正确的。但当部分相关时，IDCG 的计算方式其实和 DCG 完全相同（因为 `ideal_relevance` 就是把 1 放前面），所以 NDCG 永远等于 1.0。

**正确做法**: IDCG 应该用 `1/log2(1) + 1/log2(2) + ...` 而不是只考虑前 K 个位置中的相关结果数。当前实现使得 NDCG 在二值相关性下退化为一个恒等于 1 的指标（当有任意相关结果时），失去排序质量区分能力。

### 2.3 Redundancy 计算的局限性

**位置**: `evaluator.py:246-265`

使用 Jaccard 相似度（>0.6）计算 chunk 之间的冗余率，仅考虑内容重叠，不考虑语义层面的冗余（如不同条款引用相同法规原文）。

### 2.4 Context Relevance 的局限性

**位置**: `evaluator.py:308-323`

使用 bigram 重叠度衡量 query 与检索上下文的相关性。对于中文短查询（如"等待期"），bigram 集合可能很小（只有 1-2 个），导致该指标不稳定。

---

## 三、生成评估（RAGAS）详细分析

### 3.1 RAGAS 使用确认

**是的，生成评估使用 RAGAS**。具体使用方式：

- **位置**: `evaluator.py:464-476`
- **指标**: `faithfulness`, `answer_relevancy`, `answer_correctness`
- **LLM**: 通过 `LLMClientFactory.create_ragas_llm()` 注入
- **Embedding**: 通过 `LLMClientFactory.create_ragas_embed_model()` 注入
- **数据格式**: 使用 `datasets.Dataset` 构造 RAGAS 输入

### 3.2 生成评估不保存逐题 detail

**位置**: `eval.py:228-234`

```python
if req.mode in ("generation", "full"):
    gen_eval = GenerationEvaluator(...)
    gen_report = gen_eval.evaluate_batch(samples, rag_engine=eval_engine)
```

`evaluate_batch` 只返回汇总的 `GenerationEvalReport`，不返回逐题的 `generated_answer`、`retrieved_docs`、各指标分数。导致：

1. 前端展开行无法显示生成回答
2. 无法按题型分组查看生成评估详情
3. 无法追溯具体哪条样本 faithfulness 低

### 3.3 RAGAS 批量评估的资源开销

**位置**: `evaluator.py:524-583`

`_ragas_evaluate_batch` 对**所有样本**调用一次 RAGAS evaluate，而非逐样本调用。这意味着：
- 需要同时加载所有样本的上下文和答案到内存
- RAGAS 内部会逐样本调用 LLM（faithfulness 和 answer_correctness 需要推理），是 **串行** 的
- 对于 150 条样本的 full 模式评测，LLM 调用量极大，运行时间可能很长

### 3.4 生成评估中的检索结果未持久化

在 `full` 模式下，`_ragas_evaluate_batch` 内部调用 `engine.ask()` 获取答案和检索结果，但这些检索结果没有保存到 `eval_sample_results` 表中。即使检索评估部分保存了 `retrieved_docs`（master 最新代码），生成评估的检索结果是独立的，未保存。

---

## 四、数据库设计分析

### 4.1 eval_sample_results 表结构

```sql
CREATE TABLE IF NOT EXISTS eval_sample_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    sample_id TEXT NOT NULL,
    retrieved_docs_json TEXT NOT NULL DEFAULT '[]',
    generated_answer TEXT NOT NULL DEFAULT '',
    retrieval_metrics_json TEXT NOT NULL DEFAULT '{}',
    generation_metrics_json TEXT NOT NULL DEFAULT '{}'
);
```

**问题**: `generation_metrics_json` 在当前代码中**从未被写入**。生成评估的逐题指标只存在于 RAGAS 的 DataFrame 中，未被持久化。

### 4.2 eval_runs 表缺少字段

- 无 `config_id` 字段 — 配置 ID 藏在 `config_json.dataset.config_id` 中
- 无 `dataset_version` 字段 — 版本号存在 `config_json.dataset.dataset_version` 中
- 无 `snapshot_id` 字段 — 快照 ID 不记录

### 4.3 _eval_tasks 内存字典

**位置**: `eval.py:43`

```python
_eval_tasks: dict = {}
```

使用进程内存字典追踪评测任务状态，服务重启后丢失。对于"运行中"的评测，重启后状态永远停留在 `running`。

---

## 五、API 层问题

### 5.1 compare_evaluations 硬编码指标列表

**位置**: `eval.py:342-343`

```python
for metric in ["precision_at_k", "recall_at_k", "mrr", "ndcg",
                "faithfulness", "answer_relevancy", "answer_correctness"]:
```

对比 API 硬编码了指标列表，如果 report 中有其他指标（如 `redundancy_rate`, `context_relevance`）会被忽略。

### 5.2 评测任务异常处理

**位置**: `eval.py:249-253`

```python
except Exception as e:
    logger.error(f"Eval run {evaluation_id} failed: {e}")
    update_evaluation_status(evaluation_id, "failed")
```

所有异常统一标记为 `failed`，不区分：配置加载失败、引擎初始化失败、RAGAS 依赖缺失、单条样本异常等。用户无法从错误信息定位问题。

### 5.3 缺少评测任务取消 API

没有 API 可以取消正在运行的评测任务。`_eval_tasks` 字典中也没有取消标志位。

---

## 六、前端交互问题

### 6.1 版本对比使用后端 API 而非客户端计算

当前前端（master 分支）的版本对比有两种实现：
1. 旧版：`compareEvaluations` API 只支持 2 个 ID（`baseline_id`, `compare_id`）
2. 新版（当前 worktree）：客户端获取 report 做多版本对比

后端 `compare_evaluations` API 已不被新版前端使用，但仍保留在代码中。

### 6.2 逐题详情展开行的数据依赖

前端展开行需要 `generated_answer` 和 `retrieved_docs`，但：
- retrieval 模式：`retrieved_docs` 在旧数据中为空（master 最新代码已修复），`generated_answer` 始终为空（正确行为）
- generation 模式：`generated_answer` 未被持久化，`retrieved_docs` 未被持久化
- full 模式：混合了上述两个问题

---

## 七、测试覆盖

### 7.1 零测试覆盖

`scripts/tests/` 目录下**没有任何评测相关的测试文件**。以下模块完全无测试：

- `evaluator.py` — 检索评估 + 生成评估的核心逻辑
- `eval_dataset.py` — 数据集模型
- `quality_detector.py` — 质量检测
- `badcase_classifier.py` — Badcase 分类
- `dataset_validator.py` — 数据集校验
- `eval_guide.py` — 指标解读

---

## 八、关键问题汇总

| # | 严重度 | 类别 | 位置 | 问题描述 |
|---|--------|------|------|----------|
| 1 | **高** | Bug | `evaluator.py:378-387` | NDCG 计算在二值相关性下恒等于 1（当有相关结果时），失去排序区分能力 |
| 2 | **高** | 设计缺陷 | `eval.py:228-234` | 生成评估不保存逐题 detail（generated_answer, retrieved_docs, generation_metrics） |
| 3 | **高** | 缺失 | `tests/` | 零测试覆盖 |
| 4 | **中** | 设计缺陷 | `evaluator.py:200-227` | `_is_relevant()` 相关性判定逻辑脆弱：2 个关键词即判定相关、法规名匹配绕过关键词 |
| 5 | **中** | 设计缺陷 | `evaluator.py:222-224` | Embedding 回退使用关键词拼接而非原始 query |
| 6 | **中** | 状态管理 | `eval.py:43` | `_eval_tasks` 内存字典，服务重启后运行中任务状态丢失 |
| 7 | **中** | 缺失 | `eval.py` | 无评测任务取消 API |
| 8 | **低** | API | `eval.py:342-343` | compare API 硬编码指标列表，缺少 redundancy_rate/context_relevance |
| 9 | **低** | 性能 | `evaluator.py:524-583` | RAGAS 批量评估串行调用 LLM，无并发优化 |
| 10 | **低** | 数据 | `eval_sample_results` | `generation_metrics_json` 字段从未被写入 |

---

## 九、改进建议

### 9.1 优先级 P0（必须修复）

1. **修复 NDCG 计算** — IDCG 应基于所有相关文档的最优排列，而非简单将 1 前置
2. **生成评估保存逐题 detail** — 在 `_ragas_evaluate_batch` 中返回逐题结果，并在 `eval.py` 中调用 `save_sample_result` 保存 `generated_answer`、`retrieved_docs`、`generation_metrics`

### 9.2 优先级 P1（应该修复）

3. **增加评测测试** — 至少覆盖 `_is_relevant()` 的各种场景、NDCG/Recall 计算、report 生成
4. **优化 `_is_relevant()` 判定** — 提高关键词匹配阈值，使用原始 query 做 Embedding 回退
5. **持久化 `_eval_tasks`** — 使用 SQLite 或 JSON 文件替代内存字典，支持重启恢复
6. **增加取消 API** — 在 `_eval_tasks` 中添加 `cancelled` 标志，循环中检查

### 9.3 优先级 P2（可以改进）

7. **RAGAS 并发评估** — 使用 `asyncio.gather` 或多线程加速 LLM 调用
8. **对比 API 动态化** — 从 report 中提取所有指标，而非硬编码列表
9. **`generation_metrics_json` 字段** — 在生成评估中逐题写入该字段

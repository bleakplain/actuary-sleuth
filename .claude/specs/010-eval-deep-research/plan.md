# 评测系统深度改进方案

生成时间: 2026-04-10
源文档: research.md
模式: 兼容模式（无 spec.md）

---

## 一、问题修复方案

### 🔴 P0 - 必须修复

#### 问题 1.1: NDCG 计算错误（`evaluator.py:378-387`）

**问题概述**: 二值相关性下，当存在相关结果时 NDCG 恒等于 1.0，失去排序质量区分能力。

**当前代码**:
```python
dcg = sum(rel / math.log2(rank + 1) for rank, rel in enumerate(relevance, 1))
n_relevant = min(sum(relevance), len(relevance))
ideal_relevance = [1] * n_relevant + [0] * (len(relevance) - n_relevant)
idcg = sum(rel / math.log2(rank + 1) for rank, rel in enumerate(ideal_relevance, 1))
ndcg = dcg / idcg if idcg > 0 else 0.0
```

**根因**: `ideal_relevance` 只取前 K 个位置中的相关结果数排前面，但二值相关性下 DCG 和 IDCG 在相同 n_relevant 时相等。当 n_relevant < K 时，理想排列应该是前 n_relevant 个位置都是 1，但 IDCG 的计算位置数和 DCG 相同，所以 NDCG 永远等于 1。

**修复方案**: IDCG 应基于所有相关文档的最优排列，不受 K 限制：
```python
total_relevant = sum(relevance)
if total_relevant == 0:
    ndcg = 0.0
else:
    # DCG 按实际排序计算
    dcg = sum(rel / math.log2(rank + 1) for rank, rel in enumerate(relevance, 1))
    # IDCG: 所有相关文档排在最前，不受 K 限制
    ideal = [1.0] * total_relevant
    idcg = sum(r / math.log2(rank + 1) for rank, r in enumerate(ideal, 1))
    ndcg = dcg / idcg
```

**涉及文件**: `scripts/lib/rag_engine/evaluator.py`

---

#### 问题 1.2: 生成评估不保存逐题 detail（`eval.py:228-234`）

**问题概述**: `GenerationEvaluator.evaluate_batch` 只返回汇总的 `GenerationEvalReport`，不返回逐题的 `generated_answer`、`retrieved_docs`、`generation_metrics`。前端展开行无法显示生成回答。

**根因**: `_ragas_evaluate_batch` 内部调用 `engine.ask()` 获取答案和检索结果，但这些结果没有持久化到 `eval_sample_results` 表。

**修复方案**:

1. 修改 `GenerationEvaluator._ragas_evaluate_batch` 返回逐题结果：
```python
def _ragas_evaluate_batch(
    self,
    engine,
    samples: List[EvalSample],
) -> Tuple[GenerationEvalReport, List[Dict[str, Any]]]:
    # ... 收集 questions, contexts_list, answers, ground_truths ...
    # 返回 (report, details) 其中 details 包含每条的 answer, contexts, metrics
```

2. 修改 `eval.py` 中 `_run_eval` 的 generation 评估部分：
```python
if req.mode in ("generation", "full"):
    gen_eval = GenerationEvaluator(...)
    gen_report, gen_details = gen_eval.evaluate_batch(samples, rag_engine=eval_engine)
    for detail in gen_details:
        sample_id = detail.get("sample_id", "")
        save_sample_result(
            evaluation_id, sample_id,
            retrieved_docs=detail.get("retrieved_docs", []),
            generated_answer=detail.get("generated_answer", ""),
            generation_metrics=detail.get("metrics", {}),
        )
```

**涉及文件**: `scripts/lib/rag_engine/evaluator.py`, `scripts/api/routers/eval.py`

---

### 🟠 P1 - 应该修复

#### 问题 2.1: `_is_relevant()` 相关性判定逻辑脆弱

**问题概述**:
1. 关键词匹配 `required = min(2, len(long_keywords))` 过低，单个词匹配就判定相关
2. 法规名匹配绕过了关键词要求（`elif source_file and source_file in doc_set: return True`）
3. Embedding 回退使用关键词拼接而非原始 query

**修复方案**:

1. 提高关键词匹配阈值：至少 60% 的关键词匹配才算相关（当关键词数 ≥3 时）
2. 移除法规名匹配绕过逻辑，当无关键词时不直接判定相关
3. Embedding 回退改用原始 query 而非 keywords 拼接

**修改位置**: `evaluator.py:190-227`

```python
def _is_relevant(
    result: Dict[str, Any],
    evidence_docs: List[str],
    evidence_keywords: List[str],
    original_query: str = "",
) -> bool:
    content = result.get('content', '')
    source_file = result.get('source_file', '')
    law_name = result.get('law_name', '')

    if evidence_keywords:
        long_keywords = [kw for kw in evidence_keywords if len(kw) >= 2]
        if long_keywords:
            matched = sum(1 for kw in long_keywords if kw in content)
            # 提高阈值：至少 60% 关键词匹配，或最少 2 个（取较大值）
            threshold = max(2, int(len(long_keywords) * 0.6))
            if matched >= threshold:
                return True

    # 移除法规名绕过逻辑，改为严格匹配：source_file + keywords 都满足才行
    doc_set = set(evidence_docs)
    if source_file and source_file in doc_set:
        if evidence_keywords and _contains_keyword(content, evidence_keywords):
            return True
        # 法规名匹配需要同时满足：doc_stem 匹配 AND 有关键词
        if law_name:
            for doc in evidence_docs:
                doc_stem = doc.replace('.md', '').replace('_', '')
                if doc_stem and len(doc_stem) >= 4 and doc_stem in law_name:
                    if evidence_keywords and _contains_keyword(content, evidence_keywords):
                        return True

    # Embedding 回退：优先用原始 query，其次用 keywords 拼接
    query_for_embed = original_query if original_query else ' '.join(evidence_keywords)
    if query_for_embed and len(query_for_embed) >= 4:
        similarity = _compute_embedding_similarity(query_for_embed, content)
        if similarity >= _SEMANTIC_RELEVANCE_THRESHOLD:
            return True

    return False
```

**涉及文件**: `scripts/lib/rag_engine/evaluator.py`

---

#### 问题 2.2: `_eval_tasks` 内存字典状态丢失

**问题概述**: 使用进程内存字典追踪评测任务状态，服务重启后运行中任务状态丢失。

**修复方案**: 状态本就是存 DB 的（`eval_runs` 表），只是内存字典用于实时进度。改为直接在 DB 查询状态，或使用 JSON 文件持久化 `_eval_tasks`。

简化方案：直接依赖 DB 状态，移除 `_eval_tasks` 内存字典（已在 `eval_runs` 表存储 progress 和 status）。

**涉及文件**: `scripts/api/routers/eval.py`

---

#### 问题 2.3: 无评测任务取消 API

**问题概述**: 没有 API 可以取消正在运行的评测任务。

**修复方案**: 在 `eval_runs` 表添加 `cancelled` 字段（默认为 0），添加 cancel API：
```python
@router.post("/evaluations/{evaluation_id}/cancel")
async def cancel_evaluation(evaluation_id: str):
    with get_connection() as conn:
        conn.execute(
            "UPDATE eval_runs SET cancelled = 1 WHERE id = ? AND status = 'running'",
            (evaluation_id,),
        )
    return {"cancelled": True}
```

在 `_run_eval` 循环中检查 `cancelled` 标志。

**涉及文件**: `scripts/api/routers/eval.py`, `scripts/api/database.py`

---

#### 问题 2.4: compare API 硬编码指标列表

**问题概述**: `compare_evaluations` 硬编码了指标列表，缺少 `redundancy_rate`、`context_relevance`。

**修复方案**: 从 report 中动态提取所有 numeric 指标：
```python
for key in ["retrieval", "generation"]:
    b = baseline_report.get(key, {})
    c = compare_report.get(key, {})
    if not b or not c:
        continue
    all_metrics = set(b.keys()) | set(c.keys())
    for metric in all_metrics:
        b_val = b.get(metric)
        c_val = c.get(metric)
        if not isinstance(b_val, (int, float)) or not isinstance(c_val, (int, float)):
            continue
        # ... delta 计算 ...
```

**涉及文件**: `scripts/api/routers/eval.py`

---

### 🟡 P2 - 可以改进

#### 问题 3.1: `generation_metrics_json` 字段从未写入

**问题概述**: `eval_sample_results.generation_metrics_json` 字段存在但从未被写入。

**修复方案**: 在 `save_sample_result` 调用时传入 `generation_metrics`（已在问题 1.2 中覆盖）。

---

#### 问题 3.2: 零测试覆盖

**问题概述**: `evaluator.py` 等核心模块完全没有测试。

**修复方案**: 添加测试文件 `scripts/tests/test_evaluator.py`：
- `_is_relevant()` 各种场景测试
- NDCG 计算测试
- `compute_faithfulness` 测试
- `RetrievalEvaluator.evaluate` 测试

**涉及文件**: `scripts/tests/test_evaluator.py`（新建）

---

## 二、测试覆盖改进方案

### 新建 `scripts/tests/test_evaluator.py`

```python
import math
import pytest
from scripts.lib.rag_engine.evaluator import (
    _is_relevant, _compute_redundancy_rate, compute_faithfulness,
    RetrievalEvalReport, GenerationEvalReport,
)

class TestIsRelevant:
    def test_keyword_match_threshold(self):
        # 3 个关键词，至少需要 2 个匹配
        result = {"content": "等待期 既往症", "source_file": "05_健康保险.md", "law_name": ""}
        assert _is_relevant(result, ["05_健康保险.md"], ["等待期", "既往症", "健康人群"]) is True

        # 单个关键词
        result2 = {"content": "等待期", "source_file": "", "law_name": ""}
        assert _is_relevant(result2, [], ["等待期"]) is False  # 阈值提高

    def test_law_name_match_requires_keywords(self):
        result = {"content": "一些内容", "source_file": "05_健康保险.md", "law_name": "05_健康保险"}
        assert _is_relevant(result, ["05_健康保险.md"], ["关键词"]) is False  # 需关键词

    def test_embedding_fallback_with_original_query(self):
        result = {"content": "长期健康保险可以包含保证续保条款", "source_file": "", "law_name": ""}
        # 用原始 query 而非 keywords 拼接
        assert _is_relevant(result, [], ["健康保险", "续保"], original_query="长期健康险能否保证续保") is True

class TestNDCG:
    def test_ndcg_perfect_ranking(self):
        # 所有结果都相关，NDCG = 1.0
        pass

    def test_ndcg_partial_relevant(self):
        # K=5, 3个相关，2个不相关
        # DCG = 1/log2(2) + 1/log2(3) + 1/log2(4) + 0 + 0
        # IDCG = 1/log2(2) + 1/log2(3) + 1/log2(4)
        # NDCG < 1.0
        pass

    def test_ndcg_zero_relevant(self):
        # 无相关结果，NDCG = 0.0
        pass

class TestComputeFaithfulness:
    def test_faithfulness_with_sentences(self):
        contexts = ["既往症人群的等待期不应与健康人群有过大差距。"]
        answer = "既往症人群的等待期不应与健康人群有过大差距。"
        score = compute_faithfulness(contexts, answer)
        assert score > 0.8

    def test_faithfulness_no_context(self):
        assert compute_faithfulness([], "some answer") == 0.0
```

---

## 三、技术债务清理方案

### 清理 `_RAGAS_METRICS` 硬编码

当前 `_RAGAS_METRICS = ('faithfulness', 'answer_relevancy', 'answer_correctness')` 在多处硬编码，改为从 `GenerationEvalReport` 字段动态获取。

---

## 四、架构和代码质量改进

### 4.1 `RetrievalEvaluator.evaluate` 返回值增加 `retrieved_docs`

当前返回字典缺少 `retrieved_docs`，导致前端无法展示检索结果。修改返回值：
```python
return {
    'sample_id': sample.id,
    'precision': precision,
    'recall': recall,
    'mrr': mrr,
    'ndcg': ndcg,
    'redundancy_rate': redundancy,
    'context_relevance': context_relevance,
    'first_relevant_rank': first_relevant_rank,
    'num_results': len(results),
    'retrieved_docs': results,  # 新增
}
```

### 4.2 异常分类细化

将 `eval.py` 中统一的 `failed` 状态改为区分：
- `config_error`: 配置加载失败
- `engine_error`: 引擎初始化失败
- `ragas_error`: RAGAS 依赖缺失
- `eval_error`: 评估过程异常

---

## 附录

### 执行顺序建议

1. **Phase 1**: NDCG 修复 + `_is_relevant` 改进 + `evaluate` 返回 `retrieved_docs`（evaluator.py）
2. **Phase 2**: 生成评估保存逐题 detail（evaluator.py + eval.py）
3. **Phase 3**: 取消 API + compare API 动态化（eval.py + database.py）
4. **Phase 4**: 移除 `_eval_tasks` 内存字典（eval.py）
5. **Phase 5**: 测试文件（test_evaluator.py）

### 变更摘要

| 文件 | 修改类型 | 说明 |
|------|---------|------|
| `scripts/lib/rag_engine/evaluator.py` | 修改 | NDCG 修复、`_is_relevant` 改进、evaluate 返回 retrieved_docs |
| `scripts/api/routers/eval.py` | 修改 | 生成评估保存 detail、取消 API、compare 动态化、移除 `_eval_tasks` |
| `scripts/api/database.py` | 修改 | 添加 `cancelled` 字段 |
| `scripts/tests/test_evaluator.py` | 新增 | 核心模块测试 |

### 验收标准总结

| 问题 | 验收标准 | 验证方法 |
|------|---------|---------|
| NDCG 计算 | NDCG 在部分相关时 < 1.0 | 单元测试验证 |
| `_is_relevant` | 关键词阈值提高，法规名匹配不绕过关键词 | 单元测试验证 |
| 生成评估保存 detail | `eval_sample_results` 表 `generated_answer` 和 `generation_metrics_json` 有值 | 实际运行 generation 模式评测，检查 DB |
| 取消 API | 调用 cancel API 后评测状态变为 cancelled | API 测试 |
| compare API | `redundancy_rate`、`context_relevance` 出现在对比结果中 | API 测试 |
| 测试覆盖 | `test_evaluator.py` 覆盖核心函数 | `pytest scripts/tests/test_evaluator.py` |

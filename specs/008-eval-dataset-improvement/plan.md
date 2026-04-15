# Implementation Plan: 评测数据集系统性改进

**Branch**: `008-eval-dataset-improvement` | **Date**: 2026-04-10 | **Spec**: spec.md
**Input**: spec.md + research.md

## Summary

修复评测指标体系的三类根本性缺陷：(1) 指标体系 — Recall 值域修正、相关性判断增加同义词/泛关键词感知、faithfulness 引入语义相似度；(2) 数据集构建方法论 — Chunk 级合成 pipeline、覆盖度评估、弱点驱动迭代；(3) 样本质量 — UNANSWERABLE 类型、来源标记、去重去硬编码、增强验证。

## Technical Context

**Language/Version**: Python 3.10+
**Primary Dependencies**: lancedb (现有), jieba (现有), fastapi (现有), ragas (现有)
**Storage**: SQLite (eval_samples 表), JSON 文件 (eval_dataset.json)
**Testing**: pytest
**Constraints**: 无新增外部依赖；遵循 `scripts/lib/` 现有结构

## Constitution Check

- [x] **Library-First**: 复用 `LLMClientFactory.create_qa_llm()` (合成)、`_get_embed_model()` / `_compute_embedding_similarity()` (faithfulness)、`_INSURANCE_SYNONYMS` + `_build_synonym_index()` (同义词)、`KBManager.get_active_paths()` (Chunk 遍历)、`tokenize_chinese()` / `_jaccard_similarity()` (验证器)
- [x] **测试优先**: 每个 Phase 均包含对应测试用例，FR-014 专项更新现有断言
- [x] **简单优先**: Recall 修复在 `evaluate()` 内直接构建匹配集合；同义词扩展作为 fallback 层插入而非独立系统；faithfulness 在 embedding 可用时语义优先，不可用时回退 bigram
- [x] **显式优于隐式**: 泛关键词白名单基于 `insurance_dict.txt` + `synonyms.json` 构建，不靠长度猜测；UNANSWERABLE 样本跳过 retrieval 评估有显式分支
- [x] **可追溯性**: 每个 Phase 标注对应 spec.md User Story 编号，附录含完整追溯矩阵
- [x] **独立可测试**: Phase 1-3 (指标修复) 可独立运行 pytest 验证；Phase 4 (合成) 可独立调用 CLI；Phase 5 (覆盖度/弱点) 可独立生成报告

## Project Structure

### Documentation

```text
specs/008-eval-dataset-improvement/
├── spec.md
├── research.md
├── plan.md          # 本文件
└── tasks.md         # exec-plan 生成
```

### Source Code

```text
scripts/lib/rag_engine/
├── evaluator.py         # 修改: US1, US2, US4, US8, US12
├── eval_dataset.py      # 修改: US5, US9, US13
├── dataset_validator.py # 修改: US10
├── eval_guide.py        # 修改: US12
├── synth_qa.py          # 新增: US3
├── coverage.py          # 新增: US6
├── weakness.py          # 新增: US7
└── data/
    ├── eval_dataset.json # 新增: US9 (持久化后自动生成)

scripts/api/
├── routers/eval.py      # 修改: US3 (合成 API), US5 (schema), US6 (覆盖度 API), US7 (弱点 API)
└── schemas/eval.py      # 修改: US5 (UNANSWERABLE pattern)

scripts/tests/lib/rag_engine/
├── test_evaluator.py    # 修改: FR-014 (recall 断言), US2, US4, US8, US12
├── test_eval_dataset.py # 修改: US5, US9, US13
├── test_synth_qa.py     # 新增: US3
├── test_coverage.py     # 新增: US6
└── test_weakness.py     # 新增: US7
```

---

## Implementation Phases

### Phase 1: 修复 Recall 指标 + UNANSWERABLE 类型 + 来源标记

> 对应 US1 (P0), US5 (P1), US13 (P1)

前置条件：无。这三个改动相互独立但都是后续 Phase 的基础。

#### 1.1 修复 Recall 计算 (US1)

→ 对应 spec.md User Story 1: 修复 Recall 指标定义错误

**当前代码** (`evaluator.py:368`):
```python
recall = sum(relevance) / len(sample.evidence_docs) if sample.evidence_docs else 0.0
```

**修改方案**: 在 `evaluate()` 中，对每个被 `_is_relevant()` 判定为相关的 result，通过 `source_file` 与 `evidence_docs` 做模糊匹配，构建去重集合 `matched_docs`。

- 文件: `scripts/lib/rag_engine/evaluator.py`
- 步骤:
  1. 在 `evaluate()` 方法中，`relevance` 列表构建后，增加 `matched_docs` 集合计算
  2. 新增辅助函数 `_match_source_to_evidence(source_file: str, evidence_docs: List[str]) -> Optional[str]`

```python
def _match_source_to_evidence(source_file: str, evidence_docs: List[str]) -> Optional[str]:
    """将检索结果的 source_file 与 evidence_docs 模糊匹配，返回匹配到的 evidence_doc 名。"""
    if not source_file or not evidence_docs:
        return None
    src_normalized = source_file.replace('.md', '').replace('_', '').strip()
    for doc in evidence_docs:
        doc_normalized = doc.replace('.md', '').replace('_', '').strip()
        if src_normalized == doc_normalized:
            return doc
        # source_file 可能是完整路径，取文件名部分
        if '/' in source_file or '\\' in source_file:
            fname = Path(source_file).stem.replace('_', '')
            if fname == doc_normalized:
                return doc
    return None
```

  3. 修改 `evaluate()` 中 recall 计算:

```python
# 判断每个结果是否相关
matched_docs: Set[str] = set()
relevance = []
for r in results:
    is_rel = _is_relevant(r, sample.evidence_docs, sample.evidence_keywords)
    relevance.append(1 if is_rel else 0)
    if is_rel:
        matched_doc = _match_source_to_evidence(
            r.get('source_file', ''), sample.evidence_docs
        )
        if matched_doc:
            matched_docs.add(matched_doc)

precision = sum(relevance) / len(relevance)

if not sample.evidence_docs:
    recall = 0.0
else:
    recall = len(matched_docs) / len(sample.evidence_docs)
```

  4. 在 `evaluate_batch()` 的 recall_at_k 均值计算中，跳过 evidence_docs 为空的样本（UNANSWERABLE）

#### 1.2 新增 UNANSWERABLE 类型 (US5)

→ 对应 spec.md User Story 5: 增加"知识库无答案"否定样本

- 文件: `scripts/lib/rag_engine/eval_dataset.py:20-24`
- 步骤:
  1. 在 `QuestionType` 枚举中新增 `UNANSWERABLE = "unanswerable"`
  2. 修改 `dataset_validator.py` — UNANSWERABLE 样本不报 evidence_docs 为空的 error

```python
# eval_dataset.py
class QuestionType(Enum):
    FACTUAL = "factual"
    MULTI_HOP = "multi_hop"
    NEGATIVE = "negative"
    COLLOQUIAL = "colloquial"
    UNANSWERABLE = "unanswerable"
```

  3. 修改 `api/schemas/eval.py` — `EvalSampleCreate.question_type` pattern 增加 `unanswerable`

```python
question_type: str = Field("factual", pattern="^(factual|multi_hop|negative|colloquial|unanswerable)$")
```

#### 1.3 修正 created_by 来源标记 (US13)

→ 对应 spec.md User Story 13: ground_truth 来源标记准确性

- 文件: `scripts/lib/rag_engine/eval_dataset.py:63`
- 步骤:
  1. `EvalSample.created_by` 默认值保持 `"human"` 不变（API 手工创建场景）
  2. 合成 pipeline (US3) 中显式传入 `created_by="llm"` — 在 Phase 3 实现
  3. 在 `create_default_eval_dataset()` 中，将所有现有硬编码样本的 `created_by` 改为 `"human"` — 当前已是默认值，无需改动
  4. 在 `load_eval_dataset()` 中新增一次性迁移逻辑：首次从硬编码生成 JSON 时，对现有样本标记 `created_by="human"` — 当前已是默认值，无需改动

#### 1.4 更新测试断言 (FR-014)

- 文件: `scripts/tests/lib/rag_engine/test_evaluator.py`
- 步骤:
  1. 更新 `test_evaluate_single_sample_all_relevant` — `recall == 2.0` → `recall == 1.0`（2 个 relevant result 对应同一 evidence_doc，去重后 1/1=1.0）
  2. 更新 `test_evaluate_single_sample_partial_relevant` — `recall == 2.0` → `recall == 1.0`
  3. 新增测试 `test_evaluate_single_sample_multi_doc_recall` — 构造 evidence_docs 含 2 个文档、检索结果分别匹配 2 个文档的场景，验证 recall=1.0
  4. 新增测试 `test_evaluate_unanswerable_sample` — evidence_docs 为空时 recall=0.0
  5. 新增测试 `test_match_source_to_evidence` — 测试模糊匹配辅助函数

---

### Phase 2: 同义词扩展 + 泛关键词收紧

> 对应 US2 (P0), US4 (P1)

前置条件：Phase 1 完成（_is_relevant 接口不变，仅内部逻辑增强）。

#### 2.1 同义词扩展匹配 (US2)

→ 对应 spec.md User Story 2: 评估侧利用同义词表增强相关性判断

- 文件: `scripts/lib/rag_engine/evaluator.py:190-227`
- 步骤:
  1. 从 `query_preprocessor.py` 导入 `_INSURANCE_SYNONYMS`
  2. 新增辅助函数 `_expand_keywords_with_synonyms(keywords: List[str]) -> Set[str]`

```python
def _expand_keywords_with_synonyms(keywords: List[str]) -> Set[str]:
    """将关键词通过同义词表扩展，返回扩展后的集合（含原始词）。"""
    from .query_preprocessor import _INSURANCE_SYNONYMS
    expanded: Set[str] = set(keywords)
    for kw in keywords:
        if kw in _INSURANCE_SYNONYMS:
            expanded.update(_INSURANCE_SYNONYMS[kw])
        # 反向查找：kw 是否是某个标准词的同义词
        for standard, variants in _INSURANCE_SYNONYMS.items():
            if kw in variants:
                expanded.add(standard)
                expanded.update(variants)
    return expanded
```

  3. 在 `_is_relevant()` 中，在来源文档匹配（第2层）和 embedding 语义匹配（第4层）之间，插入同义词扩展层（第3层）：

```python
def _is_relevant(result, evidence_docs, evidence_keywords):
    # ... 现有第1层（字面关键词）和第2层（来源文档匹配）不变 ...

    # 第3层: 同义词扩展匹配（新增）
    if evidence_keywords and not _any_keyword_match:
        expanded = _expand_keywords_with_synonyms(evidence_keywords)
        expanded_long = [kw for kw in expanded if len(kw) >= 2]
        matched = sum(1 for kw in expanded_long if kw in content)
        if matched >= 2:
            return True

    # 第4层: embedding 语义匹配（不变）
    # ...
```

#### 2.2 泛关键词收紧 (US4)

→ 对应 spec.md User Story 4: 增强相关性判断的准确性

- 文件: `scripts/lib/rag_engine/evaluator.py:199-204`
- 步骤:
  1. 新增模块级泛关键词集合 `_GENERIC_KEYWORDS`，基于 `stopwords.txt` + 长度规则构建，排除 `insurance_dict.txt` 和 `synonyms.json` 中的领域术语

```python
def _build_generic_keywords() -> Set[str]:
    """构建泛关键词集合：短通用词，排除保险领域术语。"""
    from pathlib import Path
    from .tokenizer import tokenize_chinese

    # 加载保险领域术语白名单
    domain_terms: Set[str] = set()
    synonyms_file = Path(__file__).parent / 'data' / 'synonyms.json'
    if synonyms_file.exists():
        import json
        with open(synonyms_file, 'r', encoding='utf-8') as f:
            for standard, variants in json.load(f).items():
                domain_terms.add(standard)
                domain_terms.update(variants)

    dict_file = Path(__file__).parent / 'data' / 'insurance_dict.txt'
    if dict_file.exists():
        with open(dict_file, 'r', encoding='utf-8') as f:
            for line in f:
                term = line.strip().split()[0] if line.strip() else ''
                if term:
                    domain_terms.add(term)

    # 泛关键词: ≤3 字且不在领域术语中
    generic = {
        '保险', '条款', '规定', '办法', '通知', '要求', '内容',
        '相关', '应当', '可以', '不得', '按照', '根据', '关于',
        '合同', '产品', '公司', '投保', '被保', '人身', '财产',
    }
    return generic - domain_terms

_GENERIC_KEYWORDS: Set[str] = _build_generic_keywords()
```

  2. 修改 `_is_relevant()` 第1层的关键词匹配逻辑：区分领域关键词和泛关键词，泛关键词不单独计数

```python
if evidence_keywords:
    domain_kw = [kw for kw in evidence_keywords
                 if len(kw) >= 2 and kw not in _GENERIC_KEYWORDS]
    generic_kw = [kw for kw in evidence_keywords
                  if len(kw) >= 2 and kw in _GENERIC_KEYWORDS]
    domain_matched = sum(1 for kw in domain_kw if kw in content)
    generic_matched = sum(1 for kw in generic_kw if kw in content)

    # 至少 2 个领域关键词匹配，或 1 个领域 + 来源文档佐证
    if domain_matched >= 2:
        return True
    if domain_matched >= 1 and generic_matched >= 1 and source_file in doc_set:
        return True
```

#### 2.3 测试更新

- 文件: `scripts/tests/lib/rag_engine/test_evaluator.py`
- 步骤:
  1. 新增 `test_is_relevant_synonym_expansion` — evidence_keywords=["退保"]，content 含"解除保险合同"但不含"退保" → relevant
  2. 新增 `test_is_relevant_generic_keywords_rejected` — evidence_keywords=["保险", "条款"]，content 含两者但来源不匹配 → not relevant
  3. 新增 `test_is_relevant_domain_keyword_with_synonym` — evidence_keywords=["免赔额"]，content 含"自付额" → relevant

---

### Phase 3: Chunk 级合成 Pipeline

> 对应 US3 (P0)

前置条件：无（独立于 Phase 1-2，但建议在 Phase 1 完成后实施以便 Recall 验证）。

#### 3.1 合成核心模块 (US3)

→ 对应 spec.md User Story 3: 实现从文档 Chunk 自动合成问答对的 Pipeline

- 文件: `scripts/lib/rag_engine/synth_qa.py` (新增)
- 步骤:
  1. 新建模块，实现 `SynthQA` 类

```python
"""评测样本自动合成 pipeline — 从知识库 Chunk 生成候选问答对。"""
import json
import logging
import uuid
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field

from .eval_dataset import EvalSample, QuestionType, ReviewStatus, save_eval_dataset
from .tokenizer import tokenize_chinese

logger = logging.getLogger(__name__)

_SYNTH_PROMPT = """你是一个保险监管法规领域的专家。根据以下法规条款内容，生成 2-3 个保险精算审核人员可能会问的问题。

要求：
1. 问题必须是保险产品审核相关（条款、定价、免责、等待期等），不涉及公司运营
2. 问题应该多样化：事实查询、对比分析、边界条件
3. 每个问题的答案必须完全来自提供的条款内容，不得编造

法规条款内容：
{chunk_text}

请以 JSON 数组格式返回，每个元素包含：
- "question": 问题文本
- "answer": 答案文本（基于条款内容）
- "keywords": 2-3 个关键词
- "topic": 所属主题
- "difficulty": "easy"/"medium"/"hard"

仅输出 JSON 数组，不要输出其他内容。"""


@dataclass
class SynthConfig:
    questions_per_chunk: int = 3
    min_answer_length: int = 20
    max_question_similarity: float = 0.8
    kb_version: str = ""


@dataclass
class SynthResult:
    total_chunks: int
    processed_chunks: int
    generated_samples: int
    filtered_samples: int
    failed_chunks: int
    samples: List[EvalSample] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            'total_chunks': self.total_chunks,
            'processed_chunks': self.processed_chunks,
            'generated_samples': self.generated_samples,
            'filtered_samples': self.filtered_samples,
            'failed_chunks': self.failed_chunks,
            'samples': [s.to_dict() for s in self.samples],
            'errors': self.errors,
        }


class SynthQA:
    """从知识库 Chunk 合成评测问答对。"""

    def __init__(self, config: Optional[SynthConfig] = None):
        self.config = config or SynthConfig()

    def load_chunks(self) -> List[Dict[str, Any]]:
        """从 KBManager 获取活跃版本的 LanceDB 索引，遍历所有 Chunk。"""
        import lancedb
        from .kb_manager import KBManager

        kb_mgr = KBManager()
        paths = kb_mgr.get_active_paths()
        if not paths:
            raise ValueError("无活跃知识库版本")

        db = lancedb.connect(paths["vector_db_path"])
        table = db.open_table("regulations_vectors")
        df = table.to_pandas()

        chunks = []
        for _, row in df.iterrows():
            text = row.get("text", "")
            metadata = row.get("metadata", {})
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except json.JSONDecodeError:
                    metadata = {}

            source_file = metadata.get("file_name", metadata.get("source_file", ""))
            law_name = metadata.get("law_name", "")

            if not text or len(text.strip()) < 50:
                continue

            chunks.append({
                "text": text,
                "source_file": source_file,
                "law_name": law_name,
                "metadata": metadata,
            })

        logger.info(f"加载 {len(chunks)} 个有效 Chunk")
        return chunks

    def _generate_for_chunk(self, chunk: Dict[str, Any]) -> List[Dict]:
        """对单个 Chunk 调用 LLM 生成问答对。"""
        from lib.llm.factory import LLMClientFactory

        llm = LLMClientFactory.create_qa_llm()
        prompt = _SYNTH_PROMPT.format(chunk_text=chunk["text"][:3000])

        try:
            response = llm.generate(prompt)
            return self._parse_response(response)
        except Exception as e:
            logger.warning(f"Chunk 合成失败: {e}")
            return []

    def _parse_response(self, response: str) -> List[Dict]:
        """解析 LLM 返回的 JSON 问答对。"""
        text = response.strip()
        # 去除 markdown 代码块标记
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        try:
            items = json.loads(text)
            if isinstance(items, list):
                return items
            return []
        except json.JSONDecodeError:
            logger.warning("LLM 返回非 JSON 格式，跳过")
            return []

    def _filter_samples(
        self,
        candidates: List[EvalSample],
        existing: List[EvalSample],
    ) -> List[EvalSample]:
        """质量过滤：答案长度、重复检测、关键词一致性。"""
        filtered = []
        existing_questions = {s.question for s in existing}

        for sample in candidates:
            # 答案太短
            if len(sample.ground_truth) < self.config.min_answer_length:
                continue

            # 与已有问题重复
            if sample.question in existing_questions:
                continue

            # 关键词一致性：答案中应包含至少 1 个 evidence_keyword
            if not any(kw in sample.ground_truth for kw in sample.evidence_keywords if len(kw) >= 2):
                continue

            existing_questions.add(sample.question)
            filtered.append(sample)

        return filtered

    def synthesize(
        self,
        chunks: Optional[List[Dict]] = None,
        existing_samples: Optional[List[EvalSample]] = None,
    ) -> SynthResult:
        """执行合成 pipeline。"""
        if chunks is None:
            chunks = self.load_chunks()

        existing = existing_samples or []
        result = SynthResult(total_chunks=len(chunks))

        for chunk in chunks:
            result.processed_chunks += 1
            items = self._generate_for_chunk(chunk)

            if not items:
                result.failed_chunks += 1
                continue

            source_file = chunk.get("source_file", "")
            candidates = []
            for item in items:
                try:
                    sample = EvalSample(
                        id=f"synth_{uuid.uuid4().hex[:8]}",
                        question=item["question"],
                        ground_truth=item["answer"],
                        evidence_docs=[source_file] if source_file else [],
                        evidence_keywords=item.get("keywords", []),
                        question_type=QuestionType.FACTUAL,
                        difficulty=item.get("difficulty", "medium"),
                        topic=item.get("topic", ""),
                        created_by="llm",
                        review_status=ReviewStatus.PENDING,
                        kb_version=self.config.kb_version,
                    )
                    candidates.append(sample)
                    result.generated_samples += 1
                except (KeyError, TypeError) as e:
                    result.errors.append(f"字段解析失败: {e}")

            before_filter = len(candidates)
            filtered = self._filter_samples(candidates, existing)
            result.filtered_samples += before_filter - len(filtered)

            result.samples.extend(filtered)
            existing.extend(filtered)

        logger.info(
            f"合成完成: {result.processed_chunks} chunks, "
            f"{len(result.samples)} 有效样本, "
            f"{result.filtered_samples} 过滤, "
            f"{result.failed_chunks} 失败"
        )
        return result
```

#### 3.2 API 路由 (US3)

- 文件: `scripts/api/routers/eval.py`
- 步骤:
  1. 新增合成 API 端点

```python
@router.post("/dataset/synthesize")
async def synthesize_samples():
    from lib.rag_engine.synth_qa import SynthQA, SynthConfig
    from lib.rag_engine.eval_dataset import load_eval_dataset, save_eval_dataset

    synth = SynthQA(SynthConfig())
    existing = load_eval_dataset()
    result = synth.synthesize(existing_samples=existing)

    if result.samples:
        merged = existing + result.samples
        save_eval_dataset(merged)

    return result.to_dict()
```

#### 3.3 测试

- 文件: `scripts/tests/lib/rag_engine/test_synth_qa.py` (新增)
- 步骤:
  1. `test_parse_response_valid_json` — 验证 JSON 解析
  2. `test_parse_response_markdown_wrapped` — 验证 markdown 代码块包裹的 JSON
  3. `test_parse_response_invalid` — 验证非 JSON 返回返回空列表
  4. `test_filter_short_answer` — 答案 < 20 字被过滤
  5. `test_filter_duplicate_question` — 与已有样本重复被过滤
  6. `test_filter_missing_keyword` — 答案不含关键词被过滤
  7. `test_synth_sample_created_by_llm` — 合成样本 created_by="llm"

---

### Phase 4: 覆盖度评估 + 弱点报告

> 对应 US6 (P1), US7 (P1)

前置条件：无（独立模块）。

#### 4.1 覆盖度评估 (US6)

→ 对应 spec.md User Story 6: 实现知识库文档覆盖度评估

- 文件: `scripts/lib/rag_engine/coverage.py` (新增)
- 步骤:
  1. 新建模块

```python
"""知识库文档覆盖度评估 — 检查评测数据集对 KB 文档的引用覆盖情况。"""
from dataclasses import dataclass, field
from typing import List, Dict
from pathlib import Path

from .eval_dataset import EvalSample


@dataclass
class CoverageReport:
    total_samples: int
    docs: Dict[str, int]           # doc_name → sample_count
    blind_spots: List[str]         # 引用数为 0 的文档
    undercovered: List[str]        # 引用数 < 5 的文档
    distribution: Dict[str, int]   # topic → sample_count

    def to_dict(self) -> Dict:
        return {
            'total_samples': self.total_samples,
            'docs': self.docs,
            'blind_spots': self.blind_spots,
            'undercovered': self.undercovered,
            'distribution': self.distribution,
        }


def compute_coverage(
    samples: List[EvalSample],
    kb_docs: List[str],
    min_coverage: int = 5,
) -> CoverageReport:
    """计算评测数据集对知识库文档的覆盖度。

    Args:
        samples: 评测样本列表
        kb_docs: 知识库文档文件名列表
        min_coverage: 覆盖不足的阈值
    """
    doc_counts: Dict[str, int] = {doc: 0 for doc in kb_docs}
    topic_counts: Dict[str, int] = {}

    for sample in samples:
        for doc in sample.evidence_docs:
            # 模糊匹配：去 .md 后缀、去下划线
            doc_normalized = doc.replace('.md', '').replace('_', '')
            for kb_doc in kb_docs:
                kb_normalized = kb_doc.replace('.md', '').replace('_', '')
                if doc_normalized == kb_normalized:
                    doc_counts[kb_doc] += 1
                    break
        if sample.topic:
            topic_counts[sample.topic] = topic_counts.get(sample.topic, 0) + 1

    blind_spots = [doc for doc, count in doc_counts.items() if count == 0]
    undercovered = [doc for doc, count in doc_counts.items()
                    if 0 < count < min_coverage]

    return CoverageReport(
        total_samples=len(samples),
        docs=doc_counts,
        blind_spots=blind_spots,
        undercovered=undercovered,
        distribution=topic_counts,
    )


def get_kb_doc_names(regulations_dir: str) -> List[str]:
    """从知识库目录获取所有 .md 文档文件名。"""
    reg_path = Path(regulations_dir)
    if not reg_path.exists():
        return []
    return sorted(f.name for f in reg_path.glob("*.md"))
```

#### 4.2 弱点报告 (US7)

→ 对应 spec.md User Story 7: 实现弱点驱动的样本补充建议

- 文件: `scripts/lib/rag_engine/weakness.py` (新增)
- 步骤:
  1. 新建模块

```python
"""弱点驱动的样本补充建议 — 分析评估结果，识别薄弱领域。"""
from dataclasses import dataclass, field
from typing import List, Dict, Tuple

from .coverage import CoverageReport


@dataclass
class WeaknessReport:
    failed_samples: List[Dict]
    weak_areas: List[Dict]       # {topic, question_type, avg_recall, count}
    suggestions: List[str]

    def to_dict(self) -> Dict:
        return {
            'failed_samples': self.failed_samples,
            'weak_areas': self.weak_areas,
            'suggestions': self.suggestions,
        }


def generate_weakness_report(
    eval_results: List[Dict],
    coverage: CoverageReport,
    recall_threshold: float = 0.5,
) -> WeaknessReport:
    """基于评估结果和覆盖度报告生成弱点分析。

    Args:
        eval_results: evaluate_batch 返回的详细结果列表
        coverage: 覆盖度报告
        recall_threshold: 失败阈值
    """
    failed = [
        r for r in eval_results
        if r.get('recall', 0.0) < recall_threshold
    ]

    # 按 topic × question_type 聚合
    area_stats: Dict[Tuple[str, str], List[float]] = {}
    for r in eval_results:
        topic = r.get('topic', 'unknown')
        qtype = r.get('question_type', 'unknown')
        key = (topic, qtype)
        area_stats.setdefault(key, []).append(r.get('recall', 0.0))

    weak_areas = []
    for (topic, qtype), recalls in area_stats.items():
        avg_recall = sum(recalls) / len(recalls)
        if avg_recall < recall_threshold:
            weak_areas.append({
                'topic': topic,
                'question_type': qtype,
                'avg_recall': round(avg_recall, 3),
                'count': len(recalls),
            })

    weak_areas.sort(key=lambda x: x['avg_recall'])

    # 生成补充建议
    suggestions = []
    for area in weak_areas:
        suggestions.append(
            f"优先在 '{area['topic']}' 补充 {area['question_type']} 类型样本"
            f"（当前 {area['count']} 条，平均 recall={area['avg_recall']}）"
        )

    for doc in coverage.blind_spots:
        suggestions.append(f"知识库文档 '{doc}' 无覆盖样本，需要补充")

    return WeaknessReport(
        failed_samples=failed,
        weak_areas=weak_areas,
        suggestions=suggestions,
    )
```

#### 4.3 API 路由 (US6, US7)

- 文件: `scripts/api/routers/eval.py`
- 步骤:
  1. 新增覆盖度端点

```python
@router.get("/dataset/coverage")
async def get_dataset_coverage():
    from lib.rag_engine.coverage import compute_coverage, get_kb_doc_names
    from lib.rag_engine.eval_dataset import load_eval_dataset
    from lib.rag_engine.kb_manager import KBManager

    kb_mgr = KBManager()
    paths = kb_mgr.get_active_paths()
    if not paths:
        raise HTTPException(status_code=404, detail="无活跃知识库版本")

    kb_docs = get_kb_doc_names(paths["regulations_dir"])
    samples_data = get_eval_samples()
    samples = [EvalSample.from_dict(s) for s in samples_data]
    report = compute_coverage(samples, kb_docs)
    return report.to_dict()
```

  2. 新增弱点报告端点

```python
@router.get("/evaluations/{evaluation_id}/weakness")
async def get_evaluation_weakness(evaluation_id: str):
    from lib.rag_engine.weakness import generate_weakness_report
    from lib.rag_engine.coverage import compute_coverage, get_kb_doc_names
    from lib.rag_engine.kb_manager import KBManager

    run = get_evaluation(evaluation_id)
    if run is None:
        raise HTTPException(status_code=404, detail="评估运行不存在")
    if run["status"] != "completed":
        raise HTTPException(status_code=400, detail="评估尚未完成")

    results = get_sample_results(evaluation_id)

    kb_mgr = KBManager()
    paths = kb_mgr.get_active_paths()
    kb_docs = get_kb_doc_names(paths["regulations_dir"]) if paths else []
    samples_data = get_eval_samples()
    samples = [EvalSample.from_dict(s) for s in samples_data]
    coverage = compute_coverage(samples, kb_docs)

    report = generate_weakness_report(results, coverage)
    return report.to_dict()
```

#### 4.4 测试

- 文件: `scripts/tests/lib/rag_engine/test_coverage.py` (新增)
- 文件: `scripts/tests/lib/rag_engine/test_weakness.py` (新增)
- 步骤:
  1. `test_coverage_all_covered` — 所有文档都有样本引用
  2. `test_coverage_blind_spots` — 部分文档无引用，标记为盲点
  3. `test_coverage_undercovered` — 文档引用数 < 5，标记为覆盖不足
  4. `test_coverage_empty_dataset` — 空数据集，所有文档为盲点
  5. `test_weakness_report_failed_samples` — 失败样本正确聚合
  6. `test_weakness_report_suggestions` — 建议包含盲点和薄弱领域

---

### Phase 5: Faithfulness 语义改进

> 对应 US8 (P1)

前置条件：无（独立于其他 Phase）。

#### 5.1 语义感知 faithfulness (US8)

→ 对应 spec.md User Story 8: 修正 Faithfulness 评估

- 文件: `scripts/lib/rag_engine/evaluator.py:280-305`
- 步骤:
  1. 修改 `compute_faithfulness()` — 在 embedding 可用时使用句子级语义相似度

```python
_SEMANTIC_COVERAGE_THRESHOLD = 0.7

def compute_faithfulness(contexts: List[str], answer: str) -> float:
    """评估答案对检索上下文的忠实度。embedding 可用时使用语义相似度，否则回退 bigram。"""
    if not contexts or not answer:
        return 0.0

    context_text = ' '.join(contexts)

    sentences = _ANSWER_SENTENCE_PATTERN.findall(answer)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 3]

    # 尝试语义方式
    embed_model = _get_embed_model()
    if embed_model and sentences:
        supported_count = 0
        for sentence in sentences:
            similarity = _compute_embedding_similarity(sentence, context_text)
            if similarity >= _SEMANTIC_COVERAGE_THRESHOLD:
                supported_count += 1
        sentence_coverage = supported_count / len(sentences)

        answer_bigrams = _token_bigrams(answer)
        context_bigrams = _token_bigrams(context_text)
        bigram_overlap = _bigram_overlap(answer_bigrams, context_bigrams)

        return 0.7 * sentence_coverage + 0.3 * bigram_overlap

    # 回退: bigram 方式（与原逻辑一致）
    context_bigrams = _token_bigrams(context_text)
    answer_bigrams = _token_bigrams(answer)

    if not sentences:
        return _bigram_overlap(answer_bigrams, context_bigrams)

    supported_count = 0
    for sentence in sentences:
        sentence_bigrams = _token_bigrams(sentence)
        if not sentence_bigrams:
            continue
        covered = sentence_bigrams & context_bigrams
        if len(covered) / len(sentence_bigrams) >= _SENTENCE_COVERAGE_THRESHOLD:
            supported_count += 1

    sentence_coverage = supported_count / len(sentences)
    bigram_overlap = _bigram_overlap(answer_bigrams, context_bigrams)
    return 0.7 * sentence_coverage + 0.3 * bigram_overlap
```

#### 5.2 测试更新

- 文件: `scripts/tests/lib/rag_engine/test_qa_prompt.py`
- 步骤:
  1. `test_high_faithfulness` — 现有测试应仍通过（语义 + bigram 都应高分）
  2. `test_low_faithfulness` — 现有测试应仍通过
  3. 新增 `test_semantic_faithfulness_different_numbers` — 上下文"不超过180天"，答案"不超过360天" → 低分（embedding 可区分）

---

### Phase 6: 拒绝回答指标

> 对应 US12 (P2)

前置条件：Phase 1 完成（UNANSWERABLE 类型已就绪）。

#### 6.1 rejection_rate 指标 (US12)

→ 对应 spec.md User Story 12: 增加"拒绝回答"评估指标

- 文件: `scripts/lib/rag_engine/evaluator.py`
- 步骤:
  1. 在 `RetrievalEvalReport` 中新增 `rejection_rate` 字段

```python
@dataclass
class RetrievalEvalReport:
    precision_at_k: float = 0.0
    recall_at_k: float = 0.0
    mrr: float = 0.0
    ndcg: float = 0.0
    redundancy_rate: float = 0.0
    context_relevance: float = 0.0
    rejection_rate: Optional[float] = None  # 新增
    by_type: Dict[str, Dict[str, float]] = field(default_factory=dict)
```

  2. 在 `evaluate_batch()` 中计算 rejection_rate：对 UNANSWERABLE 样本，检查系统回答是否包含拒绝信号

```python
_REJECTION_PATTERNS = re.compile(
    r'(未找到|没有找到|无法回答|知识库中无|超出范围|没有相关信息|不包含)',
    re.IGNORECASE,
)

# 在 evaluate_batch() 中:
unanswerable_samples = [s for s in samples if s.question_type == QuestionType.UNANSWERABLE]
if unanswerable_samples:
    # UNANSWERABLE 样本的评估在 generation 阶段完成
    # retrieval 阶段跳过，不计入 recall 均值
    pass

# 在 by_type 计算中，UNANSWERABLE 单独展示
```

  3. 修改 `evaluate_batch()` 中 recall_at_k 均值计算，排除 UNANSWERABLE 样本

```python
# 只对非 UNANSWERABLE 样本计算 recall 均值
recall_results = [r for r, s in zip(all_results, samples)
                  if s.question_type != QuestionType.UNANSWERABLE]
if recall_results:
    report.recall_at_k = sum(r['recall'] for r in recall_results) / len(recall_results)
```

  4. 在 `eval_guide.py` 中新增 rejection_rate 阈值

```python
EVAL_THRESHOLDS: List[MetricThreshold] = [
    # ... 现有阈值 ...
    MetricThreshold('rejection_rate', 0.8, 0.6, '无答案问题正确拒绝比例', True),
]
```

#### 6.2 测试

- 文件: `scripts/tests/lib/rag_engine/test_evaluator.py`
- 步骤:
  1. 新增 `test_evaluate_batch_excludes_unanswerable_from_recall` — UNANSWERABLE 样本不计入 recall 均值
  2. 新增 `test_rejection_rate_threshold` — eval_guide 中 rejection_rate 阈值可正确解读

---

### Phase 7: 数据集持久化 + 增强验证 + 样本补充

> 对应 US9 (P2), US10 (P2), US11 (P2)

前置条件：Phase 1-3 完成（UNANSWERABLE 类型、合成 pipeline 就绪）。

#### 7.1 数据集持久化 (US9)

→ 对应 spec.md User Story 9: 数据集持久化与去硬编码

- 文件: `scripts/lib/rag_engine/eval_dataset.py:89-108`
- 步骤:
  1. 修改 `load_eval_dataset()` — 首次从硬编码生成后自动保存到 JSON

```python
def load_eval_dataset(path: Optional[str] = None) -> List[EvalSample]:
    """从 JSON 文件加载评估数据集。默认路径不存在时回退到内置数据集并保存。"""
    if path is None:
        path = DEFAULT_DATASET_PATH

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.info(f"评估数据集文件不存在: {path}，使用默认数据集")
        samples = create_default_eval_dataset()
        save_eval_dataset(samples, path)  # 自动保存
        return samples

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict) and 'samples' in data:
        items = data['samples']
    else:
        raise ValueError(f"不支持的评估数据集格式: {path}")

    return [EvalSample.from_dict(item) for item in items]
```

#### 7.2 增强验证器 (US10)

→ 对应 spec.md User Story 10: 增强数据集验证器

- 文件: `scripts/lib/rag_engine/dataset_validator.py`
- 步骤:
  1. 新增重复检测 — 基于 `_jaccard_similarity()` 检测 question 相似度过高的样本对

```python
def _check_duplicates(samples: List[EvalSample]) -> List[QualityIssue]:
    """检测 question 相似度过高的样本对。"""
    from .evaluator import _tokenize_to_set, _jaccard_similarity

    issues = []
    for i in range(len(samples)):
        tokens_i = _tokenize_to_set(samples[i].question)
        if not tokens_i:
            continue
        for j in range(i + 1, len(samples)):
            tokens_j = _tokenize_to_set(samples[j].question)
            if not tokens_j:
                continue
            sim = _jaccard_similarity(tokens_i, tokens_j)
            if sim > 0.8:
                issues.append(QualityIssue(
                    samples[j].id, 'duplicate_question', 'warning',
                    f'与样本 {samples[i].id} 高度相似 (Jaccard={sim:.2f})',
                ))
    return issues
```

  2. 新增泛关键词检测 — evidence_keywords 中包含泛化词

```python
def _check_generic_keywords(samples: List[EvalSample]) -> List[QualityIssue]:
    """检测 evidence_keywords 中的泛化关键词。"""
    from .evaluator import _GENERIC_KEYWORDS

    issues = []
    for sample in samples:
        generic = [kw for kw in sample.evidence_keywords if kw in _GENERIC_KEYWORDS]
        if generic:
            issues.append(QualityIssue(
                sample.id, 'generic_keyword', 'info',
                f'泛化关键词: {generic}',
            ))
    return issues
```

  3. 修改 `validate_dataset()` — UNANSWERABLE 样本跳过 evidence_docs 空值检查

```python
if not sample.evidence_docs:
    if sample.question_type != QuestionType.UNANSWERABLE:
        issues.append(QualityIssue(sample.id, 'no_evidence', 'error', 'evidence_docs 为空'))
```

  4. 在 `validate_dataset()` 末尾调用重复检测和泛关键词检测

#### 7.3 样本补充 (US11)

→ 对应 spec.md User Story 11: 补充高质量样本解决分布问题

- 文件: `scripts/lib/rag_engine/eval_dataset.py`
- 步骤:
  1. 在 `create_default_eval_dataset()` 中：
     - 去重：同一知识点（按 evidence_keywords 交集判断）的样本不超过 3 条
     - 补充 UNANSWERABLE 样本（5-8 条）
     - 补充带场景的 COLLOQUIAL 样本
     - 补充 3+ 文档的 MULTI_HOP 样本（至少 5 条）
  2. 具体 UNANSWERABLE 样本示例（需添加到硬编码数据集中）：

```python
# UNANSWERABLE 样本
EvalSample(
    id="unanswerable_001",
    question="保险公司可以在抖音上直播卖保险吗？",
    ground_truth="知识库中无对应规定",
    evidence_docs=[],
    evidence_keywords=["直播", "销售"],
    question_type=QuestionType.UNANSWERABLE,
    difficulty="easy",
    topic="互联网保险",
),
```

#### 7.4 测试

- 文件: `scripts/tests/lib/rag_engine/test_eval_dataset.py`
- 步骤:
  1. `test_load_creates_json_on_first_call` — 首次调用生成 JSON
  2. `test_load_reads_from_json_on_subsequent_calls` — 后续从 JSON 加载
  3. `test_unanswerable_type_serialization` — UNANSWERABLE 类型序列化/反序列化
  4. `test_validate_detects_duplicates` — 重复检测
  5. `test_validate_allows_empty_evidence_for_unanswerable` — UNANSWERABLE 不报 evidence 为空

---

## Complexity Tracking

| 违反项 | 原因 | 更简单的替代方案及排除理由 |
|--------|------|--------------------------|
| _build_generic_keywords() 启动时加载文件 | 需要构建白名单集合排除领域术语 | 可硬编码泛关键词列表，但 insurance_dict.txt 有 47 个术语，手动维护容易遗漏；文件加载只在模块首次 import 时执行一次，开销可接受 |
| SynthQA 使用 LLM 生成 | 合成 pipeline 需要 LLM | 可用模板生成，但模板生成的问答对质量远低于 LLM，不符合"可靠的评估基准"目标 |
| _match_source_to_evidence 模糊匹配 | source_file 格式不确定（可能是完整路径或纯文件名） | 可要求格式一致，但 LlamaIndex 的 metadata 格式由外部决定，无法保证 |

---

## Appendix

### 执行顺序建议

```
Phase 1 (Recall + UNANSWERABLE + 来源标记)  ← 基础，优先实施
    ↓
Phase 2 (同义词 + 泛关键词)  ← 依赖 Phase 1 的 _is_relevant 稳定
    ↓
Phase 3 (合成 Pipeline)  ← 独立，可并行但建议在 Phase 1 后
    ↓
Phase 4 (覆盖度 + 弱点)  ← 独立，可并行
    ↓
Phase 5 (Faithfulness)  ← 独立，可并行
    ↓
Phase 6 (拒绝指标)  ← 依赖 Phase 1 的 UNANSWERABLE
    ↓
Phase 7 (持久化 + 验证 + 补样本)  ← 依赖前面所有 Phase
```

Phase 1-2 是 P0 优先级，应最先完成。Phase 3-7 可根据需要调整顺序，但 Phase 7 应最后实施（因为它依赖前面所有改动）。

### 验收标准总结

| User Story | 验收标准 | 对应测试 |
|-----------|---------|---------|
| US1 (Recall) | recall 值域 [0,1]，test_evaluator 全通过 | test_evaluate_single_sample_*, test_match_source_to_evidence |
| US2 (同义词) | "解除保险合同" 匹配 "退保" 关键词 | test_is_relevant_synonym_expansion |
| US3 (合成) | 单 Chunk 生成 2-3 个格式正确的问答对 | test_synth_qa.py 全部 |
| US4 (泛关键词) | "保险"+"条款" 不触发相关 | test_is_relevant_generic_keywords_rejected |
| US5 (UNANSWERABLE) | QuestionType 含 UNANSWERABLE，不报 evidence 空值 | test_unanswerable_type_serialization |
| US6 (覆盖度) | 输出每份 KB 文档的引用数 | test_coverage_*.py |
| US7 (弱点) | 列出 recall < 0.5 的失败样本 + 补充建议 | test_weakness_*.py |
| US8 (Faithfulness) | 语义不同但 bigram 高重叠 → 低分 | test_semantic_faithfulness_different_numbers |
| US9 (持久化) | 首次加载生成 JSON，后续从 JSON 加载 | test_load_creates_json_on_first_call |
| US10 (验证) | 检测重复样本 + 泛关键词 | test_validate_detects_duplicates |
| US11 (补样本) | 知识点重复 ≤ 3，UNANSWERABLE ≥ 5 | test_eval_dataset.py |
| US12 (拒绝指标) | rejection_rate 正确计算 | test_evaluate_batch_excludes_unanswerable_from_recall |
| US13 (来源标记) | 合成样本 created_by="llm" | test_synth_sample_created_by_llm |

### 问题追溯矩阵

| # | 原始问题 | Phase | FR |
|---|---------|-------|----|
| 1 | Recall 值域超过 1.0 | Phase 1 | FR-001, FR-014 |
| 2 | 无自动合成 pipeline | Phase 3 | FR-003 |
| 3 | _is_relevant 未利用同义词 | Phase 2 | FR-002 |
| 4 | 缺少"无答案"否定样本 | Phase 1, 7 | FR-005 |
| 5 | created_by 不准确 | Phase 1, 3 | FR-013 |
| 6 | 关键词匹配过于宽松 | Phase 2 | FR-004 |
| 7 | faithfulness 用 bigram | Phase 5 | FR-008 |
| 8 | 缺少覆盖度评估 | Phase 4 | FR-006 |
| 9 | 缺少弱点驱动策略 | Phase 4 | FR-007 |
| 10 | 知识点重复过多 | Phase 7 | FR-011 |
| 11 | 口语感不够真实 | Phase 7 | FR-011 |
| 12 | 数据集硬编码 | Phase 7 | FR-009 |
| 13 | 验证器太浅 | Phase 7 | FR-010 |
| 14 | 缺少拒绝指标 | Phase 6 | FR-012 |
| 15 | MULTI_HOP 缺复杂推理 | Phase 7 | FR-011 |
| 16 | topic 分布不均 | Phase 7 | FR-011 |

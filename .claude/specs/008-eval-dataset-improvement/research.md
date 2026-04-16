# 评测数据集系统性改进 - 技术调研报告

生成时间: 2026-04-10
源规格: .claude/specs/008-eval-dataset-improvement/spec.md

## 执行摘要

调研覆盖了 spec.md 中 13 个 User Story 涉及的所有现有模块。核心发现：(1) Recall 修复需在 `evaluate()` 中从 result 的 `source_file`/`law_name` 反查 evidence_doc 构建去重集合，改动集中在 `evaluator.py`；(2) 合成 pipeline 可通过 `KBManager.get_active_paths()` + LanceDB `table.to_pandas()` 遍历 Chunk，使用 `LLMClientFactory.create_qa_llm()` 调用 LLM；(3) `_is_relevant()` 改造需在现有 4 层匹配逻辑中插入同义词扩展层和泛关键词判定；(4) `compute_faithfulness()` 改造需复用 `_get_embed_model()` 和 `_compute_embedding_similarity()`；(5) 新增 UNANSWERABLE 类型只需扩展 `QuestionType` 枚举 + 处理 `evidence_docs` 为空的边界。所有改动均遵循现有架构边界，无需新增包依赖。

---

## 一、现有代码分析

### 1.1 相关模块梳理

| 需求 | 对应模块 | 现状 |
|------|---------|------|
| FR-001 (Recall修复) | `scripts/lib/rag_engine/evaluator.py:355-403` | 需修改：`evaluate()` 中 recall 计算逻辑 |
| FR-002 (同义词扩展) | `scripts/lib/rag_engine/evaluator.py:190-227` | 需修改：`_is_relevant()` 插入同义词匹配层 |
| FR-003 (合成pipeline) | 新增模块 | 无现有实现，需新建 |
| FR-004 (泛关键词) | `scripts/lib/rag_engine/evaluator.py:199-204` | 需修改：关键词匹配逻辑增加分类 |
| FR-005 (UNANSWERABLE) | `scripts/lib/rag_engine/eval_dataset.py:20-24` | 需修改：QuestionType 枚举 |
| FR-006 (覆盖度) | 新增模块 | 无现有实现，需新建 |
| FR-007 (弱点报告) | 新增模块 | 无现有实现，需新建 |
| FR-008 (faithfulness) | `scripts/lib/rag_engine/evaluator.py:280-305` | 需修改：`compute_faithfulness()` |
| FR-009 (持久化) | `scripts/lib/rag_engine/eval_dataset.py:89-108` | 需修改：`load_eval_dataset()` |
| FR-010 (增强验证) | `scripts/lib/rag_engine/dataset_validator.py` | 需修改：`validate_dataset()` |
| FR-011 (补样本) | `scripts/lib/rag_engine/eval_dataset.py:129-1677` | 需修改：默认数据集内容 |
| FR-012 (拒绝指标) | `scripts/lib/rag_engine/evaluator.py:326-447` | 需修改：`RetrievalEvalReport` + `evaluate_batch()` |
| FR-013 (来源标记) | `scripts/lib/rag_engine/eval_dataset.py:63` | 需修改：默认值 + 迁移脚本 |
| FR-014 (测试更新) | `scripts/tests/lib/rag_engine/test_evaluator.py` | 需修改：recall 断言值 |

### 1.2 可复用组件

**LLM 基础设施：**
- `LLMClientFactory.create_qa_llm()` (`lib/llm/factory.py:26`) — 合成 pipeline 使用
- `LLMClientFactory.create_eval_llm()` (`lib/llm/factory.py:30`) — 评估相关
- `BaseLLMClient.generate(prompt)` (`lib/llm/base.py:56`) — 统一调用接口
- `LLMClientFactory.create_ragas_llm()` / `create_ragas_embed_model()` (`lib/llm/factory.py:47-54`) — RAGAS 评估

**Embedding 基础设施：**
- `LLMClientFactory.create_embed_model()` (`lib/llm/factory.py:42-44`) — 返回 embedding 模型
- `_get_embed_model()` (`evaluator.py:31-42`) — 带缓存的 embedding 模型获取
- `_compute_embedding_similarity()` (`evaluator.py:45-60`) — 余弦相似度计算
- `get_embedding_model()` (`lib/rag_engine/llamaindex_adapter.py`) — LlamaIndex 适配器

**分词与文本处理：**
- `tokenize_chinese()` (`lib/rag_engine/tokenizer.py:60-80`) — jieba 分词 + 自定义词典 + 停用词
- `_token_bigrams()` (`evaluator.py:268-270`) — bigram 集合构建
- `_jaccard_similarity()` (`evaluator.py:238-243`) — 集合相似度

**知识库访问：**
- `KBManager.active_version` (`lib/rag_engine/kb_manager.py:90-96`) — 获取活跃版本 ID
- `KBManager.get_active_paths()` (`lib/rag_engine/kb_manager.py:224-229`) — 获取活跃版本路径
- `KBManager.load_kb()` (`lib/rag_engine/kb_manager.py:231-240`) — 创建 RAGConfig 实例
- `RAGConfig.collection_name` (`lib/rag_engine/config.py:83`) — 默认 `"regulations_vectors"`

**同义词：**
- `_INSURANCE_SYNONYMS` (`lib/rag_engine/query_preprocessor.py:31`) — 20 组同义词
- `_build_synonym_index()` (`lib/rag_engine/query_preprocessor.py:57-63`) — 双向索引（术语→标准, 变体→标准）

**数据集管理：**
- `load_eval_dataset()` / `save_eval_dataset()` (`eval_dataset.py:89-126`) — JSON 持久化
- `import_eval_samples()` (`api/database.py:574-581`) — 批量导入到 DB
- `validate_dataset()` (`dataset_validator.py:39-81`) — 现有验证逻辑
- `QualityIssue` / `QualityAuditReport` (`dataset_validator.py:10-36`) — 现有数据结构

**评估报告：**
- `RetrievalEvalReport` / `GenerationEvalReport` / `RAGEvalReport` (`evaluator.py:63-183`) — 现有报告结构
- `generate_eval_summary()` (`eval_guide.py:50-66`) — 摘要生成
- `interpret_metric()` (`eval_guide.py:30-47`) — 指标解读

### 1.3 需要新增/修改的模块

| 模块 | 操作 | 说明 |
|------|------|------|
| `scripts/lib/rag_engine/evaluator.py` | **修改** | US1(Recall)、US2(同义词)、US4(泛关键词)、US8(faithfulness)、US12(rejection_rate) |
| `scripts/lib/rag_engine/eval_dataset.py` | **修改** | US5(UNANSWERABLE枚举)、US9(持久化)、US11(补样本)、US13(created_by) |
| `scripts/lib/rag_engine/dataset_validator.py` | **修改** | US10(增强验证) |
| `scripts/lib/rag_engine/synth_qa.py` | **新增** | US3(合成pipeline) — Chunk 遍历 + LLM 合成 + 质量过滤 |
| `scripts/lib/rag_engine/coverage.py` | **新增** | US6(覆盖度评估) — 按 evidence_docs 统计 KB 文档引用 |
| `scripts/lib/rag_engine/weakness.py` | **新增** | US7(弱点报告) — 失败样本聚合 + 薄弱领域识别 + 补充建议 |
| `scripts/tests/lib/rag_engine/test_evaluator.py` | **修改** | FR-014(更新 recall 断言) |
| `scripts/tests/lib/rag_engine/test_eval_dataset.py` | **修改** | US5(UNANSWERABLE)、US9(持久化) |
| `scripts/lib/rag_engine/eval_guide.py` | **修改** | US12(新增 rejection_rate 阈值) |

---

## 二、技术选型研究

### 2.1 FR-001 Recall 修复方案

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A: 在 `_is_relevant()` 返回值中附加匹配的 evidence_doc | 改动最小 | 改变函数签名，影响所有调用方 | ❌ |
| B: 在 `evaluate()` 中从 result 的 source_file/law_name 反查 evidence_doc | 不改 `_is_relevant()` 签名，影响范围小 | 需要额外的 source_file→evidence_doc 映射逻辑 | ✅ |
| C: 引入独立的 recall 计算函数 | 职责清晰 | 增加复杂度 | ❌ |

**选择方案 B**：在 `evaluate()` 内部，对每个被 `_is_relevant()` 判定为相关的 result，提取其 `source_file` 和 `law_name`，与 sample 的 `evidence_docs` 做模糊匹配（去下划线、去 .md 后缀），构建去重匹配集合 `matched_docs`，再计算 `recall = len(matched_docs) / len(evidence_docs)`。

**source_file 与 evidence_docs 匹配逻辑**：`source_file` 来自 LlamaIndex 的 `doc.metadata.get('file_name')`，格式为文件名（如 `05_健康保险产品开发.md`）。`evidence_docs` 格式也是文件名。匹配时先去 `.md` 后缀再比较。

### 2.2 FR-002 同义词扩展方案

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A: 在 `_is_relevant()` 中内联同义词逻辑 | 简单直接 | 函数已较长(37行)，继续膨胀不好 | ❌ |
| B: 抽取 `_expand_keywords()` 辅助函数，在 `_is_relevant()` 中作为 fallback 层 | 职责清晰，可测试 | 需确认与 `_compute_embedding_similarity` 的交互 | ✅ |

**实现方式**：复用 `query_preprocessor.py` 中已有的 `_INSURANCE_SYNONYMS` 数据和 `_build_synonym_index()` 方法。在 `_is_relevant()` 中，字面匹配失败后，将 evidence_keywords 通过同义词索引扩展，再尝试匹配检索内容。

### 2.3 FR-003 合成 Pipeline 方案

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A: 独立 CLI 脚本 | 简单独立 | 与现有代码分离 | ❌ |
| B: 新增 `synth_qa.py` 模块 + API 路由 | 复用现有基础设施（LLM、KBManager、EvalSample） | 需新增模块 | ✅ |

**Chunk 遍历方式**：
```python
import lancedb
from lib.rag_engine.kb_manager import KBManager

kb_mgr = KBManager()
paths = kb_mgr.get_active_paths()
db = lancedb.connect(paths["vector_db_path"])
table = db.open_table("regulations_vectors")
df = table.to_pandas()
# 每个 row: text, metadata (dict), vector
```

**LLM 调用**：`LLMClientFactory.create_qa_llm().generate(prompt)` — 使用 qa 场景配置。

### 2.4 FR-008 Faithfulness 改进方案

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|------|
| A: 用 RAGAS 的 faithfulness 指标 | 标准实现 | 需要 LLM，与独立函数定位冲突 | ❌ |
| B: embedding 句子级语义相似度 + bigram fallback | 无额外 LLM 开销，向后兼容 | 依赖 embedding 模型可用性 | ✅ |

**实现方式**：复用 `_get_embed_model()` 和 `_compute_embedding_similarity()`，对答案每个句子计算与上下文的最相似度，阈值 0.7 判定是否被支撑。

### 2.5 依赖分析

| 依赖 | 版本 | 用途 | 兼容性 |
|------|------|------|--------|
| lancedb | 现有 | Chunk 遍历 | ✅ 已有依赖 |
| jieba | 现有 | 分词 | ✅ 已有依赖 |
| llama-index | 现有 | LlamaIndex Settings | ✅ 已有依赖 |
| ragas | 现有 | 生成评估（可选） | ✅ 已有依赖 |
| datasets | 现有 | RAGAS 数据格式 | ✅ 已有依赖 |
| **无新增外部依赖** | — | — | ✅ |

---

## 三、数据流分析

### 3.1 现有数据流

```
eval_dataset.json / 硬编码
    ↓ load_eval_dataset()
List[EvalSample]
    ↓ RetrievalEvaluator.evaluate(sample)
    ├→ RAGEngine.search(question, top_k) → List[Dict]  (source_file, law_name, content)
    ├→ _is_relevant(result, evidence_docs, evidence_keywords) → bool
    └→ 计算 precision/recall/mrr/ndcg/redundancy
    ↓
RetrievalEvalReport → RAGEvalReport
```

### 3.2 新增/变更的数据流

**US1 Recall 修复（变更）：**
```
_is_relevant(result, ...) → bool  (不变)
                    ↓
evaluate() 内部:
    对每个 relevant result:
        提取 source_file / law_name
        模糊匹配 evidence_docs → matched_doc
    matched_docs = set()
    recall = len(matched_docs) / len(evidence_docs)  (变更)
```

**US2+US4 同义词+泛关键词（变更）：**
```
_is_relevant(result, evidence_docs, evidence_keywords):
    1. 字面关键词匹配 (现有，增加泛关键词分类)
    2. 来源文档匹配 (不变)
    3. 同义词扩展匹配 (新增 fallback 层)
    4. Embedding 语义匹配 (不变)
```

**US3 合成 Pipeline（新增）：**
```
KBManager.get_active_paths()
    ↓
LanceDB table.to_pandas() → 遍历所有 Chunk
    ↓
LLMClientFactory.create_qa_llm().generate(synth_prompt)
    ↓
质量过滤 (长度/重复/一致性)
    ↓
EvalSample.from_dict() → save_eval_dataset()
```

**US6 覆盖度评估（新增）：**
```
List[EvalSample]
    ↓ 统计 evidence_docs 引用
CoverageReport { doc_name: count, is_blind_spot: bool }
```

**US7 弱点报告（新增）：**
```
RAGEvalReport.failed_samples + RetrievalEvalReport.by_type
    ↓ 按 topic × question_type 聚合
    ↓ 交叉 CoverageReport
WeaknessReport { weak_areas: [...], suggestions: [...] }
```

### 3.3 关键数据结构

**新增 CoverageReport：**
```python
@dataclass
class CoverageReport:
    total_samples: int
    docs: Dict[str, int]           # doc_name → sample_count
    blind_spots: List[str]        # 引用数为 0 的文档
    undercovered: List[str]      # 引用数 < 5 的文档
    distribution: Dict[str, int]  # topic → sample_count
```

**新增 WeaknessReport：**
```python
@dataclass
class WeaknessReport:
    failed_samples: List[Dict]    # recall < 0.5 的失败样本
    weak_areas: List[Dict]        # { topic, question_type, avg_recall, count }
    suggestions: List[str]        # "优先在 X topic 补充 Y 类型样本"
```

**修改 RetrievalEvalReport（US12）：**
```python
@dataclass
class RetrievalEvalReport:
    precision_at_k: float = 0.0
    recall_at_k: float = 0.0
    mrr: float = 0.0
    ndcg: float = 0.0
    redundancy_rate: float = 0.0
    context_relevance: float = 0.0
    by_type: Dict[str, Dict[str, float]] = field(default_factory=dict)
    rejection_rate: Optional[float] = None  # US12 新增
```

---

## 四、关键技术问题

### 4.1 需要验证的技术假设

- [ ] **source_file 值格式** — `SimpleDirectoryReader` 的 `file_name` 元数据是完整路径还是纯文件名？需运行 `table.to_pandas().iloc[0]['metadata']` 确认。这直接影响 Recall 反查匹配逻辑。
- [ ] **LanceDB metadata 序列化** — metadata 是 dict 还是 JSON 字符串？不同版本可能不同，需 `json.loads()` 兼容处理。
- [ ] **embedding 模型并发安全** — `_get_embed_model()` 使用全局缓存，合成 pipeline 批量调用时是否线程安全？
- [ ] **LLM 生成 JSON 稳定性** — 合成 pipeline 要求 LLM 返回 JSON 格式问答对，`glm-4-flash` 生成 JSON 的稳定性如何？是否需要重试逻辑？
- [ ] **jaccard 相似度对中文的适用性** — US10 的重复检测使用 `_jaccard_similarity()`（基于 jieba 分词），中文短问题（如"等待期有多长"）分词后 token 数少，Jaccard 可能不够精确。
- [ ] **泛关键词判定与 synonyms.json 的交互** — US4 定义泛关键词为"长度 ≤ 3 的中文字词"，但 synonyms.json 中"退保"(2字)是领域关键词。需确认 ≤3 字规则不会误伤短领域词。

### 4.2 潜在风险和缓解措施

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| source_file 与 evidence_docs 格式不匹配导致 Recall 反查失败 | 中 | 高 | 实现阶段先打印 sample 匹配结果验证，增加 fuzzy matching |
| LLM 生成非 JSON 格式导致合成 pipeline 失败率高 | 中 | 中 | 使用 `extract_json_from_response` 或 XML tag 约束；失败时重试 1 次 |
| 泛关键词判定规则过于严格导致漏判 | 中 | 中 | 以 `stopwords.txt` + `insurance_dict.txt` 中的术语为基准构建白名单，而非仅靠长度 |
| embedding 模型不可用时 faithfulness 回退到 bigram | 低 | 低 | 已有 `_get_embed_model()` 的 fallback 逻辑，直接复用 |
| UNANSWERABLE 样本的 evidence_keywords 为空导致 retrieval 评估无意义 | 低 | 低 | UNANSWERABLE 样本跳过 retrieval 评估，仅评估 generation 的拒绝行为 |
| 合成 pipeline 对 14 份文档全量合成 LLM 调用成本 | 低 | 低 | 单文档约 2-3 次调用，14 份约 30-40 次，成本可接受 |

---

## 五、现有代码关键位置索引

### 评估器核心

| 文件 | 行号 | 内容 |
|------|------|------|
| `evaluator.py` | 20-24 | `_SEMANTIC_RELEVANCE_THRESHOLD = 0.65` |
| `evaluator.py` | 25-26 | `_SENTENCE_COVERAGE_THRESHOLD = 0.4` |
| `evaluator.py` | 31-42 | `_get_embed_model()` — 全局 embedding 缓存 |
| `evaluator.py` | 45-60 | `_compute_embedding_similarity()` — 余弦相似度 |
| `evaluator.py` | 186-187 | `_contains_keyword()` — 单关键词检查 |
| `evaluator.py` | 190-227 | `_is_relevant()` — 4 层相关性判断 |
| `evaluator.py` | 268-270 | `_token_bigrams()` — bigram 集合 |
| `evaluator.py` | 280-305 | `compute_faithfulness()` — bigram faithfulness |
| `evaluator.py` | 308-323 | `_compute_context_relevance()` — bigram 重叠度 |
| `evaluator.py` | 335-403 | `RetrievalEvaluator.evaluate()` — 单样本评估 |
| `evaluator.py` | 405-447 | `RetrievalEvaluator.evaluate_batch()` — 批量评估 |
| `evaluator.py` | 587-623 | `evaluate_retrieval()` — 入口函数 |

### 数据集模块

| 文件 | 行号 | 内容 |
|------|------|------|
| `eval_dataset.py` | 20-24 | `QuestionType` 枚举 |
| `eval_dataset.py` | 27-29 | `ReviewStatus` 枚举 |
| `eval_dataset.py` | 48-65 | `EvalSample` frozen dataclass |
| `eval_dataset.py` | 89-108 | `load_eval_dataset()` / `save_eval_dataset()` |
| `eval_dataset.py` | 129-134 | `create_default_eval_dataset()` — 3 阶段合并 |
| `dataset_validator.py` | 39-81 | `validate_dataset()` — 现有验证逻辑 |

### KB 与 LLM 基础设施

| 文件 | 行号 | 内容 |
|------|------|------|
| `kb_manager.py` | 90-96 | `KBManager.active_version` |
| `kb_manager.py` | 224-229 | `KBManager.get_active_paths()` |
| `kb_manager.py` | 231-240 | `KBManager.load_kb()` |
| `llm/factory.py` | 26 | `create_qa_llm()` |
| `llm/factory.py` | 42-44 | `create_embed_model()` |
| `llm/base.py` | 56-59 | `BaseLLMClient.generate()` |
| `config.py` | 83 | `RAGConfig.collection_name = "regulations_vectors"` |
| `tokenizer.py` | 60-80 | `tokenize_chinese()` — jieba + 自定义词典 |

### 同义词与数据文件

| 文件 | 内容 |
|------|------|
| `data/synonyms.json` | 20 组保险同义词映射 |
| `data/stopwords.txt` | 中文停用词（7 行） |
| `data/insurance_dict.txt` | 47 个加权保险术语 |
| `data/eval_dataset.json` | 不存在（默认回退到硬编码） |

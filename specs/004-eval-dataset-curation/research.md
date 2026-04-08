# 评测数据集人工审核与维护 — 技术调研报告

生成时间: 2026-04-08 10:40:00
分析范围: RAG 评测模块 + 知识库检索 + 前端交互

---

## 执行摘要

当前 RAG 评测系统已具备完整的数据集 CRUD、评测运行、自动化指标计算和基础人工抽检能力，但**缺少面向精算师的评测 case 审核工作台**。核心痛点是：精算师在审核评测 case 时，无法便捷地查阅知识库中的法律法规原文来验证 `ground_truth` 和 `evidence_docs` 的准确性。

调研发现业界有成熟的三种交互模式可借鉴：**RAG Pipeline Evaluation**（Label Studio 模式）、**Knowledge Base Evidence Linking**（INCEpTION 模式）和 **Active Learning Verification**（Prodigy 模式）。推荐采用 **"检索 → 验证 → 标注"混合模式**：在评测 case 编辑界面内嵌知识库检索面板，精算师可以边查阅法规原文边更新评测元数据。技术可行，主要工作量在前端交互设计。

---

## 一、现有代码分析

### 1.1 评测数据集现状

| 维度 | 现状 |
|------|------|
| **数据模型** | `EvalSample`: id, question, ground_truth, evidence_docs, evidence_keywords, question_type, difficulty, topic |
| **存储** | JSON 文件 (`eval_dataset.json`) + SQLite (`eval_samples` 表) |
| **数据量** | 150+ samples，覆盖 4 种题型 |
| **元数据丰富度** | 较弱 — 无法规条文引用、无置信度、无审核状态、无审核人、无审核时间 |

**核心问题**：`evidence_docs` 仅存文件名（如 `保险法.txt`），没有精确到条文级别。精算师要验证 `ground_truth` 是否准确，需要手动去翻法规原文，效率极低。

### 1.2 知识库检索能力

| 能力 | 实现位置 | 说明 |
|------|---------|------|
| **混合检索** | `rag_engine.py` → `RAGEngine.search()` | 向量 + BM25 + RRF 融合 |
| **Rerank** | `retrieval.py` → GGUF/LLM reranker | 对检索结果精排 |
| **法规文档管理** | `api/routers/knowledge.py` | 文档列表、导入、预览 |
| **KB 版本管理** | `api/routers/kb_version.py` | 多版本 KB 切换 |

**已有能力**：`RAGEngine.search(query_text, top_k)` 可直接用于辅助检索。

### 1.3 现有人工审核 API

```python
# schemas/eval.py
class HumanReviewCreate(BaseModel):
    evaluation_id: str
    sample_id: str
    reviewer: str = ""
    faithfulness_score: Optional[float]  # 0-1
    correctness_score: Optional[float]   # 0-1
    relevancy_score: Optional[float]     # 0-1
    comment: str = ""
```

**局限**：
- 仅能在评测运行后对"结果"打分，不能在"数据集准备阶段"审核 case 本身
- 没有"已审核/未审核/需修改"状态管理
- 没有与知识库检索的联动

### 1.3.1 已有的 Badcase → 评测样本闭环

> **重要发现**：系统已实现完整的 badcase 转评测样本链路，不需要重复建设。

```
用户反馈(手动 👎 / auto_detect < 0.4)
  → feedback 表（rating, reason, correction）
    → badcase_classifier 自动分类（retrieval_failure / hallucination / knowledge_gap）
      → FeedbackPage 人工审核
        → POST /badcases/{id}/convert → eval_samples 表
```

- **前端**：`FeedbackButtons.tsx` — 👎👍 + 原因选择 + 纠正输入
- **自动检测**：`quality_detector.py` — faithfulness/retrieval/completeness 三维评分，< 0.4 自动创建 feedback
- **分类**：`badcase_classifier.py` — LLM/heuristic 三类分类 + 合规风险评估
- **转换**：`feedback.py:187` — `POST /badcases/{id}/convert` 直接写入 eval_samples

**结论**：badcase 沉淀闭环已完整，不需要在 eval 审核工作台中重复建设。

### 1.4 前端现状

- **EvalPage.tsx** — 已有完整的数据集表格、评测运行、配置管理、指标对比 UI
- **UI 框架**：Ant Design + React + TypeScript
- **缺少**：case 详情编辑面板、知识库检索面板、审核状态/流程

### 1.5 数据集自动校验

`dataset_validator.py` 已提供基础校验：
- question/ground_truth 为空检测
- evidence_docs/evidence_keywords 为空检测
- 题型分布统计

**缺少**：ground_truth 与 evidence_docs 的一致性校验、法规条文引用验证。

---

## 二、业界产品交互设计调研

### 2.1 相关工具/产品对比

| 工具/产品 | 类型 | 核心交互模式 | 与我们需求的匹配度 |
|-----------|------|-------------|-------------------|
| **Label Studio** (RAG Human Feedback) | 开源标注平台 | Question → Retrieved Docs → Answer 三栏布局，拖拽排序相关性 | ★★★★★ — 直接实现了 RAG 评测标注 |
| **GaRAGe** (Amazon Science) | 学术方法论 | evidence_relevant / evidence_correct / evidence_cited 三级标注 | ★★★★ — 标注粒度与方法论可借鉴 |
| **INCEpTION** (TU Darmstadt) | 开源标注工具 | 文本高亮 + 知识库条目链接，语义搜索 KB | ★★★★ — "搜索 KB → 链接证据"模式最贴合 |
| **Braintrust** | 商业平台 | 评测 trace 审查 + 人工打分 + 数据集版本管理 | ★★★ — 数据集版本管理思路可借鉴 |
| **Argilla** (Hugging Face) | 开源标注平台 | LLM 输出审查 + 结构化反馈 + 元数据过滤 | ★★★ — 元数据过滤/搜索可借鉴 |
| **Prodigy** (spaCy) | 商业标注工具 | 主动学习 + 快速验证 + 键盘快捷键 | ★★★ — 交互效率思路可借鉴 |
| **Langfuse** | 开源可观测平台 | Trace 审查 + 人工评分 + 数据集管理 | ★★★ — 已有类似 trace 能力 |

### 2.2 三种核心交互模式

#### 模式 A：RAG Pipeline Evaluation（Label Studio）

```
┌─────────────────────────────────────────────────────┐
│  Question: "终身寿险的等待期最长多少天？"              │
├─────────────────────┬───────────────────────────────┤
│  Retrieved Docs     │  Answer / Ground Truth        │
│  ┌────────────────┐ │  ┌───────────────────────────┐ │
│  │ ✓ 保险法 §18   │ │  │ 根据保险法第十八条...     │ │
│  │ ✓ 健康险管理办法 │ │  │                           │ │
│  │ ✗ 人身险条款    │ │  │  Faithfulness: [👍] [👎]  │ │
│  └────────────────┘ │  │  Correctness: [👍] [👎]   │ │
│                     │  └───────────────────────────┘ │
└─────────────────────┴───────────────────────────────┘
```

**优点**：最直观，精算师一眼看到问题和相关文档
**缺点**：依赖系统检索质量，如果检索不准就帮不上忙

#### 模式 B：Knowledge Base Evidence Linking（INCEpTION）

```
┌─────────────────────────────────────────────────────┐
│  Eval Case: f001                                    │
│  Ground Truth: "根据保险法第十八条..."                │
│                                                     │
│  [🔍 搜索法规库] ________________________ [搜索]     │
│  ┌─────────────────────────────────────────────────┐ │
│  │ 搜索结果:                                        │ │
│  │ 📄 保险法.txt > 第十八条 (score: 0.92)  [链接]  │ │
│  │ 📄 健康险管理办法 > 第十二条 (score: 0.85) [链接]│ │
│  └─────────────────────────────────────────────────┘ │
│                                                     │
│  已链接证据:                                         │
│  📎 保险法 §18 — "保险合同中规定的..."  [✕ 移除]     │
│  📎 健康险管理办法 §12 — "健康保险..."  [✕ 移除]     │
└─────────────────────────────────────────────────────┘
```

**优点**：精算师主动搜索，精准控制引用来源
**缺点**：需要精算师知道搜什么关键词

#### 模式 C：Active Learning Verification（Prodigy）

```
┌─────────────────────────────────────────────────────┐
│  Case 12/150  ⌨ [A]Accept  [R]Reject  [E]Edit      │
│                                                     │
│  System Suggestion:                                  │
│  ┌─────────────────────────────────────────────────┐ │
│  │ ground_truth: "根据保险法第十八条，保险人..."    │ │
│  │ evidence: [保险法.txt]                          │ │
│  │ confidence: 0.89                                │ │
│  └─────────────────────────────────────────────────┘ │
│                                                     │
│  [A] 正确  [E] 修改  [S] 跳过  [R] 错误             │
└─────────────────────────────────────────────────────┘
```

**优点**：审核效率最高，适合批量审核
**缺点**：需要先有自动化的质量评估系统

### 2.3 推荐方案：混合模式（A + B）

结合精算师的实际工作场景，推荐 **"系统推荐 + 主动搜索"混合模式**：

```
┌──────────────────────────────────────────────────────────────┐
│  评测 Case 审核  ─────────────────────  case 12 / 150        │
├──────────────────────────┬───────────────────────────────────┤
│  Case 信息               │  法规知识库                       │
│  ────────────            │  ────────────                    │
│  问题:                   │  [🔍 搜索法规] _____ [搜索]      │
│  "终身寿险等待期..."      │                                   │
│                          │  ┌─ 搜索结果 ──────────────────┐ │
│  Ground Truth:           │  │ 📄 保险法 §18    0.92 [引用] │ │
│  "根据保险法第十八条..."  │  │ 📄 健康险办法 §12 0.85 [引用] │ │
│                          │  │ 📄 保险法 §32    0.78 [引用] │ │
│  Evidence Docs:          │  │ 📄 人身险条款     0.65 [引用] │ │
│  📎 保险法.txt           │  └──────────────────────────────┘ │
│  📎 健康险管理办法.txt   │                                   │
│  ────────────            │  ┌─ 已引用证据 ────────────────┐ │
│  审核状态: ⏳ 待审核      │  │ 📎 保险法 §18 (0.92) [✕]   │ │
│  审核人:                  │  │ 📎 健康险办法 §12 (0.85)[✕] │ │
│  备注:                    │  └──────────────────────────────┘ │
│                          │  [展开原文 ▼]                    │
│  [保存] [✓ 审核通过]     │                                   │
│  [← 上一条] [下一条 →]   │                                   │
└──────────────────────────┴───────────────────────────────────┘
```

**设计原则**：
1. **纯手动搜索** — 精算师主动点击"搜索法规"按钮，输入关键词检索 KB
2. **一键引用** — 从搜索结果直接添加到 regulation_refs，自动填充条文号和原文
3. **极简状态** — 仅 pending / approved，编辑后自动回到 pending，支持无限次迭代
4. **人主导** — 系统不做自动推荐，精算师完全掌控搜索和判断

---

## 三、技术可行性分析

### 3.1 需要新增/修改的模块

| 模块 | 操作 | 说明 |
|------|------|------|
| `EvalSample` 数据模型 | **扩展** | 新增 regulation_refs（条文级引用）、review_status、reviewer、reviewed_at、review_comment |
| `eval_samples` 表 | **扩展** | 对应新增字段 + 数据迁移 |
| `api/routers/eval.py` | **修改** | 新增审核状态流转 API、KB 搜索联动 API |
| `api/schemas/eval.py` | **扩展** | 新增审核相关的 request/response schema |
| `api/database.py` | **修改** | 新增审核状态更新、批量操作 DB 方法 |
| `EvalPage.tsx` | **大幅扩展** | 新增 case 审核工作台 Tab，内嵌 KB 搜索面板 |
| `dataset_validator.py` | **扩展** | 新增 regulation_refs 与 evidence_docs 一致性校验 |
| `rag_engine.py` | **微调** | 确保 `search()` 可被 eval 审核场景复用（已满足） |

### 3.2 技术方案对比

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| **A: 扩展现有 EvalPage** | 改动最小，复用已有组件和状态管理 | EvalPage 已较大（需要拆分） | ✅ 推荐 |
| **B: 独立 ReviewPage** | 职责分离清晰 | 需要复制大量 EvalPage 逻辑 | ❌ |
| **C: 集成 Label Studio** | 标注能力强大 | 引入新系统，学习成本高，交互定制受限 | ❌ |
| **D: 浏览器扩展** | 不侵入现有系统 | 开发部署复杂，精算师使用门槛高 | ❌ |

### 3.3 关键数据结构变更

> **设计决策（2026-04-08 讨论确认）**：
> 1. **引用粒度**：条文级引用（RegulationRef），excerpt 直接存 chunk 原文；长 chunk 拆分问题暂不处理，遇到再设计
> 2. **KB 搜索触发**：纯手动触发，精算师点"搜索法规"按钮主动搜索
> 3. **审核流程**：单级审核，仅 pending / approved 两个状态；编辑 case 后自动回到 pending，支持多次迭代修改

```python
@dataclass(frozen=True)
class RegulationRef:
    """条文级法规引用 — 从 RAGEngine.search() 结果直接构建"""
    doc_name: str           # "健康保险管理办法.txt"  ← metadata.source_file
    article: str            # "第27条"               ← metadata.article_number
    excerpt: str            # chunk 原文              ← node.text（搜索结果自动填充）
    relevance: float = 1.0  # 检索相关度              ← 搜索结果自动填充

class ReviewStatus(Enum):
    PENDING = "pending"       # 默认 / 编辑后自动回到此状态
    APPROVED = "approved"     # 精算师确认通过

# EvalSample 扩展字段（保持现有字段向后兼容）
@dataclass(frozen=True)
class EvalSample:
    # ... 现有字段保持不变 ...
    id: str
    question: str
    ground_truth: str
    evidence_docs: List[str]          # 保持兼容，文件级
    evidence_keywords: List[str]      # 保持兼容
    question_type: QuestionType
    difficulty: str
    topic: str
    # ── 新增字段 ──
    regulation_refs: List[RegulationRef]  # 条文级引用（审核时填充）
    review_status: ReviewStatus           # 审核状态
    reviewer: str = ""                    # 审核人
    reviewed_at: str = ""                 # 审核时间
    review_comment: str = ""              # 审核备注（可选，精算师自由填写）
```

### 3.4 API 设计草案

```
# 审核流程
PATCH /api/eval/dataset/samples/{id}/review    # 审核通过（设为 approved）
GET  /api/eval/dataset/review-stats            # 审核统计（各状态数量）
GET  /api/eval/dataset?review_status=pending   # 按审核状态筛选列表

# KB 搜索联动（纯手动触发）
POST /api/eval/dataset/kb-search               # 搜索知识库，返回条文级结果

# 已有接口（编辑即归 pending）
PUT  /api/eval/dataset/samples/{id}            # 编辑 case 内容，自动重置 review_status
```

> 注：batch-review 和 auto-ref 在 MVP 阶段不实现，遵循简单优先原则。

### 3.5 依赖分析

| 依赖 | 现有/新增 | 说明 |
|------|----------|------|
| `RAGEngine.search()` | ✅ 现有 | 核心检索能力已就绪 |
| Ant Design 组件 | ✅ 现有 | Drawer, Table, Tag, Mentions 等可复用 |
| `eval_samples` 表 | ⚠️ 需迁移 | 新增字段需 SQLite ALTER TABLE |
| 前端路由 | ⚠️ 需调整 | EvalPage 新增 Review 子 Tab |

---

## 四、风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| SQLite ALTER TABLE 限制 | 低 | 中 | 评估样本量小（150+），可重建表 |
| KB 搜索质量不足 | 中 | 高 | 提供关键词搜索兜底，不依赖检索质量 |
| EvalPage 组件过大 | 高 | 中 | 拆分为 DatasetTab / ReviewTab / RunTab 等子组件 |
| 精算师学习成本 | 低 | 中 | 保持现有 UI 风格一致，最小化新概念 |
| regulation_refs 与 evidence_docs 双轨 | 中 | 低 | evidence_docs 保持向后兼容，regulation_refs 作为增强 |

---

## 五、分阶段实施建议

### Phase 1：核心审核工作台（MVP）
1. 扩展 `EvalSample` 数据模型，新增审核字段
2. 在 EvalPage 新增"审核"Tab — 左右分栏布局
3. 实现系统推荐（基于 question 自动搜索 KB）
4. 实现审核状态流转（待审核 → 通过/需修改）
5. 支持键盘快捷键导航

### Phase 2：精准引用与自动校验
1. 条文级引用（RegulationRef），支持从搜索结果一键引用
2. 自动校验 regulation_refs 与 evidence_docs 一致性
3. 数据集质量 Dashboard（审核进度、问题分布）

### Phase 3：批量操作与导出
1. 批量审核（按题型、难度筛选后批量通过）
2. 导出已审核通过的"准"数据集
3. 评测运行时自动关联审核状态

---

## 六、评测数据集元数据完备性分析

> 基于 RAG 评测最佳实践文章的行业对标分析。

### 6.1 参考文章

1. **《大模型评测测试集构建六步法》** — 测试集构建的系统方法论
   - 核心观点：测试集需覆盖多维度、需人工交叉验证、badcase 沉淀回流
   - 关键数据：20% 交叉抽样、~8% 错误率、badcase 持续迭代
   - 来源: https://mp.weixin.qq.com/s/GUeJCJfd03cSK5aCoefRaA

2. **《RAG评估指南：从检索到生成再到系统级评估》** — RAG 三层评估框架
   - 核心观点：retrieval → generation → system 三层递进；金融行业强调可追溯性
   - 关键数据：评测数据集需与 KB 版本绑定，确保结果可复现
   - 来源: https://mp.weixin.qq.com/s/fU0RIBiO0OE5JJWwPW156Q

### 6.2 元数据完备性对比

| 元数据字段 | 行业要求 | 当前状态 | 优先级 | 说明 |
|-----------|---------|---------|--------|------|
| `id` | ✅ 必需 | ✅ 已有 | — | 唯一标识 |
| `question` | ✅ 必需 | ✅ 已有 | — | 测试问题 |
| `ground_truth` | ✅ 必需 | ✅ 已有 | — | 标准答案 |
| `evidence_docs` | ✅ 必需 | ✅ 已有 | — | 文件级证据 |
| `evidence_keywords` | 推荐有 | ✅ 已有 | — | 关键词 |
| `question_type` | ✅ 必需 | ✅ 已有 | — | 题型分类 |
| `difficulty` | 推荐有 | ✅ 已有 | — | 难度分级 |
| `topic` | 推荐有 | ✅ 已有 | — | 主题分类 |
| `regulation_refs` | ✅ 条文级引用 | 📋 已规划 | P1 | 精确到法规条文 |
| `review_status` | ✅ 审核状态 | 📋 已规划 | P1 | pending/approved |
| `reviewer` | ✅ 审核人 | 📋 已规划 | P1 | 责任人 |
| `reviewed_at` | ✅ 审核时间 | 📋 已规划 | P1 | 时间戳 |
| `review_comment` | 推荐有 | 📋 已规划 | P1 | 审核备注 |
| **`created_by`** | ⚠️ 区分人工/LLM 生成 | ❌ 缺失 | **P2** | 文章强调人工编写 vs LLM 生成的测试问题质量差异显著，需区分来源 |
| **`kb_version`** | ⚠️ KB 版本绑定 | ❌ 缺失 | **P2** | 文章强调评测结果需可复现，KB 变更会影响 retrieval 指标 |
| `chunk_id` (RegulationRef) | 条文级精确定位 | 📋 已规划（预留） | **P2** | 在 RegulationRef 中预留 chunk_id，当前 chunker metadata 无此字段，暂为空 |

### 6.3 关键发现

**发现 1：测试问题来源追踪（created_by）**
- 两篇文章均强调人工编写和 LLM 生成的测试问题质量差异显著
- 人工编写的测试问题更贴近真实业务场景，LLM 生成的问题可能存在分布偏差
- 建议：新增 `created_by` 字段，取值为 `"human"` 或 `"llm"`，默认 `"human"`

**发现 2：KB 版本绑定（kb_version）**
- RAG 评估文章强调：KB 变更会影响 retrieval 指标，评测数据集需与 KB 版本绑定
- 当 KB 更新后，需重新验证已有评测 case 的 ground_truth 和 evidence 仍然有效
- 建议：新增 `kb_version` 字段，取值为 KB 版本标识符（如 `"v1.2"`），空字符串表示未绑定

**发现 3：Chunk 级精确定位（chunk_id）**
- 当前 RegulationRef 设计仅记录条文号（article），但同一法条可能被拆分为多个 chunk
- 增加 chunk_id 可实现从评测 case 精确定位到 KB 中的具体 chunk，便于验证和调试
- 建议：在 RegulationRef 中新增可选 `chunk_id` 字段

### 6.4 实施建议

| 字段 | 实施阶段 | 理由 |
|------|---------|------|
| `created_by` | Phase 1 | 数据模型层零成本，默认值 `"human"` |
| `kb_version` | Phase 1 | 数据模型层零成本，默认值 `""` |
| `chunk_id` (RegulationRef) | Phase 1 | 数据模型层零成本，可选字段 |

四个字段均有默认值，加入 Phase 1 数据模型扩展中，不增加额外迁移成本。前端可在 Phase 3 中渐进展示。

---

## 七、参考资源

- [Label Studio RAG Human Feedback Template](https://labelstud.io/templates/llm_rag_human_feedback) — RAG 评测标注交互参考
- [Label Studio RAG Evaluation with Ragas](https://labelstud.io/blog/how-to-build-and-evaluate-rag-applications-with-label-studio-openai-and-ragas/) — 实施参考
- [GaRAGe - GitHub (Amazon Science)](https://github.com/amazon-science/GaRAGe) — 条文级标注方法论
- [INCEpTION](https://inception-project.github.io/) — KB 知识库链接交互模式
- [Braintrust](https://www.braintrust.dev/) — 数据集版本管理与人工审查
- [Argilla](https://www.argilla.io/) — 元数据过滤与结构化反馈
- [大模型评测测试集构建六步法](https://mp.weixin.qq.com/s/GUeJCJfd03cSK5aCoefRaA) — 测试集构建方法论、badcase 沉淀
- [RAG评估指南：从检索到生成再到系统级评估](https://mp.weixin.qq.com/s/fU0RIBiO0OE5JJWwPW156Q) — RAG 三层评估、KB 版本绑定
- [Closing the Knowledge Gap in Annotation Interface Design (arXiv 2024)](https://arxiv.org/html/2403.01722v1) — 上下文增强标注界面研究
- [Verification-Based Annotation (CVPR 2021)](https://openaccess.thecvf.com/content/CVPR2021/papers/Liao_Towards_Good_Practices_for_Efficiently_Annotating_Large-Scale_Image_Classification_Datasets_CVPR_2021_paper.pdf) — 验证式标注效率研究
- [Shape of AI Pattern Library](https://www.shapeof.ai/) — AI/UX 设计模式库

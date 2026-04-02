# RAG 系统问题反馈机制 — 深度研究报告

> 日期: 2026-03-31
> 目标: 为 Actuary Sleuth RAG 问答系统设计一套完整的 Badcase 反馈闭环机制
> 参考: [阿里面试官问：你的 RAG 系统上线之后，用户反馈答案不对，你怎么处理的？](https://mp.weixin.qq.com/s/F2QU3cSO7sOW9ZPVAEkt_w)

---

## 1. 现有系统现状分析

### 1.1 RAG 引擎核心流程

当前 RAG 引擎 (`scripts/lib/rag_engine/rag_engine.py`) 的查询流程：

```
用户问题
  → QueryPreprocessor（同义词归一化、查询扩展、LLM 改写）
  → 混合检索（向量 + BM25 关键词）
  → RRF 融合（k=60）+ 去重
  → LLM Reranking（可选，top_k 筛选）
  → 上下文构建（12,000 字符限制）
  → LLM 生成（带引用要求）
  → Attribution（[来源X] 解析 + 未验证声明检测）
  → 返回：answer, citations, sources, faithfulness_score
```

**已有的质量检测能力：**
- `faithfulness_score`: 句子级覆盖率 + bigram 重叠度（0.6 * sentence_coverage + 0.4 * bigram_overlap）
- `unverified_claims`: 检测无引用的事实性陈述（数字、日期、法律术语、义务词）
- `parse_citations`: 解析 LLM 回答中的 [来源X] 标签

### 1.2 API 层现状

| 端点 | 功能 | 备注 |
|------|------|------|
| `POST /api/ask/chat` | 问答（SSE 流式） | 返回 conversation_id, citations, sources, faithfulness_score |
| `GET /api/ask/conversations` | 对话列表 | 包含 message_count |
| `GET /api/ask/conversations/{id}/messages` | 对话消息 | 含 citations_json, sources_json |
| `DELETE /api/ask/conversations/{id}` | 删除对话 | — |

**关键发现：** 当前没有任何用户反馈相关的 API 端点。

### 1.3 数据库 Schema 现状

现有 `messages` 表结构：
```sql
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    content TEXT NOT NULL DEFAULT '',
    citations_json TEXT NOT NULL DEFAULT '[]',
    sources_json TEXT NOT NULL DEFAULT '[]',
    timestamp TEXT NOT NULL DEFAULT (datetime('now'))
);
```

**关键发现：** 消息表已存储 `citations` 和 `sources`，但缺少评分、反馈类型、分类标签等字段。

### 1.4 评估系统现状

已有完善的评估体系（`scripts/lib/rag_engine/evaluator.py`）：

- **检索评估**: precision@k, recall@k, MRR, NDCG, 冗余率, context_relevance
- **生成评估**: faithfulness, answer_relevancy, answer_correctness（支持 RAGAS 或轻量级 fallback）
- **评估数据集**: 30 条内置样本（factual/multi_hop/negative/colloquial）
- **评估 API**: 完整的 CRUD + 运行 + 比较 + 导出

**关键发现：** 评估系统完善但与用户反馈完全隔离。真实 badcase 无法回流到评估数据集。

### 1.5 前端现状

- **ChatPanel**: 对话列表 + 消息展示 + 引用点击
- **MessageBubble**: 用户消息（蓝色气泡）+ 助手消息（灰色气泡 + 引用标签）
- **EvalRunPage**: 评估运行 + 报告查看 + 运行对比
- **AskStore (Zustand)**: 管理对话状态、消息流、来源面板

**关键发现：** 前端没有点赞/点踩、反馈表单、Badcase 管理页面等任何反馈 UI。

---

## 2. 参考文章核心要点提炼

### 2.1 Badcase 四分类框架

| 类型 | 占比 | 表现 | 修复方向 |
|------|------|------|----------|
| **检索失败** | ~40% | 知识库有答案但没检索到 | 优化 Chunk 策略、混合检索、RRF 权重 |
| **幻觉生成** | ~25% | 检索正确但 LLM 答案错误 | 加强 Prompt 忠实度约束、引用校验 |
| **路由错误** | ~20% | 问题走错了处理路径 | 补充路由训练样本、调整路由策略 |
| **知识缺失** | ~15% | 知识库里确实没有 | 补充文档入库 |

### 2.2 三路收集渠道

1. **用户反馈按钮** — 主动信号，质量参差不齐需过滤
2. **客服工单对接** — 高价值信号，风险最高的问题
3. **自动质量检测** — 覆盖最广的被动信号（检索相关性 + 答案忠实度 + 关键信息完整性）

### 2.3 运营闭环六步

```
收集 → 自动分类 → 按类型分配 → 修复验证 → 回归测试 → 灰度发布
```

**核心原则：**
- 修复前必须在原 badcase 上验证通过
- 回归测试允许 2% 容差（防止测试集抽样误差）
- 定位退化 case（原来对现在错的）
- 灰度发布（10% → 全量）

### 2.4 自动分类脚本

用 LLM 对 badcase 做初步四分类（准确率 ~80%），人工仅复核高风险 case（涉及赔付金额等）。

### 2.5 实战数据

- 6 个月：准确率 76% → 89%
- 每周 badcase：50 条 → 15 条
- 测试集从 200 条扩充到 350 条（150 条来自真实 badcase）

---

## 3. 差距分析（Gap Analysis）

### 3.1 已有能力 vs 需要补齐的能力

| 维度 | 已有 | 缺失 |
|------|------|------|
| **数据采集** | 对话记录（含 sources/citations）、faithfulness_score | 用户评分、反馈原因、Badcase 标记 |
| **自动检测** | faithfulness 计算、unverified_claims 检测 | 检索相关性评分、关键信息完整性检测、自动 Badcase 筛选 |
| **分类** | 无 | 四分类自动分类脚本、人工复核流程 |
| **管理** | 评估数据集 CRUD、快照 | Badcase 列表/筛选/状态管理 |
| **修复验证** | 评估运行 API | 单条 badcase 重跑验证、对比修复前后结果 |
| **回归测试** | 评估运行 + 对比 API | 与 badcase 修复流程的集成 |
| **闭环** | 评估数据集快照/恢复 | badcase → eval_sample 转化、回归退化检测 |
| **前端 UI** | 对话/评估页面 | 反馈按钮、Badcase 管理页面、反馈分析仪表盘 |

### 3.2 本系统特有适配

与文章中的通用 RAG 系统相比，本系统有几个特殊点：

1. **无路由错误类型** — 本系统只有 RAG 问答和精确检索两种模式，不存在 Text2SQL 等多路由场景。四分类需调整为三分类：**检索失败、幻觉生成、知识缺失**。

2. **已有引用归因机制** — `attribution.py` 已实现 `[来源X]` 解析和 `unverified_claims` 检测，可复用为自动质量检测的基础。

3. **已有 faithfulness_score** — 每次 QA 请求都返回此指标，可直接用于自动 Badcase 筛选阈值。

4. **精算合规场景** — 比文章中的保险理赔场景更严格，错误答案可能导致合规风险。需要增加**合规风险标记**维度。

5. **现有评估系统成熟** — 评估 API 已支持运行、对比、导出，可直接集成到回归测试环节。

---

## 4. 反馈机制设计方案

### 4.1 数据模型设计

#### 4.1.1 新增 `feedback` 表

```sql
CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    message_id INTEGER NOT NULL REFERENCES messages(id),
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    rating TEXT NOT NULL CHECK(rating IN ('up', 'down')),
    reason TEXT NOT NULL DEFAULT '',
    -- reason 可选值: '答案错误', '没有回答我的问题', '回答不完整',
    --            '引用不准确', '信息过时', '其他'
    correction TEXT DEFAULT '',           -- 用户提供的正确答案（可选）
    source_channel TEXT NOT NULL DEFAULT 'user_button',
    -- source_channel: 'user_button', 'auto_detect', 'manual_review'
    auto_quality_score REAL,             -- 自动质量评分（0-1）
    auto_quality_details_json TEXT,      -- 自动评分详情
    classified_type TEXT,                -- 自动分类: 'retrieval_failure', 'hallucination', 'knowledge_gap', 'unclear'
    classified_reason TEXT,              -- 分类原因
    classified_fix_direction TEXT,       -- 修复建议
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'classified', 'fixing', 'fixed', 'rejected', 'converted')),
    -- pending: 待分类
    -- classified: 已分类待处理
    -- fixing: 修复中
    -- fixed: 已修复
    -- rejected: 误报/无效反馈
    -- converted: 已转化为评估样本
    compliance_risk INTEGER NOT NULL DEFAULT 0,
    -- 0: 低风险, 1: 中风险(涉及金额/期限), 2: 高风险(涉及合规红线)
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_feedback_message ON feedback(message_id);
CREATE INDEX IF NOT EXISTS idx_feedback_status ON feedback(status);
CREATE INDEX IF NOT EXISTS idx_feedback_type ON feedback(classified_type);
```

#### 4.1.2 修改 `messages` 表

在 `add_message` 时额外存储检索质量元数据：

```sql
ALTER TABLE messages ADD COLUMN faithfulness_score REAL;
ALTER TABLE messages ADD COLUMN unverified_claims_json TEXT DEFAULT '[]';
ALTER TABLE messages ADD COLUMN retrieval_scores_json TEXT DEFAULT '[]';
```

> `retrieval_scores_json` 存储每个 source 的检索分数，便于后续分析检索质量问题。

### 4.2 后端 API 设计

#### 4.2.1 反馈提交 API

```
POST /api/ask/feedback
Body: {
    message_id: int,
    rating: "up" | "down",
    reason?: string,
    correction?: string
}
Response: { feedback_id: string }
```

#### 4.2.2 Badcase 管理 API

```
GET    /api/feedback/badcases                    # 列表（支持筛选：status, type, risk, date range）
GET    /api/feedback/badcases/{id}               # 详情（含完整对话上下文、检索结果、自动评分）
PUT    /api/feedback/badcases/{id}               # 更新（修改分类、状态、备注）
POST   /api/feedback/badcases/classify           # 批量自动分类
POST   /api/feedback/badcases/{id}/verify        # 单条重跑验证
POST   /api/feedback/badcases/{id}/convert       # 转化为评估样本
GET    /api/feedback/stats                       # 统计数据（按类型、时间趋势）
```

#### 4.2.3 自动检测 API（内部）

```
POST /api/feedback/auto-detect                   # 对指定消息执行自动质量检测
```

自动检测逻辑：

```python
def auto_detect_quality(message: dict) -> dict:
    """三维度自动质量评分"""
    scores = {}

    # 维度1: 答案忠实度（复用现有 faithfulness_score）
    scores['faithfulness'] = message.get('faithfulness_score', 0.0)

    # 维度2: 检索相关性（query-source 语义相似度）
    # 利用现有 _compute_context_relevance 或 embedding 相似度
    scores['retrieval_relevance'] = compute_retrieval_relevance(
        message['query'], message['sources']
    )

    # 维度3: 关键信息完整性
    # 精算场景：用户问题包含数字/比例/期限 → 回答应包含对应数字
    scores['completeness'] = compute_info_completeness(
        message['query'], message['answer']
    )

    # 综合评分
    scores['overall'] = (
        0.4 * scores['faithfulness'] +
        0.3 * scores['retrieval_relevance'] +
        0.3 * scores['completeness']
    )

    return scores
```

### 4.3 自动分类设计

```python
def classify_badcase(
    query: str,
    retrieved_docs: list[dict],
    answer: str,
    unverified_claims: list[str],
) -> dict:
    """三分类自动分类（适配本系统无路由错误的场景）

    判断逻辑：
    1. 检索文档里有没有答案 → 没有 = 知识缺失
    2. 有答案，但答案和检索文档不一致 → 幻觉生成
    3. 有答案且一致，但用户仍不满意 → 检索失败（排序/召回不足）
    """
```

分类完成后自动标记 `compliance_risk`：
- 检测答案中是否包含金额、比例、期限等精算敏感数字
- 包含敏感数字且标记为"答案错误" → 高风险（risk=2）
- 涉及合规关键词（"不得"、"必须"、"禁止"）→ 中风险（risk=1）

### 4.4 前端 UI 设计

#### 4.4.1 消息反馈组件（MessageBubble 增强）

在每条助手消息气泡底部增加：

```
[👍 有用]  [👎 有问题 ▼]
              ├─ 答案错误
              ├─ 没有回答我的问题
              ├─ 回答不完整
              ├─ 引用不准确
              ├─ 信息过时
              └─ 其他 [文本输入框]
              [可选: 提供正确答案 ____________]
```

- 点赞：`rating = "up"`，直接记录
- 点踩：`rating = "down"`，展开原因选择
- 提供正确答案：可选填，用于辅助分类和后续评估样本构建

#### 4.4.2 Badcase 管理页面（新增）

路由: `/feedback/badcases`

**功能：**
- **列表视图**: 表格展示 badcase（问题、类型、风险等级、状态、时间）
- **筛选器**: 按类型、状态、风险等级、时间范围筛选
- **详情面板**: 展开查看完整对话、检索结果、自动评分详情、分类建议
- **批量操作**: 批量分类、批量转化、批量标记已修复
- **单条验证**: 一键重跑该 badcase，对比修复前后结果
- **转化为评估样本**: 将 badcase 转入 eval_samples 表，补充 ground_truth

#### 4.4.3 反馈统计仪表盘（新增）

路由: `/feedback/stats`

**功能：**
- 总体满意度趋势（好评率/差评率随时间变化）
- Badcase 类型分布饼图
- 风险等级分布
- 每周 badcase 数量趋势
- 自动检测命中率（自动标记的 badcase 中用户确认的比例）

### 4.5 闭环流程设计

```
                    ┌─────────────────────────────┐
                    │      用户问答（现有流程）       │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │    1. 收集（三路并行）         │
                    │  ├─ 用户反馈按钮（主动）       │
                    │  ├─ 自动质量检测（被动）       │
                    │  └─ 人工标记（管理后台）       │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │    2. 自动分类                 │
                    │  检索失败 / 幻觉生成 / 知识缺失  │
                    │  + 合规风险自动标记             │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │    3. 处理（按类型分流）       │
                    │  ├─ 检索失败 → 调优检索策略    │
                    │  ├─ 幻觉生成 → 优化 Prompt     │
                    │  └─ 知识缺失 → 补充文档入库    │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │    4. 修复验证                 │
                    │  在原 badcase 上重跑确认通过    │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │    5. 回归测试                 │
                    │  全量评估数据集 + 容差 2%      │
                    │  定位退化 case                │
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │    6. 闭环完成                 │
                    │  ├─ badcase → eval_sample    │
                    │  ├─ 更新评估数据集快照         │
                    │  └─ 标记 badcase 为 fixed     │
                    └─────────────────────────────┘
```

### 4.6 与现有系统的集成点

| 集成点 | 方式 | 说明 |
|--------|------|------|
| **messages 表** | 扩展字段 | 增加 faithfulness_score, retrieval_scores_json |
| **ask/chat API** | 修改返回 | done 事件增加 faithfulness_score, unverified_claims |
| **eval_samples 表** | 复用 | badcase 可转化为 eval_sample |
| **eval_runs API** | 复用 | 回归测试直接调用现有评估运行 |
| **attribution.py** | 复用 | unverified_claims 检测用于自动评分 |
| **evaluator.py** | 复用 | _compute_context_relevance 用于检索相关性评分 |
| **AskStore** | 扩展 | 增加 feedback 状态管理 |
| **MessageBubble** | 增强 | 增加反馈按钮 UI |

### 4.7 技术实现要点

#### 4.7.1 检索分数持久化

当前 `hybrid_search` 返回结果包含 `score` 字段，但 `add_message` 时仅保存 `sources`。需在 `ask.py` 路由中将每个 source 的 score 一并保存到 `retrieval_scores_json`。

#### 4.7.2 自动检测触发时机

- **方案 A（实时）**: 每次 QA 返回后立即执行自动检测，低于阈值的自动创建 feedback 记录
- **方案 B（批处理）**: 定时任务（如每小时）扫描新增消息，批量执行自动检测

**推荐方案 A**，因为：
- 系统是内部工具，并发量不大
- 实时检测能更快发现问题
- 实现更简单，无需额外定时任务

但需要设置合理的阈值避免误报：
- `faithfulness_score < 0.5` → 自动标记
- `retrieval_relevance < 0.4` → 自动标记
- 有 unverified_claims 且涉及数字 → 自动标记

#### 4.7.3 分类用 LLM 选择

自动分类使用现有 QA LLM（glm-4-flash），无需额外模型。分类 prompt 模板固定，不消耗额外 token 预算。

#### 4.7.4 Badcase → EvalSample 转化

```python
def convert_badcase_to_eval_sample(feedback: dict) -> dict:
    """将已修复的 badcase 转化为评估样本"""
    return {
        "id": f"bc_{feedback['id']}",
        "question": feedback['user_question'],
        "ground_truth": feedback['correction'] or feedback['expected_answer'],
        "evidence_docs": [s['source_file'] for s in feedback['sources']],
        "evidence_keywords": extract_keywords(feedback['user_question']),
        "question_type": feedback['classified_type'],
        "difficulty": "medium",
        "topic": extract_topic(feedback['user_question']),
    }
```

---

## 5. 实施优先级建议

### Phase 1: 基础反馈能力（最小可用）

1. `feedback` 表建表 + CRUD 函数
2. `POST /api/ask/feedback` 反馈提交 API
3. MessageBubble 增加 👍👎 按钮
4. `messages` 表扩展 faithfulness_score 字段

### Phase 2: 自动检测 + 分类

5. 自动质量检测逻辑（三维度评分）
6. 自动分类脚本（三分类）
7. 合规风险自动标记
8. Badcase 管理页面（列表 + 详情 + 筛选）

### Phase 3: 闭环集成

9. 单条 badcase 重跑验证
10. Badcase → EvalSample 转化
11. 回归测试集成（评估运行 API 复用）
12. 反馈统计仪表盘

---

## 6. 风险与权衡

| 风险 | 应对 |
|------|------|
| 自动检测误报率高 | 设置较高阈值，初期以人工复核为主 |
| 用户不愿提供反馈 | 反馈 UI 轻量化（一键操作），不强制填写原因 |
| 分类 LLM 不稳定 | 分类结果置信度低时标记为 `unclear`，人工复核 |
| 精算场景的 ground_truth 难确定 | 转化 eval_sample 时需人工确认 ground_truth |
| feedback 表数据膨胀 | 定期归档已 fixed/rejected 的记录 |

---

## 7. 与文章方案的差异总结

| 维度 | 文章方案 | 本系统适配 |
|------|----------|------------|
| Badcase 分类 | 四分类（含路由错误） | 三分类（无路由错误场景） |
| 收集渠道 | 用户按钮 + 客服工单 + 自动检测 | 用户按钮 + 自动检测 + 人工标记（无客服工单系统） |
| 自动检测 | 检索相关性 + 忠实度 + 完整性 | 复用 faithfulness_score + context_relevance + 新增完整性检测 |
| 合规风险 | 未提及 | 新增合规风险三级标记（适配精算场景） |
| 回归测试 | 自定义脚本 | 复用现有评估运行 + 对比 API |
| 灰度发布 | 10% 用户灰度 | 内部工具不需要灰度，直接全量 |
| 数据集扩充 | badcase → 测试集 | badcase → eval_samples（复用现有表和 API） |

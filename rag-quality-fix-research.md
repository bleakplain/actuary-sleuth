# Actuary Sleuth RAG 系统 — 质量保障体系深度研究报告

生成时间: 2026-04-03
分析范围: 全代码库 `scripts/`，聚焦 RAG 质量保障体系（badcase 收集、分类、回归测试、幻觉预防）
参考文章: [RAG 系统上线后的 Badcase 运营闭环](https://mp.weixin.qq.com/s/F2QU3cSO7sOW9ZPVAEkt_w)

---

## 执行摘要

本报告参照阿里 RAG 系统运营闭环方法论（三路收集 + 四分类 + 回归验证），深入评估 Actuary Sleuth 当前 RAG 系统的质量保障能力。

**核心结论：系统已建立质量保障的骨架，但多个关键环节存在缺陷，尚未形成有效的运营闭环。**

| 文章建议的运营环节 | 当前实现状态 | 评级 |
|---|---|---|
| 三路 badcase 收集（用户反馈 / 客服工单 / 自动检测） | 用户反馈 + 自动检测（2/3） | ⚠️ 部分实现 |
| 四分类框架（检索失败 / 幻觉 / 路由错误 / 知识缺失） | 三分类（缺路由错误）（3/4） | ⚠️ 部分实现 |
| 修复验证（原 badcase 上验证通过） | 有 verify 端点，需手动触发 | ⚠️ 部分实现 |
| 全量回归测试（recall@5 + faithfulness + accuracy） | 有评估框架，缺自动化和趋势追踪 | ❌ 薄弱 |
| 灰度发布 | 无 | ❌ 缺失 |
| 知识库老化检测 | 无 | ❌ 缺失 |

---

## 一、文章方法论 vs 系统现状对照

### 1.1 文章核心框架摘要

文章提出了 RAG 系统 Badcase 运营闭环的六个步骤：

```
收集 → 自动分类 → 按类型分配 → 修复验证 → 回归测试 → 灰度发布
   ↑                                                    |
   └────────────────────────────────────────────────────┘
```

**三路收集渠道**：用户反馈按钮、客服工单对接、自动质量检测（检索相关性 + 答案忠实度 + 信息完整性）

**四分类框架**：
- A. 检索失败型（~40%）：知识库有答案但没检索到
- B. 幻觉生成型（~25%）：检索正确但 LLM 生成错误答案
- C. 路由错误型（~20%）：问题被分配到错误的处理路径
- D. 知识缺失型（~15%）：知识库确实没有该信息

**回归测试三个核心指标**：recall@5、faithfulness、answer_accuracy（允许 2% 容差）

### 1.2 系统架构对照图

```
                    文章建议                          Actuary Sleuth 现状
                    =========                        ====================

[收集]                                               [收集]
├── 用户反馈按钮  ────────────────── ✅ api/routers/feedback.py
├── 客服工单对接  ────────────────── ❌ 无
└── 自动质量检测  ────────────────── ⚠️ quality_detector.py（检测维度弱）

[分类]                                               [分类]
├── 检索失败型    ────────────────── ✅ badcase_classifier.py
├── 幻觉生成型    ────────────────── ⚠️ 基于启发式，非 LLM 分类
├── 路由错误型    ────────────────── ❌ 无（系统无路由层）
└── 知识缺失型    ────────────────── ✅ badcase_classifier.py

[验证]                                               [验证]
├── 原 badcase 验证 ─────────────── ⚠️ POST /badcases/{id}/verify（手动触发）
└── 全量回归测试  ────────────────── ⚠️ evaluate_rag.py（无自动化、无趋势追踪）

[发布]                                               [发布]
└── 灰度发布      ────────────────── ❌ 无
```

---

## 二、三路收集渠道评估

### 2.1 用户反馈渠道

**实现位置**: `scripts/api/routers/feedback.py:17-38` + `scripts/api/routers/ask.py:76-84`

**当前实现**:
- 用户通过 API 提交 👍/👎 反馈（`POST /api/feedback/submit`）
- 反馈关联到 `message_id`（绑定具体回答）和 `conversation_id`（绑定完整对话）
- message 表存储 `sources_json`（完整检索结果）、`citations_json`（引用标注）、`faithfulness_score`、`unverified_claims_json`

**优势**:
- 反馈与检索结果和生成答案完整关联，可追溯
- 支持用户填写详细原因和修正建议

**问题**:

#### 问题 2.1.1: 缺少前端反馈 UI

- **类型**: 🏗️ 设计
- **严重程度**: P2
- **说明**: 系统后端已实现反馈收集，但文章强调需要"在前端每条回答下面加两个按钮"。当前 API 层存在但缺少对应的前端组件，用户反馈渠道的实际覆盖率可能很低。

#### 问题 2.1.2: 反馈不区分"答案错误"和"用户不满意"

- **类型**: ⚠️ 质量
- **严重程度**: P3
- **说明**: 文章指出"有些用户的差评是因为系统回答正确但他不满意（比如赔付条件不符合他的期望），这类属于误踩，需要过滤"。当前反馈只有 `reason` 文本字段，缺少结构化的反馈分类（如"答案错误"、"没有回答我的问题"、"回答太模糊"、"信息过时"），无法有效过滤误踩。

### 2.2 自动质量检测渠道

**实现位置**: `scripts/api/routers/ask.py:86-108` + `scripts/lib/rag_engine/quality_detector.py`

**当前实现**: 每次回答后自动计算三维质量分数，低于 0.4 阈值自动创建 badcase

```python
# ask.py:86-108
quality = detect_quality(
    query=req.question,
    answer=answer,
    sources=result.get("sources", []),
    faithfulness_score=result.get("faithfulness_score"),
)
if quality["overall"] < 0.4:
    fb_id = create_feedback(
        message_id=msg_id,
        conversation_id=conversation_id,
        rating="down",
        reason="auto_detected",
        source_channel="auto_detect",
    )
```

**三维评分模型**:

| 维度 | 权重 | 计算方法 | 问题 |
|------|------|----------|------|
| 忠实度 (faithfulness) | 40% | LLM 自评分数或默认 0.0 | 默认禁用（`enable_faithfulness=False`），不提供时权重浪费 |
| 检索相关性 | 30% | query 与检索文档的 bigram 重叠 | 表面匹配，无语义理解 |
| 信息完整性 | 30% | 正则匹配数字/金额/百分比 | 仅覆盖数值型回答，遗漏定性问题 |

#### 问题 2.2.1: 忠实度评分默认禁用，自动检测形同虚设

- **文件**: `scripts/lib/rag_engine/config.py:47`
- **类型**: 🔴 设计缺陷
- **严重程度**: P1

**问题描述**:

`enable_faithfulness` 默认为 `False`，这意味着 `faithfulness_score` 通常为 `None`。在 `detect_quality()` 中，`None` 被替换为 `0.0`：

```python
# quality_detector.py:67
faithfulness = faithfulness_score if faithfulness_score is not None else 0.0
```

由于忠实度占总分的 40%，当 faithful=0.0 时，overall = `0.4 * 0.0 + 0.3 * relevance + 0.3 * completeness`。这意味着即使检索相关性和信息完整性都很高（如 0.8），总分也只有 `0 + 0.24 + 0.24 = 0.48`，勉强超过 0.4 阈值。这导致自动检测要么完全失效（忠实度未启用时大量误报），要么阈值形同虚设。

**影响**: 自动质量检测渠道——文章强调的"最关键的一路"——在默认配置下几乎无法正常工作。

**建议修复**:
1. 在 `detect_quality()` 中，当 faithful 不可用时，动态调整权重（如仅用 50/50 分配给 relevance 和 completeness）
2. 或在生产环境中默认启用 `enable_faithfulness`

#### 问题 2.2.2: 检索相关性仅用 bigram 重叠

- **文件**: `scripts/lib/rag_engine/quality_detector.py:14-37`
- **类型**: ⚠️ 质量
- **严重程度**: P2

**问题描述**:

```python
# quality_detector.py:22-36
def compute_retrieval_relevance(query: str, sources: List[Dict[str, Any]]) -> float:
    query_tokens = list(query)  # 按字符拆分
    source_tokens = []
    for s in sources:
        source_tokens.extend(list(s.get("content", "")))
    # bigram 重叠率
    query_bigrams = set(zip(query_tokens, query_tokens[1:]))
    source_bigrams = set(zip(source_tokens, source_tokens[1:]))
    overlap = query_bigrams & source_bigrams
    return len(overlap) / len(query_bigrams) if query_bigrams else 0.0
```

中文按字符 bigram 计算，无法捕捉语义相似性。例如：
- query: "意外伤害赔付上限是多少"
- source: "被保险人因意外事故导致身故，保险金给付额度为基本保额的5倍"
- bigram 重叠极低（几乎无共同字组合），但语义高度相关

**对比文章**: 文章建议"计算用户问题和 Top5 检索文档之间的语义相似度，如果最高分都低于 0.6，说明检索结果可能不相关"——使用的是 embedding 语义相似度，而非 bigram 重叠。

**建议修复**: 使用 embedding cosine similarity 替代 bigram 重叠。可复用已有的 Jina embedding 模型（`JinaEmbeddingAdapter`），计算 query 与各检索文档的语义相似度。

#### 问题 2.2.3: 信息完整性仅覆盖数值型回答

- **文件**: `scripts/lib/rag_engine/quality_detector.py:40-57`
- **类型**: ⚠️ 质量
- **严重程度**: P2

**问题描述**:

```python
# quality_detector.py:43-45
_NUMBER_PATTERN = re.compile(r'(\d+[\.\d]*[万亿]?[元%天年个月]?|\d{4}[-/年]\d{1,2}[-/月]\d{1,2})')
```

仅用正则匹配数字+单位模式（如"90天"、"5万元"），无法检测：
- 定性问题："健康保险等待期有什么规定？" → 正确回答应包含等待期天数，但正则只能检测回答中是否有数字
- 多部分问题：用户问了两个子问题，只回答了一个
- 比较类问题：需要对比不同条款的规定

### 2.3 客服工单渠道

**状态**: ❌ 完全缺失

**说明**: 文章指出客服工单渠道"能捞到用户没有点差评、但确实有问题的case。很多用户在移动端不喜欢点按钮，但会打电话投诉。客服工单捞上来的 badcase，往往也是影响最大、风险最高的那些。" 当前系统无任何客服对接机制。

**评估**: 在精算审核场景中，用户主要通过 API 调用系统，客服工单渠道的优先级相对较低，但如果有业务人员使用系统进行审核，则人工反馈渠道仍然重要。

---

## 三、Badcase 分类框架评估

### 3.1 当前分类系统

**实现位置**: `scripts/lib/rag_engine/badcase_classifier.py:22-103`

**三分类 vs 文章四分类对比**:

| 文章分类 | 占比 | 当前系统 | 对应 |
|---------|------|----------|------|
| A. 检索失败型 | ~40% | `retrieval_failure` | ✅ 有 |
| B. 幻觉生成型 | ~25% | `hallucination` | ⚠️ 有，但检测逻辑弱 |
| C. 路由错误型 | ~20% | — | ❌ 无 |
| D. 知识缺失型 | ~15% | `knowledge_gap` | ✅ 有 |

#### 问题 3.1.1: 缺少路由错误分类

- **类型**: 🏗️ 设计
- **严重程度**: P3

**说明**: 当前系统只有 RAG 检索路径，不存在路由层（无 Text2SQL、无直接回答模式），因此不需要路由错误分类。但如果未来系统扩展（如增加数据库查询、规则引擎），需要补充分类。

#### 问题 3.1.2: 幻觉检测依赖启发式规则，非 LLM 判断

- **文件**: `scripts/lib/rag_engine/badcase_classifier.py:37-97`
- **类型**: ⚠️ 质量
- **严重程度**: P1

**问题描述**:

文章建议用 LLM 做自动分类，准确率可达 80%。当前系统使用纯启发式规则：

```python
# badcase_classifier.py:71-90
# 判断逻辑：
# 1. 有 unverified_claims → hallucination
# 2. 回答含"未找到"短语 → knowledge_gap（需要进一步验证）
# 3. 回答与检索文档 bigram 重叠 < 0.2 → hallucination
# 4. 否则 → retrieval_failure
```

**关键缺陷**:

1. **`unverified_claims` 检测脆弱**（`attribution.py:87-128`）：基于正则检测"未引用的事实陈述"，但 LLM 如果正确引用了来源但内容有误（如数字错了），正则无法检测。例如：条款写"200%"，LLM 写"150% [来源1]"——正则认为已引用，但实际是幻觉。

2. **bigram 重叠阈值 0.2 过低**：正常的简洁回答与长文档的 bigram 重叠天然就低，容易误判为幻觉。

3. **无法区分"检索到了但答案错了"和"检索结果本身就不相关"**：两者都可能被标记为 `retrieval_failure`。

**对比文章**: 文章的分类脚本将用户问题、Top3 检索文档、系统回答一起喂给 LLM，让 LLM 做推理判断，准确率约 80%。当前系统的启发式方法准确率无法达到这个水平。

**建议修复**: 改用 LLM 辅助分类（可复用已有的 LLM 抽象层），保留启发式作为快速预筛。

#### 问题 3.1.3: 分类需手动触发，非自动运行

- **文件**: `scripts/api/routers/feedback.py:82-135`
- **类型**: ⚠️ 质量
- **严重程度**: P2

**问题描述**: 分类通过 `POST /api/feedback/badcases/classify` 端点手动触发。文章建议"每天新进来的 badcase 跑一遍自动分类脚本"——应该是定时自动执行。

```python
# feedback.py:82
@router.post("/badcases/classify")
async def classify_badcases():
    """对所有 pending 状态的 badcase 执行自动分类"""
```

**建议修复**: 添加定时任务（如 cron），每天自动执行分类。

#### 问题 3.1.4: 合规风险评估过于简单

- **文件**: `scripts/lib/rag_engine/badcase_classifier.py:106-117`
- **类型**: ⚠️ 质量
- **严重程度**: P2

**问题描述**:

```python
# badcase_classifier.py:111-115
def assess_compliance_risk(reason: str, answer: str) -> int:
    high_patterns = [r'\d+元', r'\d+万元', r'赔付', r'保额']
    medium_patterns = [r'不得', r'禁止', r'必须', r'应当']
    # 只要匹配到高/中风险模式就标记
```

这种正则匹配无法区分"正确引用了赔付金额"和"给出了错误的赔付金额"。文章强调"涉及赔付金额的 badcase 需要高级工程师或产品人工复核"——风险应基于"是否给出了错误信息"，而非"是否提到了金额"。

**建议修复**: 合规风险应结合分类结果（hallucination + 涉及金额 = 高风险），而非仅基于关键词。

---

## 四、幻觉预防机制评估

### 4.1 Prompt 层面的幻觉约束

**实现位置**: `scripts/lib/rag_engine/rag_engine.py:32-54`

**当前 QA Prompt 的忠实度约束**:

```python
_QA_PROMPT_TEMPLATE = """你是一位保险法规专家。请**仅依据**下方编号的法规条款回答用户问题。
如果条款中没有足够信息，请坦诚说明"提供的法规条款中未找到相关信息"，不要自行补充外部知识。

## 回答要求
1. **仅依据**上方编号的法规条款回答，不使用条款外的知识
4. 每个事实性陈述（数字、条款规定、法律要求）必须在句末用 [来源X] 标注来源编号
5. 不得包含法规条款中不存在的信息（包括但不限于条款号、数字、日期）
6. 如果法规条款不足以回答问题，明确说明"以上法规条款未涉及此问题"，不要猜测
"""
```

**评估**:

| 文章建议 | 当前实现 | 评估 |
|---------|---------|------|
| "只能使用以下文档中的信息" | ✅ "仅依据"强调两次 | 强 |
| "不得引用文档以外的任何知识" | ✅ "不使用条款外的知识" | 强 |
| "如果文档中没有明确说明，必须回答不知道" | ✅ 两条 fallback 短语 | 强 |
| "加上引用校验，附上原文出处" | ✅ [来源X] 标注要求 | 强 |
| 引用示例 | ✅ 包含回答示例 | 好 |

**优势**: Prompt 忠实度约束设计得相当完善，多层次的"仅依据"强调、明确的引用格式、两条"不知道"fallback 指令、回答示例——基本符合文章的所有建议。

### 4.2 后处理层面的幻觉检测

**实现位置**: `scripts/lib/rag_engine/attribution.py`

**当前实现**:

1. **引用解析** (`parse_citations`, lines 52-84): 提取 `[来源X]` 标注，建立引用映射
2. **未验证声明检测** (`_detect_unverified_claims`, lines 87-128): 正则匹配事实性陈述（数字、日期、法律术语），检查是否跟随引用标注

```python
# attribution.py:16-31
_FACTUAL_PATTERNS = [
    r'\d+天', r'\d+年', r'\d+个月',       # 时间
    r'\d+%$',                             # 百分比
    r'\d+元', r'\d+万元',                 # 金额
    r'\d+周岁',                           # 年龄
    r'第[一二三四五六七八九十百千\d]+条',  # 条款号
    r'《[^》]+》',                        # 法规名
    r'(必须|应当|不得|禁止|严禁)',         # 法律义务
    r'(有权|无权|免除|承担)',             # 权利
]
```

#### 问题 4.2.1: 引用校验仅检查格式，不验证内容

- **文件**: `scripts/lib/rag_engine/attribution.py:52-84`
- **类型**: 🔴 设计缺陷
- **严重程度**: P1

**问题描述**: 当前系统只检查"事实性陈述后是否跟随 [来源X]"（格式校验），但不验证"来源 X 的内容是否真的支持该陈述"（内容校验）。

**具体案例**:
- 条款原文: "身故保险金为基本保额的 200%"
- LLM 回答: "身故保险金为基本保额的 150% [来源1]"
- 系统判定: ✅ 已引用（格式正确）
- 实际情况: ❌ 幻觉（数字错误，但引用了正确的来源）

**对比文章**: 文章强调"引用校验，让 LLM 在回答里附上原文出处，方便后续核对"——关键在于"核对"，而不仅仅是"标注"。

**建议修复**: 添加引用内容验证步骤，对比 LLM 引用的具体数值/条款与原始检索文档中的内容是否一致。

#### 问题 4.2.2: 检索结果截断可能丢失关键信息

- **文件**: `scripts/lib/rag_engine/rag_engine.py:283-306`
- **类型**: ⚠️ 质量
- **严重程度**: P2

**问题描述**:

```python
# rag_engine.py:296-300
if total_chars + len(full_part) > max_chars:
    remaining = max_chars - total_chars - 50
    if remaining > 100:
        truncated_content = content[:remaining] + '……'
        context_parts.append(header + truncated_content)
    break
```

当上下文超过 12000 字符限制时，后面的条款被截断。截断位置是纯字符数，不尊重语义边界。如果关键数字或条款细节恰好在截断点附近，LLM 可能因信息不完整而生成错误回答。

**建议修复**: 按句子或条款边界截断，而非纯字符数。

### 4.3 Reranker 对幻觉的影响

**实现位置**: `scripts/lib/rag_engine/reranker.py`（`LLMReranker`）

#### 问题 4.3.1: LLM Reranker 截断 800 字符可能丢失精排依据

- **文件**: `scripts/lib/rag_engine/reranker.py:75-83`
- **类型**: ⚠️ 质量
- **严重程度**: P2

```python
truncated = content[:800] if len(content) > 800 else content
```

精排时将每个候选条款截断到 800 字符。如果条款的关键信息（如赔付比例、免赔额）在后半部分，精排器无法正确评估相关性，可能导致真正相关的条款被排在后面，最终进入 LLM 上下文的检索结果质量下降。

---

## 五、检索质量评估

### 5.1 检索管线架构

```
用户查询
    ↓
QueryPreprocessor.preprocess()
    ├── _normalize()           # 同义词归一化
    ├── _rewrite_with_llm()    # LLM 重写（>8字符触发）
    └── _expand()              # 同义词扩展（最多3个变体）
    ↓
hybrid_search()
    ├── 并行: vector_search (LanceDB/Jina) + bm25_search (jieba)
    └── 扩展查询并行检索
    ↓
reciprocal_rank_fusion()  # k=60, 向量权重=1.0, 关键词权重=1.0
    ├── 去重: 按 (law_name, article_number)
    └── 限流: 每条款最多 3 个 chunk
    ↓
LLMReranker.rerank()  # 截取 top 20, LLM 排序, 返回 top 5
```

### 5.2 检索管线中的潜在问题

#### 问题 5.2.1: Query 预处理中 LLM 重写使用原始 query 而非归一化结果

- **文件**: `scripts/lib/rag_engine/query_preprocessor.py:62-82`
- **类型**: ⚠️ 质量
- **严重程度**: P2

```python
# query_preprocessor.py:62-70
def preprocess(self, query: str) -> PreprocessedQuery:
    normalized = self._normalize(query)          # 步骤1：归一化（"理赔"→"保险赔付"）
    rewritten = self._rewrite_with_llm(query)     # 步骤2：LLM重写（传入原始"理赔"！）
    if rewritten and rewritten != normalized:
        normalized = rewritten                    # 步骤3：覆盖归一化结果
```

`_rewrite_with_llm(query)` 传入的是原始 query 而非归一化后的结果。如果归一化步骤将口语"理赔"替换为标准术语"保险赔付"，但 LLM 重写用的是原始的"理赔"，那么重写结果可能仍然包含口语化表达，归一化的效果被完全覆盖。

**建议修复**: `self._rewrite_with_llm(normalized)` 传入归一化后的 query。

#### 问题 5.2.2: 无检索相关性阈值过滤

- **文件**: `scripts/lib/rag_engine/retrieval.py:57-112`
- **类型**: 🏗️ 设计
- **严重程度**: P2

**问题描述**: 检索管线返回 top_k 结果后直接进入 RRF 融合和精排，没有任何相关性阈值过滤。即使用户的问题与知识库完全不相关（如"今天天气如何"），系统仍然会返回 5 个"最相关"的法规条款并生成回答，而非触发"知识缺失"fallback。

**影响**: 文章指出第四类 badcase（知识缺失型）占 15%。当前系统缺少检索相关性阈值，可能导致对不相关问题也强行生成低质量回答。

**建议修复**: 在 RRF 融合后、精排前，添加分数阈值过滤。如果最高 RRF 分数低于阈值（如 0.01），直接返回"未找到相关法规条款"。

#### 问题 5.2.3: RRF 融合后无相关性分数校验

- **文件**: `scripts/lib/rag_engine/fusion.py:24-79`
- **类型**: 🏗️ 设计
- **严重程度**: P2

**问题描述**: RRF 分数的绝对值含义不明确（取决于 k 值和结果数量），但当前代码不做任何分数校验就传递给精排器。没有机制检测"所有结果分数都很低，说明没有真正相关的文档"。

---

## 六、回归测试能力评估

### 6.1 当前评估框架

**实现位置**: `scripts/lib/rag_engine/evaluator.py` + `scripts/evaluate_rag.py`

**已有能力**:

| 能力 | 实现状态 | 位置 |
|------|---------|------|
| 检索评估 (P@K, R@K, MRR, NDCG) | ✅ | evaluator.py:262-383 |
| 生成评估 (faithfulness, relevancy) | ✅ | evaluator.py:386-643 |
| RAGAS 集成（可选） | ✅ | evaluator.py:433-452 |
| 评估报告生成 | ✅ | evaluate_rag.py |
| 报告对比 | ✅ | evaluate_rag.py:140-209 |
| 评估数据集管理 | ✅ | eval_dataset.py (30 samples) |
| Badcase 转评估样本 | ✅ | feedback.py:188-226 |

### 6.2 回归测试的关键缺陷

#### 问题 6.2.1: 无自动化回归测试流程

- **类型**: 🏗️ 设计
- **严重程度**: P1

**问题描述**: 文章强调"每次修复，除了在原 badcase 上验证之外，还必须在全量测试集上跑一遍回归"。当前系统有评估框架，但：
- 无 CI/CD 集成
- 无定时自动运行
- 需要手动执行 `python evaluate_rag.py`
- 无基线管理（无"golden baseline"概念）

```python
# evaluate_rag.py 中的回归对比是手动的
def compare_reports(old_report: Dict, new_report: Dict) -> str:
    # 需要手动传入两个报告文件路径
```

#### 问题 6.2.2: 缺少趋势追踪和退化检测

- **类型**: 🏗️ 设计
- **严重程度**: P1

**问题描述**: 文章强调"`find_regressions` 函数不只输出总体分数，还要定位到具体哪些 case 发生了退化——原来能答对，现在答错了的"。

当前评估结果存储在数据库中（`eval_runs` + `eval_sample_results` 表），但：
- 无趋势可视化
- 无自动退化告警
- 无法按时间维度对比指标变化
- 无法定位具体退化的 case

#### 问题 6.2.3: 评估数据集过小

- **文件**: `scripts/lib/rag_engine/eval_dataset.py:90-396`
- **类型**: ⚠️ 质量
- **严重程度**: P2

**问题描述**: 默认评估数据集仅 30 个样本。文章提到"测试集从最初的 200 条扩充到了 350 条，其中 150 条直接来自真实 badcase"。

30 个样本的统计置信度极低：
- 单个样本的通过/失败变化会导致指标波动 >3%
- 无法按问题类型做有意义的子组分析
- 文章建议的 2% 容差在 30 样本下无统计意义

**对比文章**: 文章中初始测试集 200 条，6 个月后扩充到 350 条。当前 30 条仅为文章建议的 1/7 到 1/10。

**建议修复**: 优先将已收集的 badcase 转为评估样本（当前已有 `POST /badcases/{id}/convert` 端点），系统性扩充数据集。

#### 问题 6.2.4: 缺少文章建议的三个核心回归指标

- **类型**: 🏗️ 设计
- **严重程度**: P2

| 文章建议指标 | 当前实现 | 状态 |
|-------------|---------|------|
| recall@5 | ✅ `Recall@K` | 有 |
| faithfulness | ⚠️ 轻量级 bigram 方法 | 弱（非 LLM 评判） |
| answer_accuracy | ✅ correctness via RAGAS | 有（依赖 RAGAS） |

faithfulness 的轻量级实现（bigram 重叠 + 句子覆盖率）与文章建议的"用轻量级 LLM 评判模型判断答案是否能在检索文档里找到依据"差距较大。

---

## 七、知识库老化检测

**状态**: ❌ 完全缺失

**文章指出**: "保险产品会更新，条款会修订，但如果没有机制持续检测，系统给出的还是旧版本的信息，用户拿到的是过期答案。"

**当前系统**: `KBVersionManager` 支持知识库版本管理（v1, v2, ...），可以构建新版本并切换，但：
- 无自动检测知识库是否过期的机制
- 无外部法规变更监控
- 无定期重建知识库的触发条件
- 版本切换完全手动

**评估**: 在精算审核场景中，法规更新频率相对可控（季度/年度），但仍然需要建立知识库更新检查机制。建议至少添加"上次更新时间"的监控告警。

---

## 八、数据库与数据流评估

### 8.1 反馈数据流完整性

```
用户提问 → ask.py → RAG 引擎检索+生成
    ↓
回答存储到 messages 表（含 sources_json, citations_json, faithfulness_score）
    ↓
自动质量检测（ask.py:86-108）
    ├── quality >= 0.4 → 正常返回
    └── quality < 0.4 → 创建 feedback（source_channel="auto_detect"）
    ↓
用户反馈 → feedback.py:submit → 创建 feedback（source_channel="user_button"）
    ↓
feedback 表存储（含 message_id, conversation_id 外键）
    ↓
手动触发 /badcases/classify → classify_badcase() + detect_quality() + assess_compliance_risk()
    ↓
更新 feedback（classified_type, status="classified"）
    ↓
手动触发 /badcases/{id}/verify → 重跑原问题 → 对比
    ↓
手动触发 /badcases/{id}/convert → 转为评估样本
```

### 8.2 数据流中的问题

#### 问题 8.2.1: 无反馈闭环自动化

- **类型**: 🏗️ 设计
- **严重程度**: P1

**问题描述**: 整个流程从"收集"到"转换"都需要手动触发。文章的六步闭环中，只有第一步（收集）是自动的，后续五步全部手动。

**影响**: 在实际运营中，手动流程很难持续执行。文章的实战数据显示，建立自动化闭环后 6 个月将准确率从 76% 提升到 89%。如果每个环节都需要人工介入，这个提升无法实现。

---

## 九、问题汇总与优先级

### 9.1 按严重性排序

| 优先级 | 问题 | 类型 | 影响 |
|--------|------|------|------|
| **P1** | 忠实度评分默认禁用，自动检测失效 | 🔴 设计 | 自动收集渠道形同虚设 |
| **P1** | 幻觉检测依赖启发式，非 LLM 判断 | ⚠️ 质量 | badcase 分类准确率低 |
| **P1** | 引用校验仅检查格式不验证内容 | 🔴 设计 | 无法检测数值类幻觉 |
| **P1** | 无自动化回归测试流程 | 🏗️ 设计 | 修复后无法防止退化 |
| **P1** | 无趋势追踪和退化检测 | 🏗️ 设计 | 指标退化不可见 |
| **P1** | 反馈闭环无自动化 | 🏗️ 设计 | 运营闭环断裂 |
| **P2** | 检索相关性仅用 bigram 重叠 | ⚠️ 质量 | 自动检测误报率高 |
| **P2** | 信息完整性仅覆盖数值型回答 | ⚠️ 质量 | 定性问题漏检 |
| **P2** | 分类需手动触发 | ⚠️ 质量 | 延迟发现和修复 |
| **P2** | 合规风险评估过于简单 | ⚠️ 质量 | 高风险 case 可能被低估 |
| **P2** | 检索结果截断不尊重语义边界 | ⚠️ 质量 | 可能丢失关键信息 |
| **P2** | Reranker 截断 800 字符 | ⚠️ 质量 | 精排质量下降 |
| **P2** | 无检索相关性阈值过滤 | 🏗️ 设计 | 对无关问题强行回答 |
| **P2** | 评估数据集过小（30条） | ⚠️ 质量 | 回归测试无统计意义 |
| **P2** | Query LLM 重写使用原始 query | ⚠️ 质量 | 归一化效果被覆盖 |
| **P3** | 反馈不区分"答案错误"和"用户不满意" | ⚠️ 质量 | 误踩过滤困难 |
| **P3** | 缺少路由错误分类 | 🏗️ 设计 | 当前无路由层，暂不需要 |
| **P3** | 知识库老化检测缺失 | 🏗️ 设计 | 过期信息风险 |

### 9.2 按文章运营环节分组

| 运营环节 | 关键问题数 | 状态 |
|---------|-----------|------|
| 收集 | 3 (P1×1, P2×2) | ⚠️ 骨架在，检测弱 |
| 分类 | 3 (P1×1, P2×2) | ⚠️ 有分类，不准且手动 |
| 验证 | 1 (P1×1) | ❌ 缺自动化 |
| 回归测试 | 2 (P1×2) | ❌ 框架在，缺自动化和趋势 |
| 灰度发布 | 0 | ❌ 无 |
| 知识库维护 | 1 (P3×1) | ❌ 无 |

---

## 十、改进路线图

### 阶段一：修复核心缺陷（P1）

**目标**: 让自动收集和分类真正可用

1. **修复自动质量检测**（`quality_detector.py`）
   - 当 faithful 不可用时动态调整权重
   - 或默认启用 `enable_faithfulness`

2. **升级幻觉检测**（`badcase_classifier.py`）
   - 引入 LLM 辅助分类，保留启发式作为快速预筛
   - 添加引用内容验证（数值比对）

3. **建立自动化回归测试**（`evaluate_rag.py`）
   - 添加定时任务自动运行评估
   - 实现基线管理和退化告警
   - 添加趋势数据存储和查询

### 阶段二：强化检测能力（P2）

**目标**: 提升检测准确率和覆盖面

4. **升级检索相关性检测**（`quality_detector.py`）
   - 用 embedding cosine similarity 替代 bigram 重叠
   - 复用已有 Jina embedding 模型

5. **完善信息完整性检测**
   - 添加定性问题完整性检查
   - 检测多部分问题的覆盖情况

6. **自动化分类流程**
   - 添加定时任务自动执行分类
   - 添加分类置信度

7. **优化检索管线**
   - 添加检索相关性阈值过滤
   - 修复 Query 预处理的归一化覆盖问题
   - 改进截断策略（语义边界）

### 阶段三：形成闭环（中长期）

**目标**: 建立可持续运营的质量保障体系

8. **扩充评估数据集**
   - 系统性将 badcase 转为评估样本
   - 目标: 200+ 样本

9. **添加知识库老化检测**
   - 监控知识库版本年龄
   - 添加更新提醒

10. **反馈闭环自动化**
    - 分类 → 分配 → 验证 → 回归 → 告警 全流程自动化
    - 添加统计面板

---

## 十一、系统现有优势

在指出问题的同时，需要肯定系统已有的良好设计：

1. **Prompt 忠实度约束设计优秀**: 多层次的"仅依据"强调、引用标注要求、"不知道"fallback 指令——基本达到文章建议水平
2. **数据可追溯性完整**: 每条回答完整关联检索结果、引用、质量分数，可追溯全链路
3. **反馈数据库设计完善**: feedback 表结构完整，包含分类字段、工作流状态、合规风险等级
4. **评估框架全面**: P@K、R@K、MRR、NDCG、冗余率等标准指标齐全
5. **Badcase 工作流设计合理**: pending → classified → fixing → fixed/rejected/converted 状态流转清晰
6. **混合检索架构标准**: 向量 + BM25 + RRF 融合是业界标准实践
7. **优雅降级**: BM25 不可用时回退到纯向量检索、精排解析失败时回退到原始顺序

---

## 十二、总结

Actuary Sleuth 的 RAG 系统在架构层面已经建立了质量保障的骨架——混合检索、Prompt 约束、引用标注、反馈收集、自动分类、评估框架一应俱全。但在运营层面，系统尚未形成文章所描述的有效闭环：

**最关键的三个断裂点**:

1. **自动检测失效**: 忠实度默认禁用 + bigram 检测弱 → 自动收集渠道形同虚设
2. **分类不准**: 启发式规则无法可靠区分检索失败、幻觉和知识缺失
3. **无自动化**: 收集后的分类、验证、回归全部需要手动触发

**核心改进方向**: 文章的核心洞察是"开发 RAG 系统是一道题，运营 RAG 系统才是真正的考卷"。当前系统已经完成了"开发"部分的绝大部分工作，但"运营"部分——自动化、持续性、闭环反馈——是接下来需要重点建设的方向。建议按 P1 → P2 → P3 的优先级逐步修复，优先让已有的质量保障机制真正运转起来。

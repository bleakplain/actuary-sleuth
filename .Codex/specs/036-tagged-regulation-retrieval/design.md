# 产品标签驱动的法规适用性匹配与分层检索

## 1. 目标

把已经验收的产品标签与法规标签接入审核检索流程，使系统先判断法规是否适用于产品，再根据当前产品条款的主题缩小候选范围，最后在安全候选集中执行 BM25、向量召回和融合。

本次改动不重写确定性规则引擎，也不在索引层实施不可逆的硬过滤。第一版以“明确冲突才排除、信息不足则保守保留”为安全原则，优先降低 LLM 上下文长度，同时避免漏查。

## 2. 总体链路

```text
产品名称 + 完整解析内容
        ↓
ProductTags（值 + 证据 + unknown）
        ↓
法规 chunk 元数据 → RegulationApplicability
        ↓
三态适用性匹配
  applicable / not_applicable / indeterminate
        ↓
按当前条款主题分层
  精确主题 → 同族主题 → 无主题 → 信息不足
        ↓
BM25 + 向量召回 → RRF
        ↓
法规结果 + 匹配状态 + 匹配标签 + 回退轨迹
```

## 3. 第一性原理

### 3.1 产品标签与法规标签含义不同

- 产品标签描述一个具体产品的事实；产品侧互斥维度必须是单值，例如长期/短期、个人/团体、主险/附加险。
- 法规标签描述适用范围；法规侧同一维度可以有多个允许值，空值表示该维度没有限制。
- 产品标签 unknown 表示证据不足，不能当成 False。
- 法规维度为空表示通用适用，不能当成元数据缺失错误。

### 3.2 只有明确冲突才能排除

法规过滤的错误成本不对称：

- 错误保留一条法规：增加少量检索和 LLM 成本。
- 错误排除一条法规：可能直接造成漏检。

因此匹配器必须返回三态，而不是布尔值：

| 情况 | 状态 | 检索行为 |
|---|---|---|
| 所有限定维度均匹配 | applicable | 优先候选 |
| 任一限定维度明确冲突 | not_applicable | 排除 |
| 无冲突但产品存在未知值 | indeterminate | 保守候选 |

### 3.3 条款主题不是产品适用条件

产品标签回答“法规是否适用于该产品”；条款主题回答“当前审核哪个 section 时应优先取这条法规”。两者必须顺序执行，不能用 Excel 的条款栏目名称反向推断监管结论。

例如短期健康险规则的 Excel 栏目为“保证续保”，但正文要求写明“不保证续保”。该法规的产品适用条件是 `health + short_term`，条款主题应包含 `renewal.non_guaranteed`，而不是仅依据栏目名称标记 `renewal.guaranteed`。

### 3.4 合规要求不能充当前置过滤条件

法规条件分为主体范围、风险触发事实和合规要求。主体范围回答“法规规范谁”，风险触发事实回答“产品是否出现法规关注的设计”，合规要求回答“该设计必须满足什么”。

法规要求“费率可调产品仅限长期医疗保险”时，`rate_adjustable` 是触发事实，`long_term` 是待审核要求；短期费率可调医疗险必须被保留并形成违规候选，不能因 `term_class=short_term` 提前排除。同理，任何产品出现保证续保事实时，都应进入保证续保相关检查，不能先假设只有正确分类的健康险才可能出现该设计。

风险触发标签只用于阻止错误排除，不直接形成合规结论。触发命中时，即使常规主体标签冲突也保守保留；触发未知时返回 `indeterminate`；只有触发明确不满足且主体范围明确冲突时才允许排除。

## 4. 数据模型

### 4.1 法规适用性

从 chunk metadata 的 `适用标签` 解析出受控值，并保留条款主题：

```python
@dataclass(frozen=True)
class RegulationApplicability:
    lines: frozenset[str]
    subtypes: frozenset[str]
    design_types: frozenset[str]
    term_classes: frozenset[str]
    customer_scopes: frozenset[str]
    contract_roles: frozenset[str]
    special_features: frozenset[str]
    risk_triggers: frozenset[str]
    clause_topics: frozenset[str]
```

同一标签只能归入一个维度；无法识别的标签记录为 warning，不参与排除。

### 4.2 匹配结果

```python
class MatchStatus(str, Enum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class ApplicabilityResult:
    status: MatchStatus
    matched_dimensions: tuple[str, ...]
    indeterminate_dimensions: tuple[str, ...]
    excluded_by: tuple[str, ...]
    reasons: tuple[str, ...]
```

匹配结果必须可解释，以便测试、日志和审核报告追溯。

## 5. 逐维度匹配规则

同一维度多个法规值使用 OR，不同维度使用 AND：

| 法规值 | 产品值 | 维度结果 |
|---|---|---|
| 空 | 任意 | 匹配（该维度通用） |
| `{health}` | `health` | 匹配 |
| `{health, accident}` | `health` | 匹配 |
| `{health}` | `life` | 冲突 |
| `{health}` | `unknown` | 信息不足 |
| `{internet_exclusive}` | `True` | 匹配 |
| `{internet_exclusive}` | `False` | 冲突 |
| `{internet_exclusive}` | `None` | 信息不足 |

最终结果计算顺序：

1. 存在任何冲突，返回 `not_applicable`。
2. 没有冲突但存在信息不足，返回 `indeterminate`。
3. 其他情况返回 `applicable`。

## 6. 分层检索策略

### 6.1 第一版采用检索后过滤

当前 v5 有 174 个 chunk，第一版先让 BM25 和向量各自扩大召回，再对融合候选执行确定性适用性和主题分层。这样不需要改变 LanceDB 查询表达式，也不会因标签缺失在召回前永久丢失法规。

合规候选检索刻意不调用外部 LLM 做 query rewrite 或 rerank：产品标签和法规元数据已经提供了确定性的缩小范围依据，外部模型不可用时也不应阻断法规召回。后续法规内容审核本身仍可使用 LLM。

### 6.2 候选层级

候选按以下顺序补足 `top_k`：

1. 产品明确适用且精确命中当前条款主题。
2. 产品明确适用且命中同族通用主题，如 `renewal.general`。
3. 产品明确适用但法规没有主题标签。
4. 产品适用性为 `indeterminate`，主题命中。
5. 产品适用性为 `indeterminate`，无主题。
6. 候选不足时保留适用性信息不足的候选作为安全回退。

明确 `not_applicable` 的法规在所有层级中排除，任何回退路径都不得恢复。

### 6.3 主题族

主题使用首个点之前或配置的受控前缀形成主题族，例如：

- `renewal.non_guaranteed` 与 `renewal.general` 属于 `renewal` 族。
- `claim.application` 与 `claim.payment` 属于 `claim` 族，但只有显式 general 主题才作为同族回退，避免所有理赔规则互相污染。

## 7. 接口设计

内部检索入口：

```python
def retrieve_audit_regulations(
    query: str,
    category: str | None,
    product_tags: ProductTags,
    clause_topics: tuple[str, ...],
    top_k: int = 12,
) -> list[AuditRegulationItem]:
    ...
```

内部分层器返回：

```python
@dataclass(frozen=True)
class LayeredRetrievalResult:
    chunks: tuple[RetrievedRegulation, ...]
    candidate_count: int
    excluded_count: int
    fallback_used: bool
    trace: tuple[RetrievalTrace, ...]
```

每个法规结果应附带：

- `applicability_status`
- `matched_dimensions`
- `matched_topics`
- `retrieval_sources`
- `fallback_layer`

外部审核接口第一版保持兼容：不提供产品标签时继续使用原检索路径；提供产品名称和解析结果时生成产品标签并启用新路径。

## 8. 模块边界

- `lib/compliance/applicability.py`
  - 法规元数据解析。
  - 三态适用性判断。
  - 不依赖 LLM 和数据库。
- `lib/rag_engine/layered_retrieval.py`
  - 对已融合候选进行主题和适用性分层。
  - 不定义保险业务标签含义。
- `lib/compliance/checker.py`
  - 组织产品标签、法规加载和审核调用。
  - 对外保持简单接口。
- `lib/rag_engine/rag_engine.py`
  - 提供不依赖外部 LLM 的 BM25、向量召回和 RRF 候选入口。

## 9. 可观测性

每次分层检索记录：

- 原始候选数。
- applicable、indeterminate、not_applicable 数量。
- 每层选入数量。
- 被排除法规及冲突维度。
- 是否触发安全回退。
- 最终法规的召回来源与匹配理由。

这些信息进入 trace，不默认塞入 LLM prompt。

## 10. 测试与验收

### 10.1 单元测试

- 法规空维度通用适用。
- 同维度多值 OR。
- 不同维度 AND。
- 产品 unknown 返回 indeterminate。
- 特殊布尔标签的 True、False、None。
- 明确冲突优先于其他维度的信息不足。
- 未识别法规标签不造成误排除。

### 10.2 分层测试

- 精确主题优先。
- `*.general` 作为同族回退。
- 无主题法规保留。
- indeterminate 晚于 applicable。
- not_applicable 永不返回。
- 候选不足时安全回退，但仍不恢复明确不适用法规。
- BM25 与向量重复结果只保留一次。

### 10.3 真实产品回归

- 失能收入损失保险稳定识别为健康险。
- 短期不保证续保医疗险召回对应规则。
- 长期保证续保医疗险排除仅适用于短期险的规则。
- 附加团体产品排除仅适用于个人主险的法规。
- 产品期限未知时不误排长期或短期法规。

### 10.4 验收门槛

- 明确不适用法规排除准确率 100%。
- 产品标签未知时因标签导致的漏召回为 0。
- 核心样例 Recall@10 为 100%。
- 每条返回法规均具有匹配或回退理由。
- 新链路失败时可回退旧检索，不影响审核可用性。

## 11. 发布策略

1. 先实现纯函数匹配器及固定候选集测试。
2. 接入 RAG 融合结果后的分层排序，不做索引级硬过滤。
3. 审核入口统一启用新链路；产品标签未知时按 `indeterminate` 保守保留，RAG 引擎不可用时走旧路径。
4. 对真实产品运行新旧检索对照，记录召回差异。
5. 验收通过后再考虑索引前 metadata filter 和规则引擎统一标签化。

## 12. 本次落地记录

- 新增纯业务模块 `lib/compliance/applicability.py`，负责法规元数据解析和三态适用性判断。
- 新增 `lib/rag_engine/layered_retrieval.py`，负责候选去重、主题分层、稳定排序和检索轨迹。
- RAG 引擎新增不依赖外部 LLM 的基础候选接口，保留 BM25、向量召回与 RRF。
- 审核入口使用产品名称和完整条款内容生成 `ProductTags`，再把产品标签、法规标签和条款主题交给分层检索。
- 文档解析 API 返回每个条款的主题；前端审核请求提交主险和附加险条款主题的并集。
- 法规结果携带适用性状态、命中维度、命中主题、回退层和召回来源，并随报告保存。
- Excel 转换的条款主题同时依据“条款主体”和法规正文判断；短期健康险“不保证续保”规则已修正为
  `renewal.general,renewal.non_guaranteed`。
- 产品期限解析同时支持阿拉伯数字和常见中文整数，例如 `1年`、`一年`、`二十年`。

当前审核器仍以整份产品条款为一次审核单元，因此第一版使用所有已解析条款主题的并集做法规候选分层；
若后续把审核改为逐 section 调用，可直接传单个 section 的主题，不需要改动适用性匹配器。

## 13. Review 后修正

- 移除 `lib.compliance` 包入口对 `checker` 的重导出，消除
  `compliance.__init__ → checker → layered_retrieval → compliance.applicability`
  的循环导入；调用方从具体模块导入。
- 分层去重优先使用全局 `id/chunk_id`；缺少全局 ID 时使用
  `source_file + metadata.chunk_id`，最后才使用内容摘要，允许同一法规条款保留多个正文 chunk。
- `fallback_used` 仅表示最终结果纳入了 `indeterminate` 候选；
  applicable 法规的 `topic_mismatch_fallback` 不再触发安全回退告警。
- 同一适用性/主题层内显式按 RRF `score` 降序，分数相同才保持输入顺序；
  未进入语义召回的注册法规没有分数，因此继续排在有相关性证据的候选之后。
- v5 标准适用性维度实际覆盖 line、subtype、design_type、term_class、contract_role；
  customer_scope 尚无数据，contract_role 仅 4 条，属于后续标签补录工作。
- 整篇扫描的主题并集是当前整篇审核模型的有意边界，逐 section 审核时必须改传单 section 主题。
- “不保证续保”优先于字面“保证续保”是有意的否定语义处理；不能因同一文本包含后者子串就同时标为
  `renewal.guaranteed`，否则会把“不得承诺保证续保”等否定表述误标为正向保证续保。

## 14. 注册表与降级链路修正

- 注册法规表以用户主动保留的 v5 为准，移除所有已从 v5 删除的法规名称；不通过模糊匹配掩盖数据不同步。
- 保监发〔2015〕90号既然被认定为不属于产品条款审核范围，其两条确定性规则也同步移除，避免知识库与规则引擎口径冲突。
- v5 实测注册法规去重后共 20 部，所有名称均可通过 `law_name` 精确命中，缺失数为 0。
- 常规险种识别失败时，先从 ProductTags 恢复医疗险、重疾险、健康险、寿险、年金险、分红险或意外险分类；
  产品大类仍未知时，保守加载全部险种注册法规，再由三态适用性匹配筛选。
- 医疗险、重疾险同时继承健康险注册法规，年金险、分红险同时继承寿险注册法规，避免子类分类缩小后丢失上位法规。
- 注册候选不再按法规名和条款号提前去重；注册层与分层检索统一使用 chunk 身份，保留同条款的多个 chunk。
- `retrieval_sources` 合并 BM25、vector、`registered:category`、`registered:general` 多来源，
  `source_type` 继续表示报告中的主要归类。
- RAG 引擎未初始化时无法凭空恢复法规正文，因此仍返回空法规候选，但 API 会通过 SSE 进度、
  报告字段 `retrieval_degraded` 和 `retrieval_warnings` 明确告知用户；确定性规则与负面清单仍继续执行。

## 15. 数据正确性与可观测性补强

- 检索核心新增 `RegulationRetrievalOutcome`，同时返回法规候选、降级状态和告警。
  RAG 引擎未初始化、语义检索异常、知识库无候选不再只写服务端日志；API、SSE 和持久化报告均可向前端透传。
- 语义检索失败时继续使用注册法规候选做标签分层，`retrieval_degraded=true`；
  这与“确实没有适用法规”形成可观察的状态差异。
- `MdParser` 的 chunk overlap 只允许发生在同一个 `section_path` 内。
  不同“第 N 条检核规则”之间不再把上一条正文前置到下一条，v5 已从 2026 Excel 重新转换并原位重建。
- Excel 标签增加显式语义：
  `适用标签语义=限定` 作为排除条件；`标签语义=涉及` 转为 `涉及标签`，只表达主题关联，不参与适用性排除。
  为兼容旧数据，未填写语义但已有 `适用标签` 的记录按已验收口径继续视为“限定”。
- 检索 query 除产品名称和条款正文外，加入产品标签对应的上位险种、主要责任和期限中文词。
  例如失能收入损失保险会补入“健康保险、失能收入损失保险”，降低专业产品名称缺少上位分类词导致的弱召回。
- 失能险并非没有任何直接规则：v5 实测可召回保监人身险〔2017〕134号的失能给付条件规则，
  以及 2026 负面清单的失能险责任设计规则；《健康保险管理办法》本身没有出现“失能”字样，
  不能据此推导整个知识库对失能险覆盖为零。
- 补充 subtype 明确冲突回归测试：产品为 `medical`、法规限定 `nursing` 时必须判定
  `not_applicable`，防止同维度 OR / 跨维度 AND 逻辑未来回归。

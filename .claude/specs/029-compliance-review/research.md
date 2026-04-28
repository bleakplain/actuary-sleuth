# 合规审核模块系统化 Review - 技术调研报告

生成时间: 2026-04-28
源规格: .claude/specs/029-compliance-review/spec.md

## 执行摘要

合规审核核心链路经 023 重构后架构清晰，checker.py 抽取了 4 个公开函数，职责明确。但存在 3 类系统性问题：(1) **降级缺陷** — RAG 引擎未初始化时 `check_negative_list` 静默返回空列表，而路由硬编码 `negative_list_checked=True`，用户误以为已检查；(2) **类型不一致** — `ProductCategory` 枚举（"人寿保险"）与 `VALID_CATEGORIES`（"寿险"）命名割裂，险种识别走关键词路径时 value 不匹配 registry key；(3) **测试断裂** — `test_clause_level.py` 引用已删除函数，`run_compliance_check` 的 5 层 JSON fallback 无任何测试。建议优先修复降级和类型不一致问题，再补齐测试。

---

## 一、现有代码分析

### 1.1 相关模块梳理

| 需求 | 对应模块 | 现状 |
|------|---------|------|
| FR-001 (RAG 降级) | `checker.py:_load_negative_list`, `checker.py:build_enhanced_context` | `_load_negative_list` 有降级返回 `[]`，但路由不感知降级状态 |
| FR-002 (LLM 非 JSON) | `checker.py:run_compliance_check` | 有 5 层 fallback 解析，最终返回带 `error` 的结果 |
| FR-003 (枚举一致性) | `product_types.py:ProductCategory`, `constants.py:VALID_CATEGORIES` | **不一致** — 枚举用全称"人寿保险"，VALID_CATEGORIES 用简称"寿险" |
| FR-004 (source_excerpt) | `checker.py:_check_violation` | `source_excerpt` 取 `negative_rule[:300]`，是规则摘要非文档原文 |
| FR-005 (截断不切断) | `routers/compliance.py:42-44` | `context[:8000]` 简单字符截断，可能切在条款中间 |
| FR-006 (测试引用修复) | `tests/compliance/test_clause_level.py` | 引用已删除的 `_detect_missing_clauses`, `_run_compliance_check` |
| FR-007 (测试覆盖) | `tests/compliance/` | 仅有 `test_negative_list.py` 覆盖 checker 公开函数，其他缺测试 |
| FR-008 (API 契约) | `schemas/compliance.py`, `web/src/types/index.ts` | 当前一致，但 `result: Dict[str,object]` 无类型约束 |
| FR-009 (result 类型约束) | `schemas/compliance.py:ComplianceReportOut` | `result: Dict[str, object]` 无结构约束 |
| FR-010 (识别失败标识) | `routers/compliance.py:35-37` | category=None 时静默传给 `build_enhanced_context`，无标识 |
| FR-011 (批量并行) | `checker.py:check_negative_list` | 串行逐条调用 LLM，规则多时慢 |

### 1.2 可复用组件

- `regulation_registry.py`: 法规映射集中管理，`get_category_regulations` / `get_general_regulations` 接口稳定
- `product_types.py:classify_product`: 关键词分类器可复用，但返回值需与 `VALID_CATEGORIES` 对齐
- `rag_engine.get_engine`: 单例模式，返回 `Optional[RAGEngine]`，降级路径已有但调用方未充分利用
- `llm.get_qa_llm`: 工厂方法，返回 `BaseLLMClient`，接口统一

### 1.3 需要新增/修改的模块

| 模块 | 操作 | 说明 |
|------|------|------|
| `checker.py` | 修改 | 返回降级状态信息，修复 `negative_list_checked` 语义 |
| `routers/compliance.py` | 修改 | 根据 checker 返回的降级状态设置 `negative_list_checked`，增加截断逻辑 |
| `product_types.py` | 修改 | `ProductCategory` 枚举值对齐 `VALID_CATEGORIES` |
| `schemas/compliance.py` | 修改 | `ComplianceReportOut.result` 增加类型约束（可选） |
| `tests/compliance/test_clause_level.py` | 重写 | 删除对已删除函数的引用，改为测试 checker.py 公开函数 |
| `tests/compliance/test_checker.py` | 新增 | 覆盖 `run_compliance_check`、`identify_category`、`build_enhanced_context` |

---

## 二、技术选型研究

### 2.1 核心技术决策

#### 决策 1: `ProductCategory` 枚举值对齐方案

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A: 枚举值改为简称（"寿险"） | 与 VALID_CATEGORIES 完全一致，registry 查找直接匹配 | 需检查使用 ProductCategory.value 的代码 | ✅ |
| B: 增加 name-to-alias 映射 | 不改枚举，向后兼容 | 维护两套命名，映射关系隐式 | ❌ |
| C: VALID_CATEGORIES 改为全称 | 不改枚举 | registry dict 全量修改 | ❌ |

**选择 A**：枚举值改为简称。理由：`VALID_CATEGORIES` 和 `CATEGORY_REGULATION_REGISTRY` 的 key 是业务约定，简称更自然；`ProductCategory` 当前仅被 `classify_product` 返回和 `identify_category` 消费，改动可控。

**影响分析**：需检查所有使用 `ProductCategory.value` 的代码（`checker.py:identify_category` 的关键词匹配、`routers/compliance.py` 的 category 传递）。

#### 决策 2: 降级状态传递方案

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| A: `check_negative_list` 返回 `Tuple[List, bool]` | 显式，类型安全，改动小 | 改签名，需更新调用方 | ✅ |
| B: 在返回 items 中嵌入标记字段 | 不改签名 | 结果结构隐式 | ❌ |
| C: 使用 dataclass 封装返回值 | 最类型安全 | 改动量大 | ❌ |

**选择 A**：`check_negative_list` 返回 `(items, checked)` 元组。语义清晰，路由层直接用 `checked` 设置 `negative_list_checked`。

#### 决策 3: JSON 解析 fallback 简化

`run_compliance_check` 当前有 5 层 JSON 解析 fallback：

```python
# 层级 1: strip thinking tag (<think>...</think>)
# 层级 2: strip code fence (```json ... ```)
# 层级 3: find first { ... last }
# 层级 4: json_repair 自动修复
# 层级 5: regex 提取 key-value pairs
```

| 建议 | 理由 |
|------|------|
| 保留层级 1-3 | 高频触发，处理 LLM 输出格式的常见变异 |
| 保留层级 4 | json_repair 是成熟的容错库，成本极低 |
| 移除层级 5 | regex 提取 key-value 的输出结构不可靠，不如返回带 error 标记的空结果 |

### 2.2 依赖分析

| 依赖 | 用途 | 影响 |
|------|------|------|
| `json_repair` | JSON 解析 fallback | 无版本兼容问题 |
| `rag_engine.get_engine` | 获取 RAG 引擎实例 | 返回 `Optional`，需处理 None |
| `llm.get_qa_llm` | 获取 LLM 客户端 | 工厂方法，接口稳定 |

---

## 三、数据流分析

### 3.1 现有数据流：文档合规检查

```
POST /check/document
  │
  ├─ 1. identify_category(product_name, document_content)
  │     ├─ classify_product(product_name)  → ProductCategory | None
  │     └─ (fallback) LLM 识别             → (category, confidence, method)
  │
  ├─ 2. build_enhanced_context(document_content, category)
  │     ├─ get_engine()                    → Optional[RAGEngine]
  │     ├─ engine.search_by_metadata(...)  → List[SearchResult]  (险种专属)
  │     ├─ engine.search(query, top_k=5)   → List[SearchResult]  (通用法规)
  │     └─ _build_context(results)         → (context_str, sources_info)
  │
  ├─ 3. run_compliance_check(prompt)
  │     ├─ get_qa_llm()                    → BaseLLMClient
  │     ├─ llm.ask(prompt)                 → raw_answer
  │     └─ _parse_json(raw_answer)         → Dict (5层fallback)
  │
  ├─ 4. check_negative_list(document_content)
  │     ├─ _load_negative_list()           → List[str] (RAG引擎降级时返回[])
  │     ├─ _check_violation(rule, content) → item | None (逐条调用LLM)
  │     └─ 合并 violations
  │
  └─ 5. 聚合结果 + 存储
        ├─ result["regulation_sources"] = sources_info
        ├─ result["category"] = category
        ├─ result["negative_list_checked"] = True  ← ⚠️ 硬编码
        └─ save_compliance_report(...)
```

### 3.2 关键数据结构

**`identify_category` 返回值**：`Tuple[Optional[str], float, str]`
- 问题：tuple 无字段名，`(None, 0.0, "unknown")` 的语义靠位置推断

**`build_enhanced_context` 返回值**：`Tuple[str, Dict[str, List[str]]]`
- `(context_str, sources_info)` — sources_info 为 `{法规名: [条款号]}`

**`run_compliance_check` 返回值**：`Dict[str, object]`
- 问题：无类型约束，字段名隐式约定（`summary`, `items`, `sources`, `citations`, `error`, `raw_answer`）

**`check_negative_list` 返回值**：`List[Dict]`
- 问题：无降级状态，无法区分"无违规"和"未检查"

### 3.3 数据转换点

| 转换点 | 位置 | 问题 |
|--------|------|------|
| `ProductCategory` → `category` 字符串 | `checker.py:identify_category:47` | 枚举 value（"人寿保险"）与 VALID_CATEGORIES（"寿险"）不匹配 |
| `SearchResult` → context 字符串 | `checker.py:_build_context:19` | metadata 字段名（`law_name`/`article_number`）与实际返回可能不一致 |
| LLM response → JSON Dict | `checker.py:run_compliance_check:71` | 5层 fallback，层级 5 regex 输出不可靠 |
| violations list → result 合并 | `routers/compliance.py:52` | `negative_list_checked` 硬编码 True |

---

## 四、关键技术问题

### 4.1 问题清单（按严重程度排序）

#### P0 — 数据正确性

**Q1: `ProductCategory` 枚举值与 `VALID_CATEGORIES` 命名割裂**

```python
# product_types.py — 枚举用全称
class ProductCategory(Enum):
    LIFE = "人寿保险"      # ← 全称
    HEALTH = "健康保险"    # ← 全称
    ACCIDENT = "意外保险"  # ← 全称

# constants.py — VALID_CATEGORIES 用简称
VALID_CATEGORIES = ["健康险", "医疗险", "重疾险", "寿险", "意外险", "年金险", "财产险"]
#                   ^^^^^^              ^^^^   ^^^^^^
```

**影响链路**：
1. `classify_product("重疾险产品")` → `ProductCategory.HEALTH`（因为"重疾"在 HEALTH 的 keywords 中）→ `ProductCategory.HEALTH.value` = `"健康保险"`
2. `identify_category` 返回 `("健康保险", 0.7, "keyword")`
3. `build_enhanced_context("健康保险")` → `get_category_regulations("健康保险")` → `[]`（registry key 是"健康险"不是"健康保险"）
4. **结果：险种专属法规检索失败，只命中通用法规**

```python
# checker.py:169 — 关键词匹配路径
category_enum = classify_product(product_name, document_content[:1000])
if category_enum != ProductCategory.OTHER:
    return category_enum.value, 0.7, "keyword"  # ← 返回 "健康保险"，不是 "健康险"
```

**Q2: `negative_list_checked` 硬编码为 True**

```python
# routers/compliance.py:65
result["negative_list_checked"] = True  # ← 无论 RAG 引擎是否可用都设为 True
```

当 RAG 引擎未初始化时，`_load_negative_list` 返回 `[]`，`check_negative_list` 返回 `[]`，但 `negative_list_checked` 仍为 `True`。用户看到的检查报告声称已执行负面清单检查，实际上跳过了。

**Q3: `models.py` 中存在第二个 `ProductCategory` 枚举**

```python
# lib/common/models.py:76 — 与 product_types.py 重复定义！
class ProductCategory(str, Enum):
    CRITICAL_ILLNESS = "critical_illness"  # ← 英文值！
    MEDICAL_INSURANCE = "medical_insurance"
    LIFE_INSURANCE = "life_insurance"
```

这个枚举使用英文值且继承 `str`，与 `product_types.py` 的中文值枚举完全不同。两个同名枚举在项目中并存，极易混淆。合规模块使用的是 `product_types.py` 的版本。

#### P1 — 健壮性

**Q4: `run_compliance_check` JSON 解析无测试**

5 层 fallback 的解析逻辑（`checker.py:71-115`），每层都有分支条件，但无任何单元测试覆盖。修改任一层都可能导致其他层回归。

**Q5: `identify_category` LLM 阶段使用子串匹配**

```python
# checker.py:189-191
for vc in VALID_CATEGORIES:
    if vc in extracted:  # ← 子串匹配，"医疗险" 会匹配包含"医疗险"的任意文本
        return vc, 0.85, "llm"
```

问题：遍历顺序决定匹配结果。如果 LLM 输出"短期医疗险"，会先匹配"健康险"（如果"健康险"在前）还是"医疗险"？取决于 `VALID_CATEGORIES` 列表顺序。当前顺序 `["健康险", "医疗险", ...]` 中"健康险"在前，但"医疗险"是子串，不会被误匹配。但如果 LLM 输出"健康医疗保险"会匹配"健康险"而非"医疗险"。

**Q6: 上下文截断 `context[:8000]` 无边界保护**

```python
# routers/compliance.py:44
context=context[:8000],  # ← 可能切在法规条款中间
```

截断在任意字符位置，可能切断一个法规条款的完整段落，导致 LLM 基于不完整的法规上下文做出判断。

#### P2 — 测试与维护

**Q7: `test_clause_level.py` 引用已删除函数**

```python
# tests/compliance/test_clause_level.py:3
from api.routers.compliance import _detect_missing_clauses, _run_compliance_check
# ↑ 这两个函数在 023 重构后已删除
```

`_detect_missing_clauses` 在合并时已从 router 中删除。`_run_compliance_check` 从未在 023 分支的 checker.py 中定义（checker 的对应函数是 `run_compliance_check`，无下划线前缀）。

**Q8: `ProductCategory` 枚举存在两处定义**

`lib/common/models.py:76` 和 `lib/common/product_types.py:12` 都定义了 `ProductCategory`，且值完全不同（英文 vs 中文，str-Enum vs Enum）。

### 4.2 潜在风险和缓解措施

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 枚举值不一致导致险种专属法规检索全部失败 | 高 | 高 | 对齐枚举值，增加测试验证 |
| RAG 引擎未初始化时用户误信检查结果完整 | 中 | 高 | 修复 `negative_list_checked` 语义 |
| JSON 解析 fallback 修改导致回归 | 低 | 中 | 补齐 fallback 路径的单元测试 |
| 上下文截断导致 LLM 判断依据不完整 | 中 | 中 | 按条款边界截断 |

---

## 五、API 契约分析

### 5.1 后端 Pydantic Schema → 前端 TypeScript 类型映射

| 后端 Schema | 前端 TS 类型 | 状态 |
|------------|-------------|------|
| `DocumentCheckRequest.document_content: str` | `document_content: string` | ✅ 一致 |
| `DocumentCheckRequest.product_name: Optional[str]` | `product_name?: string` | ✅ 一致 |
| `DocumentCheckRequest.parse_id: Optional[str]` | `parse_id?: string` | ✅ 一致 |
| `DocumentCheckRequest.category: Optional[str]` | `category?: string` | ✅ 一致 |
| `ComplianceItem.clause_number: str = ""` | `clause_number?: string` | ⚠️ 后端必填有默认值，前端可选 — 语义等价 |
| `ComplianceItem.value: Optional[object]` | `value?: string \| number` | ⚠️ 后端 Any，前端 string|number — 类型精度不同 |
| `ComplianceReportOut.result: Dict[str, object]` | `result: ComplianceResult` | ⚠️ 后端无结构约束，前端有完整类型定义 |
| `CategoryIdentifyResponse` | 前端无独立定义 | ⚠️ 前端未使用 `suggested_categories` |

### 5.2 关键差异

1. **`ComplianceReportOut.result`** 是 `Dict[str, object]`，Pydantic 不校验内部结构。前端 `ComplianceResult` 定义了完整类型（`summary`/`items`/`sources`/`citations`/`extracted_params`/`regulation_sources`/`category`/`negative_list_checked`），但后端无对应 schema。

2. **`ComplianceItem.value`** 后端是 `Optional[object]`（接受任意类型），前端是 `string | number`。如果后端传入其他类型（如 list），前端会类型不匹配。

---

## 六、测试覆盖分析

### 6.1 现有测试清单

| 测试文件 | 覆盖函数 | 状态 |
|---------|---------|------|
| `test_negative_list.py` | `check_negative_list` (5 cases) | ✅ 正常 |
| `test_regulation_registry.py` | `get_category_regulations`, `get_general_regulations` (4 cases) | ✅ 正常 |
| `test_clause_level.py` | `_detect_missing_clauses`, `_run_compliance_check` | ❌ ImportError |
| `test_e2e_compliance.py` | 端到端流程 (12 cases) | ⚠️ 依赖运行中的 API 服务 |
| `test_validation.py` | `compare_clause_level`, `load_fixture` | ⚠️ 不在此次范围 |

### 6.2 缺失测试

| 函数 | 当前覆盖 | 需补充 |
|------|---------|--------|
| `identify_category` | 无 | 关键词匹配、LLM 匹配、双阶段失败、LLM 返回非法值 |
| `build_enhanced_context` | 无 | RAG 引擎未初始化、category=None、有/无险种专属法规 |
| `run_compliance_check` | 无 | 正常 JSON、thinking tag、code fence、截断 JSON、纯文本、空响应 |
| `_check_violation` | 无 | 正常违规、正常不违规、LLM 返回非 JSON、LLM 抛异常 |

### 6.3 测试建议

1. 新增 `test_checker.py` 覆盖 `identify_category`、`build_enhanced_context`、`run_compliance_check`、`_check_violation`
2. 重写 `test_clause_level.py`：移除对已删除函数的引用，改为测试 `checker.py` 的公开函数
3. 为 `run_compliance_check` 的 JSON 解析每层 fallback 补齐测试用例

---

## 七、技术债务

| 债务 | 严重程度 | 位置 | 说明 |
|------|---------|------|------|
| `ProductCategory` 双定义 | 高 | `models.py:76` + `product_types.py:12` | 同名枚举两处定义，值完全不同 |
| `result: Dict[str, object]` | 中 | `schemas/compliance.py:28` | 无结构约束，前端类型定义无法自动校验 |
| `negative_list_checked` 硬编码 | 高 | `routers/compliance.py:65` | 不反映实际检查状态 |
| 上下文截断无边界保护 | 中 | `routers/compliance.py:44` | 可能切断法规条款 |
| JSON fallback 无测试 | 中 | `checker.py:71-115` | 5 层解析逻辑无单元测试 |
| `identify_category` 返回 tuple | 低 | `checker.py:158` | 无字段名，靠位置推断语义 |

---

## 八、改进建议

### 8.1 必须修复（P0）

1. **对齐 `ProductCategory` 枚举值**：将 `product_types.py` 中枚举值改为简称（"寿险"/"健康险"/"意外险"等），与 `VALID_CATEGORIES` 和 `CATEGORY_REGULATION_REGISTRY` key 一致
2. **修复 `negative_list_checked` 语义**：`check_negative_list` 返回 `(items, checked)`，路由根据 `checked` 设置 `negative_list_checked`
3. **消除 `ProductCategory` 双定义**：确认 `models.py` 中的 `ProductCategory` 是否有使用方，统一为一处定义

### 8.2 应该修复（P1）

4. **增加上下文截断边界保护**：按 `\n\n[来源` 边界截断，确保不切断条款
5. **重写 `test_clause_level.py`**：移除对已删除函数的引用
6. **新增 `test_checker.py`**：覆盖 `identify_category`、`build_enhanced_context`、`run_compliance_check`

### 8.3 可以改进（P2）

7. **`ComplianceReportOut.result` 增加类型约束**：定义 `ComplianceResult` Pydantic model 替代 `Dict[str, object]`
8. **`identify_category` 返回 NamedTuple**：增加字段名（category/confidence/method）
9. **简化 JSON fallback 层级 5**：移除 regex 提取，改为返回带 `error` 标记的空结果
10. **`_check_violation` 并行化**：当规则数量 > 10 时，使用 `asyncio.gather` 并行调用 LLM

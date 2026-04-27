# Feature Specification: 保险产品合规检查

**Feature Branch**: `022-compliance-check`
**Created**: 2026-04-23
**Status**: Draft
**Input**: 深入输入文档解析和文档审核功能，接下来，我们梳理保险产品合规检查的需求和测试验证

## Background

### 现状

系统已有基础的合规检查功能（`scripts/api/routers/compliance.py`）：

| 接口 | 功能 | 状态 |
|------|------|------|
| `POST /check/product` | 产品参数合规检查 | 已实现 |
| `POST /check/document` | 条款文档合规检查 | 已实现 |
| `POST /parse-file` | 文档解析（PDF/DOCX） | 已实现 |
| `POST /parse-rich-text` | 富文本解析 | 已实现 |
| `GET /reports` | 报告列表 | 已实现 |
| `GET /reports/{id}` | 报告详情 | 已实现 |
| `DELETE /reports/{id}` | 删除报告 | 已实现 |

**已有能力**：
- RAG 检索法规条文
- LLM 生成合规检查结果
- 法条引用格式 `[来源X]`
- 文档解析输出 `AuditDocument` 结构

**待完善**：
- 检查结果按条款结构组织（当前为扁平参数列表）
- 遗漏检测：文档有但检查未覆盖的条款
- 法条溯源的可信度
- 历史报告管理暂缓，先结构化展示审核结果

---

## User Scenarios & Testing

### User Story 1 - 文档解析后确认结构 (Priority: P1)

**角色**: 精算审核人员

**用户旅程**: 上传保险产品文档后，先查看解析结果（条款列表、费率表等），确认解析正确后再发起合规检查。

**Why this priority**: 用户需要先验证解析结果是否正确，避免对错误数据做合规检查。这是分步操作的第一步。

**Independent Test**:
- 上传文档 → 返回解析结果 → 用户确认 → 触发合规检查

**Acceptance Scenarios**:

1. **Given** 上传 PDF/DOCX 文档成功, **When** 解析完成, **Then** 展示条款列表、费率表、投保须知等结构化内容
2. **Given** 解析结果展示后, **When** 用户点击"确认并发起合规检查", **Then** 调用合规检查接口
3. **Given** 解析结果有误, **When** 用户修改解析内容, **Then** 可重新解析或手动修正

---

### User Story 2 - 合规检查报告生成 (Priority: P1)

**角色**: 精算审核人员

**用户旅程**: 确认解析结果后，系统自动检索相关法规，按条款结构逐项检查产品条款的合规性，生成包含法条溯源的检查报告。检查结果按条款编号树状组织，并可检测文档中未被检查覆盖的条款。

**Why this priority**: 合规检查是核心功能，法条溯源是验收标准之一。条款级结构化展示让用户一目了然，遗漏检测确保审核完整性。

**Independent Test**:
- 触发检查 → 返回条款级结构化报告 → 验证法条引用格式 → 检查遗漏项

**Acceptance Scenarios**:

1. **Given** 已解析的产品条款, **When** 执行合规检查, **Then** 检索相关法规条文（top_k=10）
2. **Given** 法规检索结果, **When** LLM 生成检查结果, **Then** 每个检查项包含 `clause_number`（条款编号）、`source`（法条引用）和 `source_excerpt`（原文摘录）
3. **Given** 检查完成, **When** 生成报告, **Then** 检查结果按条款编号树状组织，包含 summary（合规/不合规/需关注数量）和 items 列表
4. **Given** 检查结果, **When** 用户点击某条款, **Then** 展示该条款下所有检查项及对应法规原文
5. **Given** 文档解析的条款列表和检查结果, **When** 对比覆盖情况, **Then** 标注文档中存在但未被检查覆盖的条款（遗漏项）

---

### User Story 3 - 历史报告管理 (Priority: P2)

**角色**: 精算审核人员 / 产品开发人员

**用户旅程**: 查看历史合规检查报告，对比不同版本的检查结果，导出报告供存档或分享。

**Why this priority**: 报告管理是验收标准之一，但不是核心检查流程。

**Independent Test**:
- 查看报告列表 → 查看详情 → 对比/导出

**Acceptance Scenarios**:

1. **Given** 多个历史报告, **When** 查看报告列表, **Then** 按时间倒序展示（产品名称、检查时间、结果摘要）
2. **Given** 某报告详情, **When** 用户点击"导出", **Then** 生成 PDF/Word 格式报告
3. **Given** 两个报告, **When** 用户选择对比, **Then** 展示两次检查结果的差异（新增问题、已修复问题）

---

### User Story 4 - 产品开发自查 (Priority: P2)

**角色**: 产品开发人员

**用户旅程**: 在产品开发阶段，快速自查产品参数的合规性，及早发现潜在问题。

**Why this priority**: 扩展用户群体到产品开发人员，但核心流程与精算审核一致。

**Independent Test**:
- 输入产品参数 → 返回自查结果

**Acceptance Scenarios**:

1. **Given** 产品参数（险种类型、等待期、免赔额等）, **When** 执行自查, **Then** 检索相关法规并检查
2. **Given** 自查结果, **When** 发现不合规项, **Then** 提供修改建议

---

### User Story 5 - 测试验证流程 (Priority: P1)

**角色**: 开发人员

**用户旅程**: 建立测试验证流程，使用真实保险产品文档验证合规检查功能的正确性。

**Why this priority**: 需求明确提到"测试验证"，需要建立可重复的测试流程。

**Independent Test**:
- 准备测试数据 → 执行检查 → 对比人工审核结果

**Acceptance Scenarios**:

1. **Given** 测试集（真实保险产品文档 + 人工审核结果）, **When** 执行自动检查, **Then** 记录检查结果与人工结果的一致性
2. **Given** 多个测试样本, **When** 批量验证, **Then** 生成验证报告（一致性统计、差异详情）

---

### Edge Cases

- 文档解析失败时如何处理合规检查？（应阻止检查并提示解析错误）
- 法规检索无结果时如何处理？（应提示"未找到相关法规"并标注为 attention）
- LLM 输出格式错误时如何处理？（应捕获异常并返回原始输出供人工审查）
- 同一产品重复检查时如何处理？（应生成新报告，保留历史记录）
- 产品条款完全合规时如何展示？（应正常展示"全部合规"摘要）
- 条款编号格式不规范时如何分组？（降级为扁平列表）

---

## Requirements

### Functional Requirements

- **FR-001**: 系统 MUST 支持分步操作：先解析文档、用户确认、再执行合规检查
- **FR-002**: 系统 MUST 在检查结果中包含法条溯源（source 引用 + source_excerpt 原文摘录）
- **FR-002a**: 系统 MUST 按条款编号组织检查结果（clause_number 字段），支持树状结构展示
- **FR-002b**: 系统 MUST 检测文档中存在但未被检查覆盖的条款（遗漏项），标注为 attention
- **FR-003**: 系统 MUST 支持查看历史合规检查报告（导出/对比功能暂缓，先结构化展示审核结果）
- **FR-004**: 系统 MUST 复用现有文档解析接口（parse-file, parse-rich-text）
- **FR-005**: 系统 MUST 复用现有 RAG 引擎检索法规
- **FR-006**: 系统 MUST 在法规检索无结果时标注检查项为 attention
- **FR-007**: 系统 MUST 支持测试验证流程，对比自动检查与人工审核结果

### Non-Functional Requirements

- **NFR-001**: 合规检查响应时间 < 30 秒（单文档）
- **NFR-002**: 法条引用格式统一为 `[来源X]`
- **NFR-003**: 报告持久化存储在 SQLite 数据库

---

## Key Entities

### ComplianceReport（合规检查报告）

```python
@dataclass
class ComplianceReport:
    """合规检查报告"""
    id: str                    # 报告ID，格式 cr_xxxxxxxx
    product_name: str          # 产品名称
    category: str              # 险种类型
    mode: str                  # 检查模式：product / document
    result: Dict[str, Any]     # 检查结果
    created_at: datetime       # 创建时间

    # result 结构：
    # {
    #     "summary": {"compliant": N, "non_compliant": M, "attention": K},
    #     "items": [CheckItem, ...],
    #     "sources": [...],      # RAG 检索来源
    #     "citations": [...]     # 引用信息
    # }
```

### CheckItem（检查项）

```python
@dataclass
class CheckItem:
    """单个检查项"""
    clause_number: str    # 条款编号，如 "1.2.3"
    param: str            # 参数名称 / 检查项名称
    value: str            # 产品实际值
    requirement: str      # 法规要求
    status: str           # compliant / non_compliant / attention
    source: str           # 法条引用，格式 [来源X]
    source_excerpt: str   # 法条原文摘录
    suggestion: str       # 修改建议（仅不合规时）
```

---

## Success Criteria

- **SC-001**: 用户可在文档解析后确认结构，再发起合规检查
- **SC-002**: 每个检查项包含条款编号、法条引用和原文摘录
- **SC-002a**: 检查结果按条款编号树状组织展示
- **SC-002b**: 未被检查覆盖的条款标注为遗漏项
- **SC-003**: 支持查看历史报告（导出功能暂缓）
- **SC-004**: 建立测试验证流程，使用真实产品文档验证

---

## Assumptions

- 复用现有合规检查 API 和文档解析接口
- 复用现有 RAG 引擎检索法规
- 法条溯源依赖 RAG 检索结果，不引入额外规则库
- 测试数据来源：真实保险产品文档 + 人工审核结果
- 边界条件在测试验证中收集和定义

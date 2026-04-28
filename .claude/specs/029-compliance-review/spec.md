# Feature Specification: 合规审核模块系统化 Review

**Feature Branch**: `029-compliance-review`
**Created**: 2026-04-28
**Status**: Draft
**Input**: 系统、全面、深入 review 保险产品合规审核的整体设计和代码实现细节，包括对 doc_parser、rag_engine 等模块的依赖梳理

## Review Scope

**目标**: 系统性梳理现状 + 识别改进点，产出可执行的重构建议
**范围**: 合规核心链路（checker.py + prompts.py + rag_engine/doc_parser/llm 依赖接口 + API 契约）
**不包含**: 前端交互体验、doc_parser 解析质量优化、rag_engine 检索质量优化
**独立于**: 022-compliance-check、023-compliance-regs 的已有结论

---

## User Scenarios & Testing

### User Story 1 - 合规检查主链路质量保障 (Priority: P1)

作为开发者，当产品文档进入合规检查流程时，我需要整条链路（文档输入 → 险种识别 → 法规检索 → LLM 合规判断 → 负面清单检查 → 结果聚合 → 存储）的每个环节都有明确的正确性保证，避免因任一环节静默失败导致检查结果不可信。

**Why this priority**: 合规检查是核心业务功能，结果准确性直接影响用户决策

**Independent Test**: 对每个环节构造边界输入，验证输出的完整性和一致性

**Acceptance Scenarios**:

1. **Given** 文档内容为空字符串, **When** 调用 `/check/document`, **Then** 返回明确的参数校验错误（而非走到 LLM 调用阶段）
2. **Given** RAG 引擎未初始化, **When** 调用 `build_enhanced_context`, **Then** 返回降级结果而非静默返回空上下文
3. **Given** LLM 返回非 JSON 格式, **When** `run_compliance_check` 解析响应, **Then** 返回包含 `error` 标记的结构化结果，不抛异常
4. **Given** 负面清单知识库无数据（或 RAG 引擎未初始化）, **When** `check_negative_list` 执行, **Then** 跳过负面清单检查，结果中标记 `negative_list_checked: false`（当前代码硬编码为 True）
5. **Given** 险种识别返回 `None`, **When** 进入法规检索, **Then** 使用通用法规集作为降级策略，结果中标记识别失败

---

### User Story 2 - 法规检索策略有效性 (Priority: P1)

作为合规系统维护者，我需要 `build_enhanced_context` 的两层检索（险种专属 + 通用法规）能可靠地覆盖目标法规，且检索结果能准确传递到 LLM prompt，避免因检索缺失或上下文截断导致合规判断依据不足。

**Why this priority**: 法规检索是合规判断的事实基础，检索质量直接决定检查结果的可信度

**Independent Test**: 对已知法规文档构造检索请求，验证覆盖率、上下文完整性、截断位置

**Acceptance Scenarios**:

1. **Given** 险种为"健康险", **When** `build_enhanced_context` 执行, **Then** 返回的 context 包含 `CATEGORY_REGULATION_REGISTRY["健康险"]` 中所有法规的条款
2. **Given** 检索返回超过 8000 字符的 context, **When** 截断到 `context[:8000]`, **Then** 截断位置不切断法规条款的完整段落
3. **Given** 某法规名称在 registry 中但知识库无对应文档, **When** `search_by_metadata` 查询, **Then** 不影响其他法规的检索结果
4. **Given** `get_engine()` 返回 None, **When** `build_enhanced_context` 执行, **Then** 返回空 context 和空的 sources_info，而非抛出 AttributeError

---

### User Story 3 - 负面清单检查可靠性 (Priority: P2)

作为合规检查的使用者，我需要负面清单检查结果能准确反映文档是否违反禁止性规定，且 LLM 判断结果可追溯、可审计，避免误判和漏判。

**Why this priority**: 负面清单是监管红线，漏判风险高于误判

**Independent Test**: 构造已知违反/不违反负面清单的文档，验证检查结果的准确性和可追溯性

**Acceptance Scenarios**:

1. **Given** 文档包含明确的负面清单违规项, **When** `check_negative_list` 执行, **Then** 返回的 items 中包含该违规项，且 `source_excerpt` 为原文摘录
2. **Given** 文档不违反任何负面清单规则, **When** `check_negative_list` 执行, **Then** 返回空列表
3. **Given** LLM 返回格式异常（无 is_violation 字段）, **When** `_check_violation` 解析, **Then** 视为无违规（漏判优于误判策略需显式标注）
4. **Given** 知识库中负面清单规则数量 > 20, **When** 逐一调用 LLM, **Then** 考虑批量/并行策略的性能影响

---

### User Story 4 - 险种识别准确性 (Priority: P2)

作为合规检查的使用者，我需要险种识别结果准确且可追溯，关键词匹配和 LLM 识别的置信度有明确语义，当识别失败时用户能收到清晰反馈。

**Why this priority**: 险种识别决定法规检索范围，识别错误导致检索方向错误

**Independent Test**: 对已知产品名称和文档内容测试识别准确性

**Acceptance Scenarios**:

1. **Given** 产品名称包含"重疾", **When** `identify_category` 执行, **Then** 关键词阶段返回 `("重疾险", 0.7, "keyword")`
2. **Given** 产品名称模糊、文档内容有线索, **When** 关键词阶段返回 OTHER, **Then** LLM 阶段能正确识别并返回 `(category, 0.85, "llm")`
3. **Given** 产品名称和文档内容均无法判断险种, **When** 两阶段都失败, **Then** 返回 `(None, 0.0, "unknown")`
4. **Given** LLM 返回不在 `VALID_CATEGORIES` 中的险种, **When** 匹配阶段, **Then** 视为识别失败，返回 `(None, 0.0, "unknown")`

---

### User Story 5 - API 契约一致性 (Priority: P2)

作为前后端协作的开发者，我需要 API 请求/响应的 Pydantic schema 与前端 TypeScript 类型定义保持一致，字段增删同步更新，避免运行时类型不匹配。

**Why this priority**: API 契约不一致会导致前端运行时错误

**Independent Test**: 对比 `schemas/compliance.py` 与 `types/index.ts` 的字段定义

**Acceptance Scenarios**:

1. **Given** `DocumentCheckRequest` 新增 `category` 字段, **When** 前端发送请求, **Then** TypeScript 类型也包含 `category?: string`
2. **Given** `ComplianceResult` 接口定义 `regulation_sources` 和 `negative_list_checked`, **When** 后端返回这些字段, **Then** 前端能正确解析
3. **Given** `ComplianceItem` 定义 `clause_number` 字段, **When** 后端返回该字段, **Then** 前端 schema 和类型定义也包含该字段

---

### User Story 6 - 测试覆盖和可靠性 (Priority: P1)

作为系统维护者，我需要合规模块有足够的测试覆盖，包括单元测试（各函数独立逻辑）和集成测试（端到端链路），且现有测试不引用已删除的函数。

**Why this priority**: 测试是重构的安全网，当前 test_clause_level.py 引用了不存在的函数

**Independent Test**: 运行 `pytest scripts/tests/compliance/`，验证所有测试通过

**Acceptance Scenarios**:

1. **Given** `test_clause_level.py` 引用 `_detect_missing_clauses`, **When** 运行测试, **Then** 不应因 ImportError 失败
2. **Given** `checker.py` 中的所有公开函数, **When** 检查测试覆盖, **Then** 每个函数至少有一个单元测试
3. **Given** `build_enhanced_context` 的 RAG 依赖, **When** mock `get_engine`, **Then** 测试能验证降级逻辑
4. **Given** `run_compliance_check` 的 LLM 响应解析, **When** LLM 返回各种异常格式, **Then** 都有对应的测试用例

---

### Edge Cases

- `search_by_metadata` 返回的 metadata 字段名与 `_build_context` 读取的字段名不一致？
- `classify_product` 的 `ProductCategory` 枚举值与 `VALID_CATEGORIES` 列表不完全对应（枚举用"人寿保险"，列表用"寿险"）
- `_check_violation` 逐一调用 LLM，当规则数量大时的性能和成本问题
- `run_compliance_check` 中 JSON 解析的多层 fallback（strip thinking → strip code fence → find braces → repair → regex → empty），复杂度高且无测试
- 合规检查结果 `result` 字段是 `Dict[str, object]`，无类型约束，字段名（`regulation_sources`、`negative_list_checked`、`category`）是隐式约定
- `_html_to_docx` 使用简单的 HTML parser，无法处理复杂 HTML（嵌套表格、合并单元格）
- `negative_list_checked` 在 `check_document` 路由中硬编码为 `True`，即使 `_load_negative_list` 因 RAG 引擎未初始化而返回空列表也会标记为已检查

## Requirements

### Functional Requirements

- **FR-001**: 系统 MUST 在 RAG 引擎未初始化时，`build_enhanced_context`、`_load_negative_list` 和 `check_negative_list` 降级处理而非抛出 AttributeError；当负面清单无法检查时，`negative_list_checked` 必须为 `false`
- **FR-002**: 系统 MUST 在 LLM 返回非 JSON 响应时，`run_compliance_check` 返回包含错误标记的结构化结果
- **FR-003**: 系统 MUST 保障 `ProductCategory` 枚举值与 `VALID_CATEGORIES` 列表的一致性
- **FR-004**: 系统 MUST 确保负面清单检查结果中 `source_excerpt` 为法规原文摘录
- **FR-005**: 系统 MUST 确保上下文截断不会在法规条款中间切断
- **FR-006**: 系统 MUST 修复 `test_clause_level.py` 引用已删除函数的问题
- **FR-007**: 系统 MUST 为 `checker.py` 中每个公开函数提供单元测试覆盖
- **FR-008**: 系统 MUST 确保 Pydantic schema 与 TypeScript 类型定义字段一致
- **FR-009**: 系统 SHOULD 对合规检查结果 `result` 字段增加类型约束，替代 `Dict[str, object]`
- **FR-010**: 系统 SHOULD 在 `identify_category` 返回 None 时，API 响应中明确标识识别失败
- **FR-011**: 系统 SHOULD 为 `_check_violation` 的 LLM 调用增加批量/并行策略
- **FR-012**: [NEEDS CLARIFICATION] `run_compliance_check` 中 JSON 解析的 5 层 fallback 是否都需要保留？某些层是否可简化？

### Key Entities

- **ComplianceCheckResult**: 合规检查的完整结果（summary + items + sources + metadata），当前为隐式 Dict 结构
- **RegulationContext**: 法规检索上下文（法规条款文本 + 来源信息），由 `build_enhanced_context` 产出
- **NegativeListRule**: 负面清单规则条目，从知识库检索获得
- **CategoryIdentification**: 险种识别结果（category + confidence + method），由 `identify_category` 产出
- **ComplianceItem**: 单条合规检查项，包含条款号、参数、值、法规要求、状态、来源等

## Success Criteria

- **SC-001**: `pytest scripts/tests/compliance/` 全部通过，无 ImportError
- **SC-002**: `ProductCategory` 枚举值与 `VALID_CATEGORIES` 列表完全对应
- **SC-003**: RAG 引擎未初始化时，合规检查流程不抛出 AttributeError
- **SC-004**: API schema 与 TypeScript 类型定义的字段差异为 0
- **SC-005**: `checker.py` 公开函数测试覆盖率 ≥ 80%

## Assumptions

- doc_parser 和 rag_engine 的内部实现不在此次 review 的重构范围内，仅关注 compliance 对它们的调用接口
- 前端交互体验（CompliancePage.tsx 的 UX）不在范围内，但 API 契约一致性在范围内
- 重构应保持向后兼容——API 请求/响应格式不变，仅内部实现优化
- 测试中的 mock 策略可以依赖现有的 `get_qa_llm` 和 `get_engine` 导入点

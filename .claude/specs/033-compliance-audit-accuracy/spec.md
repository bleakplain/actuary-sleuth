# Feature Specification: 合规审核准确性提升

**Feature Branch**: `033-compliance-audit-accuracy`
**Created**: 2026-05-11
**Status**: Draft
**Input**: 用户在 review 合规审核报告时发现：(1) 审核结果遗漏条款检查项；(2) 检查项引用的法规条文与实际检查内容不对应。

## User Scenarios & Testing

### User Story 1 - 审核结果覆盖所有条款 (Priority: P1)

用户上传一份包含 50 条条款的保险产品文档，执行合规审核后，报告中的检查项应覆盖所有需要审核的条款，不应因为 LLM 输出截断、prompt 设计缺陷或文档过长而遗漏后半部分条款。

**Why this priority**: 遗漏条款意味着审核结果不完整，可能导致不合规条款漏检，直接影响审核的可信度。

**Independent Test**: 使用已知条款数量的测试文档执行审核，对比解析出的条款总数与审核检查项涉及的条款覆盖情况。

**Acceptance Scenarios**:

1. **Given** 一份包含 30 条以上条款的保险产品文档, **When** 执行合规审核, **Then** 审核报告中检查项涉及的条款编号应覆盖文档中 80% 以上的条款（不含明确无需检查的条款如释义条款）
2. **Given** 文档内容超过 150,000 字符限制, **When** 执行合规审核, **Then** 系统应明确标识哪些条款因截断而未被检查，而非静默跳过
3. **Given** 审核结果中存在条款覆盖遗漏, **When** 用户查看报告, **Then** 报告应显示已检查条款与未检查条款的对比信息

---

### User Story 2 - 检查项与法规引用准确对应 (Priority: P1)

用户查看审核报告中的某项检查结果，该检查项的法规要求（requirement）和法规来源（source_ref）应准确反映该检查项实际引用的法规条文。不应出现"检查事项是等待期，但引用的法规是关于免赔额"的张冠李戴情况。

**Why this priority**: 法规引用不准确会直接误导用户对合规状态的判断，降低审核报告的专业可信度。

**Independent Test**: 执行审核后，对每个检查项的 param/value 与 source_ref 对应的法规内容进行语义相关性验证。

**Acceptance Scenarios**:

1. **Given** 审核报告中的某个检查项涉及"等待期", **When** 查看该检查项的 source_ref, **Then** source_ref 对应的法规内容应与等待期相关（非关于免赔额、保险期间等不相关条文）
2. **Given** LLM 返回的 source_ref 为空或不匹配, **When** 系统解析结果, **Then** 检查项应标记为"法规来源待确认"而非指向错误的法规
3. **Given** 多个法规条文涉及同一检查事项, **When** LLM 选择引用某条法规, **Then** 引用的应是最直接、最相关的法规条文

---

### Edge Cases

- 文档条款编号不连续（如 1.1, 1.3, 2.1 跳过 1.2）时如何处理？
- 同一法规条文适用于多个检查项时，是否允许重复引用？
- LLM 无法确定某条款适用哪条法规时，应该如何标注？
- 知识库中某法规的 chunk 数量很多（超过 50 条），prompt 上下文是否能容纳？

## Requirements

### Functional Requirements

- **FR-001**: 系统 MUST 确保审核检查项覆盖文档中所有主要条款（定义明确的关键条款覆盖率达 80% 以上）
- **FR-002**: 系统 MUST 确保每个检查项的法规引用（source_ref）与检查内容（param/value）语义相关
- **FR-003**: 系统 SHOULD 在报告中提供条款覆盖分析（已检查 vs 未检查的条款列表）
- **FR-004**: 系统 MUST NOT 将不相关的法规条文作为某个检查项的法规依据
- **FR-005**: 系统 SHOULD 对法规来源匹配失败或不确定的检查项进行明确标注
- **FR-006**: 系统 SHOULD 在文档截断时告知用户哪些内容未被检查

### Key Entities

- **AuditCheckItem**: 审核检查项，包含条款编号、检查内容、法规引用、合规状态
- **RegulationReference**: 法规引用，包含法规名称、条款号、法规原文摘要、来源 chunk_id
- **ClauseCoverage**: 条款覆盖分析，包含文档条款列表、已检查条款、未检查条款

## Success Criteria

- **SC-001**: 使用标准测试文档执行审核，检查项涉及的条款覆盖率 ≥ 80%
- **SC-002**: 抽检 20 个检查项，source_ref 与检查内容的语义相关率 ≥ 90%
- **SC-003**: source_ref 匹配成功率 ≥ 95%（即 chunk_id 非 null 的比例）

## Assumptions

- 根因分析可能涉及 prompt 设计、LLM 行为、知识库数据质量等多个层面
- 修复方案可能需要调整 prompt 模板、增加后处理验证逻辑、或改进法规检索策略
- 当前使用本地 LLM（通过 Ollama），模型能力有限，prompt 工程是提升准确性的主要手段
- 知识库中的法规数据质量是前置条件，不在本次改进范围内（但需验证是否为根因之一）

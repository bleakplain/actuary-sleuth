# Tasks: 产品标签驱动的产品条款审核主链

**Input**: `spec.md`, `research.md`, `plan.md`
**Branch**: `036-tagged-regulation-retrieval`

## Format

- `[P]`：可与同阶段其他不同文件任务并行
- `[USn]`：对应 `spec.md` User Story
- 每项完成后必须运行对应离线测试；阶段完成后运行合规、解析和前端回归测试

## Phase 0：数据就绪、基线与验收集

- [x] T001 [US1-US6] 生成 v5 数据就绪报告，验证文档/chunk/限定标签/涉及标签/条款边界和主题覆盖基线
- [x] T002 [US1-US6] 创建版本化 `compliance-audit-v1` fixture schema、产品文件指纹和候选样例清单
- [x] T003 [US1-US6] 将精算未确认字段显式标为 pending，禁止 Phase 7 在未签收时自动切换
- [x] T004 [US1-US6] 记录 2026-07-28 全量测试既有失败和本功能离线门禁

**Checkpoint**：数据缺陷不被固化为正确基线；验收集有稳定版本和人工签收状态。

## Phase 1：统一审核输入

- [x] T005 [US1] 为所有产品内容块建立冻结模型和稳定 `clause_id`
- [x] T006 [US1] 让 DOC、DOCX、PDF 解析结果统一包含普通条款、表格、投保须知、健康告知、责任免除和附加条款
- [x] T007 [US1] 实现用户名称 > 正文名称 > 文件名的单一产品事实构建入口
- [x] T008 [US1] 修正健康险期限事实优先级和名称冲突证据
- [x] T009 [US1] 补统一输入、稳定 ID、unknown 保留和跨格式解析测试

**Checkpoint**：一次上传只生成一份产品标签和一组稳定审核内容块。

## Phase 2：冻结法规候选与条款单元

- [x] T010 [US2] 扩展法规候选元数据：KB版本、source_file、section_path、chunk_index、完整法规主题和适用性原因
- [x] T011 [US2] 按 `kb_version + source_file + article_number/section_path` 聚合法规条款单元并保留全部物理 chunk
- [x] T012 [US2] 冻结 applicable + indeterminate 候选，not_applicable 永不被回退恢复
- [x] T013 [US2] 显式返回 RAG/注册候选/产品分类降级和未覆盖范围
- [x] T014 [US2] 补同维度 OR、跨维度 AND、subtype 精确排除、单元聚合与 chunk 完整性测试

**Checkpoint**：后续阶段只消费稳定、版本化、可解释的法规条款单元。

## Phase 3：版本化条款主题与逐法规路由

- [x] T015 [US3] 新增版本化 `clause_topics.json`，关键词配置只能引用已注册主题
- [x] T016 [US3] 新增版本化 `clause_topic_relations.json`，首批覆盖续保、保险期间、责任免除和等待期
- [x] T017 [US3] 实现直接相关、结构相关、可能相关、unknown 和明确不相关路由
- [x] T018 [US3] 关系缺失、版本错误、未知主题或未覆盖关系一律降级为 unknown 并保留
- [x] T019 [US3] 补核心 Recall、跨主题关系、unknown 保留、受控排除和配置治理测试

**Checkpoint**：每个提交或剔除的产品内容块都有版本化理由，核心条款 Recall 为 100%。

## Phase 4：法规驱动的确定性事实提取

- [x] T020 [US5] 新增冻结 `ExtractedFact` 模型和 `fact_extraction.py`
- [x] T021 [US5] 提取等待期/犹豫期数值和单位，支持常见中文数字
- [x] T022 [US5] 提取续保安排、不保证续保和禁止性续保表述并处理否定语境
- [x] T023 [US5] 提取费率可调身份、首次和后续调费时间
- [x] T024 [US5] 事实只输出值、单位、clause_id、原文和置信度，不比较监管阈值、不形成结论
- [x] T025 [US5] 补单位、中文数字、否定语境、unknown 和证据归属测试

**Checkpoint**：事实需求可追溯到法规审核包，旧 Python 规则不提供监管语义。

## Phase 5：逐法规条款单元 LLM 审核

- [x] T026 [US4-US5] 新增 `RegulationAuditPackage`、四态 `RegulationAuditDecision` 和失败模型
- [x] T027 [US4] 构建法规条款单元审核包，包含产品标签证据、路由块、事实和全部法规 chunk
- [x] T028 [US4] 重写 prompt：四态输出、适用性争议只进入人工复核、禁止引用包外证据
- [x] T029 [US4] 使用严格结构化校验，验证状态、法规 ID、产品 clause_id 和引用摘录
- [x] T030 [US4] 无产品证据的 non_compliant 降为 manual_review；非法 JSON 和调用失败显式 incomplete
- [x] T031 [US4] 超长单元才分段，并按固定优先级归并
- [x] T032 [US4] 实现一单元一 HTTP、最大并发 5、总预算 300 秒、稳定输入顺序输出
- [x] T033 [US4] 将负面清单法规纳入同一审核包和判断合同
- [x] T034 [US4] 补 prompt、证据伪造、分段归并、失败隔离、并发重复和截止时间测试

**Checkpoint**：每个法规条款单元有独立四态结论；失败不会静默消失或变成合规。

## Phase 6：API、SSE、报告和前端

- [x] T035 [US6] 分离 `audit_status` 与 `compliance_conclusion`
- [x] T036 [US6] 扩展 API/报告合同：版本、计数、法规单元、多 chunk、条款证据、路由、事实、失败范围
- [x] T037 [US6] SSE 使用结构化法规级事件并保证 exactly-once 终态
- [x] T038 [US6] producer 异常、断流和多重降级保存局部报告并返回 incomplete，不再发送 completed
- [x] T039 [US6] 前端区分无违规、违规、信息不足、降级和未完成，并展示实时法规证据
- [x] T040 [US6] 前端将 negative-list skipped 显示为未执行而非通过，EOF 无终态触发错误
- [x] T041 [US6] 补旧报告兼容、RAG失败、LLM失败、多重降级、断流和证据保留测试

**Checkpoint**：任何系统失败都不能显示为“审核通过”，历史报告仍可读取。

## Phase 7：影子对照、切换与旧链清理

- [x] T042 [US4-US6] 实现旧新链路差异 runner 和版本化 JSON/CSV 指标输出
- [ ] T043 [US4-US6] 仅在 `compliance-audit-v1` 精算签收后计算 Recall、排除准确率、条款 Recall 和证据完整率
- [x] T044 [US4-US6] 生产新主链不得导入或合并 `rule_engine.py` 结果，旧实现只允许隔离影子调用
- [ ] T045 [US4-US6] 搜索并删除生产 `ProductMetadata`、全局聚合 prompt 和平行负面清单调用
- [ ] T046 [US4-US6] 精算门槛未签收时保持显式 cutover blocked；签收后切换默认入口并删除旧规则文件及专属测试
- [x] T047 [US4-US6] 补“生产模块不得导入 rule_engine”和差异指标测试

**Checkpoint**：只有一条用户可见审核主链；任何未完成的业务验收门槛均显式可见。

## Phase 8：质量审查与完成验证

- [x] T048 执行代码简化审查，修复复用性、可读性、效率和潜在 bug
- [x] T049 运行合规/解析/API/前端全部离线测试并确认不新增基线失败
- [x] T050 运行 `mypy scripts/lib/`，区分并修复本次新增错误与既有错误
- [x] T051 运行前端测试和生产构建
- [x] T052 更新 `plan.md` 阶段状态、测试结果、已知外部依赖和执行报告

## Dependencies

- Phase 1 依赖 Phase 0。
- Phase 2 依赖 Phase 1 的唯一产品事实。
- Phase 3 依赖 Phase 1 的稳定 clause_id 和 Phase 2 的法规条款单元。
- Phase 4 可在 Phase 3 路由模型稳定后实现。
- Phase 5 依赖 Phase 2–4。
- Phase 6 依赖 Phase 5 的四态判断合同。
- Phase 7 依赖 Phase 0 冻结验收集和 Phase 6 完整可观测性。
- Phase 8 依赖所有可自动完成任务；精算签收属于外部 cutover gate，不得伪造完成。

## Pending cutover tasks

T043、T045、T046 仍未完成，且必须保持未勾选：

- T043 需要精算师先完成 `compliance-audit-v1` 人工标注与签收；
- T045 只能在默认入口切换时清理旧生产链，提前删除会破坏现有用户入口；
- T046 需要签收后的在线影子对照和 5 分钟性能验收通过，之后才允许切换并删除旧规则文件。

## Phase 9：精算反馈修正与 v5 安全重建

- [x] T053 [US1-US2] 修正 2026 Excel 已确认文字错误，并把短期健康险续保复合规则拆成独立审核单元
- [x] T054 [US2] 为短期健康险法规补个人范围和“设置续保责任”受控适用条件
- [x] T055 [US2-US6] 为法规物理 chunk 生成跨重复构建稳定的确定性 ID
- [x] T056 [US2-US6] 新增 staging 构建、完整验证、原子切换和旧 v5 可恢复备份入口
- [x] T057 [US2-US6] 在 staging 重建 v5，迁移验收反馈引用并验证法规单元、标签、正文和索引身份

**Checkpoint**：生产 v5 只在 staging 全部门禁通过后切换，任一步失败均保留旧 v5。

## Phase 10：编号驱动条款解析器 v2

- [x] T058 [US1] 建立保持原文顺序的统一来源记录，DOCX 段落和表格不再二选一
- [x] T059 [US1] 以确认编号作为唯一条款边界，并将空编号续接内容归入当前条款
- [x] T060 [US1] 按编号前缀建立 level、parent、ancestors 和 hierarchy_path
- [x] T061 [US1] 让 DOC、DOCX、PDF 共用编号边界语义，保留阅读指引和附表为辅助块
- [x] T062 [US1] 补悠优保 2.5.3、2.5.4、5.3、7.42 和 12 份旧 DOC 回归

**Checkpoint**：排版只提供来源定位；有效原文覆盖率 100%，重复归入率 0%，审核块保持原文顺序。

## Phase 11：产品标签反馈闭环

- [x] T063 [US1] 用解析完整性凭证约束“缺失即否/无续保”等负向推断
- [x] T064 [US1] 同时保留保险期间与保证续保期间，并一致推导健康险监管期限
- [x] T065 [US1] 修正产品名称主体、主要责任、城市定制、医疗给付和疾病给付提取
- [x] T066 [US1-US6] 补复杂标签中文展示值和精算验收反馈回归

**Checkpoint**：所有已确认反馈都有代码或数据修正、证据和自动化回归。

## Phase 12：最终质量门禁

- [x] T067 执行代码简化和自审，修复所有本轮发现
- [x] T068 运行解析、标签、法规转换、KB、检索和 API 定向测试
- [x] T069 运行 `mypy scripts/lib/` 与全量 `pytest scripts/tests/`，确认不增加冻结基线失败
- [x] T070 更新执行报告、构建 manifest、验收表和回滚说明

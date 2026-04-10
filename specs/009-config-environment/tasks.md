# Tasks: 多环境配置管理

**Input**: plan.md
**Prerequisites**: plan.md ✅, spec.md ✅

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行执行（不同文件，无依赖）
- **[Story]**: 所属用户故事 (US1, US2, ...)

## Phase 1: Config 层适配 — US1 (P1)

- [x] T001 [US1] 更新 settings.json 数据路径为绝对路径 in scripts/config/settings.json
- [x] T002 [P] [US1] 更新 DatabaseConfig 支持新路径字段 in scripts/lib/config.py (depends on T001)
- [x] T003 [US1] 更新 _gguf_cli.py 从配置读取路径 in scripts/lib/rag_engine/_gguf_cli.py (depends on T002)
- [x] T004 [P] [US1] 更新 .gitignore 移除已迁出目录 in .gitignore

**Checkpoint**: User Story 1 ✅ — settings.json 绝对路径，_gguf_cli.py 从配置读取

## Phase 2: Skill 适配 — US2 (P1)

- [x] T005 [US2] 更新 gen-specify.md 添加配置拷贝步骤 in .claude/commands/gen-specify.md
- [x] T006 [P] [US2] 更新 exec-plan.md 添加配置拷贝和检查步骤 in .claude/commands/exec-plan.md

**Checkpoint**: User Story 2 ✅ — worktree 创建后配置自动拷贝

## Phase 3: 测试适配 — SC-004

- [x] T007 [SC-004] 验证测试 fixtures 兼容性 in scripts/tests/
- [x] T008 [SC-004] 运行完整测试套件 pytest scripts/tests/

**Checkpoint**: SC-004 ✅ — 316 passed, 8 failed（均为 master 已有问题）

## Phase 4: 文档更新 — US4 (P2)

- [x] T009 [P] [US4] 更新 CLAUDE.md Configuration 章节 in CLAUDE.md
- [x] T010 [P] [US4] 更新 .env.example in scripts/.env.example

**Checkpoint**: User Story 4 ✅ — 文档更新完成

## Dependencies & Execution Order

### Phase Dependencies
- Phase 1 (Config 层适配): No dependencies
- Phase 2 (Skill 适配): Independent of Phase 1
- Phase 3 (测试适配): Depends on Phase 1
- Phase 4 (文档更新): Independent

### Within Each Story
- T001 (settings.json) → T002 (DatabaseConfig) → T003 (_gguf_cli.py)
- T004 (.gitignore) 并行于 T002/T003

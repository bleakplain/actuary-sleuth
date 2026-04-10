# Actuary Sleuth - AI 精算审核助手

## Build And Test
- **Install**: `pip install -r requirements.txt`
- **Dev**: `python3 scripts/audit.py --documentUrl <feishu_url>`
- **Test**: `pytest scripts/tests/`
- **Type Check**: `mypy scripts/lib/`

## Architecture Boundaries
- **Entry points**: `scripts/*.py`
- **Domain logic**: `scripts/lib/audit/`, `scripts/lib/reporting`
- **Data models**: `scripts/lib/common/models.py`, `scripts/lib/common/audit.py`
- **Utilities**: `scripts/lib/common/`
- **Do not** put persistence in domain modules → use `scripts/lib/common/database.py`
- **Do not** put LLM logic in domain modules → use `scripts/lib/llm/`

## NEVER
- Modify `scripts/.env`, `scripts/config/settings.json` or CI secrets without approval
- Remove feature flags/constants without searching all call sites
- Commit without running tests (`pytest scripts/tests/`)
- Add `from lib.exceptions import *` wildcard imports
- Add sys.path manipulation in library files
- Create new service packages, reuse existing `scripts/lib/` structure

## ALWAYS
- Show diff before committing (`git diff HEAD`)
- Run tests before pushing
- Use type annotations for public APIs
- Use frozen dataclass for data models
- Archive exceptions to corresponding modules

## Code Style

### Naming
- Functions: business semantics, verb-noun组合 (`fetch_feishu_document`)
- Classes: nouns (`AuditService`, `DocumentFetcher`, `Product`)
- Private: prefix `_` (`_managed_query`)

### OOP Principles
- Hide implementation: `result.get_clauses()` not `result['clauses']`
- Bool check as property: `if result.success:` not `if result.is_success():`
- Single responsibility: one class, one purpose

### API Design
- Complex internal, simple external
```python
# ✓ Good
def execute_audit(document_url: str) -> AuditResult:
    document_content = fetch_feishu_document(document_url)
    ...

# ✗ Bad
def execute_audit(document_url: str, document_content: str) -> AuditResult:
    """User must fetch content themselves"""
```

### Data Models
```python
from dataclasses import dataclass

@dataclass(frozen=True)
class PreprocessedResult:
    audit_id: str
    document_url: str
    timestamp: datetime
    product: Product
    clauses: List[Dict[str, Any]]
```

### Exceptions
```python
# lib/exceptions.py - base
class ActuarySleuthException(Exception): pass

# lib/common/exceptions.py - re-export
from lib.exceptions import ActuarySleuthException, DatabaseError

# lib/common/exceptions.py - module specific
class DocumentFetchError(ActuarySleuthException): pass
```

## Core Flow

```
fetch_feishu_document → check_negative_list
→ analyze_pricing → calculate_result → save_db → export_report
```

## Module Organization
- **lib/common/** - models, database, exceptions, constants, shared utilities
- **lib/audit/** - audit orchestration
- **lib/reporting/** - report generation, export
- **lib/rag_engine/** - vector search, QA
- **lib/llm/** - LLM client abstraction

## Development

### Add check rule
Insert into `negative_list` table (supports keyword & regex)

### Add product type
1. Add to `ProductCategory` enum in `lib/common/models.py`
2. Add mapping in `lib/common/product_type.py`

### Add LLM client
1. Create client file in `lib/llm/`
2. Implement `lib/llm/base.py` interface
3. Register in `lib/llm/factory.py`
4. Configure in `scripts/config/settings.json`

### Modify report template
Edit `lib/reporting/template.py` → `ReportGenerationTemplate` class

## Configuration
Located at `scripts/config/settings.json`, overrideable via env vars.

数据文件存储在代码仓库外部的数据根目录中，通过 settings.json 中的绝对路径配置。

```
<data_root>/
├── db/              ← SQLite 数据库
├── kb/              ← 知识库版本（向量库、BM25 索引）
│   └── references/  ← 法规文档
├── eval/            ← 评估快照
├── models/          ← ML 模型权重
└── tools/           ← 编译工具
```

Worktree 创建时自动拷贝 settings.json 和 .env，各 worktree 配置独立。

## Constraints Summary
1. Business-semantic function names
2. Hide implementation, use object methods
3. Complex internal, simple external API
4. Specific exceptions, archived to modules
5. Frozen dataclass, metadata included, avoid nesting
6. No new service packages, reuse lib/ structure
7. Tests must pass before commit
8. Self-documenting code, no redundant comments
9. Reuse lib/llm error handling, don't implement retry in domain modules
10. Avoid unnecessary type conversions
11. Minimal parameters, use metadata
12. Constants in `lib/common/constants.py`
13. Domain-specific data files (dictionaries, stopwords) in module's `data/` subdirectory (e.g. `scripts/lib/rag_engine/data/`), not embedded in code
14. No over-engineering: avoid unnecessary config toggles and expansion points
15. Layered validation: use fast deterministic checks first (structure markers, rules), fall back to expensive probabilistic checks (embedding similarity) only when no structural signal exists
16. Dead code cleanup: remove unused code paths when default strategy makes them unreachable; delete deprecated modules directly rather than marking deprecated
17. Eval dataset scope: evaluation samples focus on insurance product audit (clauses, pricing, exclusions, waiting periods, product design), not company operations (capital changes, actuary hiring, claims process, sales management)

## Development Workflow (SDD)

采用 Spec-Driven Development，以 spec.md 为中心产物驱动开发。

### 工作流阶段

```
[可选] /gen-specify  — 需求 → spec.md（自动创建 worktree）
/gen-research        — 代码/需求分析 → research.md
/gen-plan            — 技术方案 → plan.md
/exec-plan           — 任务分解 + 实现 → tasks.md + 代码
/fix-plan            — 审查 + 批注处理
```

### Worktree 策略

- 始终基于 `origin/master` 创建 worktree，保证每个 feature 是干净起点
- worktree 目录：`.claude/worktrees/<feature-name>/`
- 分支编号：扫描本地+远程分支取 max+1，格式 `NNN-feature-name`
- 分支名 = `specs/` 子目录名

### 产物规范

所有 SDD 产物统一输出到 `specs/<feature-name>/` 下，不再输出到项目根目录：

```
specs/<feature-name>/
├── spec.md          # gen-specify 输出（可选）
├── research.md      # gen-research 输出
├── plan.md          # gen-plan 输出
└── tasks.md         # exec-plan 生成
```

### 模式检测

从当前 git branch 名提取 feature-name，检查 `specs/<feature-name>/spec.md` 是否存在：
- 存在 → SDD 模式（需求驱动）
- 不存在 → 兼容模式（问题驱动，保持原有行为）

### 治理原则（Constitution Check）

gen-plan 必须通过以下治理原则合规检查：

1. **Library-First** — 优先复用现有库和模块，避免重复造轮子
2. **测试优先** — 核心功能必须有测试覆盖
3. **简单优先** — 选择最简单的可行方案，除非有明确理由
4. **显式优于隐式** — 代码自文档化，避免魔法
5. **可追溯性** — plan.md 每个实现阶段必须回溯到 spec.md 的 User Story
6. **独立可测试** — 每个 User Story 必须能独立测试和交付

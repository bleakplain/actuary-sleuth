# Implementation Plan: 多环境配置管理

**Branch**: `009-config-environment` | **Date**: 2026-04-10 | **Spec**: spec.md
**Input**: spec.md

## Summary

将运行时数据和二进制资产从代码仓库迁移到外部数据根目录，settings.json 中的数据路径改为绝对路径。Worktree 创建时自动拷贝 settings.json 和 .env，实现多环境配置隔离。

## Technical Context

**Language/Version**: Python 3.x
**Primary Dependencies**: 现有依赖无变更
**Storage**: SQLite (外部目录), LanceDB (外部目录), GGUF 模型 (外部目录)
**Testing**: pytest
**Constraints**: 保持 settings.json 结构不变，保持 Config 单例和环境变量覆盖机制不变

## Constitution Check

- [x] Library-First: 复用现有 Config 单例、_resolve_path 机制、环境变量覆盖，不引入新配置抽象
- [x] 测试优先: 核心路径变更需更新测试 fixtures，exec-plan 增加配置检查
- [x] 简单优先: 仅改路径值（相对→绝对），不改配置结构；worktree 拷贝用 cp 命令
- [x] 显式优于隐式: 绝对路径直接写在 settings.json，无环境变量推导、无魔法行为
- [x] 可追溯性: 每个 Phase 回溯到 spec.md User Story
- [x] 独立可测试: 每个 Phase 可独立验证

## Project Structure

### Documentation

```text
specs/009-config-environment/
├── spec.md
├── plan.md          # 本文件
└── tasks.md         # exec-plan 生成
```

### Source Code

```text
scripts/
├── config/settings.json          # 路径改为绝对值
├── .env                          # 随 worktree 拷贝
├── lib/config.py                 # DatabaseConfig 默认值调整，新增 reranker 路径属性
├── lib/rag_engine/_gguf_cli.py   # 从配置读取模型/工具路径，删除硬编码 _DATA_DIR/_TOOLS_DIR
└── tests/conftest.py             # .env 加载路径兼容
```

### 外部数据目录（不在代码仓库内）

```text
/root/work/actuary-sleuth/        # 用户自定义位置
├── db/                           ← scripts/data/ 迁移
├── kb/                           ← scripts/lib/rag_engine/data/kb/ 迁移
│   └── references/               ← references/ 迁移
├── eval/                         ← scripts/data/eval_snapshots/ 迁移
├── models/                       ← scripts/lib/rag_engine/models/ 迁移
│   └── reranker/
└── tools/                        ← scripts/lib/rag_engine/tools/ 迁移
    └── hanxiao-llama.cpp/
```

## Implementation Phases

### Phase 1: Config 层适配 — User Story 1 (P1)

#### 需求回溯

→ 对应 spec.md User Story 1: 数据与代码分离

#### 实现步骤

**1.1 更新 settings.json 数据路径为绝对路径**

- 文件: `scripts/config/settings.json`
- 变更: `data_paths` 中的相对路径改为绝对路径，新增 `models_dir` 和 `tools_dir`

```json
{
  "data_paths": {
    "sqlite_db": "/root/work/actuary-sleuth/db/actuary.db",
    "regulations_dir": "/root/work/actuary-sleuth/kb/references",
    "kb_version_dir": "/root/work/actuary-sleuth/kb",
    "eval_snapshots_dir": "/root/work/actuary-sleuth/eval/snapshots",
    "models_dir": "/root/work/actuary-sleuth/models/reranker",
    "tools_dir": "/root/work/actuary-sleuth/tools/hanxiao-llama.cpp"
  }
}
```

**1.2 更新 DatabaseConfig 支持新路径字段**

- 文件: `scripts/lib/config.py`
- 变更: `DatabaseConfig` 新增 `models_dir` 和 `tools_dir` 属性，`Config` 新增对应的 `get_*` 方法

```python
class DatabaseConfig:
    def __init__(self, config_dict: Dict[str, Any]):
        self._config = config_dict.get('data_paths', {})

    @property
    def sqlite_db(self) -> str:
        return self._config.get('sqlite_db', '')

    @property
    def regulations_dir(self) -> str:
        return self._config.get('regulations_dir', '')

    @property
    def kb_version_dir(self) -> str:
        return self._config.get('kb_version_dir', '')

    @property
    def eval_snapshots_dir(self) -> str:
        return self._config.get('eval_snapshots_dir', '')

    @property
    def models_dir(self) -> str:
        return self._config.get('models_dir', '')

    @property
    def tools_dir(self) -> str:
        return self._config.get('tools_dir', '')
```

```python
# Config 类中新增
def get_models_dir(self) -> str:
    return self._resolve_path(self._data_paths.models_dir)

def get_tools_dir(self) -> str:
    return self._resolve_path(self._data_paths.tools_dir)
```

```python
# 模块级快捷函数
def get_models_dir() -> str:
    return get_config().get_models_dir()

def get_tools_dir() -> str:
    return get_config().get_tools_dir()
```

**1.3 更新 _gguf_cli.py 从配置读取路径**

- 文件: `scripts/lib/rag_engine/_gguf_cli.py`
- 变更: 删除硬编码的 `_DATA_DIR` 和 `_TOOLS_DIR`，从配置读取

```python
# 删除这行:
# _MODULE_DIR = Path(__file__).parent
# _DATA_DIR = _MODULE_DIR / "models" / "reranker"
# _TOOLS_DIR = _MODULE_DIR / "tools" / "hanxiao-llama.cpp"

# GGUFReranker.__init__ 改为:
def __init__(
    self,
    model_path: Optional[str] = None,
    projector_path: Optional[str] = None,
    llama_embedding_path: Optional[str] = None,
):
    from lib.config import get_models_dir, get_tools_dir

    models_dir = get_models_dir()
    tools_dir = get_tools_dir()

    model_path = model_path or str(Path(models_dir) / "jina-reranker-v3-Q4_K_M.gguf")
    projector_path = projector_path or str(Path(models_dir) / "projector.safetensors")
    llama_embedding_path = llama_embedding_path or str(Path(tools_dir) / "build" / "bin" / "llama-embedding")

    # 后续不变
    for path, label in [(model_path, "model"), (projector_path, "projector"), (llama_embedding_path, "llama-embedding")]:
        if not os.path.isfile(path):
            raise FileNotFoundError(f"{label} not found: {path}")
    ...
```

**1.4 更新 .gitignore**

- 文件: `.gitignore`
- 变更: 移除已迁出仓库的目录忽略规则（因为数据不再在仓库中），保留 `.env` 和 `.claude/worktrees/` 忽略

```gitignore
# 移除这些行（数据已不在仓库中）:
# data/
# scripts/lib/rag_engine/data/kb/
# scripts/lib/rag_engine/models/
# scripts/lib/rag_engine/tools/
```

---

### Phase 2: Skill 适配 — User Story 2 (P1)

#### 需求回溯

→ 对应 spec.md User Story 2: Worktree 配置自动拷贝

#### 实现步骤

**2.1 更新 gen-specify.md 添加配置拷贝步骤**

- 文件: `.claude/commands/gen-specify.md`
- 变更: 在 `git worktree add` 之后添加配置拷贝步骤

```markdown
### 第一步：创建 Worktree

1. **扫描编号** — 检查本地+远程分支中已有的 `NNN-*` 分支，取 max+1
2. **生成 feature-name** — 从需求描述中提取 3-4 个关键词，格式 `NNN-keyword-keyword`
3. **创建 worktree** — 基于 `origin/master` 创建：
   ```bash
   git worktree add .claude/worktrees/<feature-name> -b <feature-name> origin/master
   ```
4. **拷贝配置文件** — 从当前工作目录拷贝到新 worktree：
   ```bash
   cp scripts/config/settings.json .claude/worktrees/<feature-name>/scripts/config/settings.json
   cp scripts/.env .claude/worktrees/<feature-name>/scripts/.env
   ```
5. **创建产物目录**：
   ```bash
   mkdir -p .claude/worktrees/<feature-name>/specs/<feature-name>
   ```
```

**2.2 更新 exec-plan.md 添加配置拷贝步骤**

- 文件: `.claude/commands/exec-plan.md`
- 变更: 同样在 worktree 创建后添加配置拷贝步骤（与 gen-specify 保持一致）

**2.3 更新 exec-plan.md 添加配置完整性检查**

- 文件: `.claude/commands/exec-plan.md`
- 变更: 在执行任务前增加配置检查步骤

```markdown
### 前置检查（每个任务执行前）

1. **检查 settings.json 存在**: 确认 `scripts/config/settings.json` 存在
2. **检查 .env 存在**: 确认 `scripts/.env` 存在
3. **检查数据路径可达**: 读取 settings.json 中 `data_paths` 的绝对路径，验证目录/文件存在
   - 如果路径不存在，提示用户检查配置，不继续执行任务
```

---

### Phase 3: 测试适配 — SC-004

#### 需求回溯

→ 对应 spec.md SC-004: 所有现有测试通过

#### 实现步骤

**3.1 更新测试 fixtures 兼容新路径**

- 文件: `scripts/tests/conftest.py`
- 变更: 确认 .env 加载路径兼容（当前已使用 `Path(__file__).parent.parent / ".env"`，无需改动）

- 文件: `scripts/tests/api/conftest.py`
- 变更: 确认 `_patch_database` fixture 正确覆盖路径（当前通过 monkeypatch 覆盖 `get_sqlite_db_path`，无需改动）

**3.2 验证测试通过**

- 运行 `pytest scripts/tests/` 确认所有测试通过
- 重点验证 RAG engine 测试（mock 路径是否需要更新）

---

### Phase 4: 文档更新 — User Story 4 (P2)

#### 需求回溯

→ 对应 spec.md User Story 4: 迁移现有数据

#### 实现步骤

**4.1 更新 CLAUDE.md Configuration 章节**

- 文件: `CLAUDE.md`
- 变更: 更新配置说明，记录外部数据目录结构

```markdown
## Configuration
Located at `scripts/config/settings.json`, overrideable via env vars.

数据文件存储在代码仓库外部的数据根目录中，通过 settings.json 中的绝对路径配置。

外部数据目录结构:
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
```

**4.2 更新 .env.example**

- 文件: `scripts/.env.example`
- 变更: 移除路径相关的环境变量示例（路径统一由 settings.json 管理），保留 API 密钥示例

---

## Complexity Tracking

| 违反项 | 原因 | 更简单的替代方案及排除理由 |
|--------|------|--------------------------|
| 无 | | |

## Appendix

### 执行顺序建议

```
Phase 1 (Config 层适配) → Phase 2 (Skill 适配) → Phase 3 (测试适配) → Phase 4 (文档更新)
```

Phase 1 是基础，必须先完成。Phase 2 和 3 依赖 Phase 1 的路径变更。Phase 4 独立，可在任意阶段后进行。

### 用户手动迁移步骤（参考文档）

```bash
# 1. 创建外部数据目录
mkdir -p /root/work/actuary-sleuth/{db,kb/references,eval,models,tools}

# 2. 迁移数据
mv scripts/data/actuary.db /root/work/actuary-sleuth/db/
mv references/* /root/work/actuary-sleuth/kb/references/
mv scripts/lib/rag_engine/data/kb/* /root/work/actuary-sleuth/kb/
mv scripts/data/eval_snapshots/ /root/work/actuary-sleuth/eval/snapshots/
mv scripts/lib/rag_engine/models/reranker/ /root/work/actuary-sleuth/models/
mv scripts/lib/rag_engine/tools/hanxiao-llama.cpp/ /root/work/actuary-sleuth/tools/

# 3. 更新 settings.json 路径为绝对路径（见 Phase 1.1）
```

### 验收标准总结

| User Story | 验收标准 | 对应 Phase |
|-----------|---------|-----------|
| US1 - 数据与代码分离 | settings.json 使用绝对路径，_gguf_cli.py 从配置读取模型路径 | Phase 1 |
| US2 - Worktree 配置拷贝 | worktree 创建后 settings.json 和 .env 自动存在 | Phase 2 |
| US3 - 多环境独立运行 | 两个 worktree 各自独立配置、共享数据 | Phase 1+2 |
| US4 - 迁移现有数据 | 手动迁移后系统正常运行 | Phase 1 |
| SC-004 | pytest scripts/tests/ 全部通过 | Phase 3 |
| SC-005 | exec-plan 配置检查拦截缺失配置 | Phase 2 |

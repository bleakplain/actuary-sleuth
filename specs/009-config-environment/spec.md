# Feature Specification: 多环境配置管理

**Feature Branch**: `009-config-environment`
**Created**: 2026-04-10
**Status**: Draft
**Input**: 支持多测试环境，共享知识库及应用数据，但隔离配置和代码

## User Scenarios & Testing

### User Story 1 - 数据与代码分离 (Priority: P1)

用户将所有数据文件（知识库、数据库、评估数据、ML 模型权重、编译工具等）从代码仓库中迁移到外部数据根目录（如 `/root/work/actuary-sleuth`），代码仓库不再包含任何运行时数据和大型二进制资产。settings.json 中的数据路径改为绝对路径指向外部目录。

**Why this priority**: 这是整个多环境方案的基础，没有数据分离就无法实现共享。

**Independent Test**: 代码仓库目录下不存在 `data/`、`lib/rag_engine/data/kb/`、`lib/rag_engine/models/`、`lib/rag_engine/tools/` 等运行时数据和二进制资产目录，系统仍能正常启动和运行。

**Acceptance Scenarios**:

1. **Given** 外部数据根目录已创建且包含迁移后的数据, **When** 系统启动, **Then** 成功加载 settings.json 中的绝对路径数据（SQLite、知识库、ML 模型、编译工具）
2. **Given** settings.json 中 `data_paths.sqlite_db` 指向 `/root/work/actuary-sleuth/db/actuary.db`, **When** 数据库操作执行, **Then** 读写操作正确指向外部目录
3. **Given** settings.json 中 `data_paths.regulations_dir` 指向 `/root/work/actuary-sleuth/kb/references`, **When** 加载法规文档, **Then** 正确从外部目录读取
4. **Given** settings.json 中配置了 reranker 模型和工具的绝对路径, **When** GGUF reranker 执行, **Then** 正确加载外部目录中的 GGUF 模型文件和 llama.cpp 二进制工具
5. **Given** 外部数据根目录不存在, **When** 系统启动, **Then** 给出明确的错误提示，说明数据根目录缺失

---

### User Story 2 - Worktree 配置自动拷贝 (Priority: P1)

用户创建新 worktree 时，系统自动从当前工作目录拷贝 settings.json 和 .env 到新 worktree。用户按需修改当前 worktree 的配置（如切换 LLM provider、开启 debug、更换 API 密钥等），修改仅影响当前 worktree。

**Why this priority**: worktree 是代码隔离的载体，配置自动拷贝是零成本切换的关键。

**Independent Test**: 创建新 worktree 后，`scripts/config/settings.json` 和 `scripts/.env` 自动存在且内容与源目录一致。

**Acceptance Scenarios**:

1. **Given** 当前工作目录已有 settings.json 和 .env, **When** 创建新 worktree, **Then** worktree 中自动拷贝 `scripts/config/settings.json` 和 `scripts/.env`，内容与源目录一致
2. **Given** 新 worktree 已拷贝配置文件, **When** 用户修改该 worktree 的 settings.json（如切换 debug 模式）或 .env（如更换 API 密钥）, **Then** 修改仅影响当前 worktree，不影响源目录和其他 worktree
3. **Given** 用户在源目录更新了 settings.json（如添加新的 LLM 配置项）, **When** 创建新 worktree, **Then** 拷贝的是源目录最新的 settings.json 和 .env

---

### User Story 3 - 多环境独立运行 (Priority: P2)

用户在多个 worktree 中同时运行不同配置的服务实例（如一个用 zhipu 模型做调试，一个用 ollama 做测试），互不干扰。

**Why this priority**: 这是多环境价值的最终体现，验证隔离性和共享性的完整性。

**Independent Test**: 同时启动两个 worktree 的 API 服务，使用不同的 LLM 配置，两者独立响应、共享同一知识库。

**Acceptance Scenarios**:

1. **Given** 两个 worktree 各自有不同的 settings.json（不同 LLM provider）, **When** 同时启动两个 API 服务, **Then** 两个服务独立运行，各自使用自己的 LLM 配置
2. **Given** 两个 worktree 的 settings.json 中数据路径指向同一个外部数据根目录, **When** 一个 worktree 更新了知识库版本, **Then** 另一个 worktree 可以访问到更新后的知识库
3. **Given** 两个 worktree 共享同一个 SQLite 数据库, **When** 两个服务同时写入, **Then** 通过 WAL 模式正确处理并发（已有机制）

---

### User Story 4 - 迁移现有数据 (Priority: P2)

用户将当前散落在代码仓库内的数据文件手动迁移到外部数据根目录，更新主分支 settings.json 中的路径为绝对路径。

**Why this priority**: 现有数据需要迁移才能使用新结构，手动操作即可。

**Independent Test**: 迁移后系统能正常访问所有数据。

**Acceptance Scenarios**:

1. **Given** 代码仓库中存在现有数据文件, **When** 用户手动将数据迁移到外部目录, **Then** 按照约定目录结构放置，更新主分支 settings.json 路径即可
2. **Given** 外部数据根目录的目录结构, **Then** 符合约定：`<data_root>/db/`（数据库）、`<data_root>/kb/references/`（法规文档）、`<data_root>/kb/`（知识库版本）、`<data_root>/eval/`（评估数据）、`<data_root>/models/`（ML 模型权重）、`<data_root>/tools/`（编译工具）

---

## Requirements

### Functional Requirements

- **FR-001**: 系统 MUST 支持将所有运行时数据（数据库、知识库、评估数据、记忆数据、ML 模型权重、编译工具）存储在代码仓库外部的数据根目录中
- **FR-002**: 系统 MUST 通过 settings.json 中的绝对路径定位外部数据目录，保持现有 settings.json 结构不变
- **FR-003**: 系统 MUST 在创建新 worktree 时自动从当前工作目录拷贝 `scripts/config/settings.json` 和 `scripts/.env` 到新 worktree
- **FR-004**: 系统 MUST 确保每个 worktree 的 settings.json 和 .env 独立，修改不影响其他 worktree
- **FR-005**: 系统 MUST 保持现有配置加载机制（环境变量覆盖、Config 单例）不变
- **FR-006**: 外部数据根目录的约定目录结构 MUST 包含：`db/`、`kb/`（含 `references/` 子目录）、`eval/`、`models/`、`tools/`
- **FR-007**: 系统 MUST 将 `lib/rag_engine/models/`（ML 模型权重）和 `lib/rag_engine/tools/`（llama.cpp 编译工具）迁移到外部数据根目录，通过 settings.json 中的绝对路径配置，`_gguf_cli.py` 从配置读取路径而非使用相对路径

### Implementation Notes

#### 配置拷贝实现方式

worktree 创建后自动拷贝配置文件，拷贝来源是当前工作目录的本地文件（不是 git 仓库里的，因为 .env 在 .gitignore 中）：

```bash
# git worktree add 之后
cp <source>/scripts/config/settings.json <worktree>/scripts/config/settings.json
cp <source>/scripts/.env <worktree>/scripts/.env
```

拷贝逻辑需要在所有创建 worktree 的 skill（`/gen-specify`、`/gen-research` 等）中统一实现。

#### exec-plan 双重检查

`/exec-plan` 执行每个任务前 MUST 做配置完整性检查，作为最后兜底：

1. **检查 settings.json 存在**：确认 `<worktree>/scripts/config/settings.json` 存在，否则提示并终止
2. **检查 .env 存在**：确认 `<worktree>/scripts/.env` 存在，否则提示并终止
3. **检查数据路径可达**：验证 settings.json 中配置的绝对路径（db、kb、models、tools 等）实际存在且可访问，否则给出明确错误提示

### Key Entities

- **数据根目录 (Data Root)**: 外部目录，包含所有运行时数据和二进制资产。路径由用户在主分支 settings.json 中配置，绝对路径。结构为 `<data_root>/{db,kb,eval,models,tools}/`，其中 `kb/` 下含 `references/` 子目录
- **配置模板**: 当前工作目录的 `scripts/config/settings.json` 和 `scripts/.env`，作为新 worktree 的配置拷贝来源
- **环境配置**: 每个 worktree 独立的 settings.json 和 .env 拷贝，用户按需修改环境参数（LLM、debug、API 密钥等）

## Success Criteria

- **SC-001**: 代码仓库目录下不存在运行时数据目录（db/、kb/、models/、tools/），系统正常运行
- **SC-002**: 创建新 worktree 后 settings.json 和 .env 自动拷贝且可用，无需手动配置
- **SC-003**: 两个 worktree 同时运行，使用不同 LLM 配置，互不干扰
- **SC-004**: 所有现有测试通过（路径变更后测试需要相应更新）
- **SC-005**: exec-plan 执行前配置检查能正确拦截缺失的配置文件或不可达的数据路径

## Assumptions

- 数据根目录在本地文件系统上，不涉及远程存储或网络挂载
- 知识库数据（向量库、BM25 索引）为只读共享，不需要写隔离
- SQLite 数据库通过现有 WAL 机制处理并发写入，不需要额外隔离
- settings.json 的结构保持不变，仅路径值从相对路径改为绝对路径
- .env 文件随 worktree 拷贝，各 worktree 可独立修改（API 密钥不再全局共享）
- 迁移过程由用户手动完成，系统不提供自动迁移脚本
- 现有的环境变量覆盖机制（`ZHIPU_API_KEY` 等）保持不变
- 代码级静态数据（insurance_dict.txt、stopwords.txt、synonyms.json、eval_dataset.json）随代码走，不迁移
- `lib/rag_engine/models/`（约 129MB，GGUF 模型权重 + SafeTensors）和 `lib/rag_engine/tools/`（约 421MB，llama.cpp 编译工具）为二进制资产，通过子进程调用，不是 Python 代码，应迁移到外部数据目录
- 法规文档（references）作为知识库的源数据，迁移到 `kb/references/` 下

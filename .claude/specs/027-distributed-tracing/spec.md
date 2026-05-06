# Feature Specification: OpenTelemetry 分布式追踪集成

**Feature Branch**: `027-distributed-tracing`
**Created**: 2026-04-28
**Status**: Draft
**Input**: 当前追踪系统仅在 debug 模式启用，生产环境无观测数据；自定义 TraceSpan 无法接入主流可观测平台；Memory/Cache 等关键模块缺少追踪覆盖

## User Scenarios & Testing

### User Story 1 - 生产环境追踪数据可用 (Priority: P1)

运维人员在生产环境排查性能问题或错误时，能看到完整的请求追踪数据（API 请求 → LLM 调用 → 检索 → 响应），无需开启 debug 模式。追踪数据可通过标准 OTLP 协议导出到 Jaeger/Tempo 等可观测平台。

**Why this priority**: 当前生产环境无追踪数据是最大的可观测性缺口，直接影响问题排查效率。

**Independent Test**: 启动服务（非 debug 模式），发送审核请求，在追踪导出端（Console/OTLP）看到完整的 span 链路。

**Acceptance Scenarios**:

1. **Given** 服务以生产模式启动且 `OTEL_ENABLED=true`, **When** 发送审核请求, **Then** 在 OTLP 导出端看到包含 API → LLM → RAG 完整链路的 trace
2. **Given** 服务以生产模式启动且 `OTEL_ENABLED=false`, **When** 发送审核请求, **Then** 无追踪数据导出（行为与当前一致）
3. **Given** 服务启动且 `OTEL_CONSOLE_EXPORT=true`, **When** 发送请求, **Then** console 输出包含 span 名称、耗时、状态码

---

### User Story 2 - 现有 trace API 无缝桥接 (Priority: P1)

开发者使用现有 `trace_span` API 的代码无需修改。当 OTel 启用时，自动桥接到 OpenTelemetry Tracer；未启用时，保持原有 SQLite 持久化行为。

**Why this priority**: 桥接模式确保渐进式迁移，不破坏现有功能，是 OTel 能落地的必要条件。

**Independent Test**: 代码中使用 `with trace_span("name")` 的地方，在 OTel 开关切换时行为均正确。

**Acceptance Scenarios**:

1. **Given** OTel 未启用, **When** 使用 `with trace_span("name") as span:`, **Then** span 数据存储到 SQLite（原有行为）
2. **Given** OTel 已启用, **When** 使用 `with trace_span("name") as span:`, **Then** span 数据同时导出到 OTel
3. **Given** OTel 已启用, **When** 现有代码读取 `span.duration`, **Then** 返回正确的耗时值

---

### User Story 3 - Memory Service 追踪覆盖 (Priority: P2)

开发者排查记忆服务相关问题时，能看到 `memory_search` 和 `memory_add` 的调用追踪，包括命中/未命中状态和耗时。

**Why this priority**: Memory 是审核结果质量的关键依赖，缺少追踪导致记忆相关问题难以定位。

**Independent Test**: 触发记忆操作，在追踪数据中看到 memory 相关 span。

**Acceptance Scenarios**:

1. **Given** OTel 已启用, **When** 执行记忆搜索, **Then** trace 中出现 `memory_search` span，属性包含 `hit=true/false` 和耗时
2. **Given** OTel 已启用, **When** 添加记忆条目, **Then** trace 中出现 `memory_add` span

---

### User Story 4 - Cache 追踪覆盖 (Priority: P2)

开发者分析缓存效果时，能看到 `cache_get` 和 `cache_set` 的调用追踪，包括 hit/miss 状态，帮助判断缓存策略是否有效。

**Why this priority**: 缓存命中率直接影响系统性能和成本，缺少追踪无法评估缓存效果。

**Independent Test**: 触发缓存操作，在追踪数据中看到 cache 相关 span 及 hit/miss 属性。

**Acceptance Scenarios**:

1. **Given** OTel 已启用且缓存有数据, **When** 缓存命中, **Then** trace 中出现 `cache_get` span，属性 `cache.hit=true`
2. **Given** OTel 已启用且缓存无数据, **When** 缓存未命中, **Then** trace 中出现 `cache_get` span，属性 `cache.hit=false`

---

### User Story 5 - FastAPI 请求自动追踪 (Priority: P2)

开发者无需手动添加追踪代码，所有 HTTP 请求自动生成 trace 和 span，包含请求路径、方法、状态码。

**Why this priority**: 自动化追踪减少遗漏，是生产可观测性的基础能力。

**Independent Test**: 发送任意 API 请求，自动生成 trace。

**Acceptance Scenarios**:

1. **Given** OTel 已启用, **When** 发送 `POST /api/ask` 请求, **Then** 自动生成 trace，根 span 名称为 `POST /api/ask`
2. **Given** OTel 已启用, **When** 请求返回 500, **Then** span 状态为 ERROR，包含异常信息

---

### Edge Cases

- OTel SDK 初始化失败（如 OTLP 端点不可达）时是否回退到原有追踪?
- 大量并发请求时追踪开销对性能的影响?
- Mem0 外部服务超时时 span 如何记录?

## Requirements

### Functional Requirements

- **FR-001**: 系统 MUST 支持 OpenTelemetry 追踪，可通过 `OTEL_ENABLED` 环境变量开关
- **FR-002**: 系统 MUST 支持通过 OTLP 协议导出追踪数据到可观测平台
- **FR-003**: 系统 MUST 支持控制台导出（`OTEL_CONSOLE_EXPORT`），用于开发调试
- **FR-004**: 现有 `trace_span` API MUST 在 OTel 启用时自动桥接，未启用时保持原有行为
- **FR-005**: 系统 MUST 为 Memory Service 的 search/add 操作添加追踪覆盖
- **FR-006**: 系统 MUST 为 Cache 的 get/set 操作添加追踪覆盖（含 hit/miss 属性）
- **FR-007**: 系统 MUST 为 FastAPI 添加自动请求追踪中间件
- **FR-008**: OTel 初始化失败时 MUST 回退到原有追踪模式，不应阻止服务启动

### Key Entities

- **TracerProvider**: OpenTelemetry TracerProvider，管理 tracer 创建和 span 导出
- **TraceBridge**: 桥接层，将现有 `trace_span` 调用转发到 OTel 或原有实现
- **TracingMiddleware**: FastAPI 中间件，自动为 HTTP 请求创建 span

## Success Criteria

- **SC-001**: 生产模式下开启 OTel 后，完整的 API→LLM→RAG 链路可在 Jaeger/Tempo 中可视化
- **SC-002**: 现有 `trace_span` 代码零修改即可桥接到 OTel
- **SC-003**: Memory 和 Cache 模块有 span 级别的追踪覆盖
- **SC-004**: OTel 开关关闭时，系统行为与当前完全一致（无性能损耗）

## Assumptions

- 单服务追踪为主，暂不考虑跨服务 trace context 传播
- OTLP 导出端点由运维配置，项目仅提供配置入口
- 追踪数据量在可控范围内，无需采样策略
- `opentelemetry-*` 依赖可选，未安装时不影响服务启动

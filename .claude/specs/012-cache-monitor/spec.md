# Feature Specification: Cache Monitor Dashboard

**Feature Branch**: `012-cache-monitor`
**Created**: 2026-04-16
**Status**: Draft
**Input**: 在可观测页面添加 cache 的 hit、miss 监控页面，参考主流缓存中间件的可视化监控设计，基于抽象能力而非具体实现

## User Scenarios & Testing

### User Story 1 - 实时缓存监控仪表盘 (Priority: P1)

作为运维/开发人员，我需要一个实时监控仪表盘，快速了解缓存系统的整体健康状况，包括命中率、缓存大小等核心指标，以便及时发现性能问题。

**Why this priority**: 实时监控是运维和开发最基础的需求，是后续所有功能的基础。

**Independent Test**:
1. 打开 Observability 页面 → Cache 标签页
2. 验证实时数据展示（命中率、命中数、未命中数、缓存条目数）
3. 验证命名空间分组展示（embedding/retrieval/generation）

**Acceptance Scenarios**:

1. **Given** 缓存系统已初始化且有缓存数据, **When** 用户打开 Cache 监控页面, **Then** 显示实时命中率（百分比）、总命中数、总未命中数
2. **Given** 缓存系统有多个命名空间数据, **When** 用户查看命名空间分组, **Then** 显示每个命名空间的独立命中率、命中数、未命中数
3. **Given** 用户正在查看监控页面, **When** 缓存状态发生变化, **Then** 页面数据支持手动刷新更新
4. **Given** 缓存未启用, **When** 用户访问监控页面, **Then** 显示"缓存未启用"状态提示

---

### User Story 2 - 缓存层级详情视图 (Priority: P1)

作为开发人员，我需要分别查看 L1 内存缓存和 L2 持久化缓存的独立指标，以便理解缓存分层的效果并进行调优。

**Why this priority**: 三级缓存架构是当前系统的核心设计，需要直观展示各层效果。

**Independent Test**:
1. 打开 Cache 监控页面
2. 验证 L1/L2 分层展示
3. 验证各层的条目数、内存占用、命中率

**Acceptance Scenarios**:

1. **Given** 缓存系统有两级缓存, **When** 用户查看缓存层详情, **Then** 显示 L1 内存缓存的条目数、内存占用
2. **Given** L1 和 L2 缓存都有数据, **When** 用户对比层级指标, **Then** 清晰展示 L1 与 L2 的命中分布
3. **Given** L1 缓存达到容量上限, **When** 用户查看监控, **Then** 显示 L1 驱逐(eviction)次数

---

### User Story 3 - 历史趋势分析 (Priority: P2)

作为运维人员，我需要查看命中率的历史趋势图，了解缓存性能随时间的变化，以便发现周期性问题或评估配置调优效果。

**Why this priority**: 趋势分析帮助发现潜在问题，但需要额外存储支持。

**Independent Test**:
1. 打开 Cache 监控页面
2. 切换时间范围（1h/6h/24h/7d）
3. 验证趋势图展示

**Acceptance Scenarios**:

1. **Given** 系统已收集历史指标数据, **When** 用户选择时间范围(1h/6h/24h/7d), **Then** 显示该时间段的命中率趋势曲线图
2. **Given** 用户查看趋势图, **When** 鼠标悬停在数据点上, **Then** 显示该时间点的具体数值
3. **Given** 系统运行时间不足所选范围, **When** 用户选择较长时间范围, **Then** 显示从系统启动到当前的数据
4. **Given** 系统重启导致历史数据清空, **When** 用户查看趋势, **Then** 显示"无历史数据"提示

---

### User Story 4 - 缓存条目详情查询 (Priority: P2)

作为开发人员，我需要查看缓存的详细条目列表，包括 key、命名空间、创建时间、TTL 等信息，以便排查特定数据的缓存状态。

**Why this priority**: 排查问题时需要深入查看具体缓存条目。

**Independent Test**:
1. 打开 Cache 监控页面
2. 切换到"缓存条目"视图
3. 验证条目列表展示和筛选功能

**Acceptance Scenarios**:

1. **Given** 缓存有条目数据, **When** 用户切换到条目列表视图, **Then** 显示缓存条目列表（key哈希、命名空间、创建时间、TTL）
2. **Given** 用户需要查找特定命名空间的条目, **When** 用户选择命名空间筛选, **Then** 只显示该命名空间的条目
3. **Given** 用户需要清理过期缓存, **When** 用户点击"清除过期"按钮, **Then** 系统执行清理并更新统计
4. **Given** 缓存条目较多, **When** 用户浏览条目列表, **Then** 支持分页显示

---

### Edge Cases

- 缓存功能未启用时，页面如何展示？
- 系统刚启动无缓存数据时，页面如何展示？
- 多实例部署时，如何展示聚合数据？
- 缓存统计计数器溢出时如何处理？

## Requirements

### Functional Requirements

- **FR-001**: 系统 MUST 提供实时缓存命中率展示（整体 + 各命名空间）
- **FR-002**: 系统 MUST 提供缓存命中数、未命中数展示
- **FR-003**: 系统 MUST 提供缓存条目数展示（L1 内存条目数）
- **FR-004**: 系统 MUST 分层展示 L1/L2 缓存的独立指标
- **FR-005**: 系统 MUST 支持命名空间维度筛选（embedding/retrieval/generation）
- **FR-006**: 系统 SHOULD 提供历史命中率趋势图（支持 1h/6h/24h/7d 时间范围）
- **FR-007**: 系统 SHOULD 提供缓存条目详情列表
- **FR-008**: 系统 SHOULD 支持手动清除过期缓存

### Key Entities

- **CacheMetrics**: 缓存指标快照，包含时间戳、命中率、命中数、未命中数、各命名空间指标
- **CacheLayer**: 缓存层抽象，标识 L1/L2，包含条目数、容量、驱逐次数等属性
- **CacheEntry**: 缓存条目，包含 key 哈希、命名空间、创建时间、TTL、大小等属性
- **AlertRule**: 告警规则，包含指标类型、阈值、比较运算符、状态（预留，暂不实现）

## Success Criteria

- **SC-001**: 用户能在 3 秒内获取实时缓存指标数据
- **SC-002**: 趋势图支持至少 7 天的历史数据展示
- **SC-003**: 条目列表支持分页，每页默认 20 条

## Assumptions

- 当前为单实例部署，无需考虑多实例聚合
- 历史指标数据存储在 SQLite 中，与现有 Trace 数据共存
- 前端使用现有的 React + Tailwind 技术栈
- 告警阈值配置复用现有的 settings.json 机制
